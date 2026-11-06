"""Manual reference selections survive stale storyline saves and later checker passes."""
import json
from pathlib import Path
from core.files import cached_digest, write_json_atomic


def path(manifest):
    return Path(manifest).parent/'reference-choices.json'


def current_generation(manifest):
    from artwork.reference_lifecycle import generation
    parent = Path(manifest).parent
    return generation(parent.parent.parent) if parent.parent.name == 'video.artwork' else ''


def apply(manifest, story):
    try:
        choices=json.loads(path(manifest).read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return story
    generation = current_generation(manifest)
    for entity in (story or {}).get('entities',[]):
        choice=choices.get(entity.get('id'))
        if not choice or str(choice.get('reference_generation') or '') != generation:
            continue
        image=Path(choice.get('image',''))
        if image.is_file() and cached_digest(image)==choice.get('sha'):
            entity.update({k:v for k,v in choice.items() if k!='sha'})
    return story


def remember(manifest, entity_id, choice):
    from filelock import FileLock
    target=path(manifest)
    with FileLock(str(target)+'.lock',timeout=30):
        try:saved=json.loads(target.read_text(encoding='utf-8'))
        except (OSError,ValueError):saved={}
        if choice:
            saved[entity_id]=dict(choice,sha=cached_digest(Path(choice['image'])), reference_generation=current_generation(manifest))
        else:
            saved.pop(entity_id,None)
        write_json_atomic(target,saved)
