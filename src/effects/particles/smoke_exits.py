"""Smoke exits: the word smoulders for a beat, then comes apart into smoke, each exit with its own kind of smoke.

The word's ink (its soft drop shadow included) is split into patches. After a short beat that belongs to the exit
(billow swells and greys, plume smoulders patch by patch from the top, vortex twists, wisp leans into the wind,
evaporate pales and mists over) the patches leave in the exit's own order, and each one becomes smoke: soft, lobed
clouds shaded from a light top to a dark underside, so they read on dark and light paintings alike. Plume, wisp and
vortex draw each patch's smoke as a chain of puffs along one path, so columns, tendrils and the funnel are
continuous; billow and evaporate scatter a cluster. Puffs travel by the time since their patch left, so the first
away are furthest ahead; they grow as they go and thin out before the end. Every frame is a pure function of
progress."""

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter

from effects.particles.cache import sprite_key

KINDS = {'fan': 'billow', 'radial': 'evaporate', 'down': 'plume', 'spiral': 'vortex', 'left': 'wisp'}
BREAK_AT = 0.14  # the first patch leaves here; the last leaves at LAST_AT
LAST_AT = 0.62
GONE_BY = 0.98  # every patch's smoke has thinned to nothing by here
LIFT_FOR = 0.1  # a patch lifts away from the word for this long before it turns to smoke
PUFF_BASE = 48  # radius the shaded puffs are drawn at, then resized
# (dark underside, light top) of the smoke: cool mid greys, so it reads on cream as well as on navy
PALETTES = {
    'billow': ((90, 96, 114), (246, 248, 252)),
    'plume': ((78, 84, 104), (236, 238, 246)),
    'vortex': ((64, 68, 86), (226, 228, 238)),
    'wisp': ((92, 98, 116), (252, 252, 255)),
    'evaporate': ((104, 110, 128), (246, 248, 252)),
}
# per kind: puffs per patch, their spacing along the flight (a chain when > 0), base radius in word heights,
# how far a cluster is scattered about its patch, the puff's height to width, and how long its smoke lives
CLUSTERS = {
    'billow': (4, 0.0, 0.22, 0.45, 1.0, 0.75),
    'plume': (12, 0.014, 0.11, 0.0, 1.0, 0.66),
    'vortex': (7, 0.02, 0.17, 0.0, 1.0, 0.72),
    'wisp': (14, 0.013, 0.075, 0.0, 0.36, 0.66),
    'evaporate': (3, 0.0, 0.16, 0.4, 2.0, 0.6),
}


def smoother(q):
    q = max(0.0, min(1.0, q))
    return q * q * q * (q * (q * 6 - 15) + 10)


@lru_cache(maxsize=256)
def _puff(variant, palette, textured=True):
    """A lobed cloud of radius PUFF_BASE: a few overlapping domes, lit from the upper left."""
    r = PUFF_BASE
    n = 2 * r + 2
    rng = np.random.default_rng(variant * 7919 + 11)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) - r
    height = np.zeros((n, n), np.float32)
    for _ in range(3 + variant % 3):
        angle, dist, rad = rng.uniform(0, math.tau), rng.uniform(0, 0.42) * r, rng.uniform(0.5, 0.78) * r
        d2 = (xx - math.cos(angle) * dist) ** 2 + (yy - math.sin(angle) * dist) ** 2
        height = np.maximum(height, np.sqrt(np.clip(rad * rad - d2, 0, None)))
    alpha = np.clip(height / (r * 0.4), 0, 1)
    alpha = alpha * alpha * (3 - 2 * alpha)
    from scipy.ndimage import gaussian_filter
    grain = gaussian_filter(rng.random((n, n)).astype(np.float32), r * 0.12)
    grain = (grain - grain.mean()) / max(1e-6, grain.std())
    fine = gaussian_filter(rng.random((n, n)).astype(np.float32), r * 0.04)
    fine = (fine - fine.mean()) / max(1e-6, fine.std())
    # wispy, holed vapour rather than a solid cartoon blob: soft streaks, thin spots and torn edges
    if textured:
        alpha = alpha * np.clip(0.62 + 0.32 * grain + 0.14 * fine, 0, 1) * np.clip(0.4 + alpha * 1.2 + 0.25 * grain, 0, 1)
    gy, gx = np.gradient(height)
    nz = r * 0.22
    shade = (0.45 * gx + 0.78 * gy + 0.44 * nz) / np.sqrt(gx * gx + gy * gy + nz * nz)
    shade = np.clip(shade, 0, 1) ** 1.6  # a lit crown, a deep belly
    dark, light = (np.array(c, np.float32) for c in palette)
    rgb = dark + (light - dark) * shade[..., None]
    return Image.fromarray(np.dstack([rgb, alpha * 255]).clip(0, 255).astype('uint8'), 'RGBA')


