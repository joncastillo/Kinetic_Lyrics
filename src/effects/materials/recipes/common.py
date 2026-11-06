"""Helpers shared by the material recipes: erosion, plumes, sparks, lighting, letter timing."""

import math

import numpy as np

from effects.materials.fx import (
    Particles,
    environment,
    lambert,
    mix,
    paint_smoke,
    rgb,
    shift,
    sm,
    smooth,
    smoke,
    specular,
    sun,
)


def rim_cover(F, canvas, cov, alpha=1.0, width=0.026, colour=(0.07, 0.05, 0.04)):
    """A bold outline just outside whatever shape `cov` covers, ragged edges and all."""
    from scipy.ndimage import maximum_filter

    size = max(3, int(round(F.u * width)) * 2 + 1)
    grown = maximum_filter(np.asarray(cov, dtype=float), size=size)
    canvas.over(np.asarray(colour), np.clip(grown - cov, 0, 1) * alpha)


def front_band(erode, t, width=0.05, mask=None):
    """Where a front (erosion, burn, fill...) is passing right now: 1 on the front, 0 away from it."""
    band = smooth(width - np.abs(erode - t), 0, width)
    return band if mask is None else band * mask


def plume(F, canvas, t, source, colour, opacity=0.6, rise=0.6, drift=0.3, seed=0):
    """A dust, steam or smoke plume rising from `source`."""
    if np.any(source > 0.01):
        paint_smoke(F, canvas, smoke(F, source, t, rise, seed, drift=drift), colour, opacity)


def spark_burst(
    F,
    canvas,
    t,
    origins,
    born,
    seed,
    up=2.2,
    spread=1.6,
    gravity=8.0,
    life=(0.05, 0.13),
    cooling=True,
    colour=(1, 0.85, 0.6),
):
    """Motion-blurred sparks thrown from points, cooling from white to red under gravity."""
    if not len(origins):
        return
    rng = np.random.default_rng(F.seed + seed)
    n = len(origins)
    velocity = np.stack((rng.normal(0, spread, n), -rng.uniform(up * 0.3, up, n)), 1)
    Particles(
        F,
        origins,
        born,
        velocity,
        accel=(0, gravity),
        drag=0.8,
        life=rng.uniform(*life, n),
        size=rng.choice((1, 1, 2), n),
        shape='streak',
        cooling=cooling,
        color=colour,
        trail=0.02,
    ).render(canvas, t)


