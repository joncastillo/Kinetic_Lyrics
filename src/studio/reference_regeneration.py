"""Edit a saved reference recipe and invalidate its complete downstream artwork."""
import copy
import json
from pathlib import Path
import secrets
import re
import shutil
import time

from core.files import write_json_atomic
from core.paths import PROJECT_ROOT
from direction import reference_edits
from direction.entities import sheet_prompt, sheet_style
from direction.story import load, save
from models.image.catalog import model_spec, selected_model


def details(job, entity_id):
    manifest = job.manifest()
    story = load(manifest) or {}
    entity = next((e for e in story.get('entities', []) if e.get('id') == entity_id), None)
    if entity is None:
        raise ValueError('That reference is no longer in the storyline.')
    record = json.loads(manifest.read_text(encoding='utf-8'))
    technique = sheet_style(record, mood=entity.get('kind') == 'character')
    affected = reference_edits.affected(story, entity_id)
    if any(not re.fullmatch(r'[\w-]+', key) for key in affected):
        raise ValueError('Invalid reference identifier.')
    options = []
    for other in story.get('entities', []):
        if other['id'] in affected:
            continue
        image = Path(str(other.get('image') or ''))
        options.append(dict(kind='entity', id=other['id'], label=other['name'], role='identity',
                            url=job.url(image) if image.is_file() else None))
    for path in sorted((job.folder/'references').glob('*')):
        if path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
            options.append(dict(kind='project', id=path.name, label=path.stem, role='style', url=job.url(path)))
    for key, (label, filename) in reference_edits.BUILTINS.items():
        if (PROJECT_ROOT/'assets'/filename).is_file():
            options.append(dict(kind='builtin', id=key, label=label, role='style', url='/assets/'+filename))
    for path in sorted((job.folder/'reference-inputs').glob('*.png')):
        options.append(dict(kind='upload', id=path.name, label=path.stem, role='detail', url=job.url(path)))
    inputs = copy.deepcopy(entity.get('reference_inputs'))
    if inputs is None:
        from direction.entities import base_of, photo_index, photo_kind, from_lead
        base = base_of(story, entity)
        inputs = [dict(kind='entity', id=base['id'], role='identity')] if base else []
        paths = [Path(p) for p in record.get('reference_paths', []) if Path(p).is_file()]
        selected = None
        if not base:
            tagged = photo_index(entity.get('photo'), [p.name for p in paths]) if entity.get('photo') else None
            people = [p for p in paths if photo_kind(p) == 'person']
            styles = [p for p in paths if photo_kind(p) in ('object', 'place')]
            if tagged is not None:
                selected = (paths[tagged], 'identity')
            elif people and record.get('reference_use') == 'likeness' and (entity.get('cast') or from_lead(entity, story)):
                selected = (people[0], 'identity')
            elif styles:
                selected = (styles[0], 'style')
        if selected:
            path, role = selected
            if path.parent.resolve() == (job.folder/'references').resolve():
                inputs = [dict(kind='project', id=path.name, role=role)]
            else:
                for key, (_, filename) in reference_edits.BUILTINS.items():
                    if path.resolve() == (PROJECT_ROOT/'assets'/filename).resolve():
                        inputs = [dict(kind='builtin', id=key, role=role)]
    count = len(record.get('prompts', []))
    images = sorted({i for e in story.get('entities', []) if e['id'] in affected
                     for i in e.get('segments', []) if type(i) is int and 0 <= i < count})
    current = Path(str(entity.get('image') or ''))
    return dict(ok=True, version=2, id=entity_id, name=entity['name'], looks=entity.get('looks', ''),
        current_image=job.url(current) if current.is_file() else None,
        prompt=sheet_prompt(entity, technique), last_prompt=entity.get('painted_prompt') or '',
        revision=entity.get('reference_edit_revision', ''), inputs=inputs, options=options,
        images=[i+1 for i in images], dependents=[e['name'] for e in story.get('entities', []) if e['id'] in affected and e['id'] != entity_id],
        max_references=model_spec(selected_model(record, job.config)).get('max_references', 3))


