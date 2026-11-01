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


def animate_length(pipe, spec, image, prompt, seed, frames, torch):
    """(frames, parts): a clip of at least `frames` frames. Longer than the model makes in one go, it is made
    as several clips, each starting from the last frame of the one before, so the motion carries on."""
    import numpy as np
    from PIL import Image
    from video_generation.models import animate
    chunk = spec.get('chunk_frames', spec['frames'])
    pieces, total, part, start = [], 0, 0, image
    while total < frames:
        remaining = frames-total+(1 if pieces else 0)   # the next part repeats the previous part's last frame
        length = chunk if spec.get('fixed_length') else min(chunk, max(25, 8*((remaining-1+7)//8)+1))
        result = animate(pipe, spec, start, prompt, (seed+part*7919) % 2**31, torch, num_frames=length)
        if pieces:
            result = result[1:]
        pieces.append(result)
        total += len(result)
        start = Image.fromarray(result[-1])
        part += 1
        if part > 1:
            print(f'  continued with part {part} ({total}/{frames} frames)', flush=True)
    return np.concatenate(pieces), part


def clip_prompt(item):
    """The motion prompt for one clip: what was painted, then how it should move."""
    from video_generation.models import MOTION
    return (item['prompt']+' ' if item['prompt'] else '')+MOTION


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
    from video_generation.models import MOTION, animate, load, release
    free_ollama()
    emit('video', 0, message=f"Loading {spec['name']}; first use may download weights")
    prompts = [clip_prompt(item) for item in pending]
    pipe = load(spec, cache, torch, prompts)
    durations, made = [], 0
    total_frames = sum(item.get('frames', spec['frames']) for item in pending)
    try:
        for number, item in enumerate(pending):
            done = len(job['clips'])-len(pending)+number
            # Clips differ in length (a 3 s section and a 50 s one), so the estimate goes by frames still to make.
            remaining = total_frames-made
            estimate = sum(durations)/made*remaining if made else None
            seconds = item.get('frames', spec['frames'])/spec['fps']
            message = f"Animating illustration {item['index']+1} ({number+1}/{len(pending)}, {seconds:.0f} s)"
            if estimate is not None:
                message += f' · about {eta_text(estimate)} left'
            emit('video', done/len(job['clips']), image=item['index']+1, images=len(job['clips']),
                 eta_seconds=round(estimate) if estimate is not None else None, message=message)
            print(message, flush=True)
            started = time.monotonic()
            with Image.open(item['image']) as source:
                image = ImageOps.fit(source.convert('RGB'), tuple(item['size']), Image.Resampling.LANCZOS)
            prompt = clip_prompt(item)
            frames, parts = animate_length(pipe, spec, image, prompt, item['seed'], item.get('frames', spec['frames']), torch)
            folder = Path(item['folder'])
            folder.mkdir(parents=True, exist_ok=True)
            (folder/'clip.json').unlink(missing_ok=True)
            for stale in folder.glob('frames-*'):
                shutil.rmtree(stale, ignore_errors=True)  # stills cut from an older, shorter clip
            count = write_clip(frames, spec['fps'], folder/'clip.mp4')
            (folder/'clip.json').write_text(json.dumps(dict(model=spec['id'], source_sha256=item['sha256'], fps=spec['fps'],
                                                            frames=count, parts=parts, prompt=prompt, seed=item['seed']),
                                                       indent=2), encoding='utf-8')
            made += item.get('frames', spec['frames'])
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
