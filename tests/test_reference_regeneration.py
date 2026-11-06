import copy
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from core.files import content_digest, write_json_atomic
from direction import reference_edits
from direction.entities import painting_order
from direction.story import load, save
from studio import reference_regeneration as regeneration
from studio.job_routes import JobRoutes


@pytest.fixture
def project(tmp_path):
    root = tmp_path/'song'
    art = root/'video.artwork'/'run'
    (art/'entities').mkdir(parents=True)
    manifest = art/'illustrations.json'
    write_json_atomic(manifest, dict(model='Qwen/Qwen-Image-2.1', seed=1, style_prompt='Luminous color',
                                   prompts=['a scene', 'b scene', 'c scene', 'd scene']))
    entities = [dict(id='a', name='A', kind='character', looks='A blue shirt.', segments=[0]),
                dict(id='b', name='B', kind='character', looks='A blue shirt with a torn sleeve.', base='a', segments=[1]),
                dict(id='c', name='C', kind='object', looks='A blue prop.', segments=[2], reference_inputs=[dict(kind='entity', id='b', role='style')]),
                dict(id='d', name='D', kind='place', looks='A room.', segments=[3])]
    for index, entity in enumerate(entities):
        path = art/'entities'/f'{entity["id"]}.old.png'
        Image.new('RGB', (32, 32), (index*40, 40, 80)).save(path)
        entity['image'] = str(path)
        Image.new('RGB', (32, 32), (index*40, 80, 80)).save(art/f'{index:03d}.png')
        (art/f'{index:03d}.raw.png').write_bytes((art/f'{index:03d}.png').read_bytes())
    story = dict(segments=[dict(index=i) for i in range(4)], entities=entities)
    write_json_atomic(art/'story.json', story)
    (root/'references').mkdir()
    Image.new('RGB', (32, 32), 'green').save(root/'references'/'style.png')
    job = SimpleNamespace(folder=root, config={}, state=dict(status='complete', action=None, dirty=[], queued_actions=[]),
        manifest=lambda: manifest, url=lambda p: '/files/'+p.name, leave_animation=mock.Mock(), log=mock.Mock(),
        save=mock.Mock(), start_next=mock.Mock(), entity_references=lambda: [])
    args = dict(id='a', looks='A red shirt.', prompt='Paint A in a red shirt.\nKeep the face.', revision='',
                inputs=[dict(kind='project', id='style.png', role='style')])
    return SimpleNamespace(root=root, art=art, manifest=manifest, story=story, job=job, args=args)


def test_description_prompt_and_inputs_survive_a_stale_ai_save_and_fresh_story(project):
    p = project
    stale = copy.deepcopy(p.story)
    plan = regeneration.prepare(p.job, p.args)
    regeneration.commit(p.job, plan)
    save(p.manifest, stale)
    current = load(p.manifest)['entities'][0]
    assert current['looks'] == 'A red shirt.'
    assert current['prompt'] == p.args['prompt']
    assert current['reference_inputs'] == p.args['inputs']
    assert 'image' not in current
    # A fresh prompt run has a different content-addressed directory, but the same user recipe.
    other = p.art.parent/'new-run'
    other.mkdir()
    write_json_atomic(other/'story.json', stale)
    assert load(other/'illustrations.json')['entities'][0]['looks'] == 'A red shirt.'


def test_transitive_dependencies_are_archived_but_unrelated_art_survives(project):
    p = project
    candidate = p.root/'candidates'/'001'/'old'
    candidate.mkdir(parents=True)
    (candidate/'000.png').write_bytes(b'old candidate')
    digest = content_digest(p.art/'001.png')
    clip = p.root/'video-clips'/(digest[:24]+'-model')
    clip.mkdir(parents=True)
    (clip/'clip.mp4').write_bytes(b'old clip')
    plan = regeneration.prepare(p.job, p.args)
    assert plan['affected'] == {'a', 'b', 'c'}
    assert plan['indices'] == [0, 1, 2]
    _, archive = regeneration.commit(p.job, plan)
    for index in range(3):
        assert not (p.art/f'{index:03d}.png').exists()
        assert not (p.art/f'{index:03d}.raw.png').exists()
    assert (p.art/'003.png').exists()
    assert (p.art/'entities'/'d.old.png').exists()
    assert not candidate.exists() and not clip.exists()
    assert list(archive.rglob('001.png')) and list(archive.rglob('clip.mp4'))


