"""Video worker: animate each illustration listed in a clip job and save the clips.

Run as `python -m video_generation.generation <job.json> --cache <folder>`, normally from the
separate video environment. It shares the image worker's GPU lock, so a video model never loads
while an image model holds the card. After the first clip it reports the measured time per clip
and an estimate for the rest.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from core.paths import PROJECT_ROOT
from core.progress import emit
from video_generation.catalog import video_spec


def free_ollama():
    """Unload resident Ollama models; their VRAM is needed for the video model."""
    try:
        from models.ollama.gpu import unload_model
        from models.ollama.service import local_json
        for model in local_json('ps').get('models', []):
            unload_model(model.get('name') or model.get('model'))
    except Exception as exc:
        print(f'Could not unload Ollama models ({exc}); continuing.', flush=True)


def write_clip(frames, fps, target):
    """Encode frames losslessly enough to cut new render-size stills from later."""
    count, height, width, _ = frames.shape
    temporary = target.with_suffix('.tmp.mp4')
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgb24',
               '-video_size', f'{width}x{height}', '-framerate', str(fps), '-i', 'pipe:0',
               '-c:v', 'libx264', '-preset', 'medium', '-crf', '12', '-pix_fmt', 'yuv420p', str(temporary)]
    subprocess.run(command, input=frames.tobytes(), check=True)
    temporary.replace(target)
    return count


class ClipWriter:
    """Encodes a clip as its parts arrive, so a minute-long clip never sits in RAM whole (a part's frames are
    ~0.4 GB; keeping every part, joining them and copying for ffmpeg ran a 32 GB machine out of memory)."""

    def __init__(self, target, fps):
        self.target, self.fps, self.process, self.count = Path(target), fps, None, 0
        self.temporary = self.target.with_suffix('.tmp.mp4')

    def write(self, frames):
        if self.process is None:
            _, height, width, _ = frames.shape
            self.process = subprocess.Popen(
                ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgb24',
                 '-video_size', f'{width}x{height}', '-framerate', str(self.fps), '-i', 'pipe:0',
                 '-c:v', 'libx264', '-preset', 'medium', '-crf', '12', '-pix_fmt', 'yuv420p', str(self.temporary)],
                stdin=subprocess.PIPE)
        for start in range(0, len(frames), 24):   # a second at a time: no copy of the whole part
            self.process.stdin.write(frames[start:start+24].tobytes())
        self.count += len(frames)

    def close(self):
        """Finish encoding and put the clip in place; returns its frame count."""
        self.process.stdin.close()
        if self.process.wait():
            raise ValueError(f'FFmpeg could not encode {self.target}')
        self.temporary.replace(self.target)
        return self.count

    def abort(self):
        if self.process is not None:
            self.process.kill()
            self.process.wait()
        self.temporary.unlink(missing_ok=True)


def animate_length(pipe, spec, image, prompts, seed, frames, torch, on_part=None, sink=None):
    """(frames, parts): a clip of at least `frames` frames. Longer than the model makes in one go, it is made
    as several clips, each starting from the last frame of the one before, so the motion carries on. `prompts`
    is one prompt per part (the last repeats if there are fewer) or a single prompt for every part.
    `on_part(part, frames_done)` is called before each part (1-based) and once more when the clip is complete.
    With `sink` (a ClipWriter) each part is handed over as soon as it is made and not kept; frames is then None."""
    import numpy as np
    from PIL import Image
    from video_generation.models import animate
    chunk = spec.get('chunk_frames', spec['frames'])
    pieces, total, part, start = [], 0, 0, image
    while total < frames:
        if on_part:
            on_part(part+1, total)
        remaining = frames-total+(1 if part else 0)   # the next part repeats the previous part's last frame
        length = chunk if spec.get('fixed_length') else min(chunk, max(25, 8*((remaining-1+7)//8)+1))
        prompt = prompts if isinstance(prompts, str) else prompts[min(part, len(prompts)-1)]
        result = animate(pipe, spec, start, prompt, (seed+part*7919) % 2**31, torch, num_frames=length)
        if part:
            result = result[1:]
        if sink is not None:
            sink.write(result)
        else:
            pieces.append(result)
        total += len(result)
        start = Image.fromarray(result[-1])
        del result
        part += 1
    if on_part:
        on_part(part+1, total)
    return (np.concatenate(pieces) if sink is None else None), part


def clip_prompts(item):
    """One video prompt per part of the clip: what was painted, the director's beat for that part (generic natural
    motion when there is none), and the guardrails."""
    from direction.motion import part_prompt
    scene = item.get('scene') or item.get('prompt') or ''
    beats = item.get('beats') or []
    return [part_prompt(scene, beats[n] if n < len(beats) else (beats[-1] if beats else None))
            for n in range(max(1, item.get('parts', 1)))]


def eta_text(seconds):
    minutes, seconds = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m' if hours else f'{minutes}m {seconds:02d}s'


def run_job(job_path, cache):
    from filelock import FileLock
    emit('video', 0, message='Waiting for the GPU worker')
    with FileLock(str(PROJECT_ROOT/'.image-generation.lock'), timeout=-1):
        return _run_job(job_path, cache)


def _run_job(job_path, cache):
    from video_generation.step import needs_clip
    job = json.loads(job_path.read_text(encoding='utf-8'))
    pending = [item for item in job['clips'] if needs_clip(item)]
    if not pending:
        return
    spec = video_spec(job['model'])
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(cache)
    # HF_HUB_CACHE outranks HF_HOME: one inherited from the user's shell would hide the weights already in
    # <cache>/hub and start the whole download again somewhere else.
    os.environ['HF_HUB_CACHE'] = str(cache/'hub')
    os.environ.pop('HUGGINGFACE_HUB_CACHE', None)
    import torch
    from PIL import Image, ImageOps
    from video_generation.models import load, release
    free_ollama()
    emit('video', 0, message=f"Loading {spec['name']}; first use may download weights")
    pipe = load(spec, cache, torch, [prompt for item in pending for prompt in clip_prompts(item)])
    from video_generation.step import parts_for
    durations, made = [], 0
    total_frames = sum(item.get('frames', spec['frames']) for item in pending)
    finished = len(job['clips'])-len(pending)
    generating = time.monotonic()
    try:
        for number, item in enumerate(pending):
            frames_needed = item.get('frames', spec['frames'])
            parts_needed = item.get('parts') or parts_for(frames_needed, spec)
            def report(part, frames_done, item=item, number=number, frames_needed=frames_needed, parts_needed=parts_needed):
                """Progress after every part: which clip and part, seconds made, and a time estimate by frames."""
                overall = made+frames_done
                # Clips differ in length (a 3 s section and a 60 s one), so the estimate goes by frames still to make.
                estimate = (time.monotonic()-generating)/overall*(total_frames-overall) if overall else None
                step = (f'part {part} of {parts_needed} · ' if parts_needed > 1 and part <= parts_needed else '')
                message = (f"Animating illustration {item['index']+1} (clip {number+1} of {len(pending)}) · {step}"
                           f"{frames_done/spec['fps']:.0f} of {frames_needed/spec['fps']:.0f} s"
                           +(f' · about {eta_text(estimate)} left' if estimate is not None else ''))
                emit('video', (finished+len(pending)*overall/total_frames)/len(job['clips']), image=item['index']+1,
                     images=len(job['clips']), part=part, parts=parts_needed,
                     eta_seconds=round(estimate) if estimate is not None else None, message=message)
                print(message, flush=True)
            started = time.monotonic()
            with Image.open(item['image']) as source:
                image = ImageOps.fit(source.convert('RGB'), tuple(item['size']), Image.Resampling.LANCZOS)
            prompts = clip_prompts(item)
            folder = Path(item['folder'])
            folder.mkdir(parents=True, exist_ok=True)
            writer = ClipWriter(folder/'clip.mp4', spec['fps'])
            try:
                _, parts = animate_length(pipe, spec, image, prompts, item['seed'], frames_needed, torch,
                                          on_part=report, sink=writer)
            except BaseException:
                writer.abort()
                raise
            (folder/'clip.json').unlink(missing_ok=True)
            for stale in folder.glob('frames-*'):
                shutil.rmtree(stale, ignore_errors=True)  # stills cut from an older, shorter clip
            count = writer.close()
            (folder/'clip.json').write_text(json.dumps(dict(model=spec['id'], source_sha256=item['sha256'], fps=spec['fps'],
                                                            frames=count, parts=parts, prompts=prompts, seed=item['seed']),
                                                       indent=2), encoding='utf-8')
            made += frames_needed
            durations.append(time.monotonic()-started)
            print(f'Clip {number+1}/{len(pending)} took {eta_text(durations[-1])}.', flush=True)
    finally:
        release(pipe, torch)
        print('Video worker released its model and cleared cached GPU memory.', flush=True)
    emit('video', 1, message=f'{len(pending)} clip(s) animated in {eta_text(sum(durations))}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path)
    parser.add_argument('--cache', type=Path, required=True)
    options = parser.parse_args()
    try:
        run_job(options.job, options.cache.expanduser().resolve())
    except Exception as exc:
        parser.exit(1, f'Video generation failed: {exc}\n')
