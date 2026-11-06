"""The local edition must remain useful without optional implementations."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif((ROOT/'.private-repository').exists(), reason='Public edition boundary')


def test_private_implementations_are_absent():
    for name in ('video_generation', 'scene_text', 'models.online', 'clip_effects'):
        assert importlib.util.find_spec(name) is None
    assert not (ROOT/'AGENTS.md').exists()
    assert not (ROOT/'CLAUDE.md').exists()
    assert not (ROOT/'src/frontend/art/scene-assets').exists()


def test_no_private_routes_or_visible_controls():
    from studio.server import JOB_ROUTES, POST_ROUTES
    assert not {'reanimate', 'animate-missing', 'upscale', 'scene-text', 'scene-scan', 'storyboard'} & JOB_ROUTES.keys()
    assert '/api/providers' not in POST_ROUTES
    assert '/api/image-maker/cinemagraph' not in POST_ROUTES
    html = (ROOT/'src/frontend/studio.html').read_text(encoding='utf-8')
    assert 'Dracula' not in html
    assert 'value="cinemagraph"' not in html


def test_maker_refuses_motion_output(tmp_path):
    from artwork.maker import checked
    with pytest.raises(ValueError, match='Choose image output'):
        checked({'output':'cinemagraph'}, tmp_path)
