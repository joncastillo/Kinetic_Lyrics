"""Crafted lettering: bamboo, a radiant cross and an architectural sketch."""

import math

import numpy as np
from scipy.ndimage import gaussian_filter

from effects.materials.fx import (
    Particles,
    bevel,
    bloom,
    coverage,
    lambert,
    mix,
    normals,
    rgb,
    shadow,
    shift,
    sm,
    smooth,
    specular,
    sun,
)
from effects.materials.recipes.registry import recipe
from effects.materials.recipes.common import letters, lit, metal, supersampled


def telescope(q, segments):
    """Bamboo grows one internode at a time: each segment extends quickly, then the next begins."""
    q = max(0.0, min(1.0, q)) * segments
    whole = math.floor(q)
    return min(1.0, (whole + sm(q - whole, 0, 1)) / segments)


BAMBOO_CULM = (rgb(58, 116, 46), rgb(132, 168, 64), rgb(196, 204, 120))


def bamboo_culms(F):
    """Culm layout: position, height, width, lean, sway phase and internode count, back to front."""

    def build():
        rng = np.random.default_rng(F.seed + 600)
        x0, y0, x1, y1 = F.box
        count = int(np.clip(round((x1 - x0) / F.u * 1.7), 4, 11))
        xs = np.linspace(x0 + F.u * 0.05, x1 - F.u * 0.05, count) + rng.uniform(-0.08, 0.08, count) * F.u
        culms = []
        for k, cx in enumerate(xs):
            depth = rng.uniform(0, 1)
            lean = rng.uniform(0.04, 0.24) * (
                1 if (k + rng.integers(0, 2)) % 2 else -1
            )  # a clump fans out, never quite vertical
            culms.append(
                dict(
                    x=cx,
                    base=y1 + F.u * 0.04,
                    top=max(3.0, y0 - F.u * rng.uniform(1.0, 1.6)),
                    width=F.u * (0.03 + 0.03 * (1 - depth)),
                    lean=lean,
                    phase=rng.uniform(0, math.tau),
                    segments=int(rng.integers(7, 11)),
                    depth=depth,
                    start=0.02 + 0.3 * k / count + rng.uniform(0, 0.05),
                    tint=rng.uniform(0, 1),
                )
            )
        return sorted(culms, key=lambda c: -c['depth'])

    return F.memo('bamboo-culms', build)


@recipe('bamboo-lettering', 'entrance', pad=1.8)
def bamboo(F, canvas, t, intensity):
    light = sun(-2.3, 0.7)
    settle = 1 - sm(t, 0.65, 1)
    fibres = F.noise(0.02, 610, (0.25, 8.0))
    culms = bamboo_culms(F)
    leaves = []
    body_rgb = np.zeros((F.H, F.W, 3))
    body_a = np.zeros((F.H, F.W))
    for c in culms:
        grown = telescope(sm(t, c['start'], c['start'] + 0.6), c['segments'])
        if grown <= 0:
            continue
        span = c['base'] - c['top']
        tip = c['base'] - span * grown
        reach = abs(c['lean']) * span + F.u * 0.08 + c['width']
        r0, r1 = max(0, int(tip) - 2), min(F.H, int(c['base']) + 2)
        c0, c1 = max(0, int(c['x'] - reach) - 2), min(F.W, int(c['x'] + reach) + 3)
        if r1 <= r0 or c1 <= c0:
            continue
        window = (slice(r0, r1), slice(c0, c1))  # shade each culm only inside its own bounding box
        py, px = F.py[window], F.px[window]
        rise = np.clip((c['base'] - py) / span, 0, 1)
        sway = F.u * 0.05 * math.sin(t * 7 + c['phase']) * settle * rise**2
        centre = c['x'] + c['lean'] * (c['base'] - py) + sway
        width = c['width'] * (1 - 0.45 * rise**2)
        across = (px - centre) / np.maximum(width, 0.5)
        inside = (np.abs(across) < 1) & (py >= tip) & (py <= c['base'])
        if not inside.any():
            continue
        cyl = np.sqrt(np.clip(1 - across**2, 0, 1))
        internode = span / c['segments']
        d = ((c['base'] - py) / internode) % 1
        node = np.exp(-((d / 0.035) ** 2)) + np.exp(-(((1 - d) / 0.035) ** 2))
        n = np.stack((across * 0.9, -node * 0.6 * np.sign(0.5 - d), cyl + 0.15), -1)
        n = n / np.linalg.norm(n, axis=-1, keepdims=True)
        colour = mix(BAMBOO_CULM[0], BAMBOO_CULM[1], 0.35 + 0.45 * c['tint'] + 0.25 * rise)
        colour = colour * (1 + 0.08 * fibres[window])[..., None]
        colour = mix(colour, rgb(226, 232, 200), np.exp(-(((d - 0.06) / 0.05) ** 2)) * 0.35)
        colour = mix(colour, rgb(40, 70, 30), np.exp(-(((d - 0.985) / 0.02) ** 2)) * 0.6)
        shaded = colour * (0.35 + 0.85 * lambert(n, light))[..., None] + specular(n, light, 40)[..., None] * 0.45
        shaded = shaded * (1 - 0.35 * c['depth']) + rgb(150, 170, 150) * 0.35 * c['depth'] * 0.4
        alpha = inside * smooth(1 - np.abs(across), 0, 0.12) * smooth(py - tip, 0, 2.0)
        body_rgb[window] = mix(body_rgb[window], shaded, alpha)
        body_a[window] = alpha + body_a[window] * (1 - alpha)
        for s in range(2, c['segments'] + 1):  # a side spray at every joint the culm has grown past
            ny = c['base'] - internode * s
            if ny < tip - 1 or ny > F.box[3] - F.u * 0.3:
                continue
            born = c['start'] + 0.6 * (s / c['segments']) + 0.03
            nx = (
                c['x']
                + c['lean'] * (c['base'] - ny)
                + F.u * 0.05 * math.sin(t * 7 + c['phase']) * settle * ((c['base'] - ny) / span) ** 2
            )
            crown = s == c['segments']
            for side in (-1, 1) if crown else (-1 if (s + int(c['phase'] * 3)) % 2 else 1,):
                leaves.append((nx, ny, side, born, s, c, crown))
    canvas.over(np.zeros(3), shadow(body_a, F, 0.05, 0.06, 0.05, 0.35) * sm(t, 0, 0.1))
    canvas.over(np.clip(body_rgb, 0, 1), body_a)

    # Leaf sprays unfurl from the upper nodes; drawn supersampled, shading split along the midrib.
    sprays = []
    for nx, ny, side, born, s, c, crown in leaves:
        q = sm(t, born, born + 0.22)
        if q <= 0:
            continue
        local = np.random.default_rng(F.seed * 31 + int(c['x']) * 7 + s * 3 + side)
        count_leaves = int(local.integers(6, 10) if crown else local.integers(3, 7))
        twig = (nx + side * F.u * 0.12 * q, ny - F.u * 0.04 * q)
        for j in range(count_leaves):
            droop = math.radians(local.uniform(15, 70))
            spread = droop if side > 0 else math.pi - droop
            angle = -math.pi / 2 * (1 - q) + spread * q  # rolled upright, then opening into a drooping fan
            angle += local.uniform(-0.35, 0.35) * q + 0.04 * math.sin(t * 9 + j) * settle
            length = F.u * local.uniform(0.26, 0.46) * q**0.6
            sprays.append(
                (
                    twig,
                    angle,
                    length,
                    F.u * local.uniform(0.045, 0.06) * q,
                    (nx, ny),
                    local.uniform(0, 1),
                    c['depth'],
                    ny > F.box[1] + F.u * 0.1,
                )
            )
    # Sprays beside the letters sit behind them so the word stays readable; the canopy above is in front.
    paint_sprays(F, canvas, [p for p in sprays if p[-1]])
    # Letters carved from culm: telescoping growth with node rings at a fixed pitch.
    index, count = letters(F)
    pitch = 0.3
    height = bevel(F.sdf, F.u * 0.06)
    ring_d = ((F.box[3] - F.py) / (F.u * pitch)) % 1
    ring = np.exp(-((ring_d / 0.05) ** 2)) + np.exp(-(((1 - ring_d) / 0.05) ** 2))
    height = height + F.u * 0.012 * ring * np.clip(-F.sdf / (F.u * 0.02), 0, 1)
    n = normals(height)
    # The letters are older, darker culm than the fresh stalks around them, so they stand out from the grove.
    colour = mix(rgb(7, 28, 13), rgb(19, 47, 22), 0.45 + 0.3 * F.fbm(0.25, 2, 611)) * (1 + 0.06 * fibres)[..., None]
    colour = mix(colour, rgb(36, 66, 30), np.exp(-(((ring_d - 0.07) / 0.05) ** 2)) * 0.22)
    letter = lit(colour, n, light, ambient=0.24) + specular(n, light, 36)[..., None] * 0.08
    reveal = np.zeros_like(F.yn)
    for k in range(count):
        level = telescope(sm(t, 0.12 + 0.4 * k / max(1, count), 0.62 + 0.4 * k / max(1, count)), 4)
        reveal = np.where(index == k, smooth(F.yn - (1 - level * 1.02), -0.02, 0.0), reveal)
    cov = coverage(F.sdf) * reveal
    canvas.over(np.zeros(3), shadow(cov, F, 0.04, 0.06, 0.04, 0.45))
    canvas.over(np.clip(letter, 0, 1), cov)
    paint_sprays(F, canvas, [p for p in sprays if not p[-1]])


