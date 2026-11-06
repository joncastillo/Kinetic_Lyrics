"""Artwork generation jobs: run the image model over a manifest of prompts, check and save each picture.

Run as `python -m artwork.generation <manifest> --cache <folder>`; the model itself lives in models/image/.
"""
from __future__ import annotations
import argparse
import gc
import models.gpu.memory as gpu_memory
import secrets
import json
import os
from pathlib import Path
from core.paths import PROJECT_ROOT
import shutil
from core.progress import emit
from direction.illustration_prompts import uses_reference, with_reference_role
from models.image.catalog import model_spec
from models.image.pipeline import inference_options, load_pipeline, release_pipeline
from models.matting.cutout import remove_negative_space
from models.ocr.lettering import detected_lettering
from core.files import content_digest

# the folders of the stage's small pictures (direction.ornaments.paint_icons): cut-out typography art, not the song's scenes
SMALL_PICTURES = ('video.ornaments', 'video.instruments')


def diffusion_callback(image, total, attempt, attempts, steps, label='Illustration', shown=None):
    """Per diffusion step: keep the GPU session's telemetry fresh and report progress. `shown` names the picture
    as the user knows it (a replacement candidate for illustration 7 is "7", not "1/1" of its one-image job)."""
    def callback(pipe, step, timestep, kwargs):
        from models.gpu.lifecycle import current_session
        session=current_session()
        if session:session.publish()
        emit('illustrations', ((image + (step+1)/steps) / total),
             image=image+1, images=total, step=step+1, steps=steps,
             attempt=attempt+1, attempts=attempts,
             message=f'{label} {shown or f"{image+1}/{total}"} · step {step+1}/{steps} · attempt {attempt+1}')
        return kwargs
    return callback


def sheet_callback(name, sheet, sheets, steps, attempt=0, attempts=None):
    """Per diffusion step of a reference sheet: the line the illustrations show, with the picture's name in place
    of the illustration number. `attempt` counts tries in this generation only; the saved repaint revision
    controls cache invalidation and seed selection, not the displayed attempt number."""
    def callback(pipe, step, timestep, kwargs):
        from models.gpu.lifecycle import current_session
        session=current_session()
        if session:session.publish()
        emit('references', (sheet + (step+1)/steps) / sheets, image=sheet+1, images=sheets, step=step+1, steps=steps,
             attempt=attempt+1, attempts=attempts,
             message=f'Illustration ({name}) · step {step+1}/{steps} · attempt {attempt+1}')
        return kwargs
    return callback


def finished_scene(manifest, index):
    """The finished painting nearest to scene `index` (earlier ones first), as the style for an entity's model sheet,
    so the sheet looks like the scenes it will guide; None before any scene is painted."""
    from PIL import Image
    done = sorted((abs(int(p.name[:3])-index), int(p.name[:3]) > index, p)
                  for p in Path(manifest).parent.glob('[0-9][0-9][0-9].raw.png'))
    if not done:
        return None
    with Image.open(done[0][2]) as source:
        picture = source.convert('RGB')
    picture.thumbnail((1024, 1024))
    return picture


