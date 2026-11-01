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


class PartStore:
    """Saves every part of a clip the moment it is made: its own video file plus its last frame as a lossless PNG,
    listed in parts/parts.json. A run that stops (a crash, running out of memory, a cancel) resumes at the next part
    from that frame, with the prompts the clip started with, so the motion carries on as if nothing happened. Only
    one part is ever held in RAM. close() joins the parts into the clip without re-encoding and removes them.

    `key` identifies what the parts belong to (the painting's fingerprint and the seed); saved parts for anything
    else are discarded."""

    def __init__(self, folder, fps, key, prompts):
        self.folder, self.fps, self.key = Path(folder)/'parts', fps, key
        self.record = self.folder/'parts.json'
        try:
            saved = json.loads(self.record.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = None
        if (saved and saved.get('key') == key and saved.get('parts') and
                all((self.folder/f'part-{n:03d}.mp4').is_file() and (self.folder/f'part-{n:03d}.png').is_file()
                    for n in range(len(saved['parts'])))):
            self.parts, self.prompts, self.reroll = saved['parts'], saved['prompts'], saved.get('reroll', 0)
        else:
            shutil.rmtree(self.folder, ignore_errors=True)
            self.parts, self.prompts, self.reroll = [], list(prompts), 0

    def restart_requested(self):
        """True once when the studio asked to redo this clip (a 'restart' file beside it holding the first part to
        redo): 0 drops every part and starts again from the painting; n keeps parts before n and carries on from
        part n's starting frame with a new seed."""
        marker = self.folder.parent/'restart'
        if not marker.exists():
            return False
        try:
            first = int(marker.read_text(encoding='utf-8').strip() or 0)
        except (OSError, ValueError):
            first = 0
        marker.unlink(missing_ok=True)
        self.truncate(first)
        return True

    def truncate(self, first):
        """Keep the parts before `first` and forget the rest, so they are made again (with a new seed)."""
        if first <= 0:
            shutil.rmtree(self.folder, ignore_errors=True)
            self.parts, self.reroll = [], 0
            return
        for number in range(first, len(self.parts)):
            for suffix in ('.mp4', '.png'):
                (self.folder/f'part-{number:03d}{suffix}').unlink(missing_ok=True)
        self.parts = self.parts[:first]
        self.reroll += 1
        self.save()

    def save(self):
        temporary = self.record.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(key=self.key, prompts=self.prompts, parts=self.parts,
                                             reroll=self.reroll), indent=2), encoding='utf-8')
        temporary.replace(self.record)

    @property
    def frames_done(self):
        return sum(part['frames'] for part in self.parts)

    @property
    def last_frame(self):
        """The image the next part starts from, or None before the first part."""
        if not self.parts:
            return None
        from PIL import Image
        with Image.open(self.folder/f'part-{len(self.parts)-1:03d}.png') as image:
            return image.convert('RGB')

    def write(self, frames):
        from PIL import Image
        self.folder.mkdir(parents=True, exist_ok=True)
        number = len(self.parts)
        write_clip(frames, self.fps, self.folder/f'part-{number:03d}.mp4')
        Image.fromarray(frames[-1]).save(self.folder/f'part-{number:03d}.png')
        self.parts.append(dict(frames=len(frames)))
        self.save()

    def close(self, target):
        """Join the parts into `target` (stream copy: no quality loss, no re-encode); returns the frame count."""
        target = Path(target)
        listing = self.folder/'concat.txt'
        listing.write_text(''.join(f"file 'part-{n:03d}.mp4'\n" for n in range(len(self.parts))), encoding='utf-8')
        temporary = target.with_suffix('.tmp.mp4')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0',
                        '-i', str(listing), '-c', 'copy', str(temporary)], check=True)
        temporary.replace(target)
        listing.unlink(missing_ok=True)
        for preview in self.folder.glob('preview*'):
            preview.unlink(missing_ok=True)
        # The parts stay: any segment of the finished clip can be made again from the studio.
        return self.frames_done


