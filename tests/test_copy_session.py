"""Session import preserves usable paths, immutable history and checkpoint state."""
from contextlib import closing, contextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3

import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'automation'/'copy_session.py'
SPEC = importlib.util.spec_from_file_location('copy_session_automation', SCRIPT)
copy_session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(copy_session)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def session(root, name='20261106-song', **state):
    folder = root/name
    folder.mkdir(parents=True)
    write(folder/'config.json', {'name':'A song', 'audio':str(folder/'song.wav')})
    write(folder/'state.json', {'status':'complete', **state})
    (folder/'song.wav').write_bytes(b'audio bytes')
    return folder


def test_lists_sessions_and_ignores_unrelated_folders(tmp_path):
    a = session(tmp_path, '20261105-old')
    b = session(tmp_path, '20261106-new')
    (tmp_path/'cache').mkdir()
    assert [item['path'] for item in copy_session.sessions(tmp_path)] == [b, a]


def test_select_number_or_escape_without_copying(tmp_path):
    folder = session(tmp_path)
    items = copy_session.sessions(tmp_path)
    output = io.StringIO()
    assert copy_session.choose(items, iter('9\r1\r').__next__, output) == folder
    assert copy_session.choose(items, lambda:'\x1b', output) is None
    assert copy_session.choose(items, lambda:'', output) is None


def test_cancel_cli_does_not_create_destination_or_settings(tmp_path, monkeypatch):
    origin = tmp_path/'source'
    session(origin)
    destination = tmp_path/'destination'
    monkeypatch.setattr(copy_session, 'source_folder', lambda path:origin)
    monkeypatch.setattr(copy_session, 'destination_folder', lambda repo, explicit:destination)
    @contextmanager
    def escape():
        yield lambda:'\x1b'
    monkeypatch.setattr(copy_session, 'keyboard', escape)
    monkeypatch.setattr(copy_session, 'remember_destination', lambda *args:pytest.fail('Cancel changed settings'))
    assert copy_session.main([str(origin)]) == 0
    assert not destination.exists()


def test_repository_and_explicit_source_folder_resolution(tmp_path, monkeypatch):
    repo = tmp_path/'repo'
    (repo/'src/studio').mkdir(parents=True)
    (repo/'src/studio/server.py').write_text('raise RuntimeError("must never execute source code")')
    local = repo/'output/lyric-studio'
    local.mkdir(parents=True)
    assert copy_session.source_folder(repo) == local
    other = tmp_path/'custom'
    other.mkdir()
    write(repo/'.runtime/studio-settings.json', {'projects_folder':str(other)})
    assert copy_session.source_folder(repo) == other
    assert copy_session.source_folder(other) == other
    monkeypatch.delenv('KINETIC_LYRICS_OUTPUT', raising=False)
    assert copy_session.destination_folder(repo) == other


def test_copy_relocates_internal_paths_without_changing_source(tmp_path):
    source = session(tmp_path/'pub')
    external = tmp_path/'models'
    write(source/'recipe.json', {'image':str(source/'000.png'), 'cache':str(external),
                               'sibling':str(source)+'-different/file.png', 'list':[str(source/'song.wav')]})
    original = (source/'recipe.json').read_bytes()
    target, backup = copy_session.copy_session(source, tmp_path/'pro')
    assert backup is None
    config = copy_session.read_json(target/'config.json')
    recipe = copy_session.read_json(target/'recipe.json')
    assert Path(config['audio']) == target/'song.wav'
    assert Path(recipe['image']) == target/'000.png'
    assert recipe['cache'] == str(external)
    assert recipe['sibling'] == str(source)+'-different/file.png'
    assert (target/'song.wav').read_bytes() == b'audio bytes'
    assert (source/'recipe.json').read_bytes() == original