def paint_entities(pipe, model, manifest, job, entities, references, torch, ocr, memory_gib, names=()):
    """{entity id: picture} for these recurring entities (direction.entities): each painted once as a model sheet and
    kept for every later run while what it shows, the technique and the model stay the same. `references` are the
    project's pictures; each sheet gets one picture in one role only (direction.entities.sheet_inputs): a changed
    form gets the sheet of the form it comes from, painted first (painting_order); the cast and the lead in another
    form get the lead's photo; anything else a style picture for the art style, else nothing (a finished scene or
    the lead's photo given to every sheet blended the lead into other characters). A model that must start from a
    picture and has none gets a blank canvas."""
    from PIL import Image
    from direction.entities import (REFERENCE_PIXELS, SHEET_VERSION, base_of, base_sheet, current_sheet, painting_order, photo_index,
                                    scene_view, sheet_inputs, sheet_path, sheet_prompt, sheet_size, sheet_style)
    from direction.story import load as load_story
    from direction.story import story_path
    from models.image.catalog import sheet_dimensions
    from core.files import update_json
    always = model_spec(model)['pipeline'] == 'QwenImageEditPlusPipeline'
    takes_pictures = model_spec(model)['references']
    pictures = {}
    entities = painting_order(entities, load_story(manifest))  # a changed form after the form it is painted from
    for k, entity in enumerate(entities):
        # the art style first, then the mood (see sheet_style); a place or an object without the mood (without_mood)
        technique = sheet_style(job, mood=entity.get('kind') == 'character')
        uploaded = Path(str(entity.get('uploaded') or ''))
        path = uploaded if entity.get('uploaded') and uploaded.is_file() else sheet_path(manifest, entity, technique, model)
        linked = Path(str(entity.get('image') or ''))
        painted_from = None
        if not path.is_file() and entity.get('image') and linked.is_file() and current_sheet(entity):
            # still linked in the storyline: the editor drops the link when the description changes or a repaint is
            # asked for, so this picture is current; it was named under an older rule
            import shutil
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(linked, path)
        if not path.is_file():
            if job.get('reuse_references_only'):
                print(f"Reference {entity['name']} is not available; keeping references unchanged for the Illustrations-only restart.",flush=True)
                continue
            from models.gpu.edit_priority import checkpoint
            checkpoint()  # the previous reference is already saved and linked in the story
            emit('references', k/len(entities), image=k+1, images=len(entities), message=f"Generating Illustration ({entity['name']})")
            print(f"Painting the reference picture of the recurring {entity['kind']} {entity['name']}.", flush=True)
            width, height = sheet_dimensions(*sheet_size(entity), memory_gib)
            prompt = sheet_prompt(entity, technique)
            story = load_story(manifest)  # read again: a base painted just before is recorded in it
            base = base_sheet(story, entity) if takes_pictures else None
            tag = entity.get('photo') or (base_of(story, entity) or {}).get('photo')
            index = photo_index(tag, list(names)) if tag and takes_pictures else None
            conditioning, role = sheet_inputs(entity, story, list(references or []),  # (picture, kind)
                                              job.get('reference_use') == 'likeness', takes_pictures, edits=always,
                                              base_picture=base, lead_picture=None if index is None else references[index][0])
            explicit_inputs = 'reference_inputs' in entity
            if explicit_inputs:
                from direction.reference_edits import conditioning as edited_conditioning
                conditioning, role = edited_conditioning(manifest, entity, story, model_spec(model).get('max_references', 3))
            if role and (explicit_inputs or not entity.get('prompt')):
                prompt = role+prompt
                print(f"  {entity['name']}: painted with "
                      + ('the selected reference inputs' if explicit_inputs else 'the sheet of the form it comes from' if base is not None else
                         "the project's lead picture" if 'this character' in role else "the project's style picture")+'.', flush=True)
            if always and not conditioning:  # Qwen Image Edit paints over a picture: an empty one, so only the words count
                conditioning = [Image.new('RGB', (width, height), (236, 234, 228))]
                prompt = 'The input image is an empty canvas; paint over all of it. '+prompt
            repaint = int(entity.get('repaint') or 0)   # how many times this picture was painted again (a failed check, a request)
            for attempt in range(2):   # painted once more when lettering got into it
                # the first painting follows the job's seed; a repaint or a retry draws its own, so no two are alike
                seed = job['seed']+70000+k if not (repaint or attempt) else secrets.randbelow(2**31)
                print(f"Reference picture of {entity['name']} seed: {seed} (attempt {attempt+1}), {width}x{height}", flush=True)
                image = pipe(prompt=prompt, **inference_options(model, conditioning), width=width, height=height,
                             num_inference_steps=job['steps'],
                             generator=torch.Generator('cpu').manual_seed(seed),
                             callback_on_step_end=sheet_callback(entity['name'], k, len(entities), job['steps'], attempt, attempts=2)).images[0]
                if not detected_lettering(ocr, image):
                    break
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.stem+'.tmp.png')
            image.save(temporary)
            temporary.replace(path)
            from core.files import write_json_atomic
            write_json_atomic(path.with_suffix('.prompt.json'), dict(prompt=prompt))
            painted_from = prompt
            emit('references', (k+1)/len(entities), message=f"Reference picture of {entity['name']} saved", artifact=str(path))
        with Image.open(path) as source:
            picture = source.convert('RGB')
        picture = scene_view(picture, entity)  # a scene gets one view, not the sheet's rows of views
        picture.thumbnail((REFERENCE_PIXELS, REFERENCE_PIXELS))
        pictures[entity['id']] = picture
        # recorded in the story as soon as it is saved (not after the whole batch): the Artwork tab and the video
        # step find the pictures through the story, and the tab shows each one the moment it is done; a form
        # painted next finds its base's picture there too
        def record(saved, entity_id=entity['id'], image=str(path), painted_from=painted_from):
            for entry in saved.get('entities') or []:
                if entry.get('id') == entity_id:
                    if entry.get('uploaded') and entry.get('image') != image:
                        continue
                    entry['image'] = image
                    entry['sheet_version'] = SHEET_VERSION
                    if painted_from:
                        entry['painted_prompt'] = painted_from
        update_json(story_path(manifest), record)
    return pictures


