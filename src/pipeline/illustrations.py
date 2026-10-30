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
from direction.illustration_prompts import prepare_job
from core.process import module_command, module_env
from models.image.catalog import MODELS


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
                       cinematic=getattr(args, 'cinematic', False), artwork_mode=getattr(args, 'artwork_mode', 'cutout'))
    manifest = prepare_job(*job_args, lookup_only=True, **layout_args)
    if manifest.exists():
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
    emit('subjects', 0, message='Interpreting lyrics into illustration subjects')
    manifest = prepare_job(*job_args, **layout_args)
    from artwork.active import record_manifest
    record_manifest(manifest)
    emit('subjects',1,message='Illustration subjects ready',manifest=str(manifest))
    gc.collect()
    if 'torch' in sys.modules and sys.modules['torch'].cuda.is_available():
        sys.modules['torch'].cuda.empty_cache()
    subprocess.run(module_command('artwork.generation', manifest, '--cache', cache), env=module_env(), check=True)
    job = json.loads(manifest.read_text(encoding='utf-8'))
    paths=[manifest.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
    from artwork.lettering_review import require_review
    require_review(paths,args)
    return paths
