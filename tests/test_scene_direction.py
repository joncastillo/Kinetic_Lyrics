"""Scene fields survive editing and reach video generation without hidden summary beats."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from direction.scene_direction import reference_style, with_style
from direction.story import normalise, write_story, split_long_beats
from studio.job_routes import JobRoutes


def segment(**extra):
    return dict(index=0, seconds=20, characters='The Farmer: weathered, muddy overalls. A giant water bug.',
                environment='A flooded rice paddy at grey dawn.', camera='wide, low angle, slow push in',
                moment='The farmer discovers the bug.', scene_direction='summary',
                scene='The farmer discovers a water bug among the rice stalks and lifts it into a clear container.',
                beats=[], **extra)


def test_summary_writer_constructs_fields_without_requesting_timed_beats():
    request = Mock(return_value={'segments': [segment()]})
    result = write_story('director', [dict(index=0, seconds=20, lyrics='Discover the bug', scene='Paddy')],
                         request=request, scene_direction='summary')
    assert request.call_count == 1
    payload = request.call_args.args[0]
    fields = payload['format']['properties']['segments']['items']['properties']
    assert set(fields) == {'index', 'moment', 'characters', 'environment', 'camera', 'scene'}
    assert 'no timestamps' in payload['messages'][0]['content']
    assert result[0]['scene'] == segment()['scene']
    assert result[0]['beats'] == []
    assert split_long_beats('director', result, request=request) == 0
    assert request.call_count == 1


def test_reference_prompt_is_preserved_separately_from_ai_fields():
    supplied = 'Expressive faces. Delicate linework. ' * 40
    job = dict(reference_prompt=supplied, style_prompt='Do not use this combined image prompt.', reference_paths=['photo.png'])
    styled = with_style(segment(), job)
    assert styled['art_style'] == 'Use @photo1 for the rendering style.\n' + supplied.strip()
    assert normalise(styled, 20)['art_style'] == styled['art_style']
    assert with_style(dict(styled, art_style='My edit'), job)['art_style'] == 'My edit'
    assert reference_style(dict(style_prompt='Ink', reference_paths=[])) == 'Ink'






def test_scene_direction_setting_persists(tmp_path):
    job = SimpleNamespace(folder=tmp_path, config=dict(type_effect='none'))
    handler = SimpleNamespace(respond=lambda value: value)
    for choice in ('summary', 'timed'):
        JobRoutes._job_settings(handler, job, 'settings', dict(scene_direction=choice), {})
        assert json.loads((tmp_path/'config.json').read_text())['scene_direction'] == choice


def test_write_with_ai_uses_the_project_mode_and_reference_prompt(tmp_path):
    from studio import worker
    (tmp_path/'video.timings.json').write_text('[]')
    config = dict(audio='song.wav', illustration_lines=2, scene_direction='summary', style_prompt='Soft ink')
    with patch.object(worker, 'media_duration', return_value=20), patch('direction.story.ensure_story') as write:
        worker.write_story(tmp_path, config, tmp_path/'illustrations.json')
    args = write.call_args.args[3]
    assert args.scene_direction == 'summary'
    assert args.style_prompt == 'Soft ink'
    assert write.call_args.kwargs['rewrite'] is True
