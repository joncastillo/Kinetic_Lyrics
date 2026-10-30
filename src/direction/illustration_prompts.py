"""Illustration subjects and image prompts, written by the local LLM from the lyrics."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from render.layout import illustration_layout
from models.image.catalog import MODEL, model_spec


STYLE_PROMPT = ('Use the supplied images only as examples of drawing and painting technique: '
                'delicate linework, elegant proportions, soft hand-painted shading and muted pigments. '
                'Invent the subject from the lyrics. Do not reproduce reference people, faces, '
                'hairstyles, clothing, outfits, poses, objects or composition.')

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


def image_prompt(subject, layout, style_prompt=STYLE_PROMPT, has_references=False):
    if layout.get('artwork_mode') == 'verse':
        from direction.verse import image_prompt as background_prompt
        return background_prompt(subject, layout, style_prompt)
    if layout.get('artwork_mode') == 'matte':
        from artwork.greenscreen import image_prompt as scenery_prompt
        return scenery_prompt(subject, layout, style_prompt)
    if layout.get('artwork_mode') == 'fullscreen':
        technique = (style_prompt if subject_kind(subject) != 'object' else
                     'Delicate ink contours, painterly shading, luminous color and elegant material textures.')
        return ('Paint this subject in a coherent environment: '+subject+'. '+layout['visual_prompt']+
                ' Rendering technique: '+technique+'. Reference images guide technique only, never subject matter. '
                'Preserve natural anatomy for any described people. Do not add people to an object scene. '
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
        + ('REFERENCE ROLE: rendering technique ONLY. '+style_prompt+' '
           'Preserve only brushwork, ink quality, shading technique and color treatment. '
           'Do not copy reference people, clothes, objects or composition. ' if has_references else 'Rendering technique: '+style_prompt+' ')
        + 'FINAL SUBJECT TO DRAW: '+subject.strip()+'. '+scope
        + 'Anatomically accurate hands with exactly five distinct separated fingers including one thumb on each hand; clean joints, no extra digits, no fused fingers. Simple readable poses. '
        'No written words or printed marks anywhere. No additional subjects.'
    )


def prepare_job(data, folder, line_count, model=MODEL, references=None, steps=None, seed=42,
                style_prompt=STYLE_PROMPT, director_model='auto', lookup_only=False,
                width=1920, height=1080, cinematic=False, artwork_mode="cutout"):
    if steps is None:steps=model_spec(model)['steps']
    from models.ollama.service import local_json
    from direction.song_structure import analyze, grouped_lines, group_contexts
    structured=any('section_id' in line for line in data)
    config_path=Path(folder).parent/'config.json'
    if structured and config_path.is_file():
        config=json.loads(config_path.read_text(encoding='utf-8'))
        if config.get('start_step') in ('images','review','render'):
            from artwork.active import select_manifest
            try:structured=bool(json.loads(select_manifest(Path(folder).parent,config).read_text(encoding='utf-8')).get('line_groups'))
            except (OSError,ValueError):structured=False
    structure=analyze(None,director_model,data) if structured else None
    indices=grouped_lines(data,line_count,structure) if structured else [list(range(i,min(len(data),i+line_count))) for i in range(0,len(data),line_count)]
    groups=[' / '.join(data[i]['text'] for i in group) for group in indices]
    references = [Path(p).resolve() for p in (references or [])]
    layouts = [illustration_layout(i, width, height, cinematic, artwork_mode, seed) for i in range(len(groups))]
    signature = dict(version=15 if structured else 14 if artwork_mode == 'verse' else 12, director_model=director_model, artwork_mode=artwork_mode, groups=groups, model=model, steps=steps, seed=seed,
                     width=width, height=height, cinematic=cinematic, layouts=layouts,
                     style=STYLE, style_prompt=style_prompt,
                     references=[hashlib.sha256(p.read_bytes()).hexdigest() for p in references])
    if structured:signature.update(line_groups=indices,song_structure=structure)
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20]
    folder = Path(folder)/key
    manifest = folder/'illustrations.json'
    if manifest.exists() or lookup_only:
        return manifest
    from models.ollama.catalog import resolve_prompt_model
    director_model = resolve_prompt_model(local_json, director_model)
    from direction.verse import DIRECTOR_PROMPT
    if artwork_mode == 'matte':
        from artwork.greenscreen import DIRECTOR_PROMPT
    payload = dict(model=director_model, stream=False, think=False, keep_alive=-1, options=dict(num_ctx=8192),
        format={'type': 'object', 'properties': {'subjects': {'type': 'array',
                'minItems': len(groups), 'maxItems': len(groups), 'items': {'type': 'string'}}},
                'required': ['subjects']},
        messages=[dict(role='system', content=(DIRECTOR_PROMPT if artwork_mode in ('verse', 'matte') else (
            'Translate each lyric group into one distinct English visual description for an illustrator. '
            'The lyrics are the sole source of subject matter. Interpret their meaning, including Tagalog. '
            'Choose the most meaningful concrete subject: an everyday object, architectural detail, '
            'a small grounded vignette, hands, a portrait, a person, or people. '
            'Choose subjects that best express the lyrics; vary compositions naturally where the meaning allows. '
            'Describe only visible shapes, action, material, color, lighting and mood. '
            'For people, specify pose and suitable ordinary clothing; for objects, specify form and material. '
            'Do not copy clothes or content from style references. '
            'Never quote, translate verbatim or transcribe lyric lines into the description. '
            'Never request written words or captions. Signs, books and screens must be blank. '
            'No graffiti, inscriptions, visualized sound waves, invisible substances or ghostly figures. '
            'Express abstract ideas through ordinary physical objects or natural human actions. '
            'Each visual description must differ; no repeated scenes, lettering, flowers or surrealism. '
            'Match the assigned orientation and placement. Direct gestures, gaze or an object diagonal '
            'toward the available space. Do not require a person for a compositional direction. '
            + ('Describe coherent scenery. ' if artwork_mode=='fullscreen' else 'Do not specify a background. ')+'Return only JSON with a subjects array in input order.'))),
            dict(role='user', content=json.dumps([dict(lyrics=group, layout=layout['prompt'])
                 for group, layout in zip(groups, layouts)]))])
    from direction.scenes import request_subjects, repair_duplicate_subjects
    from models.ollama.gpu import gpu_chat, unload_model
    reference_images = bool(references) and model_spec(model)['references']
    meanings = []
    audit_groups = groups
    try:
        contexts=None
        if structured:
            structure=analyze(gpu_chat,director_model,data)
            indices=grouped_lines(data,line_count,structure)
            groups=[' / '.join(data[i]['text'] for i in group) for group in indices]
            layouts=[illustration_layout(i,width,height,cinematic,artwork_mode,seed) for i in range(len(groups))]
            contexts=group_contexts(data,indices,structure)
            signature.update(groups=groups,layouts=layouts,line_groups=indices,song_structure=structure)
            audit_groups=groups
            payload['format']['properties']['subjects'].update(minItems=len(groups),maxItems=len(groups))
            payload['messages'][1]['content']=json.dumps([dict(lyrics=g,layout=l['prompt'],section_context=c) for g,l,c in zip(groups,layouts,contexts)])
        if artwork_mode in ('verse', 'matte'):
            from direction.verse import lyric_meanings
            meanings = lyric_meanings(gpu_chat, director_model, groups,contexts=contexts)
            payload['messages'][1]['content'] = json.dumps([
                dict(lyrics=group,lyric_meaning=meaning,layout=layout['prompt'],section_context=contexts[i] if contexts else None)
                for i,(group,meaning,layout) in enumerate(zip(groups,meanings,layouts))])
            audit_groups = [f'Original lyric group: {group}\nEnglish meaning: {meaning}'
                            for group, meaning in zip(groups, meanings)]
        subjects = request_subjects(gpu_chat, payload)
        subjects = repair_duplicate_subjects(gpu_chat, payload, subjects)
        prompts = [image_prompt(subject, layout, style_prompt, reference_images)
                   for subject, layout in zip(subjects, layouts)]
        from direction.prompt_audit import audit_prompts
        prompts = audit_prompts(gpu_chat,director_model,audit_groups,subjects,prompts,layouts,artwork_mode)
    finally:
        try:unload_model(director_model)
        except (OSError,ValueError) as exc:print(f'Warning: prompt model cleanup: {exc}',flush=True)
    if (not isinstance(subjects, list) or len(subjects) != len(groups)
            or any(not isinstance(s, str) or not s.strip() for s in subjects)):
        raise ValueError('Illustration director must return one subject per lyric group.')
    for subject in subjects:
        if any(len(line['text']) > 12 and line['text'].casefold() in subject.casefold() for line in data):
            raise ValueError('Visual description contains a copied lyric line; rerun the illustration director.')
    folder.mkdir(parents=True, exist_ok=True)
    extra = {}
    if artwork_mode == 'matte':
        from artwork.greenscreen import plate_prompt
        extra['plate_prompts'] = [plate_prompt(subject, layout, style_prompt) for subject, layout in zip(subjects, layouts)]
    manifest.write_text(json.dumps(dict(**signature, reference_paths=[str(p) for p in references],
        lyric_meanings=meanings, visual_descriptions=subjects, prompt_audit=dict(version=1,model=director_model),
        reference_modes=['technique_prompt_only' if artwork_mode in ('verse', 'matte') or subject_kind(s) == 'object' or not reference_images else 'image_conditioning' for s in subjects],
        prompts=prompts, **extra), ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest
