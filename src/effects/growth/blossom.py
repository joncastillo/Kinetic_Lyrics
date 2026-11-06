"""The petal letterings on the crafted kit: a few large, shaded petals that turn as they fly, and letters that
end solid in a blossom gradient (one palette per word). Each lettering has its own way of forming the word."""

import math

import numpy as np

from effects.growth.crafted import (
    coverage,
    crafted,
    letter_boxes,
    per_pixel,
    relay,
    rgb,
    rim,
    shadow,
    sm,
    smooth,
    spring,
    supersampled,
)
from effects.materials.fx import mix, warp

# (deep, pale, rim) per word: rose, lilac, apricot, apple blossom
BLOSSOMS = ((rgb(212, 64, 116), rgb(255, 198, 216), rgb(92, 18, 50)),
            (rgb(142, 88, 210), rgb(228, 206, 252), rgb(56, 28, 102)),
            (rgb(232, 116, 44), rgb(255, 216, 150), rgb(110, 46, 10)),
            (rgb(226, 132, 158), rgb(255, 242, 238), rgb(108, 46, 66)))
LEAF = rgb(84, 150, 74)


def palette(F):
    return BLOSSOMS[F.seed % len(BLOSSOMS)]


def petal(d, f, x, y, angle, length, width, pal, turn=1.0, alpha=255):
    """A rounded petal with a notched tip, deep at its base and pale towards the tip, a dark edge and a vein.
    `turn` is the cosine of its flip: it narrows as it turns edge-on and shows its darker back below zero."""
    if length <= 0.5 or alpha <= 0:
        return
    deep, pale, edge = pal
    back = turn < 0
    w = width * max(0.12, abs(turn))
    ca, sa = math.cos(angle), math.sin(angle)

    def at(a, b):
        return ((x + ca * a - sa * b) * f, (y + sa * a + ca * b) * f)

    def half(s_):  # narrow at the base, widest past the middle, a round tip
        if s_ <= 0.62:
            return w * (s_ / 0.62) ** 0.7
        return w * math.sqrt(max(0.0, 1 - ((s_ - 0.62) / 0.38) ** 2))

    def outline(begin, scale_w=1.0, grow=0.0):
        steps = np.linspace(begin, 1.0, 14)
        side = [(s_ * length, half(s_) * scale_w + grow) for s_ in steps]
        notch = (length * 0.9, 0.0)  # a small notch in the middle of the tip
        right = [(a, b) for a, b in side if a < length * 0.97]
        return [at(a, b) for a, b in right] + [at(*notch)] + [at(a, -b) for a, b in reversed(right)]

    shade = 0.82 if back else 1.0

    def tone(c, k=1.0):
        return tuple(int(min(255, v * 255 * shade * k)) for v in c) + (alpha,)

    d.polygon(outline(0.0, 1.0, max(0.8, width * 0.06)), fill=tone(edge))
    d.polygon(outline(0.0, 1.0), fill=tone(deep))
    for k, begin in enumerate((0.18, 0.32, 0.46, 0.6)):  # paler towards the tip, in soft steps
        d.polygon(outline(begin, 0.96 - 0.025 * k), fill=tone(mix(deep, pale, 0.25 + 0.25 * k)))
    d.line([at(length * 0.05, 0), at(length * 0.6, 0)], fill=tone(deep, 0.85), width=max(1, round(f * 0.6)))
    d.line([at(length * 0.45, w * 0.3), at(length * 0.8, w * 0.45)], fill=(255, 255, 255, round(alpha * 0.55)), width=max(1, round(f * 0.8)))