@lru_cache(maxsize=64)
def _alpha_table(level):
    return bytes(round(v * level / 32) for v in range(256))


def _piece(variant, palette, radius, opacity, squash=1.0, textured=True):
    """The puff at `radius`, `squash` times as tall as wide, with `opacity` (0-1) folded into its alpha."""
    w = max(2, round(radius * 2))
    h = max(2, round(radius * 2 * squash))
    piece = _puff(variant, palette, textured).resize((w, h), Image.Resampling.BILINEAR)
    level = round(opacity * 32)
    if level < 32:
        piece.putalpha(piece.getchannel('A').point(_alpha_table(level)))
    return piece


def _patches(sprite, seed, size):
    """Patch seeds on the letters, and for every pixel of the word (shadow included) the index of its patch."""
    alpha = np.asarray(sprite.getchannel('A'))
    ys, xs = np.nonzero(alpha > 0)
    if len(xs) == 0:
        return None
    sy, sx = np.nonzero(alpha > 120)
    if len(sx) == 0:
        sy, sx = ys, xs
    rng = np.random.default_rng(seed)
    count = int(min(140, max(8, len(sx) / (size * size * 0.8))))
    pick = rng.choice(len(sx), size=min(count, len(sx)), replace=False)
    seeds = np.stack([sx[pick], sy[pick]], axis=1).astype(np.float32)
    owner = np.empty(len(xs), int)
    for start in range(0, len(xs), 12000):
        px = np.stack([xs[start : start + 12000], ys[start : start + 12000]], axis=1).astype(np.float32)
        owner[start : start + 12000] = np.argmin(((px[:, None, :] - seeds[None, :, :]) ** 2).sum(-1), axis=1)
    return seeds, owner, ys, xs


def _order(kind, seeds, width, height, rng):
    """When each patch leaves (0-1 within the break-up), in the exit's own order."""
    n = len(seeds)
    jitter = rng.random(n) * (0.5 if kind == 'plume' else 0.3)  # a word's top row would otherwise go all at once
    x, y = seeds[:, 0] / max(1, width), seeds[:, 1] / max(1, height)
    if kind == 'billow':
        base = x * 0.75 + (1 - y) * 0.25  # letter after letter turns to smoke, each from its foot up
    elif kind == 'plume':
        base = y * 0.7 + x * 0.3  # consumed from the top, like incense, the left end a little ahead
    elif kind == 'vortex':
        base = (np.arctan2(y - 0.5, x - 0.5) / math.tau + 0.5 + rng.random()) % 1  # a sweep round the word
    elif kind == 'wisp':
        base = 1 - x  # the wind strips the windward (right) end first
    else:
        base = rng.random(n)  # evaporate: everywhere at once
    base = (base - base.min()) / max(1e-6, base.max() - base.min())
    return np.clip(base * 0.7 + jitter, 0, 1)


def _word_colour(sprite):
    pixels = np.asarray(sprite)
    solid = pixels[..., 3] > 220
    return tuple(int(v) for v in pixels[solid][:, :3].mean(axis=0)) if solid.any() else (235, 235, 235)


def _palette(kind, ink):
    dark, light = PALETTES[kind]
    tinted = lambda c, w: tuple(round(v + (i - v) * w) for v, i in zip(c, ink))
    if kind == 'vortex':  # the vortex carries the word's own colour round, not neutral grey
        return tinted(dark, 0.35), tinted(light, 0.45)
    return tinted(dark, 0.08), tinted(light, 0.12)


