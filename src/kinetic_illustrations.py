"""Lyric-specific FLUX.2 generation, style references and transparent cutouts."""
from __future__ import annotations

from project_paths import default_model_cache
import argparse
import gc
import gpu_memory
import hashlib
import secrets
import json
import os
import re
from pathlib import Path
from project_paths import PROJECT_ROOT
import shutil
import subprocess
import sys
from PIL import Image

from kinetic_progress import emit, diffusion_callback
from kinetic_layout import illustration_layout

from image_models import MODEL, model_spec
STYLE_PROMPT = ('Delicate linework and soft painterly shading. For humans: expressive faces, flowing hair, '
                'graceful transparent fabric folds. Visual style & mood: Modern, fun, happy, bright, uplifting mood.')
STYLE = ('Confident clean delicate ink contours, elegant realistic proportions and soft '
         'painterly shading inspired by Alphonse Mucha. For human subjects only, use '
         'expressive faces and naturally flowing hair where appropriate. '
         'Natural, grounded subjects. No surrealism, flowers, foliage, ornament, '
         'frames, borders, lettering, captions, signatures, logos or text. Objects have no '
         'printed marks; signs, books and screens have blank surfaces. Isolated subjects on plain white, '
         'no scenery, shadows or glow. Keep the complete silhouette inside the image.')


def subject_kind(subject):
    subject = re.sub(r'\b(?:no|without|excluding)\b[^.;]*', '', subject, flags=re.I)
    subject = re.sub(r'\bportrait[-\s]+(?:format|orientation)\b', '', subject, flags=re.I)
    human = re.search(r'\b(woman|women|man|men|person|people|adults?|children|child|girls?|boys?|crowd|figures?|faces?|portraits?|head|shoulders|eyes)\b', subject, re.I)
    detail = re.search(r'\b(hand|hands|arm|arms|mouth|mouths|lips|ears|feet)\b', subject, re.I)
    return 'people' if human else 'detail' if detail else 'object'


REFERENCE_ROLE = ('Reference image: match only its rendering technique, brushwork and colour treatment; '
                  'do not copy its people, objects or composition. ')
REFERENCE_MARKERS = ('REFERENCE ROLE', 'Reference images guide', 'Reference image:')


def uses_reference(artwork_mode, subject):
    """Every picture is conditioned on the style references except cutout object studies, which must stay
    isolated on plain white for a clean cutout."""
    return not (artwork_mode in (None, 'cutout') and subject_kind(subject) == 'object')


def with_reference_role(prompt, likeness=False):
    """Lead with what the reference image is for, unless the prompt already says it. It goes first so FLUX.2's
    512-token cut can never drop it."""
    from reference_character import CHARACTER_ROLE
    if any(marker in prompt for marker in REFERENCE_MARKERS):
        return prompt
    return (CHARACTER_ROLE if likeness else REFERENCE_ROLE)+prompt


