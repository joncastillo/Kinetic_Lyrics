"""Silk: Mucha-style satin lettering."""

import numpy as np

from effects.materials.fx import rgb, sm, smooth
from effects.materials.recipes.registry import recipe


MUCHA_INK = rgb(66, 42, 36)


def mucha_lines(F, canvas, sdf, folds, alpha, width=0.022):
    """Art Nouveau ink: a confident contour plus thin strokes in the deepest creases."""
    edge = smooth(-np.abs(sdf + F.u * width * 0.5) + F.u * width * 0.5, 0, 0.9)
    crease = smooth(-folds, 1.05, 1.25) * np.clip(-sdf / (F.u * 0.04), 0, 1)
    canvas.over(MUCHA_INK, np.clip(edge + crease * 0.55, 0, 1) * alpha)


# Shot-silk palettes (shadow, base, light), deep enough to hold on cream as well as dusk.
MUCHA_SILKS = np.array(
    (
        (rgb(110, 40, 60), rgb(196, 98, 112), rgb(255, 214, 210)),  # rose
        (rgb(40, 72, 60), rgb(104, 150, 120), rgb(220, 240, 214)),  # sage
        (rgb(110, 64, 20), rgb(206, 148, 60), rgb(255, 232, 180)),  # ochre
        (rgb(20, 62, 80), rgb(64, 140, 160), rgb(200, 238, 240)),  # teal
    )
)


@recipe('mucha-silk-lettering', 'entrance', pad=2.6)
def mucha_silk(F, canvas, t, intensity):
    """Wind-driven translucent satin sheets twist and gather into fabric letters; as they settle solid, an Art
    Nouveau ink contour is drawn across the word and a sheen runs over the satin."""
    from effects.silk.fabric import paint_silk

    paint_silk(F, canvas, t)
    ink = smooth(t - (0.78 + 0.14 * np.clip(F.xn, 0, 1)), 0, 0.05)  # the contour is drawn left to right
    mucha_lines(F, canvas, F.sdf, np.zeros_like(F.sdf), ink * F.ink, width=0.03)
    pos = -0.4 + 1.9 * sm(t, 0.84, 0.99)
    band = np.exp(-(((F.xn * 0.8 + F.yn * 0.35 - pos) / 0.08) ** 2)) * F.ink
    canvas.add(rgb(255, 248, 236) * (band * 0.5)[..., None], 0.3)
