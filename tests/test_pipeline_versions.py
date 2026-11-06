"""Branch compatibility and restoration exercise real on-disk immutable outputs."""

import json
from unittest import mock

import pytest

from pipeline.versions import Versions
from studio.pipeline_history import capture, preserve_existing


def output(folder, name, text):
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def save(history, node, text):
    return history.capture(node, [output(history.folder, node + '.txt', text)])


def test_selecting_earlier_node_recovers_latest_compatible_descendants(tmp_path):
    history = Versions(tmp_path)
    save(history, 'timing', 'A')
    save(history, 'prompts', 'A1')
    save(history, 'prompts', 'A2')
    save(history, 'story', 'A2 story')
    original_sequence = history.summary()['active']
    save(history, 'timing', 'B')
    save(history, 'prompts', 'B1')
    save(history, 'story', 'B story')
    selected = history.select('timing', 1)
    assert selected['nodes']['prompts']['current'] == 2
    assert selected['nodes']['story']['current'] == 1
    assert (tmp_path / 'story.txt').read_text() == 'A2 story'
    assert selected['active'] > original_sequence
    assert next(s for s in selected['sequences'] if s['id'] == original_sequence)['nodes']['prompts'] == 2


def test_no_compatible_output_is_unselected_and_removed_from_working_copy(tmp_path):
    history = Versions(tmp_path)
    save(history, 'timing', 'A')
    save(history, 'prompts', 'A1')
    save(history, 'timing', 'B')
    selected = history.select('timing', 2)
    assert selected['nodes']['prompts']['current'] is None
    assert not (tmp_path / 'prompts.txt').exists()
    assert history.manifest('prompts', 1)['files']  # retained in history


def test_whole_pipeline_selection_restores_exact_series_not_latest(tmp_path):
    history = Versions(tmp_path)
    save(history, 'timing', 'A')
    save(history, 'prompts', 'first')
    first = history.summary()['active']
    save(history, 'prompts', 'second')
    summary = history.select(sequence=first)
    assert summary['nodes']['prompts']['current'] == 1
    assert (tmp_path / 'prompts.txt').read_text() == 'first'
    assert summary['sequences'][-1]['parent'] == first + 1


def test_regeneration_after_rewind_never_overwrites_existing_version(tmp_path):
    history = Versions(tmp_path)
    save(history, 'timing', 'first')
    save(history, 'timing', 'second')
    history.select('timing', 1)
    assert save(history, 'timing', 'third') == 3
    assert history.blob(history.manifest('timing', 2)['files']['timing.txt']).read_text() == 'second'


def test_identical_contents_share_objects_but_explicit_regeneration_gets_a_version(tmp_path):
    history = Versions(tmp_path)
    path = output(tmp_path, 'timing.txt', 'same')
    assert history.capture('timing', [path], force=True, run=1) == 1
    assert history.capture('timing', [path], force=True, run=1) == 1
    assert history.capture('timing', [path], force=True, run=2) == 2
    assert len(list((tmp_path / 'pipeline' / 'objects').iterdir())) == 1


def test_incompatible_version_is_rejected_without_changing_active_selection(tmp_path):
    history = Versions(tmp_path)
    save(history, 'timing', 'A')
    save(history, 'prompts', 'A')
    save(history, 'timing', 'B')
    before = history.summary()['active']
    with pytest.raises(ValueError, match='upstream'):
        history.select('prompts', 1)
    assert history.summary()['active'] == before


def test_failure_during_restore_rolls_back_files_and_index(tmp_path):
    history = Versions(tmp_path)
    save(history, 'timing', 'first')
    save(history, 'timing', 'second')
    before = history.summary()['active']
    original = history.install

    def failed_install(files, managed, times=None):
        original(files, managed, times)
        if (tmp_path / 'timing.txt').read_text() == 'first':
            raise OSError('disk error')

    with mock.patch.object(history, 'install', side_effect=failed_install):
        with pytest.raises(OSError, match='disk error'):
            history.select('timing', 1)
    assert (tmp_path / 'timing.txt').read_text() == 'second'
    assert history.summary()['active'] == before


def test_missing_blob_prevents_partial_restore(tmp_path):
    history = Versions(tmp_path)
    save(history, 'timing', 'first')
    save(history, 'timing', 'second')
    history.blob(history.manifest('timing', 1)['files']['timing.txt']).unlink()
    with pytest.raises(ValueError, match='damaged'):
        history.select('timing', 1)
    assert (tmp_path / 'timing.txt').read_text() == 'second'


def test_restored_mtime_keeps_render_provenance_valid(tmp_path):
    history = Versions(tmp_path)
    path = output(tmp_path, 'video.mp4', 'first')
    stamp = path.stat().st_mtime_ns
    history.capture('render', [path])
    history.capture('render', [output(tmp_path, 'video.mp4', 'second')])
    history.select('render', 1)
    assert path.stat().st_mtime_ns == stamp


def test_paths_cannot_escape_project(tmp_path):
    history = Versions(tmp_path)
    with pytest.raises(ValueError):
        history.safe('../outside.txt')
    with pytest.raises(ValueError):
        history.blob('../outside')


