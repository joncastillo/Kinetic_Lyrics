"""Keep a recurring visible character consistent with the reference image.

The scene writer is a text model and never sees the reference. The vision model describes the reference person
once; the description is cached next to the reference."""

import base64
import hashlib
import io
import json
import re
from pathlib import Path

from core.text import json_object

CHARACTER_ROLE = ('Reference image: this is the main character. Give the main person in the scene this exact face, '
                  'hairstyle, hair colour, skin tone, age and gender, and match its rendering technique and colour '
                  'treatment. Do not copy its clothes, pose or background. If the scene shows no person, use it only '
                  'for rendering technique and do not add anyone. ')

SCHEMA = dict(type='object', properties=dict(
    gender=dict(type='string', enum=['woman', 'man', 'girl', 'boy', 'unclear']),
    age=dict(type='string'), hair=dict(type='string'), skin=dict(type='string'), face=dict(type='string')),
    required=['gender', 'age', 'hair', 'skin', 'face'])


def describe(chat, model, reference):
    """One short appearance description of the reference person, or '' when there is no clear person."""
    from PIL import Image
    data = Path(reference).read_bytes()
    cache = Path(reference).with_name(f'character.{hashlib.sha256(data).hexdigest()[:16]}.json')
    try:
        cached = json.loads(cache.read_text(encoding='utf-8'))
        if cached.get('model') == model:
            return cached['description']
    except (OSError, ValueError, KeyError):
        pass
    with Image.open(reference) as source:
        image = source.convert('RGB')
    image.thumbnail((1024, 1024))
    encoded = io.BytesIO(); image.save(encoded, 'PNG')
    response = chat('chat', dict(model=model, stream=False, think=False, format=SCHEMA,
        options=dict(temperature=0, num_ctx=8192, num_predict=2200),  # Qwen3-VL reasons before it answers.
        messages=[dict(role='user', images=[base64.b64encode(encoded.getvalue()).decode()], content=(
            'Describe the main person in this image so an illustrator can draw the same person in other scenes. '
            'Give their apparent gender, approximate age (such as early twenties), hair (length, texture, colour, '
            'style), skin tone and distinctive facial features. Describe only the body and face, never clothing, '
            'pose, accessories or background. Each field is one short phrase of at most ten words, with no '
            'explanations. Use gender "unclear" if no single person is clearly visible.'))]))
    content = (response.get('message') or {}).get('content') or ''
    if not content.strip():
        raise ValueError(f'{model} did not describe the reference image; it may have run out of response length.')
    answer = json_object(content)
    age, hair, skin, face = (phrase(answer.get(key)) for key in ('age', 'hair', 'skin', 'face'))
    description = '' if answer.get('gender') in (None, 'unclear') else ', '.join(filter(None, (
        f"a {answer['gender']}" + (f' ({age})' if age else ''),
        hair and f'{hair} hair'.replace(' hair hair', ' hair'), skin and f'{skin} skin'.replace(' skin skin', ' skin'), face)))
    cache.write_text(json.dumps(dict(model=model, description=description, answer=answer), indent=2), encoding='utf-8')
    return description


CAST_SCHEMA = dict(type='object', properties=dict(
    kind=dict(type='string', enum=['person', 'animal', 'object', 'place', 'unclear']),
    who=dict(type='string'), looks=dict(type='string'), outfit=dict(type='string')),
    required=['kind', 'who', 'looks', 'outfit'])
CAST_VERSION = 1


def describe_subject(chat, model, reference):
    """{kind, who, looks, outfit} of the main subject of one reference picture (a person, an animal, an object or a
    place), cached next to the picture. The text models never see the pictures: this is how they learn the cast."""
    from PIL import Image
    data = Path(reference).read_bytes()
    cache = Path(reference).with_name(f'subject.{hashlib.sha256(data).hexdigest()[:16]}.json')
    try:
        cached = json.loads(cache.read_text(encoding='utf-8'))
        if cached.get('model') == model and cached.get('version') == CAST_VERSION:
            return cached['subject']
    except (OSError, ValueError, KeyError):
        pass
    with Image.open(reference) as source:
        image = source.convert('RGB')
    image.thumbnail((1024, 1024))
    encoded = io.BytesIO(); image.save(encoded, 'PNG')
    response = chat('chat', dict(model=model, stream=False, think=False, format=CAST_SCHEMA,
        options=dict(temperature=0, num_ctx=8192, num_predict=2200),
        messages=[dict(role='user', images=[base64.b64encode(encoded.getvalue()).decode()], content=(
            'This picture shows one member of the cast of a music video. Describe its main subject so an '
            'illustrator and a writer can show exactly the same one in every scene. `kind`: person, animal, '
            'object, place, or unclear. `who`: what it is in a few words (for example "a young woman", "an English '
            'bulldog", "a red vintage car"). `looks`: the features that never change: for a person apparent age, '
            'hair (length, texture, colour, style), skin tone and face; for an animal breed, size, coat colours and '
            'markings, face; for an object or place its shape, colours and details. `outfit`: what it wears in the '
            'picture (clothes, colours, shoes; a collar or harness), or "none". Short phrases, no explanations.'))]))
    content = (response.get('message') or {}).get('content') or ''
    if not content.strip():
        raise ValueError(f'{model} did not describe the reference picture; it may have run out of response length.')
    answer = json_object(content)
    subject = dict(kind=answer.get('kind') or 'unclear', who=phrase(answer.get('who'), 60),
                   looks=phrase(answer.get('looks'), 220), outfit=phrase(answer.get('outfit'), 160))
    cache.write_text(json.dumps(dict(model=model, version=CAST_VERSION, subject=subject), indent=2), encoding='utf-8')
    return subject


def describe_cast(chat, model, references, limit=3):
    """The cast sheet from the reference pictures, as one line per subject, e.g. "1. a young woman: long dark
    wavy hair, warm tan skin...; wearing an olive crop top and a floral wrap skirt. 2. an English bulldog: ..."."""
    lines = []
    for reference in list(references)[:limit]:
        subject = describe_subject(chat, model, reference)
        if subject.get('kind') in ('unclear', None) or not subject.get('who'):
            continue
        outfit = subject.get('outfit') or ''
        lines.append(f"{len(lines)+1}. {subject['who']}: {subject.get('looks', '')}"
                     + (f'; wearing {outfit}' if outfit and outfit.lower() not in ('none', 'no', 'n/a') else '') + '.')
    return ' '.join(lines)


def phrase(value, limit=90):
    """First clause of a field, so a model that keeps reasoning inside the JSON cannot leak it into prompts."""
    text = re.split(r'\s*(?:\(|\. |;|Wait|However)', str(value or ''), maxsplit=1)[0].strip(' ,.')
    return text if len(text) <= limit else text[:limit].rsplit(' ', 1)[0].rstrip(' ,')


def casting_rule(description):
    """Scene-writer instruction that keeps the cast consistent with the reference pictures."""
    return ('THE CAST FROM THE REFERENCE PICTURES: ' + description + ' Whenever one of them appears, describe them '
            'with exactly these looks (age, hair, skin, breed, coat, markings) and, unless the scene clearly calls '
            'for other clothes, this outfit; never change their appearance between scenes. Do not add a person '
            'solely because the lyric says I, me or you. Other people appear only when the story or lyrics need '
            'them. ')