def blossom_letters(F, canvas, cov, pal):
    """Solid letters in the word's blossom: deep at the foot, pale at the top, with a dark rim and soft shadow."""
    deep, pale, edge = pal
    up = np.clip(1 - F.yn, 0, 1)
    body = mix(np.asarray(deep), np.asarray(pale), (up ** 1.2 * 0.85)[..., None])
    vein = 0.94 + 0.06 * np.sin((F.px * 0.7 + F.py) / (F.u * 0.035))
    body = np.clip(body * vein[..., None], 0, 1)
    canvas.over(np.zeros(3), shadow(cov, F, 0.03, 0.05, 0.03, 0.4))
    colour, alpha = rim(F, cov, 0.02, np.asarray(edge), 0.95)
    canvas.over(colour, alpha)
    canvas.over(body, cov)


def scaled(F, letters, image, scales, anchor='centre'):
    """`image` with each letter scaled by its own factor about its centre (or its foot)."""
    index, count = letters
    if np.allclose(scales, 1):
        return image
    boxes = letter_boxes(F, letters)
    dx = np.zeros_like(F.px)
    dy = np.zeros_like(F.py)
    keep = np.zeros(F.px.shape, bool)
    for k, b in enumerate(boxes):
        s = max(1e-3, scales[k])
        cx = (b[0] + b[2]) / 2
        cy = (b[1] + b[3]) / 2 if anchor == 'centre' else b[3]
        half_w, half_h = (b[2] - b[0]) / 2 * s + 2, (b[3] - b[1]) * s + 2
        inside = (np.abs(F.px - cx) < half_w) & (np.abs(F.py - cy) < half_h) & ~keep
        dx[inside] = ((F.px - cx) * (1 - 1 / s))[inside]
        dy[inside] = ((F.py - cy) * (1 - 1 / s))[inside]
        keep |= inside
    out = warp(F, image, dx, dy)
    src = np.clip(np.round(F.px - dx).astype(int), 0, F.W - 1)
    owner = index[0][src]
    assigned = np.full(F.px.shape, -1)
    taken = np.zeros(F.px.shape, bool)
    for k, b in enumerate(boxes):
        s = max(1e-3, scales[k])
        cx = (b[0] + b[2]) / 2
        cy = (b[1] + b[3]) / 2 if anchor == 'centre' else b[3]
        inside = (np.abs(F.px - cx) < (b[2] - b[0]) / 2 * s + 2) & (np.abs(F.py - cy) < (b[3] - b[1]) * s + 2) & ~taken
        assigned[inside] = k
        taken |= inside
    mask = (owner == assigned) | ~taken
    return out * (mask[..., None] if out.ndim == 3 else mask)


# ---------------------------------------------------------------- wind: a ribbon of petals