def prepare(job, args):
    manifest = job.manifest()
    story = load(manifest) or {}
    entity_id = str(args.get('id') or '')
    entity = next((e for e in story.get('entities', []) if e.get('id') == entity_id), None)
    if entity is None:
        raise ValueError('That reference is no longer in the storyline.')
    if 'revision' in args and args['revision'] != entity.get('reference_edit_revision', ''):
        raise ValueError('This reference changed while the panel was open. Reopen it before saving.')
    looks = str(args.get('looks', entity.get('looks', ''))).strip()
    prompt = str(args.get('prompt') or '').strip()
    if not looks or len(looks) > 4000:
        raise ValueError('Write a description of 1–4000 characters.')
    if not prompt or len(prompt) > 12000:
        raise ValueError('Write a generation prompt of 1–12000 characters.')
    record = json.loads(manifest.read_text(encoding='utf-8'))
    from direction.prompt_fit import over_budget
    if over_budget(prompt, selected_model(record, job.config)):
        raise ValueError('The prompt is longer than this image model can read. Shorten it before regenerating.')
    fields = dict(looks=looks, prompt=prompt)
    if 'inputs' in args:
        fields['reference_inputs'] = reference_edits.validate_inputs(args['inputs'], entity_id, story, job.folder,
            model_spec(selected_model(record, job.config)).get('max_references', 3))
    affected = reference_edits.affected(story, entity_id)
    if any(not re.fullmatch(r'[\w-]+', key) for key in affected):
        raise ValueError('Invalid reference identifier.')
    old_images = {e.get('image') for e in story.get('entities', []) if e['id'] in affected and e.get('image')}
    count = len(record.get('prompts', []))
    indices = {i for e in story.get('entities', []) if e['id'] in affected for i in e.get('segments', [])
               if type(i) is int and 0 <= i < count}
    indices.update(s.get('index', i) for i, s in enumerate(story.get('segments', []))
                   if old_images.intersection(s.get('references', [])))
    indices = sorted(i for i in indices if type(i) is int and 0 <= i < count)
    return dict(manifest=manifest, story=story, entity_id=entity_id, fields=fields,
                affected=affected, indices=indices, name=entity.get('name', entity_id))


def archive_outputs(job, plan, revision):
    """Remove invalid output from live paths; keep a recoverable archive inside the project."""
    root, art = job.folder.resolve(), plan['manifest'].parent
    archive = art/('previous-reference-edit-'+revision)
    moved = []

    def move(path):
        path = Path(path)
        if not path.exists():
            return
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Refusing to archive artwork outside this project.')
        target = archive/path.relative_to(root)
        if not target.resolve().is_relative_to(root):
            raise ValueError('Invalid reference archive destination.')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        moved.append(str(path.relative_to(root)))

    for entity_id in plan['affected']:
        for path in list((art/'entities').glob(entity_id+'.*')):
            if path.is_file() and not path.name.endswith('.lock'):
                move(path)
    for index in plan['indices']:
        image = art/f'{index:03d}.png'
        if image.is_file():
            from core.files import file_digest as image_digest
            digest = image_digest(image)
            for clip in (root/'video-clips').glob(digest[:24]+'-*'):
                move(clip)
        for path in list(art.glob(f'{index:03d}.*')):
            if path.is_file() and not path.name.endswith('.lock'):
                move(path)
        move(root/'candidates'/f'{index:03d}')
        move(root/'versions'/f'{index:03d}')
    archive.mkdir(parents=True, exist_ok=True)
    write_json_atomic(archive/'story-before.json', plan['story'])
    write_json_atomic(archive/'invalidated.json', dict(references=sorted(plan['affected']), images=plan['indices'], files=moved))
    return archive