def _hollowing(sprite, ys, xs, seeds, seed):
    """Evaporate's order: every letter pixel's time to go, deepest in the stroke first, so letters thin to
    outlines; and each patch's start, which is when its seed pixel goes."""
    from scipy.ndimage import distance_transform_edt, gaussian_filter
    alpha = np.asarray(sprite.getchannel('A'))
    depth = distance_transform_edt(alpha > 120)
    deepest = max(1.0, float(depth.max()))
    noise = gaussian_filter(np.random.default_rng(seed + 5).random(alpha.shape), max(1.0, sprite.height * 0.03))
    noise = (noise - noise.min()) / max(1e-6, np.ptp(noise))
    # deepest first within a letter, letters in a relay left to right, a ragged front
    across = np.arange(alpha.shape[1])[None, :] / max(1, alpha.shape[1])
    # a wavy front: the hollowing edge wanders a few pixels either way as it eats inward, like heat
    yy = np.arange(alpha.shape[0])[:, None] / max(1.0, sprite.height * 0.07)
    wave = 0.5 + 0.5 * np.sin(yy * math.tau + np.arange(alpha.shape[1])[None, :] / max(1.0, sprite.height * 0.11))
    last = 0.74  # the outlines are the last to go, later than the other exits' patches
    when = BREAK_AT + (last - BREAK_AT) * ((1 - depth / deepest) * 0.5 + across * 0.3 + noise * 0.1 + wave * 0.1)
    when = np.where(alpha > 120, when, 1.0)  # the soft shadow is faded out separately
    order = (when[seeds[:, 1].astype(int), seeds[:, 0].astype(int)] - BREAK_AT) / (LAST_AT - BREAK_AT)
    return when[ys, xs].astype(np.float32), np.clip(order, 0, 1)