def test_overwrite_replaces_whole_session_and_keeps_old_backup(tmp_path):
    source = session(tmp_path/'pub')
    old = session(tmp_path/'pro')
    (old/'stale.mp4').write_bytes(b'previous export')
    target, backup = copy_session.copy_session(source, old.parent)
    assert target == old and not (target/'stale.mp4').exists()
    assert (backup/'stale.mp4').read_bytes() == b'previous export'
    assert backup.parent == old.parent/'.session-backups'
    assert not list(old.parent.glob('.session-copy-*'))


def test_failure_before_install_leaves_existing_session_intact(tmp_path, monkeypatch):
    source = session(tmp_path/'pub')
    target = session(tmp_path/'pro')
    (target/'keep.txt').write_text('keep')
    def fail(*args):
        raise OSError('disk failed')
    monkeypatch.setattr(copy_session, 'relocate_json', fail)
    with pytest.raises(OSError, match='disk failed'):
        copy_session.copy_session(source, target.parent)
    assert (target/'keep.txt').read_text() == 'keep'
    assert not list(target.parent.glob('.session-copy-*'))


def test_failed_final_rename_restores_previous_session(tmp_path, monkeypatch):
    source = session(tmp_path/'pub')
    target = session(tmp_path/'pro')
    (target/'keep.txt').write_text('keep')
    rename = Path.rename
    def fail_stage(path, destination):
        if path.name == 'session' and path.parent.name.startswith('.session-copy-'):
            raise OSError('cannot install')
        return rename(path, destination)
    monkeypatch.setattr(Path, 'rename', fail_stage)
    with pytest.raises(OSError, match='cannot install'):
        copy_session.copy_session(source, target.parent)
    assert (target/'keep.txt').read_text() == 'keep'


def test_changed_source_is_not_installed(tmp_path, monkeypatch):
    source = session(tmp_path/'pub')
    target = session(tmp_path/'pro')
    (target/'keep.txt').write_text('keep')
    relocate = copy_session.relocate_json
    def mutate(stage, move):
        relocate(stage, move)
        (source/'new-output.png').write_bytes(b'new')
    monkeypatch.setattr(copy_session, 'relocate_json', mutate)
    with pytest.raises(ValueError, match='Source session changed'):
        copy_session.copy_session(source, target.parent)
    assert (target/'keep.txt').read_text() == 'keep'


def test_overlapping_source_and_destination_are_refused(tmp_path):
    source = session(tmp_path)
    with pytest.raises(ValueError, match='overlap'):
        copy_session.copy_session(source, source.parent)
    with pytest.raises(ValueError, match='overlap'):
        copy_session.copy_session(source, source/'inside')


def test_active_destination_is_not_overwritten(tmp_path):
    source = session(tmp_path/'pub')
    target = session(tmp_path/'pro', status='running')
    with pytest.raises(ValueError, match='Stop the destination'):
        copy_session.copy_session(source, target.parent)
    assert copy_session.read_json(target/'state.json')['status'] == 'running'


def test_symlink_in_source_is_refused(tmp_path):
    source = session(tmp_path/'pub')
    outside = tmp_path/'outside.txt'
    outside.write_text('outside')
    try:
        (source/'linked.txt').symlink_to(outside)
    except OSError:
        pytest.skip('OS does not permit creating symlinks')
    with pytest.raises(ValueError, match='link or junction'):
        copy_session.copy_session(source, tmp_path/'pro')


def test_immutable_pipeline_objects_are_rehashed_and_restore_new_paths(tmp_path):
    from pipeline.versions import Versions
    source = session(tmp_path/'pub')
    versions = Versions(source)
    versions.capture('timing', [source/'config.json'], settings={'audio':str(source/'song.wav')})
    old_digest = versions.manifest('timing', 1)['files']['config.json']
    target, _ = copy_session.copy_session(source, tmp_path/'pro')
    copied = Versions(target)
    manifest = copied.manifest('timing', 1)
    digest = manifest['files']['config.json']
    assert digest != old_digest
    assert hashlib.sha256(copied.blob(digest).read_bytes()).hexdigest() == digest
    copied.select('timing', 1)
    assert Path(copy_session.read_json(target/'config.json')['audio']) == target/'song.wav'
    assert versions.manifest('timing', 1)['files']['config.json'] == old_digest