@crafted('petals-wind-lettering', pad=1.0)
def petals_wind(F, canvas, t, intensity, letters):
    """A ribbon of petals streams in on a gust from the left; each letter flushes into colour behind a scalloped
    front as the stream passes it and sways downwind before springing upright; a few petals stay on the word."""
    index, count = letters
    u = F.u
    pal = palette(F)
    x0, y0, x1, y1 = F.box
    head = x0 - u * 0.6 + (x1 - x0 + u * 3.8) * sm(t, 0.0, 0.8)
    front_x = x0 - u * 0.25 + (x1 - x0 + u * 0.5) * sm(t, 0.04, 0.62)  # the colour front leads the ribbon's middle
    scallop = u * 0.09 * np.abs(np.sin(F.py / (u * 0.16)))
    shown = smooth(front_x + scallop - F.px, 0, 1.5)
    crest = np.exp(-((front_x + scallop - F.px) / (u * 0.025)) ** 2) * coverage(F.sdf) * (0.04 < t < 0.62)
    boxes = letter_boxes(F, letters)
    # each letter leans downwind as the stream passes it, then springs back
    sway = []
    for b in boxes:
        q = min(1.0, max(0.0, (front_x - b[0]) / (u * 1.1)))
        sway.append(0.6 * math.sin(math.pi * 2 * q) * (1 - q) ** 0.7 * (1 - sm(t, 0.72, 0.86)))  # the swing back past upright holds longer  # leans, overshoots back once, upright by the end
    base = per_pixel([b[3] for b in boxes], letters)
    lean = per_pixel(sway, letters)
    cov = coverage(F.sdf) * shown
    cov = warp(F, cov, (base - F.py) * lean, np.zeros_like(cov))
    blossom_letters(F, canvas, cov, pal)
    canvas.over(np.asarray(pal[1]), np.clip(crest, 0, 1) * 0.9)  # a light crest rides the colour front
    rng = np.random.default_rng(F.seed + 401)
    n = 8 + 3 * count
    rests = [(b[0] + (b[2] - b[0]) * rng.uniform(0.3, 0.7), b[1] + (b[3] - b[1]) * rng.uniform(0.0, 0.3)) for b in boxes[::2]]

    def draw(d, f):
        for i in range(n):
            lag = rng.uniform(0, 1)
            lane = rng.uniform(-1, 1)
            phase = rng.uniform(0, math.tau)
            size = u * rng.uniform(0.26, 0.36)
            x = head - lag * u * 3.6  # a long, thin band rather than a clump
            y = y0 - u * 0.12 + lane * u * 0.28 + u * 0.24 * math.sin(x / u * 1.6 + phase)  # over the cap line, dipping through
            gone = max(sm(x, x1 + u * 0.2, x1 + u * 0.9), sm(t, 0.8, 0.93))  # the band is gone before the end
            if x < x0 - u * 0.9 or gone >= 1:
                continue
            turn = math.cos(x / u * 3.0 + phase)
            petal(d, f, x, y, x / u * 1.4 + phase, size, size * 0.4, pal, turn, round(255 * (1 - gone)))
        for j, (rx, ry) in enumerate(rests):  # petals that settle on the word
            land = sm(front_x, rx, rx + u * 0.8)
            if land <= 0:
                continue
            x = rx - (1 - land) * u * 0.6
            y = ry - (1 - land) * u * 0.4 * math.sin(math.pi * land * 0.5 + j)
            petal(d, f, x, y, -0.6 + j * 1.3 + (1 - land) * 3, u * 0.28, u * 0.12, pal, math.cos((1 - land) * 4))

    rgb_, a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(a, F, 0.02, 0.04, 0.02, 0.35))
    canvas.over(rgb_, a)


# ---------------------------------------------------------------- breeze: petals pile up inside the letters


@crafted('petals-breeze-lettering', pad=1.0)
def petals_breeze(F, canvas, t, intensity, letters):
    """Petals flutter down on a light breeze, one after another into each letter, and the letter fills with
    blossom from its foot as they land, its surface a row of petal scallops; the last petal rests on top."""
    index, count = letters
    u = F.u
    pal = palette(F)
    boxes = letter_boxes(F, letters)
    each = 3
    lands = [[0.12 + 0.42 * k / max(1, count) + 0.1 * j for j in range(each)] for k in range(count)]
    level = [sum(sm(t, L - 0.015, L + 0.04) for L in row) / each for row in lands]
    y0 = per_pixel([b[1] for b in boxes], letters)
    y1 = per_pixel([b[3] for b in boxes], letters)
    up = (y1 - F.py) / np.maximum(1, y1 - y0)
    lvl = per_pixel(level, letters) * 1.12
    surface = lvl + 0.15 * np.abs(np.sin(F.px / (u * 0.14))) * np.clip(lvl * 4, 0, 1) - 0.15 * (lvl <= 0)  # petal scallops
    cov = coverage(F.sdf) * smooth(surface - up, 0, 0.03)
    bob = [1 + 0.06 * math.sin(math.pi * min(1.0, max(0.0, (t - row[-1]) / 0.1))) for row in lands]
    cov = scaled(F, letters, cov, bob, 'foot')
    blossom_letters(F, canvas, cov, pal)
    crest = np.exp(-((surface - up) / 0.03) ** 2) * coverage(F.sdf) * (per_pixel(level, letters) < 1)
    canvas.over(np.asarray(pal[1]), np.clip(crest, 0, 1) * 0.85)
    rng = np.random.default_rng(F.seed + 402)

    def draw(d, f):
        for k, b in enumerate(boxes):
            for j, L in enumerate(lands[k]):
                fall = (t - (L - 0.26)) / 0.26
                last = j == each - 1 and k % 2 == 0
                if fall <= 0 or (fall >= 1 and not last):
                    continue
                q = min(1.0, fall)
                cx = b[0] + (b[2] - b[0]) * rng.uniform(0.25, 0.75)
                target = b[3] - (b[3] - b[1]) * min(1.0, (j + 1) / each) if not last else b[1] - u * 0.04
                x = cx - u * 0.5 * (1 - q) + u * 0.12 * math.sin(q * 7 + j)
                y = target - u * 1.1 * (1 - q) ** 1.3
                size = u * (0.34 if last else rng.uniform(0.4, 0.5))
                petal(d, f, x, y, 0.6 + math.sin(q * 6 + k) * 0.9, size, size * 0.42, pal, math.cos(q * 5 + j))

    rgb_, a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(a, F, 0.02, 0.04, 0.02, 0.35))
    canvas.over(rgb_, a)


