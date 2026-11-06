"""Stained glass: leaded panes soldered together and lit from behind."""

import math

import numpy as np

from effects.materials.fx import (
    Particles,
    bevel,
    blackbody,
    bloom,
    coverage,
    mix,
    normals,
    rgb,
    shadow,
    sm,
    smooth,
)
from effects.materials.recipes.registry import recipe
from effects.materials.recipes.common import metal, plume, rim_cover, sample, spark_burst


TIFFANY = (
    rgb(240, 160, 40),
    rgb(248, 214, 100),
    rgb(130, 180, 50),
    rgb(30, 160, 150),
    rgb(200, 40, 50),
    rgb(244, 232, 200),
    rgb(120, 80, 190),
    rgb(40, 110, 200),
)


def tiffany_panes(F):
    """Five to eight glass pieces per letter, each with its own colour, landing order and tumble."""

    def build():
        u = F.u
        ids, _, edge, centres = F.cells(0.3, 260, jitter=0.75)
        inside = np.unique(ids[F.ink > 0.5])
        rng = np.random.default_rng(F.seed + 261)
        colour = np.array(TIFFANY)[rng.integers(0, len(TIFFANY), ids.max() + 1)]
        second = np.array(TIFFANY)[rng.integers(0, len(TIFFANY), ids.max() + 1)]
        land = np.full(ids.max() + 1, 9.0)
        order = np.clip((centres[inside, 0] - F.box[0]) / max(1, F.box[2] - F.box[0]), 0, 1)
        land[inside] = 0.06 + 0.6 * order + rng.uniform(0, 0.08, len(inside))
        mottle = 0.5 + 0.5 * F.fbm(0.12, 3, 262, (1.6, 0.6))  # opalescent glass: two colours swirled together
        pane = mix(colour[ids], second[ids], smooth(mottle, 0.35, 0.75) * 0.5)
        w = u * 0.028
        seam = np.maximum(1 - smooth(edge, w * 0.6, w), smooth(F.sdf, -u * 0.04, -u * 0.026)) * coverage(F.sdf)
        bead_height = bevel(-np.abs(np.minimum(edge, -F.sdf + u * 0.034)) + w, w * 0.8) + u * 0.004 * F.noise(0.01, 263)
        count = np.maximum(1, np.bincount(ids.ravel()))
        cell_x = np.bincount(ids.ravel(), np.clip(F.xn, 0, 1).ravel()) / count
        return ids, edge, centres, inside, land, pane, seam, bead_height, cell_x, rng.uniform(0, math.tau, ids.max() + 1)

    return F.memo('tiffany', build)


@recipe('stained-glass-leading', 'entrance', pad=1.1)
def stained_glass(F, canvas, t, intensity):
    """Big glass pieces swoop in from one side and snap into the letters with a flash, a glowing solder bead
    runs the seams behind them, and a lamp flickers on behind the finished panes."""
    u = F.u
    ids, edge, centres, inside, land, pane, seam, bead_height, cell_x, spin = tiffany_panes(F)
    glass = coverage(F.sdf)
    landed = smooth(t - land[ids], 0, 0.02)
    # 1. Pieces fly in, tumbling, and snap into their places with a flash.
    flying = inside[(land[inside] - t > 0) & (land[inside] - t < 0.2)]
    if len(flying):
        q = (land[flying] - t) / 0.2
        out = centres[flying] - np.array((F.cx, F.cy + u * 0.6))
        out = out / np.maximum(1, np.linalg.norm(out, axis=1, keepdims=True))
        shards = Particles(
            F,
            centres[flying] + out * u * 1.6 * q[:, None] ** 1.3,
            0.0,
            (0, 0),
            size=u * 0.17 * (1 + q * 0.4),
            color=np.clip(
                pane[
                    np.clip(centres[flying][:, 1].astype(int), 0, F.H - 1),
                    np.clip(centres[flying][:, 0].astype(int), 0, F.W - 1),
                ]
                * 1.25,
                0,
                1,
            ),
            shape='shard',
            alpha=1 - q * 0.25,
            life=1.0,
            fade_in=0,
        )
        shards.angle0 = spin[flying] + q * 9
        shards.render(canvas, 0.001)
    snap = np.exp(-(((t - land[ids] - 0.02) / 0.04) ** 2)) * glass
    # 3. The lamp flickers on behind the glass, then glows steady and warm.
    lamp = sm(t, 0.78, 0.82) * (0.35 + 0.65 * (math.sin(t * 140) ** 2 if t < 0.9 else 1.0)) * sm(t, 0.78, 0.96)
    warm = (1.0 + 0.6 * lamp) * (0.85 + 0.3 * np.exp(-((F.xn - 0.5) ** 2 + (F.yn - 0.55) ** 2) / 0.35))
    body = pane * warm[..., None] + rgb(255, 220, 160) * (lamp * 0.16)
    canvas.over(rgb(30, 18, 6), shadow(glass * landed, F, 0.03, 0.05, 0.04, 0.4))
    canvas.over(np.clip(body, 0, 1), glass * landed * (1 - seam))
    canvas.add(np.ones(3) * (snap * (1 - seam))[..., None] * 0.8, 0.25)
    if lamp > 0:
        canvas.add(bloom(pane * (glass * landed * (1 - seam) * lamp * 0.9)[..., None], F, 0.08, 1.0), 0.35)
    # 2. Copper foil shows on the seams of landed pieces; a glowing solder bead runs along them afterwards.
    foil = seam * landed
    canvas.over(rgb(110, 70, 40), foil)
    soldered_at = land[ids] + 0.1 + 0.06 * np.clip(F.yn, 0, 1)
    done = smooth(t - soldered_at, 0, 0.02)
    bead_n = normals(bead_height)
    metal_seam = metal(bead_n, rgb(176, 168, 160), power=50) * 0.85
    canvas.over(np.clip(metal_seam, 0, 1), seam * done)
    molten = np.exp(-np.clip(t - soldered_at, 0, None) / 0.03) * done * seam
    canvas.add(
        blackbody(0.6 + 0.4 * molten) * molten[..., None] * 1.4
        + bloom(rgb(255, 200, 120) * molten[..., None], F, 0.03, 0.7),
        0.4,
    )
    if 0.12 < t < 0.85:
        tips = sample((np.abs(t - soldered_at) < 0.008) & (seam > 0.5), 30, 264 + int(t * 90), F)
        spark_burst(F, canvas, t, tips, t - 0.006, 265 + int(t * 90), 1.6, 1.8, 9.0, (0.02, 0.06))
        plume(F, canvas, t, molten * 0.8, rgb(170, 170, 176), 0.3, 0.5, 0.1, 266)
    rim_cover(F, canvas, glass * landed, sm(t, 0.3, 0.8), 0.02, colour=(0.12, 0.1, 0.08))
