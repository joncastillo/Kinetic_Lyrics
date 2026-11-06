import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from artwork.reference_lifecycle import advance, generation, retire_library, sync_library, validate_target
from core.files import write_json_atomic
from direction.entities import sheet_path
from direction.reference_choices import remember
from direction.story import load
from studio import maker_routes, server


@pytest.fixture
def project(tmp_path):
    folder = tmp_path/'projects'/'song'
    art = folder/'video.artwork'/'run'
    entities = art/'entities'
    entities.mkdir(parents=True)
    manifest = art/'illustrations.json'
    write_json_atomic(manifest, dict(prompts=['scene'], model='Qwen/Qwen-Image-2.1', seed=1))
    source = entities/'arnel.png'
    Image.new('RGB', (32, 32), 'red').save(source)
    entry = dict(id='arnel', name='Arnel', kind='character', image=str(source), looks='A man', segments=[0])
    write_json_atomic(art/'story.json', dict(segments=[dict(index=0)], entities=[entry]))
    write_json_atomic(art/'prompting.json', dict(song='saved upstream work'))
    home = tmp_path/'image-maker'
    (home/'references').mkdir(parents=True)
    job = SimpleNamespace(folder=folder, config={}, manifest=lambda: manifest)
    return SimpleNamespace(folder=folder, art=art, manifest=manifest, source=source, entry=entry, home=home, job=job)


@pytest.mark.parametrize('step', ['timing', 'prompts'])
def test_restart_before_images_cannot_resurrect_selected_or_cached_sheets(project, step):
    p = project
    remember(p.manifest, 'arnel', dict(image=str(p.source), uploaded=str(p.source)))
    cached = sheet_path(p.manifest, p.entry, '', 'Qwen/Qwen-Image-2.1')
    cached.write_bytes(p.source.read_bytes())
    (p.art/'000.png').write_bytes(p.source.read_bytes())
    server.clear_redone_work(p.folder, {}, step)
    assert not (p.art/'story.json').exists()
    assert not cached.exists()
    assert not (p.art/'000.png').exists()
    assert json.loads((p.art/'prompting.json').read_text())['song'] == 'saved upstream work'
    assert list(p.art.glob('previous-*/entities/arnel.png'))
    assert list(p.art.glob('previous-*/reference-choices.json'))
    write_json_atomic(p.art/'story.json', dict(segments=[], entities=[dict(id='arnel')]))
    assert 'image' not in load(p.manifest)['entities'][0]


def test_full_image_restart_invalidates_edit_upload_and_preserves_real_upload(project):
    p = project
    edited = p.art/'entities'/'edit.png'
    upload = p.art/'entities'/'mine.png'
    Image.new('RGB', (32, 32), 'blue').save(edited)
    Image.new('RGB', (32, 32), 'green').save(upload)
    entry = dict(p.entry, image=str(edited), uploaded=str(edited), image_history=[str(p.source)])
    write_json_atomic(p.home/'history.json', [dict(path=str(edited), edit_target=dict(job='song', id='arnel'))])
    write_json_atomic(p.art/'story.json', dict(segments=[], entities=[entry, dict(id='mine', image=str(upload), uploaded=str(upload))]))
    remember(p.manifest, 'arnel', dict(image=str(edited), uploaded=str(edited)))
    server.clear_redone_work(p.folder, {}, 'images')
    arnel, mine = load(p.manifest)['entities']
    assert 'image' not in arnel and 'uploaded' not in arnel and 'image_history' not in arnel
    assert mine['image'] == str(upload)
    assert arnel['reference_generation'] == generation(p.folder)
    assert sheet_path(p.manifest, arnel, '', 'Qwen/Qwen-Image-2.1') != sheet_path(p.manifest, entry, '', 'Qwen/Qwen-Image-2.1')
    assert edited.exists() and upload.exists()


def test_old_choices_fail_closed_even_if_old_file_is_restored(project):
    p = project
    remember(p.manifest, 'arnel', dict(image=str(p.source), uploaded=str(p.source)))
    advance(p.folder)
    write_json_atomic(p.art/'story.json', dict(segments=[], entities=[dict(id='arnel')]))
    assert 'image' not in load(p.manifest)['entities'][0]


