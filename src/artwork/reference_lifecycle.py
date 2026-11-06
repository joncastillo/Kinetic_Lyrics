"""Keep restarted artwork and Image Maker's copied references in the same generation."""
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import time

from core.files import write_json_atomic


def read(path, fallback):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def generation(folder):
    return str(read(Path(folder)/'reference-generation.json', {}).get('generation') or '')


def advance(folder):
    token = secrets.token_hex(16)
    write_json_atomic(Path(folder)/'reference-generation.json', dict(generation=token, started=time.time()))
    return token


def signature(path):
    """Pixel identity survives PNG metadata and re-encoding during uploads."""
    from PIL import Image
    try:
        with Image.open(path) as source:
            image = source.convert('RGBA')
            return image.size, hashlib.sha256(image.tobytes()).hexdigest()
    except (OSError, ValueError):
        return None


def project_pictures(folder, home):
    folder, home = Path(folder), Path(home)
    paths = list((folder/'video.artwork').rglob('*.png'))
    paths += [Path(item['path']) for item in read(home/'history.json', [])
              if (item.get('edit_target') or {}).get('job') == folder.name and item.get('path')]
    return paths


def retire_library(folder, home, keep=()):
    """Archive only copies of this project's artwork, never unrelated library inputs.

    Queued edits have frozen input copies and history has its own reference folders.
    Those remain available for explicit recovery, but not as current library inputs.
    """
    folder, home = Path(folder), Path(home)
    known = {s for p in project_pictures(folder, home) if (s := signature(p)) is not None}
    keep = {s for p in keep if (s := signature(p)) is not None}
    archive = home/'retired-references'/folder.name/str(time.time_ns())
    moved = []
    for path in (home/'references').glob('*.png'):
        identity = signature(path)
        if identity not in known or identity in keep:
            continue
        target = archive/path.name
        if path.is_symlink() or not path.resolve().is_relative_to(home.resolve()) or not target.resolve().is_relative_to(home.resolve()):
            raise ValueError('Reference archive path leaves the Image Maker folder.')
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        moved.append(path.name)
    if moved:
        write_json_atomic(archive/'retired.json', dict(project=folder.name, references=moved))
    return moved


def edited_signatures(folder, home):
    return {s for item in read(Path(home)/'history.json', [])
            if (item.get('edit_target') or {}).get('job') == Path(folder).name and item.get('path')
            if (s := signature(item['path'])) is not None}


def is_generated_edit(entity, signatures):
    if entity.get('image_origin') == 'upload':
        return False
    return entity.get('image_origin') == 'generated_edit' or bool(
        entity.get('uploaded') and signature(entity.get('image') or entity['uploaded']) in signatures)


def sync_library(home, job, target):
    """Copy current project references, comparing content rather than matching labels."""
    from direction.story import load
    from artwork.maker import free_path
    home = Path(home)
    manifest = job.manifest()
    story = load(manifest) or {}
    current = {entry['id']: (entry.get('name') or entry['id'], Path(entry['image']))
               for entry in story.get('entities', []) if entry.get('id') and entry.get('image')
               and Path(entry['image']).is_file()}
    if target.get('type') == 'illustration':
        index = int(target.get('index', -1))
        if index < 0 or index >= len(read(manifest, {}).get('prompts', [])):
            raise ValueError('Invalid illustration')
        current[f'illustration-{index}'] = (f'Illustration_{index+1}', manifest.parent/f'{index:03d}.png')
    wanted = str(target.get('id') or '')
    if wanted not in current or not current[wanted][1].is_file():
        raise ValueError('This reference is no longer current. Refresh the project first.')
    retire_library(job.folder, home, keep=[path for _, path in current.values()])
    library = home/'references'
    library.mkdir(parents=True, exist_ok=True)
    existing = {signature(p): p.name for p in sorted(library.glob('*.png'))}
    mapping = {}
    for key, (label, source) in current.items():
        identity = signature(source)
        if identity is None:
            continue
        if identity not in existing:
            name = re.sub(r'[^\w-]+', '_', label).strip('_') or key
            path = free_path(library, name, '.png')
            shutil.copy2(source, path)
            existing[identity] = path.name
        mapping[key] = existing[identity]
    if wanted not in mapping:
        raise ValueError('The current reference is not a readable image.')
    return dict(added=[mapping[wanted]], reference_map=mapping, reference_generation=generation(job.folder),
                reference_edit_revision=target_revision(job.folder, target))


def validate_target(folder, target):
    """Old queued edits cannot apply themselves to a restarted storyline."""
    if str(target.get('reference_generation') or '') != generation(folder):
        raise ValueError('This edit belongs to an earlier artwork run. Open the current reference and make a new edit.')
    if str(target.get('reference_edit_revision') or '') != target_revision(folder, target):
        raise ValueError('This reference or one of its inputs changed. Open the current image before editing it.')


def target_revision(folder, target):
    key = str(target.get('id') or '')
    if target.get('type') == 'illustration' or key.startswith('illustration-'):
        index = target.get('index', key.removeprefix('illustration-'))
        return str(read(Path(folder)/'reference-image-revisions.json', {}).get(str(index)) or '')
    return str(read(Path(folder)/'reference-edits.json', {}).get(key, {}).get('reference_edit_revision') or '')
