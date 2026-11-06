"""Image Maker: one-off pictures that belong to no song, such as reference sheets made from a template or from a prompt
alone. Studio writes a request file and runs `python -m artwork.maker <request.json>`; this reports through status.json
beside it, and leaves a recipe (.json) next to every picture so it can be made again or refined.
"""
from __future__ import annotations
import hashlib
import json
import re
import secrets
import shutil
import sys
import time
from pathlib import Path

from core.files import update_json, write_json_atomic, write_text_atomic
from core.paths import PROJECT_ROOT
from direction.entities import reference_role, reference_tags
from models.image.catalog import image_dimensions, model_spec

NO_TEXT = 'No text of any kind: no title, name, labels, captions, arrows, signatures or printed marks.'
TEMPLATES = [
    dict(id='character', name='Character reference sheet', width=1536, height=864, subject='Who it is and how they look', text=(
        'Character reference sheet of {subject}. The same single character drawn several times as separate, '
        'non-overlapping figures with identical proportions, colours and outfit, on a plain pure white background: a '
        'top row of full-body views (front, three-quarter, side profile, back) and a bottom row of head-and-shoulders '
        'close-ups with different expressions. Every figure is this same character, and no one else appears. '+NO_TEXT)),
    dict(id='object', name='Object reference sheet', width=1536, height=864, subject='What it is and how it looks', text=(
        'Object reference sheet of {subject}. The same object drawn four times as separate, non-overlapping views, '
        'evenly spaced in a row on a plain pure white background: from the front, from the side, from three-quarter '
        'above, and a close-up of its surface detail. Identical shape, size, material and colour in every view. Only '
        'this object: no person, hand or animal anywhere. '+NO_TEXT)),
    dict(id='scene', name='Scene reference sheet', width=1536, height=864, subject='The place and its mood', text=(
        'Scene reference sheet of {subject}. Three separate rectangular panels on a plain pure white background, with '
        'wide clean white margins and clear white gaps between them: a close-up view and a back view side by side '
        'along the top, and one wide front view across the bottom. Each panel is a fully painted view that fills its '
        'rectangle edge to edge; only the sheet behind the panels is white. The same place, with identical layout, '
        'light and colours in every panel. No people or animals. '+NO_TEXT)),
    dict(id='none', name='No template', width=1344, height=768, subject='', text=''),
]
FORMATS = {'png': ('PNG', '.png'), 'jpeg': ('JPEG', '.jpg'), 'webp': ('WEBP', '.webp')}
MIN_SIDE, MAX_SIDE, MAX_COUNT = 256, 2048, 8
TAG = re.compile(r'@(?:"([^"]+)"|((?:image|photo)\s*\d+(?!\w|\.\w)|[\w\-]+(?:\.\w+)?))')


def maker_folder(root):
    """Where Image Maker keeps its own files: beside the song projects, never among them."""
    return Path(root).parent/'image-maker'


def template(template_id):
    found = next((t for t in TEMPLATES if t['id'] == template_id), None)
    if found is None:
        raise ValueError('Choose a template')
    return found


def unknown_tags(prompt, names):
    """The tags in a prompt that name none of these reference pictures: the prompt would lose them silently."""
    tags = [match.group(0) for match in TAG.finditer(str(prompt or ''))]
    return list(dict.fromkeys(tag for tag in tags if 'reference image' not in reference_tags(tag, names)))


def full_prompt(template_id, prompt, subject, names):
    """The words the model reads. A template says what each reference picture is for; with no template the prompt is
    used as written, apart from tags becoming the numbers the model sees the pictures under."""
    text = str(prompt or '').replace('{subject}', ' '.join(str(subject or '').split()).rstrip('.'))
    tagged = reference_tags(text, names)
    return tagged if template_id == 'none' or not names else reference_role(tagged, [], len(names), 0, False)