def test_cycles_path_traversal_and_stale_forms_are_rejected_before_mutation(project):
    p = project
    for key in ('a', 'b', 'c'):
        with pytest.raises(ValueError, match='itself'):
            regeneration.prepare(p.job, dict(p.args, inputs=[dict(kind='entity', id=key)]))
    with pytest.raises(ValueError):
        regeneration.prepare(p.job, dict(p.args, inputs=[dict(kind='project', id='../style.png')]))
    with pytest.raises(ValueError, match='changed'):
        regeneration.prepare(p.job, dict(p.args, revision='stale'))
    assert (p.art/'000.png').exists()


def test_selected_entity_inputs_resolve_the_latest_picture_and_paint_first(project):
    p = project
    entity = dict(p.story['entities'][0], reference_inputs=[dict(kind='entity', id='d', role='detail')])
    story = dict(p.story, entities=[entity, dict(p.story['entities'][3], image='')])
    assert [e['id'] for e in painting_order([entity], story)] == ['d', 'a']
    pictures, instruction = reference_edits.conditioning(p.manifest, entity, p.story, 4)
    assert pictures[0].getpixel((0, 0)) == (120, 40, 80)
    assert 'specific visual details' in instruction


def test_panel_supplies_description_prompt_dependencies_and_builtins(project):
    info = regeneration.details(project.job, 'a')
    assert info['looks'] == 'A blue shirt.'
    assert 'A blue shirt' in info['prompt']
    assert info['images'] == [1, 2, 3]
    assert info['dependents'] == ['B', 'C']
    keys = {(i['kind'], i['id']) for i in info['options']}
    assert ('project', 'style.png') in keys
    assert ('builtin', 'default-style') in keys
    assert ('entity', 'a') not in keys and ('entity', 'b') not in keys


def test_route_queues_one_reference_batch_with_all_dependent_images(project):
    p = project
    handler = SimpleNamespace(respond=lambda value: value)
    result = JobRoutes._job_reference_repaint(handler, p.job, 'reference-repaint', p.args, {})
    assert result['ok']
    queued = p.job.state['queued_actions']
    assert {q['entity'] for q in queued} == {'a', 'b', 'c'}
    assert next(q for q in queued if q['entity'] == 'a')['images'] == [0, 1, 2]
    p.job.start_next.assert_called_once()


def test_uploaded_picture_is_an_input_not_a_replacement(project):
    p = project
    data = io.BytesIO()
    Image.new('RGB', (32, 32), 'purple').save(data, 'PNG')
    handler = SimpleNamespace(respond=lambda value: value)
    result = JobRoutes._job_reference_input_upload(handler, p.job, '', {}, {'reference': [('pose.png', data.getvalue())]})
    assert result['added'][0]['kind'] == 'upload'
    assert (p.root/'reference-inputs'/result['added'][0]['id']).is_file()
    assert load(p.manifest)['entities'][0]['image'] == p.story['entities'][0]['image']


def test_worker_installs_only_dependent_images_after_references(project):
    p = project
    plan = regeneration.prepare(p.job, p.args)
    revision, _ = regeneration.commit(p.job, plan)
    worker = SimpleNamespace(paint_references=mock.Mock(), check_references=mock.Mock(), emit=mock.Mock())
    def candidate(root, job, index, cache, prompt):
        assert worker.paint_references.called
        assert 'red shirt' in prompt if index == 0 else True
        folder = p.root/'candidates'/f'{index:03d}'/'new'
        folder.mkdir(parents=True)
        path = folder/'000.png'
        Image.new('RGB', (32, 32), 'red').save(path)
        return path
    worker.generate_candidate = mock.Mock(side_effect=candidate)
    with mock.patch('models.gpu.lifecycle.ModelSession', return_value=mock.MagicMock()):
        regeneration.regenerate(worker, p.root, p.manifest, [dict(id='a', images=[0, 1, 2], revision=revision)], {}, p.root)
    assert [call.args[2] for call in worker.generate_candidate.call_args_list] == [0, 1, 2]
    assert all((p.art/f'{i:03d}.png').is_file() for i in range(4))
    assert json.loads((p.art/'000.selection.json').read_text())['reason'] == 'reference-regeneration'