def test_prompt_restart_invalidates_other_content_addressed_runs_too(project):
    p = project
    other = p.art.parent/'older-run'
    (other/'entities').mkdir(parents=True)
    (other/'entities'/'arnel.png').write_bytes(p.source.read_bytes())
    write_json_atomic(other/'story.json', dict(segments=[], entities=[p.entry]))
    write_json_atomic(other/'illustrations.json', dict(prompts=['old scene']))
    server.clear_redone_work(p.folder, {}, 'prompts')
    assert not (other/'entities').exists()
    assert not (other/'story.json').exists()
    assert (other/'illustrations.json').exists()


def test_explicit_upload_origin_overrides_legacy_edit_inference(project):
    from artwork.reference_lifecycle import is_generated_edit, signature
    p = project
    entry = dict(p.entry, uploaded=str(p.source), image_origin='upload')
    assert not is_generated_edit(entry, {signature(p.source)})


def test_library_retires_project_copies_but_keeps_unrelated_inputs(project):
    p = project
    old = p.home/'references'/'Arnel.png'
    old.write_bytes(p.source.read_bytes())
    independent = p.home/'references'/'anatomy-study.png'
    Image.new('RGB', (32, 32), 'blue').save(independent)
    assert retire_library(p.folder, p.home) == ['Arnel.png']
    assert not old.exists() and independent.exists() and p.source.exists()
    assert list((p.home/'retired-references').glob('song/*/Arnel.png'))


def test_open_editor_refreshes_same_name_to_current_pixels(project):
    p = project
    (p.home/'references'/'Arnel.png').write_bytes(p.source.read_bytes())
    new = p.art/'entities'/'arnel-new.png'
    Image.new('RGB', (32, 32), 'blue').save(new)
    write_json_atomic(p.art/'story.json', dict(segments=[], entities=[dict(p.entry, image=str(new))]))
    result = sync_library(p.home, p.job, dict(id='arnel'))
    assert result['added'] == ['Arnel.png']
    assert (p.home/'references'/'Arnel.png').read_bytes() == new.read_bytes()
    assert len(list((p.home/'references').glob('*.png'))) == 1


def test_stale_completed_edit_cannot_replace_new_reference(project):
    p = project
    advance(p.folder)
    p.job.edit_entity = mock.Mock()
    request = dict(request_id='old', edit_target=dict(job='song', id='arnel'))
    with mock.patch.dict(server.JOBS, {'song': p.job}):
        result = maker_routes.apply_completed_reference(p.home, request, dict(state='done', files=[str(p.source)]))
    assert 'earlier artwork run' in result['reference_error']
    p.job.edit_entity.assert_not_called()


def test_stale_queued_edit_is_archived_not_launched(project):
    p = project
    advance(p.folder)
    old = dict(request_id='old', edit_target=dict(job='song', id='arnel'))
    current = dict(request_id='new', edit_target=dict(job='song', id='arnel', reference_generation=generation(p.folder)))
    write_json_atomic(p.home/'queue.json', [old, current])
    with mock.patch.dict(server.JOBS, {'song': p.job}), mock.patch.object(maker_routes, 'running', None):
        assert maker_routes.clean_queue(p.home, {}) == [current]
    assert json.loads((p.home/'retired-edits.json').read_text())[0]['request_id'] == 'old'


@pytest.mark.parametrize('step,substep', [('images', 'illustrations'), ('review', ''), ('render', '')])
def test_preserving_nodes_keep_reference_generation_and_choices(project, step, substep):
    p = project
    token = advance(p.folder)
    remember(p.manifest, 'arnel', dict(image=str(p.source), uploaded=str(p.source)))
    server.clear_redone_work(p.folder, dict(start_substep=substep), step)
    assert generation(p.folder) == token
    assert p.source.exists()
    assert load(p.manifest)['entities'][0]['image'] == str(p.source)
    validate_target(p.folder, dict(reference_generation=token))
