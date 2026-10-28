"""Remove the plain staging background an image model paints behind a cutout subject.

Pictures are prompted on a "plain uniform" background, which comes out as any flat colour: white,
light grey, beige. The background is whatever uniform colour runs in from the image border; it is
keyed out with a soft, colour-decontaminated edge so no grey fringe or rectangle survives.
"""
import numpy as np
from PIL import Image
from scipy import ndimage


def staging_alpha(image, tolerance=24.):
    """(alpha 0..1, backdrop colour) removing the uniform background that touches the border, or None
    when the border is not uniform enough to be a staging background (a full scene, say)."""
    rgb = np.asarray(image.convert('RGB'), dtype=float)
    clear = np.asarray(image.convert('RGBA').getchannel('A')) < 128  # already transparent: background too
    h, w = rgb.shape[:2]
    ring = max(2, round(min(h, w)*.015))
    edge = np.zeros((h, w), bool)
    edge[:ring], edge[-ring:], edge[:, :ring], edge[:, -ring:] = True, True, True, True
    border = rgb[edge & ~clear]
    if len(border) < edge.sum()*.15:
        return None
    reference = np.median(border, axis=0)
    spread = np.median(np.linalg.norm(border-reference, axis=1))
    if spread > 14 or np.mean(np.linalg.norm(border-reference, axis=1) < tolerance) < .8:
        return None
    distance = np.linalg.norm(rgb-reference, axis=-1)
    limit = tolerance+2*spread
    labels, _ = ndimage.label((distance < limit) | clear, structure=np.ones((3, 3)))
    edge_labels = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    background = np.isin(labels, edge_labels[edge_labels != 0])
    # A soft edge: pixels near the background blend out by how close their colour is to the backdrop.
    near = ndimage.binary_dilation(background, iterations=2) & ~background
    soft = np.clip((distance-limit*.5)/(limit*1.2), 0, 1)
    alpha = np.where(background, 0., np.where(near, soft, 1.))
    return ndimage.gaussian_filter(alpha, .6)*(~background | (alpha > 0)), reference


def remove_staging(image, tolerance=24.):
    """The image with its staging background made transparent (unchanged if there is none to remove)."""
    found = staging_alpha(image, tolerance)
    rgba = image.convert('RGBA')
    if found is None:
        return rgba
    alpha, reference = found
    pixels = np.asarray(rgba, dtype=float)
    rgb = np.asarray(image.convert('RGB'), dtype=float)
    a = np.clip(alpha, 1e-3, 1)[..., None]
    # Undo the blend with the backdrop at soft edges so the cutout has no grey halo.
    clean = np.clip((rgb-reference*(1-a))/a, 0, 255)
    pixels[..., :3] = np.where(alpha[..., None] < .999, clean, rgb)
    pixels[..., 3] = np.minimum(pixels[..., 3], alpha*255)
    return Image.fromarray(pixels.round().astype('uint8'), 'RGBA')