def _remaining_word(sprite, kind, amount, left, ys, xs, starts, owner, direction):
    """What is left of the word, with the exit's own beat worked into it. Returns (image, dx, dy) to place it."""
    word = np.asarray(sprite).copy()
    rgb = word[ys, xs, :3].astype(np.float32)
    grey = np.array((176, 176, 182), np.float32)
    if kind == 'billow':  # the letters stay crisp and crumble upward into the cloud; only a faint char creeps in
        rgb += (np.array((120, 112, 118), np.float32) - rgb) * 0.2 * smoother(amount / 0.4)
    elif kind == 'plume':  # a patch smoulders orange, then flares yellow-white just before it goes up in smoke
        heat = np.clip(1 - (starts[owner] - amount) / 0.2, 0, 1)[:, None]
        rgb += (np.array((255, 118, 36), np.float32) - rgb) * heat * 0.9
        rgb += (np.array((255, 244, 200), np.float32) - rgb) * heat**2 * 0.9
        rgb += (np.array((40, 32, 36), np.float32) - rgb) * 0.25 * smoother(amount / 0.5)
    elif kind == 'vortex':
        rgb += (grey - rgb) * 0.4 * smoother(amount / 0.4)
    elif kind == 'wisp':
        rgb += (np.array((214, 214, 220), np.float32) - rgb) * 0.35 * smoother(amount / 0.4)
    else:  # evaporate: the letters pale as they thin, and the soft shadow fades under them
        rgb += (np.array((236, 236, 242), np.float32) - rgb) * 0.45 * smoother(amount / 0.5)
        soft = word[ys, xs, 3] <= 120
        word[ys[soft], xs[soft], 3] = (word[ys[soft], xs[soft], 3] * (1 - smoother((amount - 0.25) / 0.4))).astype(np.uint8)
    word[ys, xs, :3] = rgb.clip(0, 255).astype(np.uint8)
    word[ys[left], xs[left], 3] = 0
    h, w = sprite.height, sprite.width
    pad = round(h * 0.35)
    canvas = Image.new('RGBA', (w + 2 * pad, h + 2 * pad))
    chunks = []
    if kind in ('billow', 'vortex', 'wisp'):  # a patch about to go lifts off the word first, as a chunk
        gaps = starts - amount
        for i in np.nonzero((gaps > 0) & (gaps < LIFT_FOR))[0]:
            mine = (owner == i) & ~left
            if not mine.any():
                continue
            s = float(smoother(1 - gaps[i] / LIFT_FOR))
            py, px = ys[mine], xs[mine]
            top, bottom, lft, rgt = py.min(), py.max() + 1, px.min(), px.max() + 1
            piece = np.zeros((bottom - top, rgt - lft, 4), np.uint8)
            piece[py - top, px - lft] = word[py, px]
            word[py, px, 3] = 0
            image = Image.fromarray(piece, 'RGBA')
            if kind == 'billow':  # the letter stretches up into a smeared wisp, softens and greys before it boils off
                tall, thin = 1 + 1.3 * s, 1 - 0.25 * s
                image = image.resize((max(1, round(image.width * thin)), max(1, round(image.height * tall))), Image.Resampling.BILINEAR)
                if s > 0.05:  # a smear trail: fading copies of the piece drawn above it
                    rise = round(h * 0.18 * s)
                    smear = Image.new('RGBA', (image.width, image.height + rise))
                    for n_ in range(4, 0, -1):
                        ghost = image.copy()
                        ghost.putalpha(ghost.getchannel('A').point(lambda v, k=n_: round(v * (1 - k / 5) * 0.6)))
                        smear.alpha_composite(ghost, (0, rise - round(rise * n_ / 4)))
                    smear.alpha_composite(image, (0, rise))
                    image = smear
                blur = h * 0.03 * s
                if blur > 0.4:
                    margin = int(blur * 3) + 1
                    padded = Image.new('RGBA', (image.width + 2 * margin, image.height + 2 * margin))
                    padded.alpha_composite(image, (margin, margin))
                    image = padded.filter(ImageFilter.GaussianBlur(blur))
                arr = np.asarray(image).astype(np.float32)
                arr[..., :3] += (np.array((150, 152, 164), np.float32) - arr[..., :3]) * 0.7 * s
                image = Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA')
                dx, dy = -(image.width - (rgt - lft)) / 2, -(image.height - (bottom - top)) / 2 - h * 0.12 * s
            elif kind == 'vortex':
                image = image.rotate(-direction * 25 * s, Image.Resampling.BICUBIC, expand=True)
                dx, dy = direction * h * 0.25 * s, -h * 0.16 * s
            else:
                dx, dy = -h * 0.2 * s, -h * 0.03 * s
            chunks.append((image, round(pad + lft + dx), round(pad + top + dy)))
    remaining = Image.fromarray(word, 'RGBA')
    if kind == 'evaporate':  # heat haze: the letters shimmer, each row swaying by its own phase, more as they warm
        sway = h * (0.015 + 0.03 * smoother((amount - 0.04) / 0.3)) * smoother(amount / 0.06)
        if sway >= 0.3:
            from scipy.ndimage import map_coordinates
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            # two or three slow waves per letter height, drifting upward like rising heat
            wave = np.sin(yy / max(1.0, h * 0.12) - amount * 18 + xx / max(1.0, h * 0.9))
            lift = np.sin(xx / max(1.0, h * 0.2) + amount * 11) * sway * 0.35
            arr = np.asarray(remaining).astype(np.float32)
            warped = np.stack([map_coordinates(arr[..., c], (yy + lift, xx + wave * sway), order=1, mode='constant')
                               for c in range(4)], -1)
            remaining = Image.fromarray(warped.clip(0, 255).astype(np.uint8), 'RGBA')
    canvas.alpha_composite(remaining, (pad, pad))
    for piece, px_, py_ in chunks:
        canvas.alpha_composite(piece, (px_, py_))
    cx, cy = canvas.width / 2, canvas.height / 2
    if kind == 'billow':  # a swell as the smoke fills the letters
        s = 1 + 0.035 * smoother((amount - 0.06) / 0.22)
        matrix = (1 / s, 0, cx - cx / s, 0, 1 / s, cy - cy / s)
    elif kind == 'vortex':  # the vortex turns the word a little before it takes it
        a = math.radians(7) * direction * smoother((amount - 0.08) / 0.6)
        c, s = math.cos(a), math.sin(a)
        matrix = (c, s, cx - c * cx - s * cy, -s, c, cy + s * cx - c * cy)
    elif kind == 'wisp':  # the word leans into the wind and slides a little downwind
        k = -0.24 * smoother((amount - 0.07) / 0.55)
        matrix = (1, -k, k * cy + h * 0.1 * smoother((amount - 0.1) / 0.6), 0, 1, 0)
    else:
        return canvas, -pad, -pad
    canvas = canvas.transform(canvas.size, Image.Transform.AFFINE, matrix, resample=Image.Resampling.BICUBIC)
    return canvas, -pad, -pad