def test_sqlite_wal_checkpoint_paths_and_thread_ids_are_relocated(tmp_path):
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    source = session(tmp_path/'pub')
    checkpoint = source/'video.graph.sqlite'
    codec = JsonPlusSerializer()
    kind, blob = codec.dumps_typed({'audio':str(source/'song.wav'), 'picture':source/'000.png'})
    with closing(sqlite3.connect(checkpoint)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE checkpoints (thread_id TEXT, type TEXT, checkpoint BLOB, metadata BLOB)')
        db.execute('CREATE TABLE writes (thread_id TEXT, type TEXT, value BLOB)')
        db.execute('INSERT INTO checkpoints VALUES (?,?,?,?)', (str(source/'video.mp4'), kind, blob, b'{}'))
        db.execute('INSERT INTO writes VALUES (?,?,?)', (str(source/'video.mp4'), kind, blob))
        db.commit()
        target, _ = copy_session.copy_session(source, tmp_path/'pro')
        assert db.execute('SELECT thread_id FROM checkpoints').fetchone()[0] == str(source/'video.mp4')
    with closing(sqlite3.connect(target/'video.graph.sqlite')) as copied:
        thread, kind, payload = copied.execute('SELECT thread_id, type, checkpoint FROM checkpoints').fetchone()
        assert thread == str(target/'video.mp4')
        data = codec.loads_typed((kind, payload))
        assert Path(data['audio']) == target/'song.wav'
        assert data['picture'] == target/'000.png'
        assert copied.execute('SELECT thread_id FROM writes').fetchone()[0] == str(target/'video.mp4')


def test_serialized_constructor_is_not_executed(tmp_path, monkeypatch):
    import msgpack
    monkeypatch.setattr(copy_session.os, 'system', lambda *args:pytest.fail('Executed a serialized constructor'))
    descriptor = msgpack.ExtType(0, msgpack.packb(('os', 'system', 'echo unsafe'), use_bin_type=True))
    raw = msgpack.packb({'data':descriptor}, use_bin_type=True)
    result = copy_session.relocate_msgpack(raw, copy_session.path_mapper(tmp_path/'a', tmp_path/'b'))
    assert msgpack.unpackb(result, raw=False)['data'].code == 0


def test_unsupported_checkpoint_encoding_keeps_destination(tmp_path):
    source = session(tmp_path/'pub')
    target = session(tmp_path/'pro')
    (target/'keep.txt').write_text('keep')
    with closing(sqlite3.connect(source/'video.graph.sqlite')) as db:
        db.execute('CREATE TABLE checkpoints (thread_id TEXT, type TEXT, checkpoint BLOB, metadata BLOB)')
        db.execute('INSERT INTO checkpoints VALUES (?,?,?,?)', ('thread', 'pickle', b'never deserialize', b'{}'))
        db.commit()
    with pytest.raises(ValueError, match='Unsupported checkpoint encoding'):
        copy_session.copy_session(source, target.parent)
    assert (target/'keep.txt').read_text() == 'keep'


def test_remember_destination_preserves_other_settings(tmp_path):
    settings = tmp_path/'.runtime/studio-settings.json'
    write(settings, {'other':'keep'})
    copy_session.remember_destination(tmp_path, tmp_path/'sessions')
    assert copy_session.read_json(settings) == {'other':'keep','projects_folder':str(tmp_path/'sessions')}


def test_invalid_session_state_is_reported_before_copy(tmp_path):
    source = session(tmp_path/'pub')
    write(source/'state.json', [])
    with pytest.raises(ValueError, match='Session state must contain a JSON object'):
        copy_session.copy_session(source, tmp_path/'pro')
    assert not (tmp_path/'pro').exists()


def test_path_relocation_does_not_redirect_parent_traversal(tmp_path):
    source, target = tmp_path/'source', tmp_path/'target'
    value = str(source/'..'/'outside.txt')
    assert copy_session.path_mapper(source, target)(value) == value