# ---------------------------------------------------------------- spiral: petals orbit, the letter opens like a flower


@crafted('petals-spiral-lettering', pad=1.0)
def petals_spiral(F, canvas, t, intensity, letters):
    """Petals whirl round each letter on a tightening spiral while the letter opens from its centre behind a
    five-lobed, flower-shaped front; as it locks the petals burst outward and the letter pops."""
    index, count = letters
    u = F.u
    pal = palette(F)
    boxes = letter_boxes(F, letters)
    q = relay(t, count, 0.0, 0.46, 0.32)
    cxs = per_pixel([(b[0] + b[2]) / 2 for b in boxes], letters)
    cys = per_pixel([(b[1] + b[3]) / 2 for b in boxes], letters)
    reach = per_pixel([math.hypot(b[2] - b[0], b[3] - b[1]) / 2 for b in boxes], letters)
    ang = np.arctan2(F.py - cys, F.px - cxs)
    radius = np.hypot(F.px - cxs, F.py - cys) / np.maximum(1, reach)
    open_ = per_pixel([sm(v, 0.12, 0.62) * 1.25 for v in q], letters)
    front = open_ * (0.86 + 0.14 * np.cos(5 * ang + per_pixel(range(count), letters)))
    cov = coverage(F.sdf) * smooth(front - radius, 0, 0.04)
    crest = np.exp(-((front - radius) / 0.05) ** 2) * coverage(F.sdf) * (open_ < 1.2)
    pops = [spring((v - 0.6) / 0.34, ((0, 1.0), (0.15, 0.9), (0.38, 1.13), (0.55, 1.12), (0.8, 0.98), (1, 1.0))) if v > 0.6 else 1.0 for v in q]  # squash, pop, hold
    cov = scaled(F, letters, cov, pops)
    blossom_letters(F, canvas, cov, pal)
    canvas.over(np.asarray(pal[1]), np.clip(crest, 0, 1) * cov * 0.9)  # the flower-shaped front, lighter

    def draw(d, f):
        for k, b in enumerate(boxes):
            v = q[k]
            if not 0 < v < 1:
                continue
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            rx, ry = max(u * 0.3, (b[2] - b[0]) * 0.62), (b[3] - b[1]) * 0.62  # each ring hugs its own letter
            for j in range(6):
                theta = j * math.tau / 6 + k
                if v < 0.62:  # orbit round the letter, never over it
                    r = 0.7 * (1 - v / 0.62) ** 1.4 + 1.0
                    a = theta + v * 3.2 * math.pi
                    alpha = 255
                else:  # burst outward and fade over several frames
                    b_ = (v - 0.62) / 0.38
                    r = 1.0 + 1.8 * b_ ** 0.6
                    a = theta + 0.62 * 3.2 * math.pi + b_ * 0.4
                    alpha = round(255 * (1 - b_) ** 1.3)
                x, y = cx + math.cos(a) * r * rx, cy + math.sin(a) * r * ry
                petal(d, f, x, y, a + math.pi * 0.6, u * 0.3, u * 0.13, pal, math.cos(a * 2 + j), alpha)

    rgb_, a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(a, F, 0.02, 0.04, 0.02, 0.35))
    canvas.over(rgb_, a)


