"""Artwork generation jobs: run the image model over a manifest of prompts, check and save each picture.

Run as `python -m artwork.generation <manifest> --cache <folder>`; the model itself lives in models/image/.
"""
from __future__ import annotations
import argparse
import gc
import models.gpu.memory as gpu_memory
import json
import os
from pathlib import Path
from core.paths import PROJECT_ROOT
import shutil
from PIL import Image
from core.progress import emit, diffusion_callback
from direction.illustration_prompts import subject_kind
from models.image.pipeline import inference_options, load_pipeline, release_pipeline
from models.matting.cutout import remove_negative_space
from models.ocr.lettering import detected_lettering


def run_job(manifest, cache):
    from models.gpu.lifecycle import current_session
    if current_session() is not None:
        return current_session().run_generation(_run_job, manifest, Path(cache).expanduser().resolve())
    from filelock import FileLock
    from artwork.active import record_manifest
    record_manifest(manifest)
    emit('model',0,message='Waiting for the image GPU worker',manifest=str(manifest))
    with FileLock(str(PROJECT_ROOT/'.image-generation.lock'), timeout=-1):
        return _run_job(manifest, Path(cache).expanduser().resolve())


def _run_job(manifest, cache):
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(cache)
    os.environ['U2NET_HOME'] = str(cache/'background-removal')
    job = json.loads(manifest.read_text(encoding='utf-8'))
    missing = [i for i in range(len(job['prompts'])) if not (manifest.parent/f'{i:03d}.png').exists()]
    if not missing:
        print('Using cached lyric-specific artwork.', flush=True)
        return
    try:
        import torch
        from PIL import Image
        from rembg import new_session
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ValueError('Install requirements.txt in the active environment: '+str(exc)) from exc
    if not torch.cuda.is_available():
        raise ValueError('FLUX.2 generation requires CUDA in this environment.')
    model = job['model']
    free, total = gpu_memory.dedicated_memory(torch)
    print(f'GPU memory before image model: {free/2**30:.1f} GiB free / {total/2**30:.1f} GiB total.', flush=True)
    emit('model', 0, message='Loading image model; first use may download weights')
    from models.gpu.lifecycle import current_session
    model_session = current_session()
    pipe = None
    generated = False
    try:
        pipe, guidance = model_session.acquire(model, cache, torch, load_pipeline) if model_session else load_pipeline(model, cache, torch)
        emit('model', 1, message='Image model loaded')
        ocr = RapidOCR()
        print(f'Generating with {model}: {job["steps"]} steps, guidance {guidance}.', flush=True)
        references = []
        for path in job['reference_paths']:
            with Image.open(path) as source:
                reference = source.convert('RGB')
            reference.thumbnail((1024, 1024))
            references.append(reference)
        matte = job.get('artwork_mode') == 'matte'
        def paint_plate(i, layout):
            """The plain sky behind the lyrics, painted to match scenery `i`."""
            plate = manifest.parent/f'{i:03d}.plate.png'
            emit('illustrations', i/len(job['prompts']), image=i+1, images=len(job['prompts']), message=f'Painting the matching sky plate {i+1}/{len(job["prompts"])}')
            for attempt in range(2):
                image = pipe(prompt=job['plate_prompts'][i], **inference_options(model, []),
                    width=layout['image_width'], height=layout['image_height'],
                    num_inference_steps=job['steps'],
                    generator=torch.Generator('cpu').manual_seed(job['seed']+i+50000+attempt*10000),
                    callback_on_step_end=diffusion_callback(i, len(job['prompts']), attempt, 2, job['steps'])).images[0]
                if not detected_lettering(ocr, image):
                    break
            temporary = plate.with_name(plate.stem+'.tmp.png')
            image.save(temporary);temporary.replace(plate)
        for i in missing:
            selected=manifest.parent/f'{i:03d}.png'
            if selected.exists() and selected.with_suffix('.selection.json').exists():
                emit('illustrations',(i+1)/len(job['prompts']),message=f'Keeping your replacement for illustration {i+1}')
                continue
            raw = manifest.parent/f'{i:03d}.raw.png'
            if raw.exists():
                with Image.open(raw) as cached:
                    reuse = not detected_lettering(ocr, cached)
                if reuse:
                    if matte and not raw.with_name(f'{i:03d}.plate.png').exists():
                        from models.image.catalog import image_dimensions
                        layout = dict(job['layouts'][i])
                        layout['image_width'],layout['image_height'] = image_dimensions(layout['image_width'],layout['image_height'],min(total,gpu_memory.dedicated_memory(torch)[0]+torch.cuda.memory_reserved())/2**30)
                        paint_plate(i, layout)
                    continue
            emit('illustrations', i/len(job['prompts']), image=i+1, images=len(job['prompts']), message=f'Generating illustration {i+1}/{len(job["prompts"])}')
            print(f'Generating unique illustration {i+1}/{len(job["prompts"])}...', flush=True)
            layout = dict(job['layouts'][i])
            from models.image.catalog import image_dimensions
            layout['image_width'],layout['image_height'] = image_dimensions(layout['image_width'],layout['image_height'],min(total,gpu_memory.dedicated_memory(torch)[0]+torch.cuda.memory_reserved())/2**30)
            reference_input = references if job.get('artwork_mode') not in ('verse', 'matte') and subject_kind(job['visual_descriptions'][i]) != 'object' else []
            best_path=None;best_lettering=None;best_rank=None
            for attempt in range(3):
                retry_prompt=job['prompts'][i]
                if attempt and manifest.parent.parent.name=='video.artwork':
                    retry_prompt+=' Replace any written sign or neon lettering with unlettered geometric light tubes. All signs, screens, walls and panels are completely blank. No alphabetic marks, captions, numerals or logos anywhere.'
                if attempt and matte:
                    retry_prompt+=' The whole sky above the skyline must be one flat, uniform pure #00FF00 chroma-key green with nothing in it.'
                image = pipe(prompt=retry_prompt, **inference_options(model, reference_input),
                    width=layout['image_width'], height=layout['image_height'],
                    num_inference_steps=job['steps'],
                    generator=torch.Generator('cpu').manual_seed(job['seed']+i+attempt*10000),
                    callback_on_step_end=diffusion_callback(i, len(job['prompts']), attempt, 3, job['steps'])).images[0]
                lettering = detected_lettering(ocr, image)
                screened = True
                if matte:
                    from artwork.greenscreen import usable
                    screened = usable(image)
                if not lettering and screened:
                    temporary=raw.with_name(raw.stem+'.tmp.png')
                    image.save(temporary);temporary.replace(raw)
                    emit('illustrations', (i+1)/len(job['prompts']), image=i+1, images=len(job['prompts']), message=f'Illustration {i+1} saved', artifact=str(raw))
                    break
                rejected_path=manifest.parent/f'{i:03d}.rejected-{attempt+1}.png'
                image.save(rejected_path)
                rank=(sum(len(r['text']) for r in lettering),not screened)
                if best_rank is None or rank<best_rank:
                    best_path,best_lettering,best_rank=rejected_path,lettering,rank
                print(f'{"Lettering detected" if lettering else "No usable greenscreen sky"} in illustration {i+1}; retrying with a new seed.', flush=True)
            else:
                temporary=raw.with_name(raw.stem+'.tmp.png')
                shutil.copy2(best_path,temporary);temporary.replace(raw)
                if best_lettering:
                    from artwork.lettering_review import mark_lettering
                    mark_lettering(raw,best_lettering)
                else:
                    from artwork.lettering_review import mark_greenscreen
                    mark_greenscreen(raw)
                print(f'Illustration {i+1} flagged for image review after three failed attempts; continuing the batch.',flush=True)
                emit('illustrations',(i+1)/len(job['prompts']),image=i+1,images=len(job['prompts']),message=f'Illustration {i+1} saved for review',artifact=str(raw))
            if matte:
                paint_plate(i, layout)
        generated = True
    finally:
        if model_session and generated:
            model_session.generation_done()
            pipe = None
        elif model_session:
            pipe = None
            model_session.release()
        else:
            try:
                release_pipeline(pipe, torch)
            finally:
                pipe = None
                gc.collect()
                torch.cuda.empty_cache()
                print('Image worker released its model and cleared cached GPU memory.', flush=True)
    if job.get('artwork_mode') in ('fullscreen', 'verse'):
        from filelock import FileLock
        for i in missing:
            target=manifest.parent/f'{i:03d}.png'
            with FileLock(str(target)+'.write.lock',timeout=30):
                if not target.with_suffix('.selection.json').exists():
                    temporary=target.with_suffix('.tmp.png')
                    shutil.copy2(manifest.parent/f'{i:03d}.raw.png',temporary)
                    temporary.replace(target)
            from artwork.lettering_review import propagate_lettering
            propagate_lettering(manifest.parent/f'{i:03d}.raw.png',target)
            emit('cutouts', 1, message=f'Full-screen artwork {i+1} ready', artifact=str(target))
        return
    if job.get('artwork_mode') == 'matte':
        from filelock import FileLock
        from artwork.greenscreen import compose_files
        from artwork.lettering_review import propagate_lettering
        emit('cutouts', 0, message='Keying greenscreen skies onto their matching plates')
        for i in missing:
            target=manifest.parent/f'{i:03d}.png'
            with FileLock(str(target)+'.write.lock',timeout=30):
                if not target.with_suffix('.selection.json').exists():
                    temporary=target.with_suffix('.tmp.png')
                    compose_files(manifest.parent/f'{i:03d}.raw.png',manifest.parent/f'{i:03d}.plate.png',temporary)
                    temporary.replace(target)
            propagate_lettering(manifest.parent/f'{i:03d}.raw.png',target)
            emit('cutouts', (missing.index(i)+1)/len(missing), message=f'Greenscreen scene {i+1} keyed', artifact=str(target))
        return
    emit('cutouts', 0, message='Removing illustration backgrounds on CPU')
    session = new_session('birefnet-general', providers=['CPUExecutionProvider'])
    for i in missing:
        target=manifest.parent/f'{i:03d}.png'
        if target.exists() and target.with_suffix('.selection.json').exists():
            emit('cutouts', (missing.index(i)+1)/len(missing),message=f'Keeping selected illustration {i+1}',artifact=str(target))
            continue
        with Image.open(manifest.parent/f'{i:03d}.raw.png') as source:
            cutout = remove_negative_space(source, session)
        low, high = cutout.getchannel('A').getextrema()
        if low == 255 or high == 0:
            raise ValueError(f'Background removal failed for illustration {i+1}.')
        temporary = manifest.parent/f'{i:03d}.tmp.png'
        cutout.save(temporary)
        from filelock import FileLock
        with FileLock(str(target)+'.write.lock',timeout=30):
            if not target.with_suffix('.selection.json').exists():
                temporary.replace(target)
            else:
                temporary.unlink(missing_ok=True)
        from artwork.lettering_review import propagate_lettering
        propagate_lettering(manifest.parent/f'{i:03d}.raw.png',target)
        emit('cutouts', (missing.index(i)+1)/len(missing), message=f'Transparent illustration {i+1} ready', artifact=str(manifest.parent/f'{i:03d}.png'))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--cache', type=Path, required=True)
    options = parser.parse_args()
    try:
        from studio.worker import generate_and_review
        generate_and_review(options.manifest, options.cache)
    except Exception as exc:
        parser.exit(1, f'Illustration generation failed: {exc}\n')