def _flight(kind, e, r, sx, sy, w, h, direction, helix):
    """A puff's offset from its patch and its size factor, by `e` (the time since its patch left)."""
    if kind == 'billow':  # fat lobes boil up out of the letters and roll outward and upward in a fan
        roll = e * 5 + r[2] * math.tau
        back = 0.7 + 0.6 * r[1]  # the back of the cloud rises higher and grows bigger than the front
        dx = (sx - w / 2) / max(w, h) * h * 1.6 * e + math.cos(roll) * h * 0.1 * e
        dy = -h * (0.5 * e + 2.4 * e * e) * back + math.sin(roll) * h * 0.08 * e
        return dx, dy, (1 + 2.2 * e) * (0.75 + 0.4 * back)
    if kind == 'plume':  # a column rising from each letter that leans its own way, snakes and widens as it climbs
        climb = e * (0.85 + 0.3 * r[1])
        lean = (sx / max(1, w) - 0.5) * 0.9 * h * e  # columns fan out across a long word
        dx = lean + math.sin(e * 8 + sx * 0.02 + r[2] * 2) * h * (0.12 + 0.4 * e) + (r[3] - 0.5) * h * 0.1 * e
        return dx, -h * 3.0 * climb, 1 + 2.0 * e
    if kind == 'vortex':  # the smoke rides three spiral arms that tighten steadily into one eye
        theta = helix + int(r[1] * 3) * math.tau / 3 + direction * e * 11
        radius = h * 0.04 + h * 0.9 * max(0.0, 1 - e / 0.42) ** 1.4  # falls fast, so the arm stays an open spiral
        hx = w / 2 + math.cos(theta) * radius * 1.1
        hy = h / 2 + math.sin(theta) * radius * 0.7 - h * 1.0 * e
        arrive = smoother(e / 0.06)  # on the arm at once, so the spiral reads early
        return (hx - sx) * arrive, (hy - sy) * arrive, (1 + 1.2 * e) * max(0.35, 1 - 0.9 * e)
    if kind == 'wisp':  # long flat streaks pulled off downwind, gathering speed and curling as they go
        dx = -(w * 1.6 + h * 3.2) * (0.7 + 0.6 * r[1]) * e * (0.5 + 1.2 * e)
        dy = -h * 0.25 * e + math.sin(e * 10 + r[2] * math.tau) * h * (0.05 + 0.16 * e) + (r[3] - 0.5) * h * 0.12 * e
        return dx, dy, 1 + 2.6 * e
    # evaporate: tall shimmering veils lift well above the word, drifting apart as they thin
    dx = (r[1] - 0.5) * h * 0.6 * e + math.sin(e * 6 + r[2] * math.tau) * h * 0.05
    return dx, -h * (1.6 * e + 1.0 * e * e), 1 + 1.6 * e


