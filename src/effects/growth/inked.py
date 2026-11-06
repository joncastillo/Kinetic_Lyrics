"""Two handmade letterings on the crafted kit: watercolour ink blooming through the letters, and embroidery."""

import math

import numpy as np

from effects.growth.crafted import (
    anchors,
    crafted,
    letter_boxes,
    per_pixel,
    relay,
    rgb,
    rim,
    shadow,
    sm,
    smooth,
    stroke,
    supersampled,
)
from effects.growth.ornaments import sweep_angle

# ---------------------------------------------------------------- ink bloom (ink in water, gathering)

PIGMENTS = (rgb(60, 78, 206), rgb(28, 160, 172), rgb(214, 50, 140), rgb(142, 70, 210), rgb(232, 108, 36), rgb(30, 146, 94))


@crafted('ink-bloom-lettering', pad=0.8)
def ink_bloom(F, canvas, t, intensity, letters):
    """Like a drop of ink in water played backwards: each letter starts as curling plumes of ink in two
    pigments, drifting down and swirling, that gather into the letter as the water calms and the edges
    sharpen; as it settles the pigment pools into a hard dark rim round a paler wash, like drying watercolour."""
    index, count = letters
    u = F.u
    a = np.asarray(PIGMENTS[F.seed % len(PIGMENTS)])
    b = np.asarray(PIGMENTS[(F.seed * 3 + 2) % len(PIGMENTS)])
    q = np.clip((t - 0.2 * np.clip(F.xn, 0, 1)) / 0.4, 0, 1)  # timing runs smoothly across the word: no letter-edge cuts
    calm = 1 - smooth(q, 0.0, 1.0)
    swirl = calm ** 1.5 * u * 0.7
    dx = F.flow(0.35, t, (0.3, 1.2), 1210) * swirl + F.flow(0.14, t, (-0.4, 0.8), 1211) * swirl * 0.35  # broad curls, not specks
    dy = F.flow(0.35, t, (-0.2, 1.4), 1212) * swirl * 0.8 - swirl * 0.7  # the plumes sink into place from above
    soft = u * (0.012 + 0.1 * calm)
    raw = smooth(-F.sdf, -soft, soft) ** 0.8
    from effects.materials.fx import mix, warp
    cov = warp(F, raw * smooth(q, 0.0, 0.3), dx, dy)  # the gate swirls with the ink, so no straight edge
    mixing = 0.5 + 0.5 * warp(F, F.fbm(0.12, 3, 1213), dx, dy)
    ink = mix(a, b, mixing[..., None])
    settle = smooth(q, 0.6, 0.95)
    inner = np.clip(-F.sdf / (u * 0.12), 0, 1)
    wash = mix(ink, np.clip(ink * 0.3 + 0.7, 0, 1), (inner * 0.75 * settle)[..., None])  # a paler wash inside
    pool = np.exp(-(((F.sdf + u * 0.018) / (u * 0.02)) ** 2)) * settle  # pigment pooled at the edge
    tone = np.clip(wash * (1 - 0.55 * pool)[..., None], 0, 1)
    grain = 0.9 + 0.1 * F.noise(0.012, 1214)
    tone = np.clip(tone * grain[..., None], 0, 1)
    canvas.over(np.zeros(3), shadow(cov, F, 0.02, 0.04, 0.03, 0.3 * settle))
    colour, alpha = rim(F, cov * settle, 0.012, (0.12, 0.1, 0.18), 0.7)
    canvas.over(colour, alpha)
    canvas.over(tone, cov)


# ---------------------------------------------------------------- thread stitch

# (fill thread, outline thread) per word: the outline is a deep shade of the same thread, never a second colour
THREADS = ((rgb(236, 112, 92), rgb(112, 36, 26)), (rgb(242, 186, 60), rgb(110, 62, 16)), (rgb(56, 170, 170), rgb(18, 84, 84)),
           (rgb(230, 120, 160), rgb(104, 34, 70)), (rgb(246, 236, 218), rgb(116, 88, 62)))


def stitch_grid(F, letters):
    """The cross-stitch grid: each pixel's cell, its place inside the cell, whether the cell is stitched, and
    each stitched cell's 0-1 place in its letter's raster order (rows top to bottom, left to right)."""
    index, count = letters

    def build():
        u = F.u
        cell = max(5.0, u * 0.15)  # about seven stitches per cap height  # big enough that every X reads at thumbnail size
        x0, y0 = F.box[0], F.box[1]
        gx = np.floor((F.px - x0) / cell)
        gy = np.floor((F.py - y0) / cell)
        fx = (F.px - x0) / cell - gx
        fy = (F.py - y0) / cell - gy
        cy = np.clip((y0 + (gy + 0.5) * cell).astype(int), 0, F.H - 1)
        cx = np.clip((x0 + (gx + 0.5) * cell).astype(int), 0, F.W - 1)
        sewn = F.sdf[cy, cx] < cell * 0.12
        boxes = letter_boxes(F, letters)
        top = per_pixel([math.floor((b[1] - y0) / cell) for b in boxes], letters)
        rows = per_pixel([max(1, math.ceil((b[3] - y0) / cell) - math.floor((b[1] - y0) / cell)) for b in boxes], letters)
        left = per_pixel([math.floor((b[0] - x0) / cell) for b in boxes], letters)
        cols = per_pixel([max(1, math.ceil((b[2] - x0) / cell) - math.floor((b[0] - x0) / cell)) for b in boxes], letters)
        order = np.clip((gy - top + np.clip((gx - left) / cols, 0, 0.999)) / rows, 0, 1)
        return cell, fx, fy, sewn, order
    return F.memo(('stitch-grid', count), build)