def test_image_maker_project_sync_is_reached_through_the_real_http_dispatch(project):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from studio import server
    p = project
    home = p.root/'test-maker'
    (home/'references').mkdir(parents=True)
    class Handler(server.Handler):
        def _maker_home(self): return home
        def _maker_state(self, home): return dict(references=[f.name for f in (home/'references').glob('*.png')])
        def log_message(self, *args): pass
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    with mock.patch.dict(server.JOBS, {'song': p.job}):
        thread.start()
        try:
            request = urllib.request.Request(f'http://127.0.0.1:{http.server_port}/api/image-maker/project-references',
                json.dumps(dict(job='song', id='a')).encode(),
                {'Content-Type':'application/json', 'X-Studio-Token':server.TOKEN})
            with urllib.request.urlopen(request, timeout=10) as response:
                answer = json.load(response)
            assert answer['added'] and 'a' in answer['reference_map']
        finally:
            http.shutdown();http.server_close();thread.join(timeout=5)


def test_a_reference_edit_invalidates_stale_pixel_edits_only_for_its_dependents(project):
    from artwork.reference_lifecycle import validate_target
    p = project
    regeneration.commit(p.job, regeneration.prepare(p.job, p.args))
    with pytest.raises(ValueError, match='inputs changed'):
        validate_target(p.root, dict(id='b'))
    validate_target(p.root, dict(id='d'))


def test_image_versions_include_saved_recipes_and_uploaded_inputs(project):
    from studio.pipeline_history import files
    p = project
    regeneration.commit(p.job, regeneration.prepare(p.job, p.args))
    inputs = p.root/'reference-inputs'
    inputs.mkdir()
    (inputs/'detail.png').write_bytes(b'input')
    captured = set(files(p.root, 'images', p.art))
    assert p.root/'reference-edits.json' in captured
    assert inputs/'detail.png' in captured


def version_handler(project):
    from studio.job_clips import ClipWork
    project.job.edit_entity = lambda op, entry, upload=None: ClipWork.edit_entity(project.job, op, entry, upload)
    handler = SimpleNamespace(respond=lambda value: value)
    handler._job_reference_repaint = lambda *args, **kwargs: JobRoutes._job_reference_repaint(handler, *args, **kwargs)
    return handler


def test_selecting_an_older_picture_keeps_it_selected_and_rebuilds_dependencies(project):
    p = project
    source = Path(p.story['entities'][0]['image'])
    original = source.read_bytes()
    handler = version_handler(p)
    result = JobRoutes._job_story_entities(handler, p.job, 'story-entities',
        dict(id='a', regenerate_dependents='true'), {'picture': [('original.png', original)]})
    assert result['ok']
    entity = load(p.manifest)['entities'][0]
    assert entity['uploaded'] == entity['image']
    with Image.open(entity['image']) as selected:
        assert selected.convert('RGB').getpixel((0, 0)) == (0, 40, 80)
    assert next(q for q in p.job.state['queued_actions'] if q['entity'] == 'a')['images'] == [0, 1, 2]


def test_discard_current_reference_restores_original_and_preserves_files(project):
    from artwork.reference_lifecycle import signature
    from direction.entities import earlier_sheets
    p = project
    original = Path(p.story['entities'][0]['image'])
    original_signature = signature(original)
    newer = p.art/'entities'/'a.new.png'
    Image.new('RGB', (32,32), 'white').save(newer)
    discarded_signature = signature(newer)
    p.story['entities'][0].update(image=str(newer), image_history=[str(original)])
    write_json_atomic(p.art/'story.json', p.story)
    result = JobRoutes._job_reference_version(version_handler(p), p.job, 'reference-version',
        dict(id='a', url=p.job.url(newer)), {})
    assert result['ok']
    entity = load(p.manifest)['entities'][0]
    assert signature(entity['image']) == original_signature
    assert all(signature(path) != discarded_signature for path in earlier_sheets(p.manifest, entity))
    assert list(p.art.glob('previous-reference-edit-*/**/a.new.png')), 'Discard is recoverable'


def test_discard_unselected_reference_does_not_change_current_image(project):
    from direction.entities import earlier_sheets
    p = project
    older = p.art/'entities'/'a.older.png'
    Image.new('RGB', (32,32), 'white').save(older)
    current = load(p.manifest)['entities'][0]['image']
    result = JobRoutes._job_reference_version(version_handler(p), p.job, 'reference-version',
        dict(id='a', url=p.job.url(older)), {})
    assert result['ok']
    assert load(p.manifest)['entities'][0]['image'] == current
    assert older not in earlier_sheets(p.manifest, load(p.manifest)['entities'][0])
    p.job.start_next.assert_not_called()