def paint_smoke_exit(layer, sprite, x, y, amount, effect, seed, intensity=1.0, cache=None):
    """Draw the word at exit progress `amount` (0 the plain word, 1 gone)."""
    kind = KINDS.get(effect.trajectory, 'billow')
    h, w = sprite.height, sprite.width
    count, spacing, base_radius, scatter, squash, life_span = CLUSTERS[kind]
    key = ('smoke-exit-v14', sprite_key(sprite), seed, kind)
    if cache is not None and key in cache:
        parts = cache[key]
    else:
        patches = _patches(sprite, seed, h * (0.26 if kind in ('billow', 'evaporate') else 0.2 if kind != 'wisp' else 0.17))
        if patches is None:
            return
        seeds, owner, ys, xs = patches
        rng = np.random.default_rng(seed * 31 + 7)
        when = None
        if kind == 'evaporate':
            when, order = _hollowing(sprite, ys, xs, seeds, seed)
        else:
            order = _order(kind, seeds, w, h, rng)
        randoms = rng.random((len(seeds), count, 6))
        if spacing:  # a chain shares one path; its members differ only in how far along it they are
            randoms[:, :, :4] = randoms[:, :1, :4]
            randoms[:, :, 5] = randoms[:, :1, 5]
        parts = (seeds, owner, ys, xs, order, randoms, _word_colour(sprite), when)
        if cache is not None:
            cache[key] = parts
    seeds, owner, ys, xs, order, randoms, ink, when = parts
    direction = 1 if seed % 2 else -1
    helix = (seed % 7) * 0.9
    starts = BREAK_AT + (LAST_AT - BREAK_AT) * order
    left = (amount >= when) if when is not None else (amount >= starts)[owner]
    palette = _palette(kind, ink)
    size_gain = min(1.4, max(0.7, math.sqrt(max(0.1, intensity))))
    smoke = Image.new('RGBA', layer.size)
    for i, (sx, sy) in enumerate(seeds):
        if amount < starts[i]:
            continue
        life = min(life_span, GONE_BY - starts[i])  # its smoke is gone before the end, however late it left
        age = amount - starts[i]
        fade = 1 - smoother((age - 0.2 * life) / (0.8 * life))  # the whole chain thins with its patch's age
        if fade <= 0.02:
            continue
        for j in range(count):
            e = age - j * spacing
            if e <= 0:
                continue
            r = randoms[i, j]
            dx, dy, grow = _flight(kind, e, r, sx, sy, w, h, direction, helix)
            opacity = min(1.0, e / 0.05) * fade
            if kind == 'vortex':  # the far side of the spiral half seen, so the depth reads
                theta = helix + int(r[1] * 3) * math.tau / 3 + direction * e * 11
                opacity *= 1 - 0.45 * max(0.0, -math.sin(theta)) * smoother(e / 0.14)
            elif kind == 'plume':  # the column thins toward its top and swells into a soft mass there
                opacity *= 1 - 0.6 * min(1.0, e / life)
                grow *= 1 + 0.6 * min(1.0, e / life)
            opacity *= {'billow': 0.66, 'plume': 0.76, 'vortex': 0.68, 'wisp': 0.8, 'evaporate': 0.5}[kind]
            if kind == 'wisp':  # density tapers from the head of the streak back along its tail, never a lump
                opacity *= 0.55 + 0.45 * j / max(1, count - 1)
            if opacity <= 0.02:
                continue
            ox, oy = (r[4] - 0.5) * h * scatter, (r[5] - 0.5) * h * scatter * 0.6
            vary = 0.55 + 0.9 * ((r[0] + j * 0.37) % 1)  # members of a chain differ in size over nearly 3:1
            if kind == 'wisp' and j >= count - 4:  # fine filaments trail the streak
                vary *= 0.45
            radius = h * base_radius * vary * grow * size_gain
            shade = palette
            if kind == 'billow' and e < 0.16:  # just born from the letter: still tinted with the word's colour
                level = round(4 * (1 - e / 0.16)) / 4
                shade = tuple(tuple(round(c + (i_ - c) * 0.3 * level) for c, i_ in zip(tone, ink)) for tone in palette)
            piece = _piece(int(r[3] * 12) + (i + j) % 3 * 12, shade, radius, opacity, squash, kind != 'wisp')  # wisp keeps its smooth streaks
            smoke.alpha_composite(piece, (round(x + sx + ox + dx - piece.width / 2), round(y + sy + oy + dy - piece.height / 2)))
    if kind == 'wisp':  # a few torn scraps of the letters ride the gust ahead of the streak, tumbling
        for i, (sx, sy) in enumerate(seeds):
            if i % 3 or amount < starts[i]:
                continue
            e = amount - starts[i]
            if e > 0.4:
                continue
            r = randoms[i, 0]
            half = max(2, round(h * 0.06))
            scrap = sprite.crop((int(sx) - half, int(sy) - half, int(sx) + half, int(sy) + half))
            if scrap.getbbox() is None:
                continue
            dx = -(w * 1.6 + h * 3.2) * 1.35 * e * (0.5 + 1.2 * e)
            dy = -h * 0.35 * e + math.sin(e * 12 + r[2] * math.tau) * h * 0.12 * e
            scale = max(0.2, 1 - e * 1.6)
            scrap = scrap.resize((max(1, round(scrap.width * scale)), max(1, round(scrap.height * scale))), Image.Resampling.BILINEAR)
            scrap = scrap.rotate(e * 720 * (r[1] - 0.5), Image.Resampling.BICUBIC, expand=True)
            fade = 1 - smoother((e - 0.2) / 0.2)
            if fade < 1:
                scrap.putalpha(scrap.getchannel('A').point(_alpha_table(round(fade * 32))))
            smoke.alpha_composite(scrap, (round(x + sx + dx - scrap.width / 2), round(y + sy + dy - scrap.height / 2)))
    # a soft haze under the puffs dissolves their scalloped outlines into a smooth outer margin
    box = smoke.getbbox()
    if box:
        margin = round(h * 0.12)
        box = (max(0, box[0] - margin), max(0, box[1] - margin), min(smoke.width, box[2] + margin), min(smoke.height, box[3] + margin))
        haze = smoke.crop(box).filter(ImageFilter.GaussianBlur(h * 0.05))
        haze.putalpha(haze.getchannel('A').point(_alpha_table(18)))
        layer.alpha_composite(haze, box[:2])
    layer.alpha_composite(smoke)
    word, ox, oy = _remaining_word(sprite, kind, amount, left, ys, xs, starts, owner, direction)
    layer.alpha_composite(word, (round(x) + ox, round(y) + oy))