def half_stitch(a, b, width):
    """Coverage and shading of one diagonal thread across a cell: a little twisted cylinder."""
    across = np.abs(a) / width
    inset = smooth(b, 0.1, 0.2) * smooth(1 - b, 0.1, 0.2)  # a gap of cloth between neighbouring stitches
    cov = smooth(1 - across, 0, 0.25) * inset
    shade = 0.55 + 0.6 * np.sqrt(np.clip(1 - across ** 2, 0, 1)) + 0.12 * np.sin((b * 5 + a * 3) * math.tau)
    return cov, shade


@crafted('thread-stitch-lettering', pad=0.6)
def thread_stitch(F, canvas, t, intensity, letters):
    """Letters cross-stitched on a grid: each row's stitches are laid half at a time, the first pass then the
    return pass closing each X, letter after letter; a back-stitch outline in a deeper shade of the same thread
    is sewn round each letter and a loose tail is pulled tight."""
    index, count = letters
    u = F.u
    fill_c, line_c = THREADS[F.seed % len(THREADS)]
    cell, fx, fy, sewn, order = stitch_grid(F, letters)
    first = relay(t, count, 0.02, 0.4, 0.22)
    second = relay(t, count, 0.12, 0.4, 0.22)
    laid1 = sewn & (order < per_pixel(first, letters) * 1.001)
    laid2 = sewn & (order < per_pixel(second, letters) * 1.001)
    w = 0.25
    cov1, shade1 = half_stitch((fx + fy - 1) / math.sqrt(2), (fx - fy + 1) / 2, w)  # "/" laid first
    cov2, shade2 = half_stitch((fx - fy) / math.sqrt(2), (fx + fy) / 2, w)  # "\" crosses back over it
    cov1, cov2 = cov1 * laid1, cov2 * laid2
    under = np.clip(np.asarray(fill_c) * 0.8, 0, 1)  # the first pass in a darker thread, so the return pass visibly closes it
    union = np.maximum(cov1, cov2)
    canvas.over(np.zeros(3), shadow(union, F, 0.015, 0.03, 0.015, 0.45))
    colour, alpha = rim(F, union, 0.012, np.asarray(line_c) * 0.6, 0.8)
    canvas.over(colour, alpha)
    canvas.over(np.clip(under * shade1[..., None], 0, 1), cov1)
    canvas.over(np.clip(np.asarray(fill_c) * shade2[..., None], 0, 1), cov2)
    # back-stitch outline round each letter, sewn as soon as its crosses are done
    angle = sweep_angle(F, letters)
    outline = per_pixel(relay(t, count, 0.24, 0.4, 0.2), letters)
    band = smooth(u * 0.06 - np.abs(F.sdf - u * 0.02), 0, u * 0.01)
    dashes = smooth(((angle * 40) % 1), 0.0, 0.06) * smooth(0.78 - ((angle * 40) % 1), 0.0, 0.06)
    back = band * dashes * smooth(outline * 1.05 - angle, 0, 0.02)
    canvas.over(np.zeros(3), shadow(back, F, 0.01, 0.02, 0.01, 0.4))
    edge_c = np.clip(np.asarray(fill_c) * 1.15 + 0.12, 0, 1)  # the fill's own light tone frames the letter
    canvas.over(np.asarray(line_c), back)
    canvas.over(edge_c, back * smooth(u * 0.035 - np.abs(F.sdf - u * 0.02), 0, u * 0.008))  # light core, dark edges: reads on dusk and paper
    rights = anchors(F, letters, 'right')

    def draw(d, f):
        slack = (1 - sm(t, 0.84, 0.96)) * sm(t, 0.62, 0.7)  # the tail hangs, then is pulled tight
        if slack > 0.02:
            end = rights[-1]
            pts = [(end[0] + u * 0.05 * s + u * 0.25 * math.sin(s * math.pi), end[1] + u * 0.45 * s * slack) for s in np.linspace(0, 1, 16)]
            c = tuple(int(v * 255) for v in line_c)
            stroke(d, f, pts[: max(2, round(len(pts) * (0.3 + 0.7 * slack)))], u * 0.018, (*c, 255), (40, 30, 30, 120))

    orn_rgb, orn_a = supersampled(F, draw)
    canvas.over(orn_rgb, orn_a)