def run_job(manifest, cache):
    from models.gpu.lifecycle import current_session
    if current_session() is not None:
        return current_session().run_generation(_run_job, manifest, Path(cache).expanduser().resolve())
    from filelock import FileLock
    from artwork.active import record_manifest
    record_manifest(manifest)
    emit('model',0,message='Waiting for the image GPU worker',manifest=str(manifest))
    from models.gpu.edit_priority import YieldToEdits, acquire
    lock = FileLock(str(PROJECT_ROOT/'.image-generation.lock'), timeout=-1)
    while True:
        acquire(lock)
        try:
            try:
                return _run_job(manifest, Path(cache).expanduser().resolve())
            except YieldToEdits:
                print('Yielding to queued in-image edits before the next illustration.', flush=True)
            # Clear the unwound exception's tensors before the editor can acquire the GPU.
            import torch
            gc.collect()
            torch.cuda.empty_cache()
        finally:
            lock.release()


def reference_paths(manifest, job, takes_references):
    """The pictures this job paints from. The stage's small pictures stand alone and get none."""
    manifest = Path(manifest)
    if manifest.parent.parent.name in SMALL_PICTURES:
        return []
    paths = list(job['reference_paths'])
    if takes_references:
        # The project's references as they are now (added or removed since these prompts were planned) lead.
        project = manifest.resolve().parent.parent.parent/'references'
        current = sorted(str(p) for p in project.glob('*') if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')) if project.is_dir() else []
        if current and {content_digest(Path(p)) for p in current} != {content_digest(Path(p)) for p in paths if Path(p).is_file()}:
            print(f"Using the project's {len(current)} current reference image(s).", flush=True)
            return current
    return paths


def _run_job(manifest, cache):
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(cache)
    os.environ['U2NET_HOME'] = str(cache/'background-removal')
    job = json.loads(manifest.read_text(encoding='utf-8'))
    missing = [i for i in range(len(job['prompts'])) if not (manifest.parent/f'{i:03d}.png').exists()]
    if not missing and not job.get('paint_references'):
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
    # "Randomize per image" in the studio: each picture gets its own seed instead of run seed + index.
    random_seeds = False
    if manifest.parent.parent.name == 'video.artwork':
        try:
            config = json.loads((manifest.parent.parent.parent/'config.json').read_text(encoding='utf-8'))
            random_seeds = bool(config.get('randomize_seed'))
        except (OSError, ValueError):pass
    free, total = gpu_memory.dedicated_memory(torch)
    print(f'GPU memory before image model: {free/2**30:.1f} GiB free / {total/2**30:.1f} GiB total.', flush=True)
    try:
        import psutil
        ram = psutil.virtual_memory()
        print(f'System memory before image model: {ram.available/2**30:.1f} GiB free / {ram.total/2**30:.1f} GiB RAM, '
              f'{psutil.swap_memory().free/2**30:.1f} GiB page file free.', flush=True)
        if os.name == 'nt':
            import ctypes
            class Status(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)]+[(n, ctypes.c_ulonglong) for n in
                            ('total_phys', 'avail_phys', 'total_commit', 'avail_commit', 'total_virtual', 'avail_virtual', 'ext')]
            status = Status(length=ctypes.sizeof(Status))
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                # Commit, not free RAM, is what runs out: on Windows that kills the loader with 0xC0000005, not MemoryError.
                print(f'Commit headroom: {status.avail_commit/2**30:.1f} of {status.total_commit/2**30:.1f} GiB. '
                      'Loading may crash natively if this is low; close programs or enlarge the page file.', flush=True)
    except Exception:
        pass
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
        # The same picture uploaded several times adds nothing but weight to its conditioning.
        unique = {}
        paths = reference_paths(manifest, job, model_spec(model)['references'])
        small = manifest.parent.parent.name in SMALL_PICTURES
        for path in paths:
            unique.setdefault(content_digest(Path(path)), path)
        from direction.entities import photo_subject
        reference_kinds = []  # what the vision model said each shows, for the reference sheets (sheet_inputs)
        reference_subjects = []  # what each reference photo shows (its vision description), to pass only those a scene needs
        for path in unique.values():
            with Image.open(path) as source:
                reference = source.convert('RGB')
            reference.thumbnail((1024, 1024))
            references.append(reference)
            reference_subjects.append(photo_subject(path))
            from direction.entities import photo_kind
            reference_kinds.append(photo_kind(path))
        if job.get('paint_references'):  # only these reference sheets, painted again now
            from direction.story import load as load_story
            source = Path(job.get('source_manifest') or manifest)
            wanted = set(job['paint_references'])
            entities = [e for e in (load_story(source) or {}).get('entities') or [] if e.get('id') in wanted]
            paint_entities(pipe, model, source, job, entities, list(zip(references, reference_kinds)), torch, ocr,
                           min(total, gpu_memory.dedicated_memory(torch)[0]+torch.cuda.memory_reserved())/2**30,
                           names=[Path(p).name for p in unique.values()])
            return
        # the storyline may give a segment its own reference images (a character, a place): they lead for that image
        from direction.story import load as load_story
        # A replacement candidate is a one-image copy of the job in its own folder: its storyline, entity sheets and
        # scene number are the project's (source_manifest, source_index), not the copy's.
        story_manifest = Path(job.get('source_manifest') or manifest)
        scene_of = (lambda i: int(job['source_index'])) if job.get('source_index') is not None else (lambda i: i)
        story = load_story(story_manifest)
        segment_references, segment_reference_names = {}, {}   # pictures, and their file names for @tags in the prompt
        for segment in (story or {}).get('segments', []):
            pictures, names_of = [], []
            for path in segment.get('references') or []:
                try:
                    with Image.open(path) as source:
                        picture = source.convert('RGB')
                except OSError:
                    continue
                picture.thumbnail((1024, 1024))
                pictures.append(picture)
                names_of.append(Path(path).name)
            if pictures:
                segment_references[int(segment.get('index', -1))] = pictures
                segment_reference_names[int(segment.get('index', -1))] = names_of
        # each recurring character, object or place gets one model sheet, which guides every segment that shows it;
        # a sheet is painted just before the first scene that needs it, in the style of the scenes already painted
        entity_pictures = {}
        use_entities = bool(story and story.get('entities')) and model_spec(model)['references']
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
        # the stage's small pictures (video.ornaments) are typography art, not the song's illustrations
        label = 'Illustrated Typography' if manifest.parent.parent.name == 'video.ornaments' else 'Illustration'
        # Qwen Image Edit cannot start from nothing, so a small picture gives it an empty canvas, which is no reference
        canvas = [Image.new('RGB', (1024, 1024), 'white')] if small and model_spec(model)['pipeline'] == 'QwenImageEditPlusPipeline' else []
        # a replacement candidate is a one-image job: named after the illustration it is for, not "1/1"
        shown_number = (lambda i: str(int(job['source_index'])+1)) if job.get('source_index') is not None else (lambda i: str(i+1))
        caption = (lambda i: shown_number(i)) if job.get('source_index') is not None else (lambda i: f"{i+1}/{len(job['prompts'])}")
        for i in missing:
            from models.gpu.edit_priority import checkpoint
            checkpoint()
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
            emit('illustrations', i/len(job['prompts']), image=i+1, images=len(job['prompts']), message=f'Generating {label} {caption(i)}')
            print(f'Generating {label} {caption(i)}...', flush=True)
            layout = dict(job['layouts'][i])
            from models.image.catalog import image_dimensions
            layout['image_width'],layout['image_height'] = image_dimensions(layout['image_width'],layout['image_height'],min(total,gpu_memory.dedicated_memory(torch)[0]+torch.cuda.memory_reserved())/2**30)
            # Qwen Image Edit always draws from its references (it cannot start from nothing); the reference role
            # wording tells it to use them only for rendering when the scene shows no person.
            always = model_spec(model)['pipeline'] == 'QwenImageEditPlusPipeline'
            reference_input = references if model_spec(model)['references'] and (always or uses_reference(job.get('artwork_mode'), job['visual_descriptions'][i])) else []
            from direction.entities import choose_references, reference_role, segment_entities, shows_subject
            likeness = job.get('reference_use') == 'likeness'
            names = None
            if likeness and reference_input:
                # the user's photos go only to the scenes that show who they are of: the scene, who the storyline puts
                # in it, and the cast entities it lists (each with its looks)
                segment = next((s for s in (story or {}).get('segments', []) if s.get('index') == scene_of(i)), {})
                text = ' '.join([job['visual_descriptions'][i], str(segment.get('characters') or '')]+
                                [f"{e['name']} {e['looks']}" for e in segment_entities(story, scene_of(i), painted=False) if e.get('cast')])
                wanted = [k for k, subject in enumerate(reference_subjects) if shows_subject(subject, text)]
                if len(wanted) < len(references):
                    print(f'Illustration {i+1}: {len(wanted)} of {len(references)} reference photos shown in this scene; '
                          'the rest guide the art style only.', flush=True)
                # every photo still sets the art style; only those shown in the scene are named as who to draw
                from direction.entities import lead_view
                reference_input = [lead_view(picture) for picture in references]
                names = [str((reference_subjects[k] or {}).get('who') or 'the main character') if k in wanted else None
                         for k in range(len(references))]
                # a lead the writer tagged is named by that picture in the scenes that show them, and only there
                from direction.entities import photo_index
                files = [Path(p).name for p in unique.values()]
                tagged = {photo_index(e.get('photo'), files): e for e in (story or {}).get('entities') or [] if e.get('photo')}
                for k, lead in tagged.items():
                    if k is not None and k < len(names):
                        names[k] = lead['name'] if scene_of(i) in lead.get('segments', []) else None
            own = segment_references.get(scene_of(i), []) if model_spec(model)['references'] else []
            # greenscreen scenery keeps people small and below the skyline: only objects get their picture there
            # the cast's sheet is painted too (a changed form of the lead is painted from it), but the scene is given
            # the lead's photo, not the sheet
            needed = [e for e in segment_entities(story, scene_of(i), painted=False, pictured=True) if e['id'] not in entity_pictures
                      and (not matte or e.get('kind') == 'object')] if use_entities else []
            if needed:  # each with the project's pictures in one role only (see paint_entities)
                entity_pictures.update(paint_entities(pipe, model, story_manifest, job, needed, list(zip(references, reference_kinds)), torch, ocr,
                                                      min(total, gpu_memory.dedicated_memory(torch)[0]+torch.cuda.memory_reserved())/2**30,
                                                      names=[Path(p).name for p in unique.values()]))
                story = load_story(story_manifest)  # the pictures just painted are recorded in it
            from direction.entities import KINDS, uses_entity_sheet  # characters, then objects, then places claim the reference slots
            shown = sorted([e for e in segment_entities(story, scene_of(i), painted=False, pictured=True) if e['id'] in entity_pictures
                            and uses_entity_sheet(e, likeness, bool(reference_input)) and (not matte or e.get('kind') == 'object')], key=lambda e: KINDS.index(e.get('kind', 'place')))
            # greenscreen: if the sky will not key twice with the reference sheets, the last try paints without them
            plain_input = reference_input
            plain_prompt = with_reference_role(job['prompts'][i], likeness) if reference_input else job['prompts'][i]
            unkeyed = 0
            if own or shown or names or reference_input:
                # the project's pictures lead: they set the art style of the whole scene (see reference_role)
                shown, rest = choose_references(len(own), shown, reference_input, likeness,
                                                limit=model_spec(model).get('max_references', 3))
                from direction.entities import reference_order
                subjects, places = reference_order(shown)
                from direction.entities import place_picture  # each scene at a place gets its next view of it
                reference_input = (rest+[entity_pictures[e['id']] for e in subjects]+own
                                   + [place_picture(e, scene_of(i)) or entity_pictures[e['id']] for e in places])
                from direction.entities import reference_tags
                tagged = reference_tags(job['prompts'][i], segment_reference_names.get(scene_of(i), []) if own else [], len(rest), shown)
                prompt = reference_role(tagged, shown, len(own), len(rest), likeness, names)
                if shown or own:
                    print(f"Illustration {shown_number(i)} references: {', '.join(e['name'] for e in shown) or 'none'}"
                          + (f" + {len(own)} of its own picture{'s' if len(own) != 1 else ''}" if own else ''), flush=True)
                    sent = ([f'project picture {k+1}' for k in range(len(rest))]+[e['name'] for e in subjects]
                            + (segment_reference_names.get(scene_of(i), []) if own else [])+[e['name'] for e in places])
                    print(f"Illustration {shown_number(i)} pictures sent to the model, in order: {', '.join(sent)}", flush=True)
            else:
                from direction.entities import reference_tags
                plain = reference_tags(job['prompts'][i])   # no picture reaches the model here: every @tag goes
                prompt = with_reference_role(plain, likeness) if reference_input else plain
            best_path=None;best_lettering=None;best_rank=None
            seed=secrets.randbelow(2**31) if random_seeds else job['seed']+i
            print(f'{label} {caption(i)} seed: {seed}', flush=True)
            for attempt in range(3):
                retry_prompt=prompt
                if attempt and manifest.parent.parent.name=='video.artwork':
                    retry_prompt+=' Replace any written sign or neon lettering with unlettered geometric light tubes. All signs, screens, walls and panels are completely blank. No alphabetic marks, captions, numerals or logos anywhere.'
                inputs = reference_input
                if matte and attempt == 2 and unkeyed >= 2 and shown:
                    inputs, retry_prompt = plain_input, plain_prompt
                    print(f'Illustration {i+1}: the sky did not key with the reference pictures; painting without them.', flush=True)
                if attempt and matte:
                    retry_prompt+=' The whole sky above the skyline must be one flat, uniform pure #00FF00 chroma-key green with nothing in it.'
                image = pipe(prompt=retry_prompt, **inference_options(model, inputs or canvas),
                    width=layout['image_width'], height=layout['image_height'],
                    num_inference_steps=job['steps'],
                    generator=torch.Generator('cpu').manual_seed(seed+attempt*10000),
                    callback_on_step_end=diffusion_callback(i, len(job['prompts']), attempt, 3, job['steps'], label, caption(i))).images[0]
                lettering = detected_lettering(ocr, image)
                screened = True
                if matte:
                    from artwork.greenscreen import usable
                    screened = usable(image)
                    unkeyed += not screened
                if not lettering and screened:
                    temporary=raw.with_name(raw.stem+'.tmp.png')
                    image.save(temporary);temporary.replace(raw)
                    emit('illustrations', (i+1)/len(job['prompts']), image=i+1, images=len(job['prompts']), message=f'{label} {caption(i)} saved', artifact=str(raw))
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
                print(f'{label} {caption(i)} flagged for image review after three failed attempts; continuing the batch.',flush=True)
                emit('illustrations',(i+1)/len(job['prompts']),image=i+1,images=len(job['prompts']),message=f'{label} {caption(i)} saved for review',artifact=str(raw))
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
    emit('cutouts', 0, message=f'Removing backgrounds from {len(missing)} illustration{"s" if len(missing) != 1 else ""} on the CPU')
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
        emit('cutouts', (missing.index(i)+1)/len(missing), message=f'Background removed: illustration {i+1} ({missing.index(i)+1} of {len(missing)})', artifact=str(manifest.parent/f'{i:03d}.png'))

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
