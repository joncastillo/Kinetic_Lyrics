"""The illustration step: reuse saved artwork or plan prompts and generate new images."""
from __future__ import annotations
from core.paths import default_model_cache
import gc
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from core.progress import emit
from direction.illustration_prompts import fresh_prompts, prepare_job
from core.process import module_command, module_env
from models.image.catalog import MODELS, model_spec


def saved_prompts(data, folder, args):
    """For a studio restart at Images: the saved run's manifest, kept for its prompts, with every image to make again.

    Settings decide which manifest a normal run uses, so a changed setting would rewrite the prompts and an unchanged
    one would find the old images and skip generation; the studio has already moved those images aside."""
    config_path = Path(folder).parent/'config.json'
    try:config = json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):return None
    if config.get('start_step') != 'images':
        return None
    from artwork.active import select_manifest, record_manifest
    try:manifest = select_manifest(Path(folder).parent, dict(config, start_step='review'))
    except ValueError:return None
    job = json.loads(manifest.read_text(encoding='utf-8'))
    indices = job.get('line_groups')
    count = len(job.get('groups', []))
    groups = ([' / '.join(data[i]['text'] for i in group) for group in indices] if indices else
              [' / '.join(line['text'] for line in data[i:i+n]) for n in [-(-len(data)//max(1, count))] for i in range(0, len(data), n)])
    if groups != job.get('groups'):
        print('The lyric lines changed since these prompts were written; writing new prompts.', flush=True)
        return None
    # The main character is written into the scenes, so saved prompts from the other mode would contradict it.
    wanted = 'likeness' if getattr(args, 'reference_use', 'style') == 'likeness' and job.get('reference_paths') else 'style'
    if wanted != (job.get('reference_use') or 'style'):
        print('The main-character option changed since these prompts were written; writing new prompts so the scenes '
              'show the person in the reference image.' if wanted == 'likeness' else
              'The main-character option was turned off since these prompts were written; writing new prompts.', flush=True)
        return None
    if job['model'] != args.image_model or (args.image_steps and job['steps'] != args.image_steps):
        job.update(model=args.image_model, steps=args.image_steps or model_spec(args.image_model)['steps'])
        from direction.prompt_fit import over_budget, refit
        long = [i for i, prompt in enumerate(job['prompts']) if over_budget(prompt, args.image_model)]
        if long:
            emit('fit', 0, message=f'Fitting {len(long)} saved image prompt{"s" if len(long) != 1 else ""} to {args.image_model.split("/")[-1]}')
            for i, prompt in zip(long, refit([job['prompts'][i] for i in long], args.image_model, config, job.get('style_prompt', ''))):
                job['prompts'][i] = prompt
        manifest.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Restarting at Images: reusing all {len(job["prompts"])} saved prompts and generating every image again. '
          'Changes to style text, instructions or the main-character option need Restart at Prompts.', flush=True)
    record_manifest(manifest)
    emit('fit', 1, message=f'Reusing {len(job["prompts"])} saved image prompts', manifest=str(manifest))
    return manifest


def generate(data, folder, args):
    from artwork.resume import completed_artwork
    from artwork.queue import has_pending
    resumed=completed_artwork(data,folder,args)
    if resumed is not None:
        from artwork.active import record_manifest
        manifest=resumed[0].parent/'illustrations.json';record_manifest(manifest)
        emit('illustrations',1,message='Using saved artwork',manifest=str(manifest))
        from artwork.lettering_review import needs_validation, require_review
        if needs_validation(resumed,Path(folder).parent) or has_pending(Path(folder).parent):
            cache=Path(args.image_cache or str(default_model_cache())).resolve()
            subprocess.run(module_command('artwork.generation',manifest,'--cache',cache),env=module_env(),check=True)
        require_review(resumed,args)
        return resumed
    job_args = (data, folder, args.illustration_lines, args.image_model,
                args.style_reference, args.image_steps, args.image_seed,
                args.style_prompt+' Visual mood and materials: '+getattr(args,'theme',''), args.ai_model)
    layout_args = dict(width=getattr(args, 'width', 1920), height=getattr(args, 'height', 1080),
                       cinematic=getattr(args, 'cinematic', False), artwork_mode=getattr(args, 'artwork_mode', 'cutout'),
                       image_instructions=getattr(args, 'image_instructions', ''),
                       reference_use=getattr(args, 'reference_use', 'style'), vision_model=getattr(args, 'vision_model', ''))
    reused = saved_prompts(data, folder, args)
    if reused is not None:
        cache = Path(args.image_cache or str(default_model_cache())).resolve()
        subprocess.run(module_command('artwork.generation', reused, '--cache', cache), env=module_env(), check=True)
        job = json.loads(reused.read_text(encoding='utf-8'))
        paths = [reused.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
        from artwork.lettering_review import require_review
        require_review(paths, args)
        return paths
    manifest = prepare_job(*job_args, lookup_only=True, **layout_args)
    try:run_config = json.loads((Path(folder).parent/'config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):run_config = {}
    if manifest.exists() and not fresh_prompts(manifest, run_config):
        job = json.loads(manifest.read_text(encoding='utf-8'))
        paths = [manifest.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
        from artwork.lettering_review import needs_validation
        if paths and all(path.is_file() for path in paths) and not needs_validation(paths,Path(folder).parent) and not has_pending(Path(folder).parent):
            from artwork.active import record_manifest
            record_manifest(manifest)
            emit('illustrations',1,message='Using cached lyric-specific artwork',manifest=str(manifest))
            print('Using cached lyric-specific artwork.', flush=True)
            from artwork.lettering_review import require_review
            require_review(paths,args)
            return paths
    cache = (args.image_cache or Path(os.environ.get('HF_HOME', Path.home()/'.cache/huggingface'))).resolve()
    existing = cache
    while not existing.exists():
        existing = existing.parent
    cached = cache/('models--'+args.image_model.replace('/', '--'))/'snapshots'
    required = next((m['disk_gb'] for m in MODELS if m['id']==args.image_model), 40)
    if not cached.exists() and shutil.disk_usage(existing).free < required*2**30:
        raise ValueError(f'Allow approximately {required} GiB for this model. Use --image-cache DRIVE:/models.')
    emit('song', 0, message='Reading the whole song before writing image prompts')
    manifest = prepare_job(*job_args, **layout_args)
    from artwork.active import record_manifest
    record_manifest(manifest)
    emit('fit',1,message='Image prompts ready',manifest=str(manifest))
    gc.collect()
    if 'torch' in sys.modules and sys.modules['torch'].cuda.is_available():
        sys.modules['torch'].cuda.empty_cache()
    subprocess.run(module_command('artwork.generation', manifest, '--cache', cache), env=module_env(), check=True)
    job = json.loads(manifest.read_text(encoding='utf-8'))
    paths=[manifest.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
    from artwork.lettering_review import require_review
    require_review(paths,args)
    return paths