def side(value, name):
    """A picture side as the models take it: within the limits, in multiples of 32."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a whole number') from None
    if not MIN_SIDE <= number <= MAX_SIDE:
        raise ValueError(f'{name} must be from {MIN_SIDE} to {MAX_SIDE}')
    return number//32*32


def whole(value, name, low, high, default=None):
    if value in (None, ''):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a whole number') from None
    if not low <= number <= high:
        raise ValueError(f'{name} must be from {low} to {high}')
    return number


def stem(text):
    """A file name from free text, without any picture extension typed: the Format setting decides that."""
    name = re.sub(r'\.(png|jpe?g|webp)$', '', str(text or '').strip(), flags=re.I)
    return re.sub(r'[^\w-]+', '_', name).strip('_')[:60] or 'image'


def checked(request, reference_folder):
    """The request with everything validated, or ValueError saying what to fix."""
    template_id = str(request.get('template') or 'none')
    output = str(request.get('output') or 'image')
    if output != 'image':
        raise ValueError('Choose image output')
    template(template_id)
    prompt, subject = str(request.get('prompt') or '').strip(), str(request.get('subject') or '').strip()
    if not prompt:
        raise ValueError('Write a prompt first')
    if '{subject}' in prompt and not subject:
        raise ValueError('Say what the sheet shows')
    names = [str(name) for name in request.get('references') or []]
    for name in names:
        if Path(name).name != name or not (Path(reference_folder)/name).is_file():
            raise ValueError(f'{name} is no longer in the references')
    model = str(request.get('model') or '')
    spec = model_spec(model)
    if names and not spec['references']:
        raise ValueError(f"{spec.get('name', model)} does not read reference pictures: remove them or choose another model")
    limit = spec.get('max_references', 3)
    if len(names) > limit:
        raise ValueError(f"{spec.get('name', model)} takes at most {limit} reference pictures")
    from artwork.edit_regions import checked_regions
    region_source = str(request.get('region_source') or '')
    regions = checked_regions(request.get('regions'), region_source, names, spec)
    preserve = bool(regions and request.get('preserve_outside_regions', False))
    unknown = unknown_tags(prompt+' '+subject, names)
    if unknown:
        raise ValueError(f"No reference picture has {'these tags' if len(unknown) > 1 else 'this tag'}: {', '.join(unknown)}")
    file_format = str(request.get('format') or 'png')
    if file_format not in FORMATS:
        raise ValueError('Choose PNG, JPEG or WebP')
    if preserve and file_format != 'png':
        raise ValueError('Use PNG to keep pixels outside the selected regions unchanged.')
    folder = str(request.get('folder') or '').strip()
    if not folder or not Path(folder).expanduser().is_absolute():
        raise ValueError('Choose an output folder (a full path)')
    return dict(template=template_id, prompt=prompt, subject=subject, references=names, model=model, folder=folder,
                regions=regions, region_source=region_source if regions else '', preserve_outside_regions=preserve,
                width=side(request.get('width'), 'Width'), height=side(request.get('height'), 'Height'), format=file_format,
                quality=whole(request.get('quality'), 'Quality', 1, 100, 92), steps=whole(request.get('steps'), 'Steps', 1, 150, spec.get('steps', 30)),
                seed=whole(request.get('seed'), 'Seed', 0, 2**31-1), count=whole(request.get('count'), 'Pictures', 1, MAX_COUNT, 1),
                name=stem(request.get('name') or template_id), output=output,
                duration=whole(request.get('duration'), 'Video duration', 1, 120, 5),
                motion=str(request.get('motion') or '').strip()[:2000])


def free_path(folder, name, suffix):
    """A path in `folder` that overwrites nothing."""
    number = 1
    while True:
        path = Path(folder)/f"{name}{f'-{number}' if number > 1 else ''}{suffix}"
        if not path.exists() and not path.with_suffix('.json').exists():
            return path
        number += 1


def save_picture(image, path, file_format, quality):
    kind = FORMATS[file_format][0]
    picture = image.convert('RGB') if kind == 'JPEG' else image
    picture.save(path, kind, **({} if kind == 'PNG' else dict(quality=quality)))


def load_references(folder, names):
    from PIL import Image
    pictures = []
    for name in names:
        with Image.open(Path(folder)/name) as source:
            picture = source.convert('RGB')
        picture.thumbnail((1024, 1024))
        pictures.append(picture)
    return pictures


def keep_references(request, home):
    """Copy the run's reference pictures into a folder beside its pictures, so a picture can always be made again, even
    once they have left the library. The folder is named by their content, so the same set shares one."""
    names = request['references']
    if not names:
        return ''
    digest = hashlib.sha1()
    for name in names:
        digest.update(name.encode()+(Path(request.get('input_reference_folder') or home/'references')/name).read_bytes())
    folder = Path(request['folder']).expanduser()/f"{request['name']}_references_{digest.hexdigest()[:8]}"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        if not (folder/name).exists():
            shutil.copy2(Path(request.get('input_reference_folder') or home/'references')/name, folder/name)
    return str(folder)


def paint(pipe, request, prompt, pictures, width, height, seed, torch):
    from models.image.pipeline import inference_options
    return pipe(prompt=prompt, **inference_options(request['model'], pictures), width=width, height=height,
                num_inference_steps=request['steps'], generator=torch.Generator('cpu').manual_seed(seed)).images[0]


def paint_regions(pipe, request, source, pictures, seed, torch, report, number, made):
    """Edit close-ups so the model cannot rearrange a multi-view sheet inside the mask."""
    from PIL import Image
    from artwork.edit_regions import region_context, guide_image, guide_prompt, preserve_outside_regions
    result = source.copy()
    edits = []
    source_index = request['references'].index(request['region_source'])
    others = [picture for index, picture in enumerate(pictures) if index != source_index]
    names = [request['region_source'], 'numbered-region-guide'] + [name for name in request['references'] if name != request['region_source']]
    context = full_prompt(request['template'], request['prompt'], request['subject'], names)
    for index, region in enumerate(request['regions']):
        crop, (left, top), local = region_context(source, region)
        guide = guide_image(crop, [local])
        prompt = guide_prompt(
            'This is a close-up crop, not the full reference sheet. Keep its framing, pose, scale, lighting and '
            'boundary appearance fixed. Edit only the area marked 1. Original request: '+context+
            f' For this crop apply only original region {index+1}: '+(region.get('instruction') or request['prompt']),
            [local], 1, 2)
        scale = 768/max(crop.size)
        width, height = max(256, round(crop.width*scale/32)*32), max(256, round(crop.height*scale/32)*32)
        report('painting', f'Editing region {index+1} of {len(request["regions"])} in picture {number+1}', number, made)
        edited = paint(pipe, request, prompt, [crop, guide, *others], width, height, seed+index, torch)
        edits.append(dict(region=index+1, seed=seed+index, prompt=prompt, width=width, height=height,
                          crop_box=[left, top, left+crop.width, top+crop.height]))
        canvas = source.copy()
        canvas.paste(edited.resize(crop.size, Image.Resampling.LANCZOS), (left, top))
        result = preserve_outside_regions(result, canvas, [region])
    return result, edits


def make(request, home, pipe, torch, memory_gib, report):
    """Paint the request's pictures into its folder, recording each in history.json as it is saved."""
    prompt = full_prompt(request['template'], request['prompt'], request['subject'], request['references'])
    pictures = load_references(Path(request.get('input_reference_folder') or home/'references'), request['references'])
    width, height = image_dimensions(request['width'], request['height'], memory_gib)
    note = '' if (width, height) == (request['width'], request['height']) else f' at {width}x{height}, as the GPU is short of memory'
    folder = Path(request['folder']).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    suffix = FORMATS[request['format']][1]
    reference_folder = keep_references(request, home)
    original = None
    clean_pictures = pictures.copy()
    if request.get('regions'):
        from artwork.edit_regions import checked_regions, guide_image, guide_prompt
        regions = checked_regions(request['regions'],request['region_source'],request['references'],model_spec(request['model']))
        source_number=request['references'].index(request['region_source'])+1
        pictures.append(guide_image(pictures[source_number-1],regions))
        prompt=guide_prompt(prompt,regions,source_number,len(pictures))
        if request.get('preserve_outside_regions'):
            from PIL import Image
            with Image.open(Path(request.get('input_reference_folder') or home/'references')/request['region_source']) as source:
                original = source.copy()
    made = []
    for number in range(request['count']):
        seed = request['seed']+number if request['seed'] is not None else secrets.randbelow(2**31)
        report('painting', f"Painting picture {number+1} of {request['count']}{note}", number, made)
        edits = []
        if original is not None:
            image, edits = paint_regions(pipe, request, original, clean_pictures, seed, torch, report, number, made)
        else:
            image = paint(pipe, request, prompt, pictures, width, height, seed, torch)
        path = free_path(folder, request['name'], suffix)
        save_picture(image, path, request['format'], request['quality'])
        sent = '\n\n'.join(f'Region {edit["region"]}: {edit["prompt"]}' for edit in edits) if edits else prompt
        recipe = dict(request, seed=seed, width=image.width, height=image.height, sent_prompt=sent, made=time.time(), path=str(path),
                      reference_folder=reference_folder, region_edits=edits)
        write_text_atomic(path.with_suffix('.json'), json.dumps(recipe, indent=2, ensure_ascii=False))

        def remember(history, recipe=recipe):
            history.append(dict(recipe, id=secrets.token_hex(8)))
            return history[-200:]
        update_json(home/'history.json', remember)
        made.append(str(path))
    return made