def sample(mask, count, seed, F):
    """Random pixel positions where `mask` is set."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return np.zeros((0, 2))
    pick = np.random.default_rng(F.seed + seed).integers(0, len(xs), count)
    return np.stack((xs[pick], ys[pick]), 1).astype(float)


def self_shadow(F, height, light, steps=8, reach=0.18):
    """Height-field cast shadows: a pixel is shaded if terrain toward the sun rises above its sightline."""
    flat = math.hypot(light[0], light[1])
    if flat < 1e-3:
        return np.zeros_like(height)
    dx, dy = light[0] / flat, light[1] / flat
    rise = light[2] / flat
    shade = np.zeros_like(height)
    step = max(1.0, reach * F.u / steps)
    for k in range(1, steps + 1):
        ox, oy = round(dx * step * k), round(dy * step * k)
        ahead = shift(height, -oy, -ox)
        shade = np.maximum(shade, ahead - height - rise * step * k)
    return smooth(shade, 0, F.u * 0.03)


def grain(F, amount, seed=0, scale=0.012):
    return 1 + amount * F.noise(scale, seed + 400)


def rounded_box(F, left, top, right, bottom, radius):
    """Signed distance (px) to a rounded rectangle around the ink box, margins in units."""
    x0, y0, x1, y1 = F.box
    x0, x1 = x0 - left * F.u, x1 + right * F.u
    y0, y1 = y0 - top * F.u, y1 + bottom * F.u
    r = radius * F.u
    qx = np.abs(F.px - (x0 + x1) / 2) - ((x1 - x0) / 2 - r)
    qy = np.abs(F.py - (y0 + y1) / 2) - ((y1 - y0) / 2 - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def lit(albedo, n, light, brightness=1.0, tint=1.0, ambient=0.32, shade=None, sky=rgb(120, 140, 175)):
    diffuse = lambert(n, light)
    if shade is not None:
        diffuse = diffuse * (1 - shade * 0.85)
    fill = ambient * (0.55 + 0.45 * n[..., 2])
    return albedo * (diffuse[..., None] * brightness * np.asarray(tint) + fill[..., None] * sky * 1.6)


def metal(n, tint, light=None, power=80, env_gain=1.0):
    light = sun() if light is None else light
    env = environment(n) * env_gain
    return env * np.asarray(tint) + specular(n, light, power)[..., None] * 1.2


def block_erosion(F, key, margins, wind, noise, hard_bands=0.0, chips=None, span=(0.05, 0.88), power=0.85):
    """Erosion time per pixel for a block around the word; letters (rough outline) survive to the end.
    `span` is when the waste starts and finishes going; a low `power` clears the waste near the letters
    sooner, so the word reads earlier."""

    def build():
        block = rounded_box(F, *margins) + F.fbm(0.3, 4, 1) * F.u * 0.08
        rough = F.sdf + F.u * noise * F.fbm(0.05, 3, 7)
        outside = np.clip(rough / F.u, 0, None)
        skin = np.clip(-block / F.u, 0, None)
        fraction = (skin / (skin + outside + 1e-3)) ** power
        if hard_bands:
            fraction = fraction * (1 + hard_bands * np.sin(F.Y * 19 + F.fbm(0.6, 3, 2) * 2.2))
        start, end = span
        erode = start + (end - start) * fraction - wind[0] * (1 - np.clip(F.xn, 0, 1)) - wind[1] * (1 - np.clip(F.yn, 0, 1))
        erode = erode + 0.07 * F.fbm(0.08, 3, 3)
        if chips:
            ids, _, edge, _ = F.cells(chips, 21)
            flat = np.bincount(ids.ravel(), erode.ravel()) / np.maximum(1, np.bincount(ids.ravel()))
            erode = flat[ids] + 0.01 * np.clip(edge / F.u, 0, 1)
        erode = np.where(block > 0, -1, np.minimum(erode, 0.95))
        return np.where(rough <= 0, 1.0 + np.clip(-rough / F.u, 0, None) * 2.5, erode)

    return F.memo(('erosion', key), build)


def front_particles(F, erode, count, seed):
    front = np.nonzero((erode > 0.03) & (erode < 0.94) & (F.sdf > 0))
    rng = np.random.default_rng(F.seed + seed)
    if not len(front[0]):
        return None, rng, (np.zeros(0, int),) * 2
    pick = rng.integers(0, len(front[0]), count)
    ys, xs = front[0][pick], front[1][pick]
    return np.stack((xs, ys), 1), rng, (ys, xs)


def silk_letter_spans(F):
    """Separate ink columns into glyph slots, including detached dots over i and j."""

    def build():
        columns = np.flatnonzero(np.any(F.ink > 0.35, axis=0))
        if not len(columns):
            return [(F.box[0], F.box[2])]
        cuts = np.flatnonzero(np.diff(columns) > 1) + 1
        groups = [part for part in np.split(columns, cuts) if len(part)]
        return [(int(part[0]), int(part[-1] + 1)) for part in groups]

    return F.memo('silk-letter-spans', build)


def silk_strokes(F, lo, hi):
    """The letter's stroke centrelines between columns lo and hi, as one route a ribbon can follow:
    [(x, y, half stroke width, drawn)], where `drawn` is False on the hops between separate strokes."""

    def build():
        from scipy.ndimage import distance_transform_edt
        from skimage.morphology import skeletonize

        mask = F.ink > 0.5
        mask[:, : max(0, int(lo))] = False
        mask[:, int(hi) :] = False
        if not mask.any():
            return []
        width = distance_transform_edt(mask)
        skeleton = skeletonize(mask)
        pixels = set(zip(*np.nonzero(skeleton)))

        def around(p):
            return [
                (p[0] + dy, p[1] + dx)
                for dy in (-1, 0, 1)
                for dx in (-1, 0, 1)
                if (dy or dx) and (p[0] + dy, p[1] + dx) in pixels
            ]

        degree = {p: len(around(p)) for p in pixels}
        used, chains = set(), []

        def walk(a, b):
            chain = [a, b]
            used.add(frozenset((a, b)))
            while degree[chain[-1]] == 2:
                step = [q for q in around(chain[-1]) if frozenset((chain[-1], q)) not in used]
                if not step:
                    break
                used.add(frozenset((chain[-1], step[0])))
                chain.append(step[0])
            return chain

        for p in sorted(pixels, key=lambda p: (degree[p] == 2, p[1], p[0])):
            for q in around(p):
                if frozenset((p, q)) not in used:
                    chains.append(walk(p, q))
        # Drop the short spurs a skeleton grows into corners.
        spur = max(3.0, float(np.median([width[p] for p in pixels])) * 1.5)
        kept = [c for c in chains if len(c) >= spur or (degree[c[0]] != 1 and degree[c[-1]] != 1)] or chains
        # Small separate marks (the dot of an i, a full stop) keep their own stroke, even a single pixel's.
        from scipy.ndimage import label

        parts, count = label(mask, structure=np.ones((3, 3)))
        covered = {parts[c[0]] for c in kept}
        for part in range(1, count + 1):
            if part in covered:
                continue
            own = max((c for c in chains if parts[c[0]] == part), key=len, default=[])
            ys, xs = np.nonzero(parts == part)
            y, x = int(round(ys.mean())), int(round(xs.mean()))
            if len(own) >= width[y, x] * 1.5:
                kept.append(own)
                continue
            # A round mark's skeleton is a point: give it a short stroke across its middle instead.
            reach = max(1, int(width[y, x] * 0.7))
            kept.append([(y, x + dx) for dx in range(-reach, reach + 1) if mask[y, x + dx]] or [(y, x)])
        chains = kept
        # Join the strokes into one route: start at the top-left, then always the nearest loose end.
        route, chains = [], [list(c) for c in chains]
        chains.sort(key=lambda c: min(c[0][1] + c[0][0] * 0.5, c[-1][1] + c[-1][0] * 0.5))
        current = chains.pop(0)
        if current[-1][1] + current[-1][0] * 0.5 < current[0][1] + current[0][0] * 0.5:
            current.reverse()
        while True:
            route.extend((x, y, width[y, x], k > 0 or not route) for k, (y, x) in enumerate(current))
            if not chains:
                break
            last = current[-1]
            k, flip = min(
                ((k, flip) for k in range(len(chains)) for flip in (False, True)),
                key=lambda kf: math.dist(last, chains[kf[0]][-1 if kf[1] else 0]),
            )
            current = chains.pop(k)[::-1] if flip else chains.pop(k)
            hop = math.dist(last, current[0]) > 2.5
            route.append((current[0][1], current[0][0], width[current[0]], not hop))
        # Ease the pixel staircase into smooth strokes.
        xy = np.array([(x, y) for x, y, _, _ in route], dtype=float)
        smoothed = xy.copy()
        for k in range(len(route)):
            if route[k][3] and 0 < k < len(route) - 1 and route[k - 1][3] and route[k + 1][3]:
                smoothed[k] = xy[max(0, k - 2) : k + 3].mean(axis=0)
        return [(float(x), float(y), float(w), drawn) for (x, y), (_, _, w, drawn) in zip(smoothed, route)]

    return F.memo(('silk-strokes', int(lo), int(hi)), build)


def letters(F):
    """Per-pixel letter index from gaps in the ink's column coverage, plus the letter count."""

    def build():
        from scipy.ndimage import label

        columns = F.ink.max(axis=0) > 0.3
        labels, count = label(columns)
        index = np.maximum.accumulate(labels)
        index = np.where(index == 0, 1, index)
        return np.broadcast_to(index[None, :] - 1, F.ink.shape).astype(float), max(1, count)

    return F.memo('letters', build)


