"""The optional video step: after the artwork is approved, animate every illustration with the chosen model."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from core.paths import PROJECT_ROOT, default_model_cache
from core.process import module_command, module_env
from core.progress import emit
from video_generation.catalog import VIDEO_MODES, clip_size, video_spec
from video_generation.clips import FOLDER, clip_folder, image_digest, saved_clips

def environment():
    """Where setup.ps1 builds the video environment: KINETIC_VIDEO_ENV, else .venv-video in the project."""
    return Path(os.environ.get('KINETIC_VIDEO_ENV') or PROJECT_ROOT/'.venv-video')


def video_python():
    """The interpreter with Modular Diffusers: KINETIC_VIDEO_PYTHON, else the video environment's, else this one."""
    override = os.environ.get('KINETIC_VIDEO_PYTHON')
    if override:
        return Path(override)
    candidate = environment()/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return candidate if candidate.is_file() else Path(sys.executable)


def clip_length(folder):
    """Frames in the finished clip in `folder`, or None when there is none."""
    try:
        return int(json.loads((Path(folder)/'clip.json').read_text(encoding='utf-8'))['frames'])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def prompts_for(illustrations):
    """The image prompt behind each illustration, so the motion matches what was painted."""
    record = Path(illustrations[0]).parent/'illustrations.json'
    prompts = json.loads(record.read_text(encoding='utf-8')).get('prompts', []) if record.is_file() else []
    result = []
    for path in illustrations:
        stem = Path(path).stem
        index = int(stem) if stem.isdecimal() else None
        result.append(prompts[index] if index is not None and index < len(prompts) else '')
    return result


def on_screen_seconds(illustrations, data, duration, args):
    """How long each illustration is on screen, the same way the compositor will show it.

    A painting appears at its start (the first one at 0 s, through the instrumental intro) and stays visible
    until the next one has finished crossfading in, `min(20, max(1, 0.9 x the next section))` seconds after the
    next start. None when the timings are unknown."""
    if not data or not duration:
        return None
    from render.timeline import checked_art_times, illustration_starts
    cues = [line['words'][0]['start'] for line in data]
    record = Path(illustrations[0]).parent/'illustrations.json'
    groups = None
    if record.is_file():
        groups = json.loads(record.read_text(encoding='utf-8')).get('line_groups')
        if groups is not None and len(groups) != len(illustrations):
            groups = None
    starts = illustration_starts(cues, len(illustrations), getattr(args, 'illustration_lines', 2) or 2,
                                 getattr(args, 'lead_in', 1.), groups)
    if getattr(args, 'art_times', None) is not None:
        starts = checked_art_times(args.art_times, len(illustrations), duration)
    if len(starts) != len(illustrations):
        return None
    def crossing(k):
        gap = starts[k+1]-starts[k] if k+1 < len(starts) else starts[k]-starts[k-1]
        return min(20., max(1., gap*.9))
    seconds = []
    for i, start in enumerate(starts):
        end = starts[i+1]+crossing(i+1) if i+1 < len(starts) else duration
        seconds.append(max(1., min(duration, end)-(0. if i == 0 else start)))
    return seconds


def frames_for(seconds, spec):
    """Frames to cover `seconds` (plus a little), as the 8k+1 counts LTX-style models take; the default clip
    length when the timing is unknown."""
    if seconds is None:
        return spec['frames']
    import math
    needed = math.ceil(min(seconds, 180.)*spec['fps'])+1
    return max(25, 8*math.ceil((needed-1)/8)+1)


def animate(illustrations, output, args, data=None, duration=None):
    """{image digest: frame folder} for the clips of these illustrations, generating any that are missing.

    With the song's timings each clip is as long as its painting is on screen; a section longer than the model
    makes in one go is generated as several clips, each continuing from the last frame of the one before."""
    model = getattr(args, 'video_model', None)
    if not model or not illustrations:
        return None
    if getattr(args, 'artwork_mode', 'cutout') not in VIDEO_MODES:
        print('Video generation skipped: it needs full-screen or verse artwork.', flush=True)
        return None
    spec = video_spec(model)
    project = Path(output).parent
    size = clip_size(spec, args.width, args.height)
    prompts = prompts_for(illustrations)
    seconds = on_screen_seconds(illustrations, data, duration, args) or [None]*len(illustrations)
    items = []
    for index, path in enumerate(illustrations):
        digest = image_digest(path)
        items.append(dict(index=index, image=str(path), sha256=digest, prompt=prompts[index], size=size,
                          frames=frames_for(seconds[index], spec), seed=(args.image_seed+index) % 2**31,
                          folder=str(clip_folder(project, model, digest))))
    # A clip shorter than its painting's time on screen (made before clips followed the timing, or before the
    # sections were re-timed) is made again; frames=None means an older clip of unknown length.
    missing = [item for item in items if (clip_length(item['folder']) or 0) < item['frames']]
    if missing:
        cache = Path(getattr(args, 'image_cache', None) or default_model_cache()).resolve()
        existing = cache
        while not existing.exists():
            existing = existing.parent
        if not (cache/('models--'+model.replace('/', '--'))).exists() and shutil.disk_usage(existing).free < spec['disk_gb']*2**30:
            raise ValueError(f"Allow approximately {spec['disk_gb']} GiB for {spec['name']}. Use --image-cache DRIVE:/models.")
        job = project/FOLDER/'job.json'
        job.parent.mkdir(parents=True, exist_ok=True)
        job.write_text(json.dumps(dict(model=model, clips=items), indent=2), encoding='utf-8')
        emit('video', 0, message=f"Animating {len(missing)} illustration(s) with {spec['name']}")
        subprocess.run(module_command('video_generation.generation', job, '--cache', cache, python=video_python()),
                       env=module_env(), check=True)
    clips = saved_clips(project, model, [item['sha256'] for item in items], args.width, args.height)
    print(f'Video clips: {len(clips)} of {len(items)} illustrations animated.', flush=True)
    return clips


def project_clips(project, config, illustrations):
    """Finished clips for a Studio rebuild; images replaced since the video step stay still until the next full run."""
    model = config.get('video_model')
    if not model or config.get('artwork_mode') not in VIDEO_MODES:
        return None
    return saved_clips(project, model, [image_digest(p) for p in illustrations if Path(p).is_file()], config['width'], config['height'])