def test_legacy_import_and_node_adapter_preserve_audio_settings_and_artwork(tmp_path):
    audio = output(tmp_path, 'song.wav', 'original audio')
    output(tmp_path, 'config.json', json.dumps(dict(audio=str(audio), name='Song', image_seed=7)))
    output(tmp_path, 'video.timings.json', '[]')
    output(tmp_path, 'video.artwork/key/illustrations.json', '{"prompts":["first"]}')
    output(tmp_path, 'video.artwork/key/000.png', 'first image')
    output(tmp_path, 'active-artwork.json', '{"manifest":"video.artwork/key/illustrations.json"}')
    preserve_existing(tmp_path)
    first = Versions(tmp_path).summary()['active']
    output(tmp_path, 'video.artwork/key/000.png', 'second image')
    capture(tmp_path, 'images', force=True)
    output(tmp_path, 'song.wav', 'changed audio')
    Versions(tmp_path).select(sequence=first)
    assert audio.read_text() == 'original audio'
    assert (tmp_path / 'video.artwork/key/000.png').read_text() == 'first image'
    assert json.loads((tmp_path / 'config.json').read_text())['image_seed'] == 7


def test_prompt_snapshot_does_not_reuse_future_substeps(tmp_path):
    output(tmp_path, 'config.json', '{}')
    output(
        tmp_path,
        'video.artwork/key/prompting.json',
        json.dumps(dict(song={}, meanings=[], story=['later'], scenes=['later'], fit=['later'], saved_at={})),
    )
    capture(tmp_path, 'prompts', artwork=tmp_path / 'video.artwork/key')
    Versions(tmp_path).select('prompts', 1)
    saved = json.loads((tmp_path / 'video.artwork/key/prompting.json').read_text())
    assert 'song' in saved and 'meanings' in saved
    assert not {'story', 'scenes', 'fit'} & saved.keys()


def test_video_and_text_branches_are_independent_until_final_cut(tmp_path):
    history = Versions(tmp_path)
    for node in (
        'timing',
        'prompts',
        'story',
        'image-prompts',
        'images',
        'review',
        'render',
        'video',
        'scene-scan',
        'final',
    ):
        save(history, node, 'first')
    save(history, 'video', 'second')
    current = history.summary()['nodes']
    assert current['render']['current'] == 1
    assert current['scene-scan']['current'] is None
    assert current['final']['current'] is None
    restored = history.select('video', 1)['nodes']
    assert restored['scene-scan']['current'] == 1
    assert restored['final']['current'] == 1


def test_interrupted_rollback_is_recovered_on_next_open(tmp_path):
    history = Versions(tmp_path)
    save(history, 'timing', 'first')
    save(history, 'timing', 'second')
    original = history.install

    def interrupted(files, managed, times=None):
        original(files, managed, times)
        raise OSError('interrupted')

    with mock.patch.object(history, 'install', side_effect=interrupted):
        with pytest.raises(OSError):
            history.select('timing', 1)
    assert (tmp_path / 'pipeline/restore.json').exists()
    assert Versions(tmp_path).summary()['nodes']['timing']['current'] == 2
    assert (tmp_path / 'timing.txt').read_text() == 'second'
    assert not (tmp_path / 'pipeline/restore.json').exists()


def test_switch_clears_unfinished_output_but_retains_its_bytes(tmp_path):
    history = Versions(tmp_path)
    save(history, 'timing', 'finished')
    unfinished = output(tmp_path, 'video.artwork/abandoned/illustrations.json', '{"prompts":["unfinished"]}')
    history.select('timing', 1, extra_managed=[unfinished])
    assert not unfinished.exists()
    index = json.loads(history.index.read_text())
    backup = json.loads((tmp_path / index['working_copies'][-1]).read_text())
    digest = backup['files']['video.artwork/abandoned/illustrations.json']
    assert json.loads(history.blob(digest).read_text())['prompts'] == ['unfinished']


def test_restoring_implicit_defaults_removes_later_explicit_settings(tmp_path):
    output(tmp_path, 'config.json', '{"name":"Song"}')
    output(tmp_path, 'video.design.json', '{"plan":1}')
    capture(tmp_path, 'render')
    output(tmp_path, 'config.json', '{"name":"Song","font_family":"anton","audio_mode":"karaoke"}')
    capture(tmp_path, 'render')
    Versions(tmp_path).select('render', 1)
    config = json.loads((tmp_path / 'config.json').read_text())
    assert config['name'] == 'Song'
    assert 'font_family' not in config and 'audio_mode' not in config


def test_render_snapshots_include_typography_pictures_and_scene_windows(tmp_path):
    output(tmp_path, 'config.json', '{}')
    picture = output(tmp_path, 'video.ornaments/type/abc/000.png', 'picture')
    output(tmp_path, 'video.blocks.json', '{}')
    output(tmp_path, 'scene-lyrics.json', '{"windows":[[1,2]]}')
    capture(tmp_path, 'render')
    capture(tmp_path, 'scene-scan')
    history = Versions(tmp_path)
    sequence = history.summary()['active']
    picture.unlink()
    output(tmp_path, 'scene-lyrics.json', '{"windows":[]}')
    history.select(sequence=sequence)
    assert picture.read_text() == 'picture'
    assert json.loads((tmp_path / 'scene-lyrics.json').read_text())['windows'] == [[1, 2]]