def image_prompt(subject, layout, style_prompt=STYLE_PROMPT, has_references=False, likeness=False):
    if layout.get('artwork_mode') == 'verse':
        from verse_backgrounds import image_prompt as background_prompt
        return background_prompt(subject, layout, style_prompt)
    if layout.get('artwork_mode') == 'fullscreen':
        technique = (style_prompt if subject_kind(subject) != 'object' else
                     'Delicate ink contours, painterly shading, luminous color and elegant material textures.')
        return ('Paint this subject in a coherent environment: '+subject+'. '+layout['visual_prompt']+
                ' Rendering technique: '+technique+'. '
                +('The reference image shows the main character: keep their face, hair, skin tone, age and gender, with clothing and pose from this scene. '
                  if likeness else 'Reference images guide technique only, never subject matter. ')+
                'Preserve natural anatomy for any described people. Each person’s face and body match their stated gender; women have smooth faces with no moustache, beard or stubble. Do not add people who are not described in the scene. '
                'No text, captions, watermarks or printed marks.')
    kind = subject_kind(subject)
    if kind == 'object':
        subject = re.sub(r'\b(?:no|without|excluding)\b[^.;]*', '', subject, flags=re.I).strip(' ,.;')
        shape = 'Tall portrait-format' if layout['image_height'] > layout['image_width'] else 'Wide landscape-format'
        return (
            'OBJECT STUDY: '+subject+'. '
            'Delicate confident ink contours, soft hand-painted gouache and watercolor shading, '
            'muted pigments, elegant natural proportions, carefully described material textures. '
            +shape+' composition. The specified physical object fills the canvas, centered with '
            'a small clean margin. Isolated on uniform white. '
            'Render exactly these physical forms and nothing else: '+subject+'. '
            'Unlettered and unmarked surfaces.'
        )
    scope = ('Show only the specified body detail, not a complete person, head or added character. '
             if kind == 'detail' else
             'Objects only. No people, human faces, hands, bodies or added characters. '
             if kind == 'object' else 'Show only the described people and objects. ')
    return (
        'Draw only this visual scene: '+subject.strip()+'. '+STYLE+' '+layout['visual_prompt']+' '
        + ('REFERENCE ROLE: the main character and rendering technique. '+style_prompt+' '
           'Give the main person the reference person’s face, hairstyle, skin tone, age and gender. '
           'Do not copy reference clothes, pose, objects or composition. ' if has_references and likeness else
           'REFERENCE ROLE: rendering technique ONLY. '+style_prompt+' '
           'Preserve only brushwork, ink quality, shading technique and color treatment. '
           'Do not copy reference people, clothes, objects or composition. ' if has_references else 'Rendering technique: '+style_prompt+' ')
        + 'FINAL SUBJECT TO DRAW: '+subject.strip()+'. '+scope
        + 'Anatomically accurate hands with exactly five distinct separated fingers including one thumb on each hand; clean joints, no extra digits, no fused fingers. Each person’s face and body match their stated gender; women have smooth faces with no moustache, beard or stubble. Simple readable poses. '
        'No written words or printed marks anywhere. No additional subjects.'
    )


