"""Cast the person in a reference image as the song's main character.

The scene writer is a text model and never sees the reference, so without a description it guesses who the
narrator is, and the image model then blends that guess with the reference face. The vision model describes
the reference person once; the description is cached next to the reference."""

import base64
import hashlib
import io
import json
import re
from pathlib import Path

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
    answer = json.loads(content)
    age, hair, skin, face = (phrase(answer.get(key)) for key in ('age', 'hair', 'skin', 'face'))
    description = '' if answer.get('gender') in (None, 'unclear') else ', '.join(filter(None, (
        f"a {answer['gender']}" + (f' ({age})' if age else ''),
        hair and f'{hair} hair'.replace(' hair hair', ' hair'), skin and f'{skin} skin'.replace(' skin skin', ' skin'), face)))
    cache.write_text(json.dumps(dict(model=model, description=description, answer=answer), indent=2), encoding='utf-8')
    return description


def phrase(value, limit=90):
    """First clause of a field, so a model that keeps reasoning inside the JSON cannot leak it into prompts."""
    text = re.split(r'\s*(?:\(|\. |;|Wait|However)', str(value or ''), maxsplit=1)[0].strip(' ,.')
    return text if len(text) <= limit else text[:limit].rsplit(' ', 1)[0].rstrip(' ,')


def casting_rule(description):
    """Scene-writer instruction that keeps the main character consistent with the reference person."""
    return ('MAIN CHARACTER FROM THE REFERENCE IMAGE: ' + description + '. Whenever a scene shows the singer, the '
            'narrator (I, me) or the song\'s main person, draw exactly this person and state their gender and age as '
            'given; never change their gender. Choose clothing that suits the scene instead of describing the '
            'reference clothing. Other people appear only when the lyrics describe them. ')