def run(request_path):
    request_path = Path(request_path)
    home = request_path.parent
    request = json.loads(request_path.read_text(encoding='utf-8'))

    def report(state, message, done=0, files=()):
        write_json_atomic(home/'status.json', dict(state=state, message=message, done=done, total=request['count'], files=list(files), at=time.time()))
    try:
        if not (home/'history.json').exists():
            write_text_atomic(home/'history.json', '[]')
        if request.get('source_image'):
            made = [request['source_image']]
        else:
            from filelock import FileLock
            import torch
            import models.gpu.memory as gpu_memory
            from models.image.pipeline import load_pipeline, release_pipeline
            report('waiting', 'Waiting for the GPU')
            with FileLock(str(PROJECT_ROOT/'.image-generation.lock'), timeout=-1):
                from models.gpu.lifecycle import ModelSession
                ModelSession().before_generation(request['model'])
                report('loading', f"Loading {model_spec(request['model']).get('name', request['model'])}")
                pipe, _ = load_pipeline(request['model'], Path(request['cache']).expanduser().resolve(), torch)
                try:
                    free, total = gpu_memory.dedicated_memory(torch)
                    made = make(request, home, pipe, torch, min(total, free+torch.cuda.memory_reserved())/2**30, report)
                finally:
                    release_pipeline(pipe, torch)
                    del pipe  # release the last reference before the video worker takes the GPU
            pass
        pass
        kind = 'picture'
        report('done', f"{len(made)} {kind}{'s' if len(made) != 1 else ''} saved", len(made), made)
    except Exception as exc:  # noqa: BLE001 (the panel shows the reason; a traceback goes to the log)
        report('failed', str(exc)[:600] or type(exc).__name__)
        raise




if __name__ == '__main__':
    run(sys.argv[1])
