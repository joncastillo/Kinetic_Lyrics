"""Discard a reference version without deleting source files or losing the previous choice."""
import json
from pathlib import Path

from artwork.maker import maker_folder
from artwork.reference_lifecycle import signature
from core.files import update_json, write_json_atomic
from direction.entities import earlier_sheets
from direction.story import load


def read(path, default):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError): return default


def discard_plan(job, args):
    manifest = job.manifest()
    entity_id = str(args.get('id') or '')
    entity = next((e for e in (load(manifest) or {}).get('entities', []) if e.get('id') == entity_id), None)
    if entity is None:
        raise ValueError('This reference is no longer in the project.')
    current = Path(str(entity.get('image') or ''))
    paths = ([current] if current.is_file() else []) + earlier_sheets(manifest, entity)
    home = maker_folder(job.folder.parent)
    history = read(home/'history.json', [])
    source = None
    if args.get('maker_id'):
        item = next((i for i in history if i.get('id') == args['maker_id']), None)
        target = (item or {}).get('edit_target') or {}
        if target.get('job') != job.folder.name or target.get('id') != entity_id:
            raise ValueError('This generated image does not belong to that reference.')
        source = Path(item['path'])
    else:
        source = next((p for p in paths if job.url(p).split('?')[0] == str(args.get('url') or '').split('?')[0]), None)
    if source is None or not source.is_file():
        raise ValueError('That history image is no longer available.')
    identity = signature(source)
    if identity is None:
        raise ValueError('This history item is not a readable image.')
    aliases = [p for p in paths if signature(p) == identity]
    aliases.append(source)
    for item in history:
        if (item.get('edit_target') or {}).get('job') == job.folder.name and (item.get('edit_target') or {}).get('id') == entity_id:
            path = Path(str(item.get('path') or ''))
            if signature(path) == identity:
                aliases.append(path)
    replacement = None
    if current.is_file() and signature(current) == identity:
        replacement = next((p for p in paths if signature(p) not in (None, identity)), None)
        if replacement is None:
            raise ValueError('There is no older version to restore yet. Generate another version before discarding the only reference.')
    return dict(id=entity_id, paths=list(dict.fromkeys(str(p.resolve()) for p in aliases)), replacement=replacement)


def mark_discarded(job, entity_id, paths):
    marker = job.folder/'reference-discarded.json'
    if not marker.exists():
        write_json_atomic(marker, {})
    update_json(marker, lambda data: data.update({entity_id: sorted(set(data.get(entity_id, [])) | set(paths))}))
    history = maker_folder(job.folder.parent)/'history.json'
    if history.is_file():
        def mark(items):
            for item in items:
                if str(Path(str(item.get('path') or '')).resolve()) in paths:
                    item['discarded'] = True
        update_json(history, mark)
