"""Continuous silhouette morphs from a particle material into a glyph fragment."""

from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt


def _field(alpha):
    mask = alpha > max(8, float(alpha.max()) * 0.2)
    return (distance_transform_edt(mask) - distance_transform_edt(~mask)).astype(
        np.float32
    )


@dataclass
class MaterialMorph:
    particle: Image.Image
    glyph: Image.Image
    particle_field: np.ndarray
    glyph_field: np.ndarray
    particle_color: np.ndarray
    glyph_color: np.ndarray
    particle_opacity: float
    glyph_opacity: float

    def frame(self, fraction):
        if fraction <= 0:
            return self.particle
        if fraction >= 1:
            return self.glyph
        field = self.particle_field * (1 - fraction) + self.glyph_field * fraction
        opacity = self.particle_opacity * (1 - fraction) + self.glyph_opacity * fraction
        alpha = np.clip(field + 0.5, 0.0, 1.0) * opacity
        color_fraction = fraction * fraction
        rgb = (
            self.particle_color * (1 - color_fraction)
            + self.glyph_color * color_fraction
        )
        rgba = np.empty((*field.shape, 4), dtype=np.uint8)
        rgba[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        rgba[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)
        return Image.fromarray(rgba)


def prepare_morph(particle, glyph):
    size = tuple(
        max(a, b) + (max(a, b) - b) % 2 for a, b in zip(particle.size, glyph.size)
    )
    canvases = []
    for image in (particle, glyph):
        canvas = Image.new("RGBA", size)
        canvas.alpha_composite(
            image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2)
        )
        canvases.append(np.asarray(canvas, dtype=np.float32))
    colors = []
    for rgba in canvases:
        alpha = rgba[:, :, 3]
        color = (rgba[:, :, :3] * alpha[:, :, None]).sum(axis=(0, 1)) / max(
            1.0, alpha.sum()
        )
        color_field = np.broadcast_to(color, rgba[:, :, :3].shape).copy()
        mask = alpha > 100
        color_field[mask] = rgba[:, :, :3][mask]
        colors.append(color_field)
    return MaterialMorph(
        particle,
        glyph,
        _field(canvases[0][:, :, 3]),
        _field(canvases[1][:, :, 3]),
        colors[0],
        colors[1],
        float(canvases[0][:, :, 3].max()),
        float(canvases[1][:, :, 3].max()),
    )
