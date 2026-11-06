import numpy as np
import pytest
from PIL import Image, ImageDraw


def test_sidewalls_preserve_counters_and_face_outward():
    pytest.importorskip('skimage')
    from render.stage_3d.sculpture import side_vertices

    mask = Image.new('L', (32, 32))
    draw = ImageDraw.Draw(mask)
    draw.rectangle((4, 4, 27, 27), fill=255)
    draw.rectangle((12, 12, 19, 19), fill=0)
    vertices = side_vertices(mask)
    assert len(vertices) > 0 and len(vertices) % 6 == 0
    assert np.isfinite(vertices).all()
    assert set(vertices[:, 2]) == {0.0, -1.0}
    faces = vertices.reshape((-1, 6, 6)).mean(axis=1)
    right_outer = faces[(faces[:, 0] > 0.3) & (abs(faces[:, 1]) < 0.35)]
    assert (right_outer[:, 3] > 0).any()
    right_inner = faces[(faces[:, 0] > 0.05) & (faces[:, 0] < 0.2) & (abs(faces[:, 1]) < 0.2)]
    assert (right_inner[:, 3] < 0).any()


def test_blank_word_produces_no_geometry():
    pytest.importorskip('skimage')
    from render.stage_3d.sculpture import side_vertices

    assert side_vertices(Image.new('L', (32, 32))).shape == (0, 6)