def arrival(F, key, per_unit=1.0, noise=0.15, seed=0):
    """0..1 time for a front spreading through the glyph from seeds scattered along the word."""

    def build():
        x0, _, x1, _ = F.box
        seeds = F.ink_spread(max(2, round((x1 - x0) / F.u * per_unit)), seed)
        d = F.distance_from(seeds, ('arrival', key)) + noise * F.fbm(0.12, 3, seed + 500)
        inside = F.ink > 0.3
        low, high = d[inside].min(), d[inside].max()
        return np.clip((d - low) / max(1e-3, high - low), 0, 1.2)

    return F.memo(('arrival', key), build)


def transform(F, canvas, t, until, material):
    """The word's own colours give way to a material over the first part of an exit."""
    w = sm(t, 0, until)
    return mix(F.source, material, w), w


def supersampled(F, draw_fn, factor=2):
    """Draw with PIL at `factor` times the working resolution and return an antialiased float RGBA."""
    from PIL import Image, ImageDraw

    big = Image.new('RGBA', (F.W * factor, F.H * factor))
    draw_fn(ImageDraw.Draw(big), factor)
    small = big.resize((F.W, F.H), Image.LANCZOS)
    rgba = np.asarray(small, dtype=float) / 255
    return rgba[..., :3], rgba[..., 3]