def prepare_job(data, folder, line_count, model=MODEL, references=None, steps=None, seed=42,
                style_prompt=STYLE_PROMPT, director_model='auto', lookup_only=False,
                width=1920, height=1080, cinematic=False, artwork_mode="cutout", image_instructions='',
                reference_use='style', vision_model=''):
    from image_instruction_cleanup import clean_legacy_imported_meaning
    image_instructions = clean_legacy_imported_meaning(image_instructions)
    if steps is None:steps=model_spec(model)['steps']
    from kinetic_director import local_json
    from song_structure import analyze,grouped_lines,group_contexts
    structured=any('section_id' in line for line in data)
    config_path=Path(folder).parent/'config.json'
    try:run_config=json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError,ValueError):run_config={}
    if structured and config_path.is_file():
        config=json.loads(config_path.read_text(encoding='utf-8'))
        if config.get('start_step') in ('images','review','render'):
            from active_artwork import select_manifest
            try:structured=bool(json.loads(select_manifest(Path(folder).parent,config).read_text(encoding='utf-8')).get('line_groups'))
            except (OSError,ValueError):structured=False
    structure=analyze(None,director_model,data) if structured else None
    indices=grouped_lines(data,line_count,structure) if structured else [list(range(i,min(len(data),i+line_count))) for i in range(0,len(data),line_count)]
    groups=[' / '.join(data[i]['text'] for i in group) for group in indices]
    references = [Path(p).resolve() for p in (references or [])]
    layouts = [illustration_layout(i, width, height, cinematic, artwork_mode, seed) for i in range(len(groups))]
    signature = dict(version=36 if structured else 35 if artwork_mode == 'verse' else 34, director_model=director_model, artwork_mode=artwork_mode, groups=groups, model=model, steps=steps, seed=seed,
                     width=width, height=height, cinematic=cinematic, layouts=layouts,
                     style=STYLE, style_prompt=style_prompt, image_instructions=image_instructions,
                     references=[hashlib.sha256(p.read_bytes()).hexdigest() for p in references])
    if structured:signature.update(line_groups=indices,song_structure=structure)
    likeness = reference_use == 'likeness' and bool(references)
    if likeness:signature['reference_use'] = 'likeness'
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20]
    folder = Path(folder)/key
    manifest = folder/'illustrations.json'
    if lookup_only or (manifest.exists() and not fresh_prompts(manifest, run_config)):
        return manifest
    if manifest.exists():
        # Same settings as a finished run, but the person asked for new prompts: its images go aside, not away.
        from active_artwork import archive_folder
        archive_folder(folder)
    from gpu_models import resolve_prompt_model
    director_model = resolve_prompt_model(local_json, director_model)
    character = ''
    if likeness and vision_model:
        from reference_character import describe
        from ollama_gpu import gpu_chat, unload_model
        try:
            emit('song', .8, message=f'Describing the main character from the reference image with {vision_model}')
            character = describe(gpu_chat, vision_model, references[0])
            print(f'Main character from the reference image: {character or "no clear person found"}', flush=True)
        except (OSError, ValueError) as exc:
            print(f'Warning: the reference person could not be described, so scene prompts will not name them: {exc}', flush=True)
        finally:
            try:unload_model(vision_model)
            except (OSError,ValueError) as exc:print(f'Warning: vision model cleanup: {exc}',flush=True)
    elif likeness:
        print('Warning: choose an Image Quality Scoring (VL) model so scene prompts know who the reference image shows.', flush=True)
    if character:
        from reference_character import casting_rule
        image_instructions = (casting_rule(character)+image_instructions).strip()
    from verse_backgrounds import DIRECTOR_PROMPT, LANGUAGE_RULE, PEOPLE_RULE
    director_options = dict(num_ctx=8192)
    if seed is not None:
        director_options['seed'] = int(seed % (2**31))
    payload = dict(model=director_model, stream=False, think=False, keep_alive=-1, options=director_options,
        format={'type': 'object', 'properties': {'subjects': {'type': 'array',
                'minItems': len(groups), 'maxItems': len(groups), 'items': {'type': 'string'}}},
                'required': ['subjects']},
        messages=[dict(role='system', content=(DIRECTOR_PROMPT if artwork_mode == 'verse' else LANGUAGE_RULE+PEOPLE_RULE+(
            'Translate each lyric group into one distinct English visual description for an illustrator. '
            'The lyrics are the sole source of subject matter. Interpret their meaning, including Tagalog. '
            'Choose the most meaningful concrete subject: an everyday object, architectural detail, a place, '
            'weather or nature, a small grounded vignette, or a person when the lyric shows someone. '
            'Choose subjects that best express the lyrics; vary compositions naturally where the meaning allows. '
            'Describe only visible shapes, action, material, color, lighting and mood, in a detailed 120 to 180 word description. '
            'For people, specify pose and suitable ordinary clothing; for objects, specify form and material. '
            'Do not copy clothes or content from style references. '
            'Never quote, translate verbatim or transcribe lyric lines into the description. '
            'Never request written words or captions. Signs, books and screens must be blank. '
            'No graffiti, inscriptions, visualized sound waves, invisible substances or ghostly figures. '
            'Express abstract ideas through ordinary physical objects, places or nature. '
            'Each visual description must differ; no repeated scenes, lettering, flowers or surrealism. '
            'Match the assigned orientation and placement. Direct gestures, gaze or an object diagonal '
            'toward the available space. Do not require a person for a compositional direction. '
            + ('Describe coherent scenery. ' if artwork_mode=='fullscreen' else 'Do not specify a background. ')
            + 'Use additional image instructions only when they fit the lyric meaning. Return only JSON with a subjects array in input order.'))),
            dict(role='user', content=json.dumps([dict(lyrics=group, layout=layout['prompt'], image_instructions=image_instructions)
                 for group, layout in zip(groups, layouts)]))])
    if character:
        payload['messages'][0]['content'] += ' '+casting_rule(character)
    from subject_director import request_subjects, repair_duplicate_subjects
    from ollama_gpu import gpu_chat, unload_model
    reference_images = bool(references) and model_spec(model)['references']
    meanings = []
    gist = ''
    from prompt_checkpoint import Checkpoint
    checkpoint = Checkpoint(folder, [line['text'] for line in data], run_config)
    song = checkpoint.get('song')
    if song:
        saved_indices = song.get('indices')
        expected = ([' / '.join(data[i]['text'] for i in group) for group in saved_indices]
                    if saved_indices and all(0 <= i < len(data) for group in saved_indices for i in group) else groups)
        if song.get('groups') != expected or len(song.get('layouts') or []) != len(expected):
            print('Saved prompting work does not match these lyric lines; starting prompting from the song.', flush=True)
            checkpoint.data.clear(); song = None
    try:
        contexts=None
        from song_gist import song_gist, attach_gist
        if song:
            gist = song['gist']
            if song.get('indices'):
                structured, structure, indices = True, song['structure'], song['indices']
            groups, layouts = song['groups'], song['layouts']
        else:
            gist = song_gist(gpu_chat, director_model, [line['text'] for line in data], image_instructions)
            if structured:
                emit('song',.5,message=f'Finding the verses, choruses and bridges in {len(data)} lyric lines')
                structure=analyze(gpu_chat,director_model,data)
                indices=grouped_lines(data,line_count,structure)
                groups=[' / '.join(data[i]['text'] for i in group) for group in indices]
                layouts=[illustration_layout(i,width,height,cinematic,artwork_mode,seed) for i in range(len(groups))]
            checkpoint.save('song', dict(gist=gist, indices=indices if structured else None, structure=structure,
                                         groups=groups, layouts=layouts))
        if structured:
            contexts=group_contexts(data,indices,structure)
            signature.update(groups=groups,layouts=layouts,line_groups=indices,song_structure=structure)
            payload['format']['properties']['subjects'].update(minItems=len(groups),maxItems=len(groups))
            payload['messages'][1]['content']=json.dumps([dict(lyrics=g,layout=l['prompt'],section_context=c,image_instructions=image_instructions) for g,l,c in zip(groups,layouts,contexts)])
        else:
            signature.update(groups=groups,layouts=layouts)
            payload['messages'][1]['content']=json.dumps([dict(lyrics=g,layout=l['prompt'],image_instructions=image_instructions) for g,l in zip(groups,layouts)])
        if artwork_mode == 'verse':
            from verse_backgrounds import lyric_meanings
            meanings = checkpoint.get('meanings')
            if not meanings or len(meanings) != len(groups):
                meanings = lyric_meanings(gpu_chat, director_model, groups, contexts=contexts,
                                         image_instructions=image_instructions, song_gist=gist)
                checkpoint.save('meanings', meanings)
            payload['messages'][1]['content'] = json.dumps([
                dict(lyrics=group,lyric_meaning=meaning,layout=layout['prompt'],section_context=contexts[i] if contexts else None,image_instructions=image_instructions)
                for i,(group,meaning,layout) in enumerate(zip(groups,meanings,layouts))])
        else:
            checkpoint.save('meanings', [])
        attach_gist(payload, gist)
        from kinetic_progress import counted
        subjects = checkpoint.get('scenes')
        if not subjects or len(subjects) != len(groups):
            subjects = request_subjects(gpu_chat, payload, max_words=240 if artwork_mode == 'verse' else 180,
                                        progress=counted('scenes', 0, .6, 'Writing the scene for lyric group',
                                                         names=groups))
            subjects = repair_duplicate_subjects(gpu_chat, payload, subjects)
            checkpoint.save('scenes', subjects)
        prompts = [image_prompt(subject, layout, style_prompt, reference_images, likeness)
                   + (' Additional image direction: '+image_instructions if image_instructions else '')
                   for subject, layout in zip(subjects, layouts)]
        fitted = checkpoint.get('fit')
        if fitted and len(fitted) == len(groups):
            prompts = fitted
        else:
            from prompt_fit import fit_prompts
            prompts = fit_prompts(gpu_chat, director_model, model, prompts, style_prompt)
            checkpoint.save('fit', prompts)
    finally:
        try:unload_model(director_model)
        except (OSError,ValueError) as exc:print(f'Warning: prompt model cleanup: {exc}',flush=True)
    if (not isinstance(subjects, list) or len(subjects) != len(groups)
            or any(not isinstance(s, str) or not s.strip() for s in subjects)):
        raise ValueError('Illustration director must return one subject per lyric group.')
    folder.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(dict(signature, reference_paths=[str(p) for p in references],
        lyric_meanings=meanings, song_gist=gist, visual_descriptions=subjects,
        reference_use='likeness' if likeness else 'style', main_character=character, prompt_model=director_model,
        reference_modes=['image_conditioning' if reference_images and uses_reference(artwork_mode, s) else 'technique_prompt_only' for s in subjects],
        prompts=prompts), ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def fresh_prompts(manifest, config):
    """True when this run restarts at Prompts but `manifest` was written before it began, so it must be rewritten
    even though the settings, and so its folder, are unchanged."""
    return (config.get('start_step') == 'prompts' and Path(manifest).is_file()
            and Path(manifest).stat().st_mtime < config.get('run_started', 0))


def saved_prompts(data, folder, args):
    """For a studio restart at Images: the saved run's manifest, kept for its prompts, with every image to make again.

    Settings decide which manifest a normal run uses, so a changed setting would rewrite the prompts and an unchanged
    one would find the old images and skip generation; the studio has already moved those images aside."""
    config_path = Path(folder).parent/'config.json'
    try:config = json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):return None
    if config.get('start_step') != 'images':
        return None
    from active_artwork import select_manifest, record_manifest
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
        from prompt_fit import over_budget, refit
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
    from artwork_resume import completed_artwork
    from generation_queue import has_pending
    resumed=completed_artwork(data,folder,args)
    if resumed is not None:
        from active_artwork import record_manifest
        manifest=resumed[0].parent/'illustrations.json';record_manifest(manifest)
        emit('illustrations',1,message='Using saved artwork',manifest=str(manifest))
        from lettering_review import needs_validation,require_review
        if needs_validation(resumed,Path(folder).parent) or has_pending(Path(folder).parent):
            cache=Path(args.image_cache or str(default_model_cache())).resolve()
            subprocess.run([sys.executable,'-u',str(Path(__file__).resolve()),str(manifest),'--cache',str(cache)],check=True)
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
        subprocess.run([sys.executable, '-u', str(Path(__file__).resolve()), str(reused), '--cache', str(cache)], check=True)
        job = json.loads(reused.read_text(encoding='utf-8'))
        paths = [reused.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
        from lettering_review import require_review
        require_review(paths, args)
        return paths
    manifest = prepare_job(*job_args, lookup_only=True, **layout_args)
    try:run_config = json.loads((Path(folder).parent/'config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):run_config = {}
    if manifest.exists() and not fresh_prompts(manifest, run_config):
        job = json.loads(manifest.read_text(encoding='utf-8'))
        paths = [manifest.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
        from lettering_review import needs_validation
        if paths and all(path.is_file() for path in paths) and not needs_validation(paths,Path(folder).parent) and not has_pending(Path(folder).parent):
            from active_artwork import record_manifest
            record_manifest(manifest)
            emit('illustrations',1,message='Using cached lyric-specific artwork',manifest=str(manifest))
            print('Using cached lyric-specific artwork.', flush=True)
            from lettering_review import require_review
            require_review(paths,args)
            return paths
    cache = (args.image_cache or Path(os.environ.get('HF_HOME', Path.home()/'.cache/huggingface'))).resolve()
    existing = cache
    while not existing.exists():
        existing = existing.parent
    cached = cache/('models--'+args.image_model.replace('/', '--'))/'snapshots'
    required = next((m['disk_gb'] for m in __import__('image_models').MODELS if m['id']==args.image_model), 40)
    if not cached.exists() and shutil.disk_usage(existing).free < required*2**30:
        raise ValueError(f'Allow approximately {required} GiB for this model. Use --image-cache DRIVE:/models.')
    emit('song', 0, message='Reading the whole song before writing image prompts')
    manifest = prepare_job(*job_args, **layout_args)
    from active_artwork import record_manifest
    record_manifest(manifest)
    emit('fit',1,message='Image prompts ready',manifest=str(manifest))
    gc.collect()
    if 'torch' in sys.modules and sys.modules['torch'].cuda.is_available():
        sys.modules['torch'].cuda.empty_cache()
    command = [sys.executable, '-u', str(Path(__file__).resolve()), str(manifest), '--cache', str(cache)]
    subprocess.run(command, check=True)
    job = json.loads(manifest.read_text(encoding='utf-8'))
    paths=[manifest.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
    from lettering_review import require_review
    require_review(paths,args)
    return paths




def remove_negative_space(source, biref_session):
    """Remove outer staging negative space while preserving drawn background features, props, and setting."""
    from rembg import remove
    import scipy.ndimage as ndi
    import numpy as np

    biref_cutout = remove(source, session=biref_session).convert('RGBA')
    biref_alpha = np.array(biref_cutout.getchannel('A'))

    arr = np.array(source.convert('RGB'))
    h, w, _ = arr.shape

    r, g, b = arr[..., 0].astype(float), arr[..., 1].astype(float), arr[..., 2].astype(float)
    max_c = np.maximum(np.maximum(r, g), b)
    min_c = np.minimum(np.minimum(r, g), b)
    sat = np.where(max_c == 0, 0, (max_c - min_c) / (max_c + 1e-5))
    val = max_c

    corners = np.array([arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]], dtype=float)
    light_corners = [c for c in corners if np.mean(c) > 210]
    corner_match = np.zeros((h, w), dtype=bool)
    if light_corners:
        ref_corner = np.mean(light_corners, axis=0)
        diff = np.linalg.norm(arr.astype(float) - ref_corner, axis=-1)
        corner_match = diff < 22

    is_neg_candidate = ((val > 232) & (sat < 0.10)) | corner_match

    border_mask = np.zeros((h, w), dtype=bool)
    border_mask[0, :] = True
    border_mask[-1, :] = True
    border_mask[:, 0] = True
    border_mask[:, -1] = True

    structure = ndi.generate_binary_structure(2, 2)
    labeled, _ = ndi.label(is_neg_candidate, structure=structure)
    border_labels = np.unique(labeled[border_mask])
    border_labels = border_labels[border_labels != 0]

    is_negative_space = np.isin(labeled, border_labels)
    painted_content = ~is_negative_space
    painted_content = ndi.binary_fill_holes(painted_content)

    dist_inside = ndi.distance_transform_edt(painted_content)
    edge_alpha = np.clip(dist_inside * 128, 0, 255).astype(np.uint8)

    combined_alpha = np.maximum(biref_alpha, edge_alpha)
    combined_alpha[is_negative_space & (val > 238)] = 0
    from staging_matte import staging_alpha
    staging = staging_alpha(source)  # a flat staging backdrop of any colour (grey, beige...), not only near-white
    if staging is not None:
        combined_alpha = np.minimum(combined_alpha, (staging[0]*255).astype(np.uint8))

    result = source.convert('RGBA')
    result.putalpha(Image.fromarray(combined_alpha))
    return result


def load_pipeline(model, cache, torch, offload=False):
    """Quantize on CUDA; offload inactive components to RAM under pressure."""
    import diffusers
    spec = model_spec(model)
    if not torch.cuda.is_available():
        raise ValueError('CUDA is required. CPU fallback is disabled.')
    free, _ = gpu_memory.dedicated_memory(torch)
    required = int(spec['vram_gib']*2**30)
    if free < required + .5*2**30:
        offload = True
        print(f'GPU-only estimate: {spec["vram_gib"]} GiB plus 0.5 GiB reserve; '
              f'{free/2**30:.1f} GiB is free. Enabling automatic RAM offload.',flush=True)
    _, total = gpu_memory.dedicated_memory(torch)
    limit=min(.98,(free+torch.cuda.memory_allocated()-.5*2**30)/total)
    torch.cuda.set_per_process_memory_fraction(max(.01,limit))
    pipeline_type = getattr(diffusers, spec['pipeline'])
    options = dict(torch_dtype=torch.bfloat16, cache_dir=cache, device_map='cuda',
                   max_memory={torch.cuda.current_device():int(free-.5*2**30)})
    if spec['quantize']:
        options['quantization_config'] = diffusers.PipelineQuantizationConfig(
            quant_backend='bitsandbytes_4bit',
            quant_kwargs=dict(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                              bnb_4bit_compute_dtype=torch.bfloat16),
            components_to_quantize=spec['quantize'])
    print(f'Loading {model} with CUDA quantization'+(' / 4-bit weights' if spec['quantize'] else '')
          +(' / automatic RAM offload' if offload else ' / GPU resident'),flush=True)
    try:
        pipe = pipeline_type.from_pretrained(model, **options)
    except Exception as exc:
        if 'gated' in str(exc).lower() or '401' in str(exc) or '403' in str(exc):
            raise ValueError(f'Access required: accept the model terms at https://huggingface.co/{model} '
                             'and sign in with hf auth login, then retry.') from exc
        raise
    for component in pipe.components.values():
        for device in getattr(component,'hf_device_map',{}).values():
            if str(device) in ('cpu','disk','meta'):
                raise ValueError('CUDA model preparation placed a component on CPU/disk/meta before offload hooks could be installed.')
        if hasattr(component,'parameters'):
            if any(parameter.device.type!='cuda' for parameter in component.parameters()):
                raise ValueError('Image weights must finish CUDA preparation before automatic offload hooks can be installed.')
    remaining, _ = gpu_memory.dedicated_memory(torch)
    if not spec.get('quantize'):
        offload = offload or remaining < 3*2**30
        if offload:
            staged=[]
            for name,component in pipe.components.items():
                if name not in ('transformer','unet') and hasattr(component,'parameters'):
                    component.to('cpu');staged.append(name)
            if staged:
                gc.collect();torch.cuda.empty_cache()
                print('Staged inactive components in RAM before image-layer preparation: '+', '.join(staged),flush=True)
    if spec['pipeline']=='QwenImagePipeline':
        from qwen_precision import protect_image_modulation
        protect_image_modulation(pipe,model,cache,torch)
    if offload and not spec.get('quantize') and not getattr(pipe, 'hf_device_map', None):
        try:
            pipe.enable_model_cpu_offload(gpu_id=torch.cuda.current_device(), device='cuda')
            print('Automatic image offload enabled: inactive components use RAM; computation stays on CUDA.', flush=True)
        except Exception as exc:
            print(f'Warning: Automatic image offload could not be installed ({exc}).', flush=True)
    pipe.vae.enable_tiling()
    if hasattr(pipe.vae,'enable_slicing'):pipe.vae.enable_slicing()
    return pipe, spec['guidance']


def inference_options(model, references):
    spec = model_spec(model)
    if spec['references']:
        from prompt_fit import FLUX_TOKENS
        return dict(image=references or None, guidance_scale=spec['guidance'], max_sequence_length=FLUX_TOKENS)
    if spec['pipeline'] == 'QwenImagePipeline':
        return dict(true_cfg_scale=spec['guidance'], max_sequence_length=1024, negative_prompt=
                    'extra limbs, extra fingers, fused fingers, malformed anatomy, mixed male and female anatomy on one body, moustache or beard on a woman, nudity, see-through clothing, lettering, watermark, grainy, noisy, pixelated, blurry, over-sharpened, low quality')
    result = dict(guidance_scale=spec['guidance'])
    if spec['pipeline'] == 'FluxPipeline':
        result['max_sequence_length'] = 512
    return result


def release_pipeline(pipe, torch):
    try:
        torch.cuda.synchronize()
    finally:
        if pipe is not None:
            pipe.maybe_free_model_hooks()


def detected_lettering(ocr, image):
    """Ignore tiny low-confidence shape readings; flag substantial drawn lettering."""
    import numpy as np
    results, _ = ocr(np.asarray(image.convert('RGB')))
    readings = [dict(text=entry[1], confidence=float(entry[2])) for entry in (results or [])
                if entry[2] >= .82 and len(re.sub(r'\W', '', entry[1])) >= 3]
    return readings if sum(len(re.sub(r'\W', '', entry['text'])) for entry in readings) >= 6 else []


def run_job(manifest, cache):
    from model_lifecycle import current_session
    if current_session() is not None:
        return current_session().run_generation(_run_job, manifest, Path(cache).expanduser().resolve())
    from filelock import FileLock
    from active_artwork import record_manifest
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
    # "Randomize per image" in the studio: each picture gets its own seed instead of run seed + index.
    random_seeds = False
    if manifest.parent.parent.name == 'video.artwork':
        try:random_seeds = bool(json.loads((manifest.parent.parent.parent/'config.json').read_text(encoding='utf-8')).get('randomize_seed'))
        except (OSError, ValueError):pass
    free, total = gpu_memory.dedicated_memory(torch)
    print(f'GPU memory before image model: {free/2**30:.1f} GiB free / {total/2**30:.1f} GiB total.', flush=True)
    try:
        import psutil
        ram = psutil.virtual_memory()
        print(f'System memory before image model: {ram.available/2**30:.1f} GiB free / {ram.total/2**30:.1f} GiB RAM, '
              f'{psutil.swap_memory().free/2**30:.1f} GiB page file free.', flush=True)
    except Exception:
        pass
    emit('model', 0, message='Loading image model; first use may download weights')
    from model_lifecycle import current_session
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
        for path in job['reference_paths']:
            unique.setdefault(hashlib.sha256(Path(path).read_bytes()).hexdigest(), path)
        for path in unique.values():
            with Image.open(path) as source:
                reference = source.convert('RGB')
            reference.thumbnail((1024, 1024))
            references.append(reference)
        for i in missing:
            selected=manifest.parent/f'{i:03d}.png'
            if selected.exists() and selected.with_suffix('.selection.json').exists():
                emit('illustrations',(i+1)/len(job['prompts']),message=f'Keeping your replacement for illustration {i+1}')
                continue
            raw = manifest.parent/f'{i:03d}.raw.png'
            if raw.exists():
                with Image.open(raw) as cached:
                    if not detected_lettering(ocr, cached):
                        continue
            emit('illustrations', i/len(job['prompts']), image=i+1, images=len(job['prompts']), message=f'Generating illustration {i+1}/{len(job["prompts"])}')
            print(f'Generating unique illustration {i+1}/{len(job["prompts"])}...', flush=True)
            layout = dict(job['layouts'][i])
            from gpu_models import image_dimensions
            layout['image_width'],layout['image_height'] = image_dimensions(layout['image_width'],layout['image_height'],min(total,gpu_memory.dedicated_memory(torch)[0]+torch.cuda.memory_reserved())/2**30)
            reference_input = references if model_spec(model)['references'] and uses_reference(job.get('artwork_mode'), job['visual_descriptions'][i]) else []
            best_path=None;best_lettering=None
            seed=secrets.randbelow(2**31) if random_seeds else job['seed']+i
            print(f'Illustration {i+1} seed: {seed}', flush=True)
            for attempt in range(3):
                retry_prompt=with_reference_role(job['prompts'][i], job.get('reference_use') == 'likeness') if reference_input else job['prompts'][i]
                if attempt and manifest.parent.parent.name=='video.artwork':
                    retry_prompt+=' Replace any written sign or neon lettering with unlettered geometric light tubes. All signs, screens, walls and panels are completely blank. No alphabetic marks, captions, numerals or logos anywhere.'
                image = pipe(prompt=retry_prompt, **inference_options(model, reference_input),
                    width=layout['image_width'], height=layout['image_height'],
                    num_inference_steps=job['steps'],
                    generator=torch.Generator('cpu').manual_seed(seed+attempt*10000),
                    callback_on_step_end=diffusion_callback(i, len(job['prompts']), attempt, 3, job['steps'])).images[0]
                lettering = detected_lettering(ocr, image)
                if not lettering:
                    temporary=raw.with_name(raw.stem+'.tmp.png')
                    image.save(temporary);temporary.replace(raw)
                    emit('illustrations', (i+1)/len(job['prompts']), image=i+1, images=len(job['prompts']), message=f'Illustration {i+1} saved', artifact=str(raw))
                    break
                rejected_path=manifest.parent/f'{i:03d}.rejected-{attempt+1}.png'
                image.save(rejected_path)
                if best_lettering is None or sum(len(r['text']) for r in lettering)<sum(len(r['text']) for r in best_lettering):
                    best_path,best_lettering=rejected_path,lettering
                print(f'Lettering detected in illustration {i+1}; retrying with a new seed.', flush=True)
            else:
                temporary=raw.with_name(raw.stem+'.tmp.png')
                shutil.copy2(best_path,temporary);temporary.replace(raw)
                from lettering_review import mark_lettering
                mark_lettering(raw,best_lettering)
                print(f'Illustration {i+1} flagged for image review after three lettering detections; continuing the batch.',flush=True)
                emit('illustrations',(i+1)/len(job['prompts']),image=i+1,images=len(job['prompts']),message=f'Illustration {i+1} saved for lettering review',artifact=str(raw))
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
            from lettering_review import propagate_lettering
            propagate_lettering(manifest.parent/f'{i:03d}.raw.png',target)
            emit('cutouts', 1, message=f'Full-screen artwork {i+1} ready', artifact=str(target))
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
        from lettering_review import propagate_lettering
        propagate_lettering(manifest.parent/f'{i:03d}.raw.png',target)
        emit('cutouts', (missing.index(i)+1)/len(missing), message=f'Background removed: illustration {i+1} ({missing.index(i)+1} of {len(missing)})', artifact=str(manifest.parent/f'{i:03d}.png'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--cache', type=Path, required=True)
    options = parser.parse_args()
    try:
        from studio_worker import generate_and_review
        generate_and_review(options.manifest, options.cache)
    except Exception as exc:
        parser.exit(1, f'Illustration generation failed: {exc}\n')