def commit(job, plan):
    revision = secrets.token_hex(12)
    archive = archive_outputs(job, plan, revision)
    updates = {entity_id: dict(reference_edit_revision=revision) for entity_id in plan['affected']}
    updates[plan['entity_id']].update(plan['fields'])
    existing = reference_edits.recipes(plan['manifest'])
    for entity_id, update in updates.items():
        updates[entity_id] = dict(existing.get(entity_id, {}), **update)
    reference_edits.remember(plan['manifest'], updates)
    from direction.reference_choices import remember
    old_images = {e.get('image'): e for e in plan['story'].get('entities', [])
                  if e['id'] in plan['affected'] and e.get('image')}
    for index, segment in enumerate(plan['story'].get('segments', [])):
        number = segment.get('index', index)
        for old in segment.get('references', []):
            if old in old_images:
                entity = old_images[old]
                entity['segments'] = sorted(set(entity.get('segments', [])) | {number})
        if 'references' in segment:
            segment['references'] = [p for p in segment['references'] if p not in old_images]
    for entity in plan['story'].get('entities', []):
        if entity['id'] in plan['affected']:
            for key in reference_edits.OUTPUT_FIELDS:
                entity.pop(key, None)
            entity.update(updates[entity['id']])
            entity['repaint'] = int(entity.get('repaint') or 0)+1
            remember(plan['manifest'], entity['id'], None)
    save(plan['manifest'], plan['story'])
    # Explicit scene-image inputs pointing at the old sheet follow its replacement.
    from core.files import update_json
    revisions = job.folder/'reference-image-revisions.json'
    if not revisions.exists():
        write_json_atomic(revisions, {})
    update_json(revisions, lambda current: current.update({str(i): revision for i in plan['indices']}))
    from artwork.gallery import publish_gallery
    publish_gallery(plan['manifest'])
    job.state['dirty'] = sorted(set(job.state.get('dirty', [])) | set(plan['indices']))
    return revision, archive


def regenerate(worker, root, manifest, items, config, cache):
    """One worker paints all prerequisite sheets, then installs fresh dependent images."""
    from models.gpu.lifecycle import ModelSession
    from core.files import content_digest, update_json
    from filelock import FileLock
    ids = list(dict.fromkeys(item['id'] for item in items))
    indices = sorted({i for item in items for i in item.get('images', [])})
    expected = {item['id']: item.get('revision') for item in items if item.get('revision')}
    with ModelSession([config.get('vision_model')]):
        worker.paint_references(root, manifest, ids, cache)
        worker.check_references(root, manifest, config, cache, requeue=False)
        record = json.loads(manifest.read_text(encoding='utf-8'))
        chosen = selected_model(record, config)
        if record.get('model') != chosen:
            record.update(model=chosen, steps=model_spec(chosen)['steps'])
            update_json(manifest, lambda saved: saved.update(model=chosen, steps=record['steps']))
        story = load(manifest) or {}
        for index in indices:
            current = reference_edits.recipes(manifest)
            if any(current.get(key, {}).get('reference_edit_revision') != revision for key, revision in expected.items()):
                raise ValueError('Reference changed during regeneration; the newer request takes precedence.')
            base_prompts = record.setdefault('reference_prompt_bases', {})
            original = base_prompts.setdefault(str(index), record['prompts'][index])
            descriptions = [f'{e["name"]}: {e["looks"]}' for e in story.get('entities', [])
                            if index in e.get('segments', []) and e.get('reference_edit_revision')]
            prompt = original + ('\n\nCurrent reference descriptions override earlier appearance details: '
                                  +' '.join(descriptions) if descriptions else '')
            record['prompts'][index] = prompt
            update_json(manifest, lambda saved: saved.update(prompts=record['prompts'], reference_prompt_bases=base_prompts))
            candidate = worker.generate_candidate(root, record, index, cache, prompt)
            current = reference_edits.recipes(manifest)
            if any(current.get(key, {}).get('reference_edit_revision') != revision for key, revision in expected.items()):
                raise ValueError('Discarded a stale result after another reference edit.')
            target = manifest.parent/f'{index:03d}.png'
            with FileLock(str(target)+'.write.lock', timeout=30):
                for source in candidate.parent.glob('000.*'):
                    if source.is_file() and not source.name.endswith('.lock'):
                        destination = target.with_name(f'{index:03d}'+source.name[3:])
                        temporary = destination.with_name(destination.name+'.reference.tmp')
                        shutil.copy2(source, temporary)
                        temporary.replace(destination)
                write_json_atomic(target.with_suffix('.selection.json'), dict(selected=str(candidate), automatic=True,
                    reason='reference-regeneration', time=time.time(), sha256=content_digest(target)))
            worker.emit('illustrations', (indices.index(index)+1)/len(indices), artifact=str(target),
                        message=f'Illustration {index+1} regenerated with the edited references', index=index)
        if indices and config.get('auto_verify') and config.get('vision_model'):
            from studio.batches import process_batch
            process_batch(worker, root, manifest, 'verify',
                [dict(index=i, model=config['vision_model']) for i in indices])