def paint_sprays(F, canvas, sprays):
    """Bamboo leaf sprays, drawn supersampled with the shading split along each midrib."""
    if sprays:

        def draw(d, f):
            for twig, angle, length, width, node, tone, depth, _ in sprays:
                d.line(
                    [(node[0] * f, node[1] * f), (twig[0] * f, twig[1] * f)],
                    fill=(92, 112, 52, 255),
                    width=max(1, round(f * F.u * 0.012)),
                )
                ca, sa = math.cos(angle), math.sin(angle)
                bend = 0.18 * length
                spine, left, right = [], [], []
                for k in range(13):
                    s = k / 12
                    along = s * length
                    sag = bend * s * s
                    px, py = twig[0] + ca * along, twig[1] + sa * along + sag
                    w = width * (s**0.45) * (1 - s) ** 0.9 * 2.2
                    spine.append((px * f, py * f))
                    left.append(((px - sa * w) * f, (py + ca * w) * f))
                    right.append(((px + sa * w) * f, (py - ca * w) * f))
                top_c = mix(rgb(52, 112, 40), rgb(110, 160, 56), tone) * (1 - 0.3 * depth)
                under = mix(rgb(120, 168, 70), rgb(176, 200, 98), tone) * (1 - 0.3 * depth)
                d.polygon(spine + left[::-1], fill=tuple(int(v * 255) for v in top_c) + (255,))
                d.polygon(spine + right[::-1], fill=tuple(int(v * 255) for v in under) + (255,))
                d.line(spine, fill=tuple(int(min(255, v * 255 * 1.25)) for v in under) + (255,), width=max(1, f))
                d.line(right, fill=(206, 222, 120, 160), width=max(1, f // 2))

        leaf_rgb, leaf_a = supersampled(F, draw)
        canvas.darken(shadow(leaf_a, F, 0.04, 0.07, 0.03, 0.35))
        veins = 0.92 + 0.08 * np.sin(F.px * 1.7 + F.py * 1.1)
        canvas.over(np.clip(leaf_rgb * veins[..., None], 0, 1), leaf_a)


def cross_geometry(F):
    """Signed distances of a trefoil-tipped Latin cross above the word, plus its key points."""

    def build():
        x0, y0, x1, y1 = F.box
        u = F.u
        cx, foot, top = (x0 + x1) / 2, y0 - u * 0.08, max(F.u * 0.12, y0 - u * 0.95)
        bar = top + (foot - top) * 0.3
        half, arm = u * 0.052, (foot - top) * 0.32

        def box(px, py, hx, hy):
            qx, qy = np.abs(F.px - px) - hx, np.abs(F.py - py) - hy
            return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0)

        def disc(px, py, r):
            return np.hypot(F.px - px, F.py - py) - r

        sdf = np.minimum(box(cx, (top + foot) / 2, half, (foot - top) / 2), box(cx, bar, arm, half))
        lobe = half * 1.25
        for ex, ey, dx, dy in ((cx, top, 0, -1), (cx - arm, bar, -1, 0), (cx + arm, bar, 1, 0)):
            sdf = np.minimum(sdf, disc(ex + dx * lobe * 0.35, ey + dy * lobe * 0.35, lobe))
            sdf = np.minimum(
                sdf,
                disc(ex + dy * lobe * 0.95 - dx * lobe * 0.35, ey + dx * lobe * 0.95 - dy * lobe * 0.35, lobe * 0.78),
            )
            sdf = np.minimum(
                sdf,
                disc(ex - dy * lobe * 0.95 - dx * lobe * 0.35, ey - dx * lobe * 0.95 - dy * lobe * 0.35, lobe * 0.78),
            )
        sdf = np.minimum(sdf, box(cx, foot - half * 0.6, half * 1.9, half * 0.6))
        reach = np.maximum(np.abs(F.px - cx) / max(1, arm), np.abs(F.py - bar) / max(1, foot - bar))
        return sdf, dict(cx=cx, bar=bar, top=top, foot=foot, half=half, arm=arm), reach

    return F.memo('cross', build)


def cross_surfaces(F):
    """Everything about the cross and its letters that does not change from frame to frame."""

    def build():
        sdf, g, reach = cross_geometry(F)
        u, half = F.u, g['half']
        dx, dy = F.px - g['cx'], F.py - g['bar']
        phi = np.arctan2(dy, dx)
        groove = np.exp(-(((sdf + half * 0.5) / (half * 0.12)) ** 2))
        n = normals(bevel(sdf, half * 0.95) - half * 0.18 * groove)
        gold = np.clip(metal(n, rgb(255, 196, 92), power=90) * (1 - 0.25 * groove)[..., None], 0, 1)
        gem_r = np.hypot(dx, dy) / (half * 1.05)
        gem_n = np.stack(
            (dx / (half * 1.05) * 0.8, dy / (half * 1.05) * 0.8, np.sqrt(np.clip(1 - gem_r**2, 0, 1)) + 0.2), -1
        )
        gem_n = gem_n / np.linalg.norm(gem_n, axis=-1, keepdims=True)
        ruby = mix(rgb(110, 0, 20), rgb(230, 30, 60), lambert(gem_n, -sun() * np.array((1, 1, -1))))
        ruby = np.clip(ruby + specular(gem_n, sun(), 120)[..., None] * 1.5, 0, 1)
        star = np.exp(-np.abs(dx) / (u * 0.004)) * np.exp(-np.abs(dy) / (u * 0.12)) + np.exp(
            -np.abs(dy) / (u * 0.004)
        ) * np.exp(-np.abs(dx) / (u * 0.12))
        ln = normals(bevel(F.sdf, u * 0.05))
        enamel = (
            mix(rgb(236, 226, 204), rgb(255, 250, 238), lambert(ln, sun())) + specular(ln, sun(), 60)[..., None] * 0.35
        )
        rim = smooth(-F.sdf, 0, 1.0) * (1 - smooth(-F.sdf, u * 0.03, u * 0.04))
        letter = mix(enamel, metal(ln, rgb(255, 196, 92), power=70), rim)
        warm = (rgb(255, 210, 130) * (np.clip(-ln[..., 1], 0, 1) * 0.25)[..., None]) * (1 - rim)[..., None]
        origin = np.hypot(F.px - g['cx'], (F.py - F.box[1]) * 1.6) / max(1.0, F.box[2] - F.box[0])
        return dict(
            sdf=sdf,
            g=g,
            reach=reach,
            dx=dx,
            dy=dy,
            r=np.hypot(dx, dy) / u,
            c16=np.cos(phi * 16),
            s16=np.sin(phi * 16),
            gold=gold,
            gem=smooth(1 - gem_r, 0, 0.15),
            ruby=ruby,
            star=star,
            letter=np.clip(letter, 0, 1),
            warm=warm,
            gild=0.42 + 0.42 * np.clip(origin * 1.6, 0, 1),
            cover=coverage(sdf),
            letter_cover=coverage(F.sdf),
        )

    return F.memo('cross-surfaces', build)


@recipe('catholic-cross-lettering', 'entrance', pad=1.2)
def cross_radiance(F, canvas, t, intensity):
    S = cross_surfaces(F)
    g, r = S['g'], S['r']
    u = F.u

    # Radiance: alternating long and short rays turning slowly, a halo, and a fine aureole ring.
    burst = sm(t, 0.04, 0.3)
    calm = 0.45 + 0.55 * (1 - sm(t, 0.4, 0.95))
    spin = t * 0.9
    wave = S['c16'] * math.cos(spin) - S['s16'] * math.sin(spin)  # cos(16 phi + spin) from cached terms
    long_rays = (0.5 + 0.5 * wave) ** 10
    short_rays = (0.5 - 0.5 * wave) ** 14
    length = (0.2 + 0.45 * burst) * (0.75 + 0.25 * calm) * (1 - 0.35 * sm(t, 0.9, 1))
    rays = (long_rays * np.exp(-r / length) + 0.6 * short_rays * np.exp(-r / (length * 0.6))) * smooth(r, 0.0, 0.06)
    halo = np.exp(-((r / (0.16 + 0.12 * burst)) ** 2))
    ring = np.exp(-(((r - 0.3 * burst) / 0.012) ** 2)) * sm(t, 0.2, 0.45) * (1 - sm(t, 0.9, 1) * 0.5)
    glow = (rays * 0.75 + halo * 0.55 + ring * 0.35) * burst * calm
    canvas.add(
        rgb(255, 214, 140) * glow[..., None] * 0.9
        + bloom(rgb(255, 200, 120) * (halo * burst * calm)[..., None], F, 0.1, 0.4),
        0.5,
    )
    if t < 0.35:
        flare = sm(t, 0.02, 0.1) * (1 - sm(t, 0.2, 0.35))
        streak = np.exp(-((S['dy'] / (u * 0.008)) ** 2)) * np.exp(-np.abs(S['dx']) / (u * 0.9)) * flare
        canvas.add(rgb(255, 236, 200) * (streak + np.exp(-((r / 0.03) ** 2)) * flare * 2)[..., None])

    # The cross is first drawn in light from the crossing outwards, then cools into engraved gold.
    cov = S['cover'] * smooth(sm(t, 0.1, 0.42) * 1.15 - S['reach'], 0, 0.05)
    solid = smooth(t - 0.38 - 0.22 * np.clip(S['reach'], 0, 1), 0, 0.12)
    canvas.over(rgb(40, 20, 0), shadow(cov, F, 0.03, 0.05, 0.03, 0.35 * solid))
    canvas.over(mix(rgb(255, 246, 220), S['gold'], solid), cov)
    canvas.add(bloom(rgb(255, 220, 150) * (cov * (1 - solid))[..., None], F, 0.04, 1.1))
    canvas.over(S['ruby'], S['gem'] * sm(t, 0.5, 0.62))
    sparkle = sm(t, 0.6, 0.7) * (1 - sm(t, 0.78, 0.9))
    if sparkle > 0:
        canvas.add(np.ones(3) * (S['star'] * sparkle)[..., None])

    # Letters: ivory enamel within gold rims, gilded outward from the foot of the cross.
    lcov = S['letter_cover'] * smooth(t - S['gild'], 0, 0.1)
    canvas.over(rgb(40, 20, 0), shadow(lcov, F, 0.03, 0.06, 0.04, 0.45))
    canvas.over(np.clip(S['letter'] + S['warm'] * sm(t, 0.5, 1), 0, 1), lcov)
    canvas.add(
        rgb(255, 230, 170) * (np.exp(-(((t - S['gild'] - 0.05) / 0.03) ** 2)) * S['letter_cover'])[..., None] * 0.8
    )

    if 0.1 < t < 0.95:
        rng = np.random.default_rng(F.seed + 640)
        n_ = 160
        angle = rng.uniform(0, math.tau, n_)
        speed = rng.uniform(0.3, 1.1, n_)
        motes = Particles(
            F,
            np.tile((g['cx'], g['bar']), (n_, 1)),
            rng.uniform(0.1, 0.7, n_),
            np.stack((np.cos(angle) * speed, np.sin(angle) * speed * 0.7 - 0.2), 1),
            accel=(0, -0.3),
            drag=2.0,
            life=rng.uniform(0.15, 0.3, n_),
            size=rng.choice((1, 1, 2), n_),
            color=rgb(255, 226, 160),
            glow=True,
            swirl=0.03,
        )
        motes.render(canvas, t)


GRAPHITE = (46, 50, 58)
BLUE_PENCIL = (70, 120, 200)


def sketch_plan(F):
    """Every stroke of an architectural sketch of the word as 3D blocks, in drawing order: construction
    lines, perspective boxes, front contours, extruded back contours and corner edges, then hatching.
    Each stroke is (points, weight, darkness, start, end, kind); times are fractions of the entrance."""

    def build():
        from skimage.measure import approximate_polygon, find_contours

        rng = np.random.default_rng(F.seed + 900)
        u = F.u
        x0, y0, x1, y1 = F.box
        depth = np.array((u * 0.13, -u * 0.1))  # the extrusion runs back, up and to the right
        vanish = np.array((x1 + u * 3.5, y0 - u * 2.2))
        strokes = []

        def wobbly(a, b, overshoot=0.12, jitter=0.006):
            a, b = np.array(a, float), np.array(b, float)
            d = b - a
            a, b = a - d * rng.uniform(0, overshoot), b + d * rng.uniform(0, overshoot)
            n = max(2, int(np.linalg.norm(b - a) / (u * 0.08)))
            line = np.linspace(a, b, n)
            normal = np.array((-d[1], d[0])) / max(1e-6, np.linalg.norm(d))
            return line + normal * (rng.normal(0, u * jitter, n).cumsum() * 0.35)[:, None]

        # 1. construction: guide lines across the word, rays toward the vanishing point
        cap = y0
        for y in (y1, cap, y0 + (y1 - y0) * 0.45):
            strokes.append(['guide', wobbly((x0 - u * 0.5, y), (x1 + u * 0.5, y), 0.05)])
        index, count = letters(F)
        boxes = []
        for k in range(count):
            cols = np.nonzero((index[0] == k) & (F.ink.max(axis=0) > 0.3))[0]
            rows = np.nonzero(F.ink[:, cols].max(axis=1) > 0.3)[0] if len(cols) else []
            if len(cols) and len(rows):
                boxes.append((cols[0], rows[0], cols[-1], rows[-1]))
        for bx0, by0, bx1, by1 in boxes[:: max(1, len(boxes) // 3)]:
            strokes.append(['ray', wobbly((bx1, by0), vanish, 0, 0.003)])
        # 2. a perspective box around each letter
        for bx0, by0, bx1, by1 in boxes:
            front = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
            back = [tuple(np.array(p) + depth) for p in front]
            for a, b in zip(front, front[1:] + front[:1]):
                strokes.append(['box', wobbly(a, b)])
            for a, b in zip(back[:2], back[1:3]):
                strokes.append(['box', wobbly(a, b)])
            for a, b in ((front[0], back[0]), (front[1], back[1]), (front[2], back[2])):
                strokes.append(['box', wobbly(a, b)])
        # 3. front contours, then their extruded back and the corner edges joining them
        contours = [c[:, ::-1] for c in find_contours(F.ink, 0.5) if len(c) > 8]
        contours.sort(key=lambda c: c[:, 0].min())
        corners = []
        for contour in contours:
            jitter = rng.normal(0, u * 0.003, contour.shape)
            strokes.append(['contour', contour + jitter])
            strokes.append(['contour2', contour + rng.normal(0, u * 0.004, contour.shape) + u * 0.004])
            simple = approximate_polygon(contour, tolerance=u * 0.035)
            corners.extend(simple[:-1])
        for contour in contours:
            strokes.append(['back', contour + depth])
        for p in corners:
            strokes.append(['edge', wobbly(p, p + depth, 0.02, 0.002)])
        weights = {
            'guide': (1.1, 0.6),
            'ray': (0.9, 0.5),
            'box': (1.3, 0.7),
            'contour': (1.6, 1.0),
            'contour2': (0.9, 0.6),
            'back': (1.1, 0.7),
            'edge': (1.1, 0.75),
        }
        windows = {
            'guide': (0.0, 0.08),
            'ray': (0.03, 0.12),
            'box': (0.06, 0.26),
            'contour': (0.18, 0.46),
            'contour2': (0.26, 0.5),
            'back': (0.34, 0.56),
            'edge': (0.4, 0.62),
        }
        plan = []
        for kind in ('guide', 'ray', 'box', 'contour', 'contour2', 'back', 'edge'):
            group = [s for s in strokes if s[0] == kind]
            start, end = windows[kind]
            span = (end - start) / max(1, len(group))
            for number, (_, points) in enumerate(group):
                begin = start + number * span
                plan.append((np.asarray(points, float), *weights[kind], begin, begin + span * 1.6, kind))
        # 4. the extruded sides: the swept volume behind each letter, minus its front face
        swept = np.zeros_like(F.ink)
        for k in range(1, 13):
            swept = np.maximum(swept, shift(F.ink, round(depth[1] * k / 12), round(depth[0] * k / 12)))
        sides = np.clip(swept - F.ink, 0, 1)
        ground = np.clip(
            shift(gaussian_filter(F.ink, u * 0.02), round(u * 0.06), round(u * 0.12)) - F.ink - sides, 0, 1
        )
        return plan, sides, ground

    return F.memo('sketch', build)


def hatching(F, angle, spacing, seed):
    """Parallel pencil hatching (0..1) at an angle, with slightly irregular pressure."""
    u = F.u
    coordinate = (F.px * math.cos(angle) + F.py * math.sin(angle)) / (u * spacing)
    line = 1 - smooth(np.abs((coordinate % 1) - 0.5) * 2, 0.55, 0.85)
    return line * (0.75 + 0.25 * F.noise(0.04, seed))


@recipe('architectural-sketch', 'entrance', pad=1.0)
def architectural_sketch(F, canvas, t, intensity):
    from PIL import Image, ImageDraw

    plan, sides, ground = sketch_plan(F)
    u = F.u
    sweep = np.clip(F.xn, 0, 1)
    shaded = smooth(t - 0.54 - 0.24 * sweep, 0, 0.08)
    # Shading after the line work: faces washed in the word's own ink, cross-hatched sides, a hatched cast shadow.
    face = (
        mix(mix(rgb(244, 238, 224), rgb(226, 218, 200), 0.5 + 0.5 * F.fbm(0.05, 2, 901)), F.source, 0.85)
        * (1 - 0.06 * F.noise(0.006, 902))[..., None]
    )
    side_tone = np.clip(hatching(F, 0.9, 0.045, 903) + hatching(F, -0.5, 0.06, 904) * 0.7, 0, 1)
    canvas.over(rgb(250, 246, 236), ground * shaded * 0.25)
    canvas.over(np.array(GRAPHITE) / 255, ground * hatching(F, 0.9, 0.06, 905) * shaded * 0.55)
    canvas.over(rgb(236, 230, 214), sides * shaded * 0.85)
    canvas.over(np.array(GRAPHITE) / 255, sides * side_tone * shaded * 0.9)
    canvas.over(face, coverage(F.sdf) * smooth(t - 0.48 - 0.24 * sweep, 0, 0.1))
    # The line work, drawn supersampled, stroke by stroke; construction lines fade back once shaded.
    f = 2
    lines = Image.new('L', (F.W * f, F.H * f))
    blue = Image.new('L', (F.W * f, F.H * f))
    halo = Image.new('L', (F.W * f, F.H * f))
    ld, bd, hd = ImageDraw.Draw(lines), ImageDraw.Draw(blue), ImageDraw.Draw(halo)
    tip = None
    for points, weight, darkness, begin, end, kind in plan:
        q = (t - begin) / (end - begin)
        if q <= 0:
            continue
        shown = points[: max(2, int(len(points) * min(1.0, q)))]
        if q < 1:
            tip = shown[-1]
        construction = kind in ('guide', 'ray', 'box')
        alpha = darkness * (1 - 0.6 * sm(t, 0.62, 0.95) * construction)
        width = max(1, round(weight * f * max(1.0, u / 90)))
        path = [tuple(p * f) for p in shown]
        (bd if construction else ld).line(path, fill=round(255 * alpha), width=width)
        hd.line(path, fill=round(160 * alpha), width=width + 3 * f)
    halo_a = np.asarray(halo.resize((F.W, F.H), Image.LANCZOS), dtype=float) / 255
    line_a = np.asarray(lines.resize((F.W, F.H), Image.LANCZOS), dtype=float) / 255
    blue_a = np.asarray(blue.resize((F.W, F.H), Image.LANCZOS), dtype=float) / 255
    canvas.over(
        rgb(250, 248, 240), gaussian_filter(halo_a, 1.0) * 0.45
    )  # a pale halo keeps lines legible on dark scenes
    canvas.over(np.array(BLUE_PENCIL) / 255, np.clip(blue_a * 1.1, 0, 1))  # construction in drafting blue
    canvas.over(np.array(GRAPHITE) / 255, np.clip(line_a * 1.2, 0, 1))
    if tip is not None and t < 0.8:
        glint = np.exp(-((F.px - tip[0]) ** 2 + (F.py - tip[1]) ** 2) / (u * 0.012) ** 2)
        canvas.add(np.ones(3) * glint[..., None] * 0.8, 0.5)
