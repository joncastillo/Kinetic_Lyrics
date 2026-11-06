"""User-authored reference recipes, kept separately from regenerable AI output."""
import copy
import json
from pathlib import Path

from core.files import update_json
from core.paths import PROJECT_ROOT

OUTPUT_FIELDS = ('image', 'uploaded', 'sheet_review', 'review_repaints', 'painted_prompt',
                 'force_used', 'force_review', 'image_updated_at', 'image_origin', 'image_history')
BUILTINS = {'default-style': ('Default art-style reference', 'reference_female_2.jpeg'),
            'default-portrait': ('Default character reference', 'reference_female_1.jpeg')}


def project_root(manifest):
    parent = Path(manifest).parent
    return parent.parent.parent if parent.parent.name == 'video.artwork' else parent


def recipes_path(manifest):
    return project_root(manifest)/'reference-edits.json'


def recipes(manifest):
    try:
        result = json.loads(recipes_path(manifest).read_text(encoding='utf-8'))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def apply(manifest, story):
    saved = recipes(manifest)
    for entity in (story or {}).get('entities', []):
        recipe = saved.get(entity.get('id'))
        if not recipe:
            continue
        if entity.get('reference_edit_revision') != recipe['reference_edit_revision']:
            for field in OUTPUT_FIELDS:
                entity.pop(field, None)
        entity.update(copy.deepcopy(recipe))
    return story


def remember(manifest, updates):
    path = recipes_path(manifest)
    if not path.exists():
        from core.files import write_json_atomic
        write_json_atomic(path, {})
    update_json(path, lambda saved: saved.update(copy.deepcopy(updates)))


def dependencies(entity, story):
    from direction.entities import base_of
    base = base_of(story, entity)
    result = [base['id']] if base else []
    result += [r['id'] for r in entity.get('reference_inputs', []) if r.get('kind') == 'entity']
    return list(dict.fromkeys(result))


def affected(story, entity_id):
    result = {entity_id}
    while True:
        found = {e['id'] for e in story.get('entities', []) if set(dependencies(e, story)) & result}
        if found <= result:
            return result
        result.update(found)


def validate_inputs(value, entity_id, story, root, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f'This image model accepts at most {limit} reference pictures.')
    result, seen = [], set()
    blocked = affected(story, entity_id)
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError('Invalid reference input.')
        kind, key = str(entry.get('kind') or ''), str(entry.get('id') or '')
        role = str(entry.get('role') or ('style' if kind == 'builtin' else 'identity'))
        if role not in ('style', 'identity', 'detail'):
            raise ValueError('Choose style, identity or detail for each reference.')
        if (kind, key) in seen:
            continue
        seen.add((kind, key))
        if kind == 'entity':
            if key in blocked:
                raise ValueError('A reference cannot depend on itself or on one of its derived references.')
            if not any(e.get('id') == key for e in story.get('entities', [])):
                raise ValueError('That recurring reference is no longer in the story.')
        elif kind == 'builtin':
            if key not in BUILTINS:
                raise ValueError('Unknown built-in reference.')
        elif kind in ('project', 'upload'):
            folder = Path(root)/('references' if kind == 'project' else 'reference-inputs')
            path = folder/key
            if (not key or Path(key).name != key or '\\' in key or not path.is_file()
                    or not path.resolve().is_relative_to(folder.resolve())):
                raise ValueError('That reference image is no longer available.')
        else:
            raise ValueError('Unknown reference input type.')
        result.append(dict(kind=kind, id=key, role=role))
    return result


def input_paths(manifest, entity, story):
    """Resolve entity links now, so an input always uses its latest reference picture."""
    root = project_root(manifest)
    result = []
    for entry in entity.get('reference_inputs', []):
        kind, key = entry['kind'], entry['id']
        if kind == 'entity':
            other = next((e for e in story.get('entities', []) if e.get('id') == key), None)
            path = Path(str((other or {}).get('image') or ''))
            label = (other or {}).get('name') or key
        elif kind == 'builtin':
            label, filename = BUILTINS[key]
            path = PROJECT_ROOT/'assets'/filename
        else:
            path = root/('references' if kind == 'project' else 'reference-inputs')/key
            label = Path(key).stem
        if not path.is_file():
            raise ValueError(f'Reference input {label} has not been painted or is no longer available.')
        result.append((path, label, entry.get('role', 'identity')))
    return result


def conditioning(manifest, entity, story, limit):
    from PIL import Image
    from direction.entities import REFERENCE_PIXELS
    paths = input_paths(manifest, entity, story)
    if len(paths) > limit:
        raise ValueError(f'This model accepts at most {limit} reference inputs.')
    pictures, roles = [], []
    for number, (path, label, role) in enumerate(paths, 1):
        with Image.open(path) as source:
            picture = source.convert('RGB')
        picture.thumbnail((REFERENCE_PIXELS, REFERENCE_PIXELS))
        pictures.append(picture)
        purpose = {'style': 'drawing technique, palette and shading only; its subjects are not added',
                   'identity': 'the identity and appearance described in the prompt',
                   'detail': 'the specific visual details described in the prompt'}[role]
        roles.append(f'Picture {number} ({label}) guides {purpose}.')
    return pictures, ' '.join(roles)+'\n\n' if roles else ''