def animate_length(pipe, spec, image, prompts, seed, frames, torch, on_part=None, sink=None):
    """(frames, parts): a clip of at least `frames` frames. Longer than the model makes in one go, it is made
    as several clips, each starting from the last frame of the one before, so the motion carries on. `prompts`
    is one prompt per part (the last repeats if there are fewer) or a single prompt for every part.
    `on_part(part, frames_done)` is called before each part (1-based) and once more when the clip is complete.
    With `sink` (a PartStore) each part is saved as soon as it is made and not kept, and a clip it already holds
    parts of carries on after them with their prompts; frames is then None."""
    import numpy as np
    from PIL import Image
    from video_generation.models import animate
    chunk = spec.get('chunk_frames', spec['frames'])
    pieces, total, part, start = [], 0, 0, image
    if sink is not None and sink.parts:
        total, part, start, prompts = sink.frames_done, len(sink.parts), sink.last_frame, sink.prompts
    while total < frames:
        if sink is not None and sink.restart_requested():
            if sink.parts:
                total, part, start = sink.frames_done, len(sink.parts), sink.last_frame
                print(f'  Redoing this clip from part {part+1}, as asked in the studio.', flush=True)
            else:
                total, part, start, pieces = 0, 0, image, []
                print('  Restarting this clip from the painting, as asked in the studio.', flush=True)
        if on_part:
            on_part(part+1, total)
        remaining = frames-total+(1 if part else 0)   # the next part repeats the previous part's last frame
        length = chunk if spec.get('fixed_length') else min(chunk, max(25, 8*((remaining-1+7)//8)+1))
        prompt = prompts if isinstance(prompts, str) else prompts[min(part, len(prompts)-1)]
        reroll = getattr(sink, 'reroll', 0)            # each redo of a segment draws a new seed
        result = animate(pipe, spec, start, prompt, (seed+part*7919+reroll*104729) % 2**31, torch, num_frames=length)
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
    return [part_prompt(scene, beats[n] if n < len(beats) else (beats[-1] if beats else None), first=(n == 0))
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
    # Parts saved by an earlier, stopped run are picked up again; their clip keeps the prompts it started with,
    # so those are among the prompts to encode.
    stores = {}
    for item in pending:
        Path(item['folder']).mkdir(parents=True, exist_ok=True)
        stores[item['folder']] = PartStore(item['folder'], spec['fps'], f"{item['sha256']}:{item['seed']}", clip_prompts(item))
        if stores[item['folder']].parts:
            print(f"Illustration {item['index']+1}: resuming after {len(stores[item['folder']].parts)} saved part(s) "
                  f"({stores[item['folder']].frames_done/spec['fps']:.0f} s).", flush=True)
    emit('video', 0, message=f"Loading {spec['name']}; first use may download weights")
    pipe = load(spec, cache, torch, [prompt for store in stores.values() for prompt in store.prompts])
    from video_generation.step import parts_for
    durations, made = [], 0
    total_frames = sum(item.get('frames', spec['frames']) for item in pending)
    resumed_total = sum(store.frames_done for store in stores.values())
    generated = 0   # frames made in this run, for the time estimate (saved parts took no time now)
    finished = len(job['clips'])-len(pending)
    generating = time.monotonic()
    try:
        for number, item in enumerate(pending):
            frames_needed = item.get('frames', spec['frames'])
            parts_needed = item.get('parts') or parts_for(frames_needed, spec)
            store = stores[item['folder']]
            resumed_here = store.frames_done
            def report(part, frames_done, item=item, number=number, frames_needed=frames_needed, parts_needed=parts_needed,
                       resumed_here=resumed_here):
                """Progress after every part: which clip and part, seconds made, and a time estimate by frames."""
                overall = made+frames_done
                made_now = generated+frames_done-resumed_here
                # Clips differ in length (a 3 s section and a 60 s one), so the estimate goes by frames still to make,
                # at the rate of frames made in this run.
                estimate = (time.monotonic()-generating)/made_now*(total_frames-overall) if made_now > 0 else None
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
            folder = Path(item['folder'])
            # A failure leaves the saved parts in place: the next run carries on from them.
            _, parts = animate_length(pipe, spec, image, store.prompts, item['seed'], frames_needed, torch,
                                      on_part=report, sink=store)
            (folder/'clip.json').unlink(missing_ok=True)
            for stale in folder.glob('frames-*'):
                shutil.rmtree(stale, ignore_errors=True)  # stills cut from an older, shorter clip
            count = store.close(folder/'clip.mp4')
            (folder/'clip.json').write_text(json.dumps(dict(model=spec['id'], source_sha256=item['sha256'], fps=spec['fps'],
                                                            frames=count, parts=parts, prompts=store.prompts,
                                                            segments=[part['frames'] for part in store.parts],
                                                            seed=item['seed']), indent=2), encoding='utf-8')
            made += frames_needed
            generated += frames_needed-resumed_here
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
