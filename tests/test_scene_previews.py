import json
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from effects.particles import preview
from effects.particles.scene_backdrops import backdrop_choices, render_backdrop, scene_backdrop


def test_ten_distinct_backdrops_have_five_light_and_five_dark():
    choices = backdrop_choices()
    assert len(choices) == 10
    assert sum(b['mode'] == 'light' for b in choices) == 5
    assert sum(b['mode'] == 'dark' for b in choices) == 5
    images = [render_backdrop(b['id'], (160, 90)) for b in choices]
    assert len({im.tobytes() for im in images}) == 10
    for b, im in zip(choices, images):
        assert (np.asarray(im).mean() > 150) == (b['mode'] == 'light')
        assert im.tobytes() == render_backdrop(b['id'], im.size).tobytes()


def test_backdrop_cache_and_validation(tmp_path):
    one = scene_backdrop(tmp_path, (160, 90), 'midnight')
    assert one == scene_backdrop(tmp_path, (160, 90), 'midnight')
    assert one != scene_backdrop(tmp_path, (160, 90), 'porcelain')
    with pytest.raises(ValueError):
        scene_backdrop(tmp_path, (160, 90), '../../unsafe')


def test_scene_preview_disables_global_party_effects_and_forwards_settings(tmp_path):
    calls = []

    def compositor(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(frame=lambda t: Image.new('RGB', (40, 24)), realtime=SimpleNamespace(stage=None))

    with (
        patch('render.compositor.Compositor', side_effect=compositor),
        patch.object(preview, 'SCENE_SIZE', (40, 24)),
        patch.object(preview, 'SCENE_SECONDS', 0.2),
        patch.object(preview, 'SCENE_FPS', 10),
        patch.object(preview, 'scene_backdrop', return_value=tmp_path / 'art.png') as art,
    ):
        result = preview._render_scene(
            'baseline-reveal', settings=json.dumps({'size': 0.7, 'font': 'serif'}), background='porcelain'
        )
    assert result.startswith(b'GIF')
    kinetic = calls[0]['kinetic']
    assert kinetic['beat_confetti'] is False and kinetic['beat_effect'] == 'none'
    assert kinetic['scene_settings']['baseline-reveal'] == {'size': 0.7, 'font': 'serif'}
    assert art.call_args.args[-1] == 'porcelain'


def test_preview_cache_key_includes_background():
    with patch.object(preview, '_cached', side_effect=lambda kind, args, renderer: args):
        dark = preview.render_scene_preview('baseline-reveal', background='midnight')
        light = preview.render_scene_preview('baseline-reveal', background='porcelain')
    assert dark != light


def test_empty_stage_recipe_stays_clean():
    from test_scene_controls import make

    for scene in ('plain-blocks', 'sweet-contrast'):
        engine = make(scene).realtime.engine(0)
        assert engine.owned_effects(0) == []
        assert all(word['effect'] is None for block in engine.plan() for word in block['words'])


@pytest.mark.parametrize('scene', ['baseline-reveal', 'word-wall', 'black-hole-sun', 'panning-canvas'])
def test_scene_fonts_change_pixels_without_leaking(scene):
    from test_scene_controls import make

    plain = make(scene)
    before = plain.frame(1.8).tobytes()
    serif = make(scene, {'font': 'serif'})
    modern = make(scene, {'font': 'modern-sans'})
    assert serif.frame(1.8).tobytes() != modern.frame(1.8).tobytes()
    assert plain.frame(1.8).tobytes() == before


def test_scene_default_font_inherits_global_font_choice():
    from test_scene_controls import make
    from render.typography_settings import selected_font

    c = make('baseline-reveal')
    original = c.frame(1.8).tobytes()
    c.custom_font = selected_font('georgia', 'regular')
    assert c.frame(1.8).tobytes() != original
    c.custom_font = None
    assert c.frame(1.8).tobytes() == original
