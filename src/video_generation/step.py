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

ENVIRONMENT = PROJECT_ROOT/'.venv-video'


def video_python():
    """The interpreter with Modular Diffusers: KINETIC_VIDEO_PYTHON, else .venv-video, else this one."""
    override = os.environ.get('KINETIC_VIDEO_PYTHON')
    if override:
        return Path(override)
    candidate = ENVIRONMENT/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return candidate if candidate.is_file() else Path(sys.executable)


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


def animate(illustrations, output, args):
    """{image digest: frame folder} for the clips of these illustrations, generating any that are missing."""
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
    items = []
    for index, path in enumerate(illustrations):
        digest = image_digest(path)
        items.append(dict(index=index, image=str(path), sha256=digest, prompt=prompts[index], size=size,
                          seed=(args.image_seed+index) % 2**31, folder=str(clip_folder(project, model, digest))))
    missing = [item for item in items if not (Path(item['folder'])/'clip.json').is_file()]
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