# ---------------------------------------------------------------- grow: each letter is a bud that blooms


@crafted('petals-grow-lettering', pad=1.0)
def petals_grow(F, canvas, t, intensity, letters):
    """Each letter starts as a green bud that swells and splits; five petals unfurl into a flower and the letter
    rises out of its heart with a spring; the petals then drop away, leaving a small blossom on the letter."""
    index, count = letters
    u = F.u
    pal = palette(F)
    boxes = letter_boxes(F, letters)
    q = relay(t, count, 0.0, 0.46, 0.4)
    rise = [spring((v - 0.35) / 0.4, ((0, 0.0), (0.6, 1.1), (0.85, 0.97), (1, 1.0))) if v > 0.35 else 0.0 for v in q]
    cov = scaled(F, letters, coverage(F.sdf), [max(1e-3, r) for r in rise])
    cov = cov * per_pixel([1.0 if r > 0 else 0.0 for r in rise], letters)

    def flowers(d, f, front):
        for k, b in enumerate(boxes):
            v = q[k]
            if v <= 0:
                continue
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            bloom = sm(v, 0.18, 0.5)
            drop = sm(v, 0.6, 0.88)
            if not front and drop < 1:
                for j in range(5):  # the flower behind the letter
                    a = -math.pi / 2 + j * math.tau / 5 + (1 - bloom) * 0.8
                    length = u * 0.56 * bloom * (1 - drop)  # the flower closes up once its letter has risen
                    petal(d, f, cx, cy, a - drop * 0.6, length, length * 0.34, pal, 1.0)
                if drop < 0.85:  # a dark heart
                    r = u * 0.11 * bloom * (1 - drop)
                    d.ellipse(((cx - r) * f, (cy - r) * f, (cx + r) * f, (cy + r) * f), fill=tuple(int(v * 255) for v in pal[2]) + (255,))
                    for m in range(5):  # golden stamens round the heart
                        sx, sy = cx + math.cos(m * 1.257) * r * 0.75, cy + math.sin(m * 1.257) * r * 0.75
                        rr = r * 0.32
                        d.ellipse(((sx - rr) * f, (sy - rr) * f, (sx + rr) * f, (sy + rr) * f), fill=(255, 214, 70, 255))
            if not front and v < 0.4:  # the bud
                s = u * 0.38 * sm(v, 0.0, 0.16) * (1 - sm(v, 0.3, 0.4))
                if s > 0.5:
                    c = tuple(int(x * 255) for x in LEAF)
                    d.ellipse(((cx - s * 0.55) * f, (cy - s) * f, (cx + s * 0.55) * f, (cy + s * 0.6) * f), fill=(*c, 255))
                    split = sm(v, 0.14, 0.3)
                    petal(d, f, cx, cy + s * 0.3, -math.pi / 2, s * (0.9 + split * 0.4), s * 0.45 * (0.6 + split), pal)
            if front and v > 0.85 and k % 2 == 0:  # a small blossom stays on the letter's shoulder
                g = sm(v, 0.85, 1.0)
                for j in range(5):
                    a = -math.pi / 2 + j * math.tau / 5
                    petal(d, f, b[2] - u * 0.04, b[1] + u * 0.06, a, u * 0.15 * g, u * 0.08 * g, pal)

    back_rgb, back_a = supersampled(F, lambda d, f: flowers(d, f, False))
    canvas.over(np.zeros(3), shadow(back_a, F, 0.02, 0.04, 0.02, 0.3))
    canvas.over(back_rgb, back_a)
    blossom_letters(F, canvas, cov, pal)
    front_rgb, front_a = supersampled(F, lambda d, f: flowers(d, f, True))
    canvas.over(front_rgb, front_a)
