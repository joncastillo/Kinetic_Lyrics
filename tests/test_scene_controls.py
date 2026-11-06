"""Scene controls are validated, isolated, persistent, and visible in actual render output."""

import json

import numpy as np
import pytest
from PIL import Image

from direction.scene_catalog import scene_catalog
from direction.scene_controls import scene_settings
from direction.theme import theme_for
from direction.typography import rules_plan
from render.compositor import Compositor
from render.typography_settings import kinetic_options


def make(scene, overrides=None, size=(320, 180)):
    words = [
        dict(text=w, start=1 + i * 0.5, end=1.4 + i * 0.5) for i, w in enumerate('a quiet light stays here'.split())
    ]
    data = [dict(text='a quiet light stays here', words=words)]
    plan = dict(rules_plan(data, theme_for('bright')), scene_flows=[dict(start=0, end=1, scene=scene)])
    return Compositor(
        data,
        plan,
        *size,
        5.0,
        reading_flow='mixed',
        entrance_effect='none',
        exit_effect='none',
        kinetic=dict(fade=False, scene_settings={scene: overrides or {}}),
    )


def test_catalog_has_specific_motion_tags_and_controls_for_every_scene():
    catalog = scene_catalog()
    assert len(catalog) == 32
    for scene in catalog.values():
        assert scene['entry'] and scene['exit'] and scene['selection']
        assert scene['controls'] and scene['tags']
        assert len({s['key'] for s in scene['controls']}) == len(scene['controls'])
    assert {'minimalist', 'professional'} <= set(catalog['black-hole-sun']['tags'])
    assert 'ignored' in catalog['black-hole-sun']['selection']
    assert 'Fixed pairs' in catalog['camera-tour']['entry']


@pytest.mark.parametrize(
    'settings',
    [
        [],
        {'missing': {}},
        {'word-wall': {'speed': 2}},
        {'word-wall': {'motion': float('nan')}},
        {'word-wall': {'motion': True}},
        {'word-wall': {'motion': 9}},
        {'word-wall': {'accent': 'red'}},
        {'word-wall': {'variant': 0.5}},
    ],
)
def test_invalid_scene_settings_rejected(settings):
    with pytest.raises(ValueError):
        scene_settings(settings)


def test_settings_roundtrip_and_legacy_defaults():
    value = {'stamp-collage': {'accent': '#AABBCC', 'imperfection': 0}, 'word-wall': {'motion': 2}}
    options = kinetic_options({'scene_settings': value})
    assert kinetic_options(json.dumps(options)) == options
    assert options['scene_settings']['stamp-collage']['accent'] == '#aabbcc'
    assert kinetic_options({})['scene_settings'] == {}


@pytest.mark.parametrize('scene', ['editorial', 'quiet-focus', 'baseline-reveal', 'gallery-caption'])
@pytest.mark.parametrize('size', [(320, 180), (180, 320)])
def test_minimal_scenes_render_deterministically_and_respond_to_controls(scene, size):
    c = make(scene, size=size)
    engine = c.realtime.engine(0)
    line = engine.plan()[0]
    plain = Image.new('RGBA', size)
    engine.paint_minimal(plain, line, 1.7)
    assert plain.getbbox() is not None
    again = Image.new('RGBA', size)
    engine.paint_minimal(again, line, 1.7)
    assert plain.tobytes() == again.tobytes()
    changed = make(scene, dict(accent='#33ccbb', size=0.75, tracking=0.1, motion=0), size=size)
    assert not np.array_equal(c.frame(1.7), changed.frame(1.7))


@pytest.mark.parametrize(
    'scene,key,value',
    [
        ('word-wall', 'motion', 0),
        ('word-seal', 'motion', 0),
        ('title-grid', 'motion', 0),
        ('stamp-collage', 'imperfection', 0),
        ('misregistration', 'imperfection', 0),
        ('proportion-stack', 'swelling', 4),
        ('type-mobile', 'motion', 0),
        ('black-hole-sun', 'accent', '#33ccbb'),
        ('panning-canvas', 'size', 0.7),
    ],
)
def test_existing_controls_change_pixels(scene, key, value):
    plain, changed = make(scene), make(scene, {key: value})
    assert any(not np.array_equal(plain.frame(t), changed.frame(t)) for t in (1.3, 1.8, 2.2))


def test_same_renderer_scenes_have_independent_configuration():
    c = make('word-wall')
    from render.scene_mix import SceneMix

    mix = SceneMix(
        c,
        options={'scene_settings': {'word-wall': {'motion': 0}}},
        flows=[dict(start=0, end=1, scene='word-wall'), dict(start=0, end=1, scene='word-seal')],
    )
    assert mix.engine(0) is not mix.engine(1)
    assert mix.engine(0).scene_config == {'motion': 0.0}
    assert mix.engine(1).scene_config == {}


def test_configuring_one_poster_preserves_other_scenes_palette_and_side():
    from copy import deepcopy
    from render.scene_mix import SceneMix

    c = make('word-wall')
    second = deepcopy(c.data[0])
    for word in second['words']:
        word['start'] += 5
        word['end'] += 5
    c.data.append(second)
    c.duration = 10
    flows = [dict(start=0, end=1, scene='word-wall'), dict(start=1, end=2, scene='word-seal')]
    plain = SceneMix(c, flows=flows)
    changed = SceneMix(c, flows=flows, options={'scene_settings': {'word-wall': {'motion': 0}}})
    expected = plain.engine(1).plan()[1]
    actual = changed.engine(1).plan()[0]
    assert expected['palette'] == actual['palette']
    assert expected['side'] == actual['side']
    a, b = Image.new('RGBA', (320, 180)), Image.new('RGBA', (320, 180))
    plain.engine(1).paint_seal(a, expected, 6.7)
    changed.engine(1).paint_seal(b, actual, 6.7)
    assert a.tobytes() == b.tobytes()


def test_scene_preview_route_validates_and_forwards_overrides():
    from types import SimpleNamespace
    from unittest.mock import patch
    from urllib.parse import urlencode, urlparse
    from studio.get_routes import GetRoutes
    from effects.particles import preview

    response = SimpleNamespace(respond=lambda data, **kw: (data, kw))
    query = urlencode(dict(scene='word-seal', settings=json.dumps(dict(shape='round', motion=0))))
    with (
        patch.object(preview, 'render_scene_preview', return_value=b'gif') as render,
        patch.object(preview, 'request_prerender'),
    ):
        result = GetRoutes._get_scene_preview(response, urlparse('/api/scene-preview?' + query))
        assert result[0] == b'gif'
        assert json.loads(render.call_args.args[4]) == dict(shape='round', motion=0.0)
    bad = urlencode(dict(scene='word-seal', settings=json.dumps(dict(shape='triangle'))))
    with pytest.raises(ValueError):
        GetRoutes._get_scene_preview(response, urlparse('/api/scene-preview?' + bad))


def test_caption_pill_fits_portrait_frame():
    c = make('word-wall', size=(270, 480))
    engine = c.realtime.engine(0)
    line = engine.plan()[0]
    screen = Image.new('RGBA', (270, 480))
    engine.paint_caption(screen, line, 2.0, (224, 194, 133), (22, 18, 30), 1.0, 0.0)
    left, _, right, _ = screen.getbbox()
    assert left > 0 and right < screen.width
