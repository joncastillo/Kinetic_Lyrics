"""Petal exits: the word blushes, then comes apart into real petals, each exit with its own wind.

The word is divided into petal-sized patches (a Voronoi split of its ink). After a short blush-and-swell beat the
patches detach in the exit's own order; each patch leaves the word as a petal (a pointed, veined teardrop with a
darker rim, so it reads on dark and light grounds) that flips as it tumbles and shrinks away before the end, so
nothing is left behind. Every frame is a pure function of progress."""

import math
import random
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from effects.particles.cache import sprite_key

PETAL_COLOURS = ((255, 120, 160), (214, 46, 96), (255, 168, 196), (236, 84, 128), (196, 34, 84), (255, 196, 210))


@lru_cache(maxsize=1024)
def petal(size, colour_index, veined=True, ink=None, step=4):
    """A petal `size` px long, pointing up: one of three shapes (a teardrop, a notched cherry petal, a slender
    one), shaded from a deeper base to a light tip, with a darker rim and a centre vein."""
    s = max(4, int(size))
    shape = colour_index % 3
    w = max(3, int(s * (0.62, 0.78, 0.42)[shape]))
    colour = PETAL_COLOURS[colour_index % len(PETAL_COLOURS)]
    if ink is not None and step < 4:  # still partly the letter: its colour, then blush white, then the petal's
        blushed = tuple(round(i + (b - i) * 0.45) for i, b in zip(ink, (255, 150, 190)))
        white = (252, 236, 242)
        f = step / 4
        if f < 0.5:
            colour = tuple(round(a + (b - a) * f * 2) for a, b in zip(blushed, white))
        else:
            colour = tuple(round(a + (b - a) * (f - 0.5) * 2) for a, b in zip(white, colour))
    rim = tuple(round(c * 0.7) for c in colour)

    def half_width(v):  # v: 0 at the tip (top), 1 at the base
        if shape == 1:  # a cherry petal: broad and round, notched at the tip
            return (w / 2) * math.sin(math.pi * (0.15 + 0.85 * v)) ** 0.6
        return (w / 2) * math.sin(math.pi * v) ** (0.75 if shape == 0 else 0.9)

    left = [(1 + w / 2 - half_width(v), 1 + s * v) for v in (k / 24 for k in range(25))]
    right = [(1 + w / 2 + half_width(v), 1 + s * v) for v in (1 - k / 24 for k in range(25))]
    outline = left + right
    if shape == 1:  # the notch at the tip
        outline = [(1 + w / 2, 1 + s * 0.12)] + outline
    mask = Image.new('L', (w + 2, s + 2))
    ImageDraw.Draw(mask).polygon(outline, fill=255)
    # shading: deeper at the base, light at the tip
    ramp = np.linspace(0, 1, s + 2)[:, None]
    base = np.array([c * 0.78 for c in colour], np.float32)
    tip = np.array([c + (w - c) * 0.38 for c, w in zip(colour, (255, 226, 232))], np.float32)  # a warm blush tip
    rgb = tip[None, None, :] + (base - tip)[None, None, :] * ramp[..., None] ** 1.3
    rgb = np.broadcast_to(rgb, (s + 2, w + 2, 3))
    image = Image.fromarray(np.dstack([rgb, np.asarray(mask, np.float32)]).clip(0, 255).astype('uint8'), 'RGBA')
    draw = ImageDraw.Draw(image)
    draw.line(outline + outline[:1], fill=(*rim, 255), width=1)
    if veined and s >= 10:
        draw.line(
            (1 + w / 2, 1 + s * (0.22 if shape == 1 else 0.15), 1 + w / 2, 1 + s * 0.85), fill=(*rim, 190), width=1
        )
    return image


def _layout(sprite, seed):
    """Petal seeds over the word's ink, and for every ink pixel the index of its patch (nearest seed)."""
    alpha = np.asarray(sprite.getchannel('A'))
    ink = alpha > 0  # every pixel, the soft drop shadow included, belongs to a patch
    ys, xs = np.nonzero(ink)
    if len(xs) == 0:
        return np.zeros((0, 2)), ink, np.zeros(0, int), ys, xs
    size = max(7.0, sprite.height * 0.2)
    rng = np.random.default_rng(seed)
    count = int(min(140, max(8, len(xs) / (size * size * 0.9))))
    pick = rng.choice(len(xs), size=count, replace=False)
    seeds = np.stack([xs[pick], ys[pick]], axis=1).astype(np.float32)
    owner = np.empty(len(xs), int)
    for start in range(0, len(xs), 40000):  # nearest seed, in chunks to keep memory small
        px = np.stack([xs[start : start + 40000], ys[start : start + 40000]], axis=1).astype(np.float32)
        owner[start : start + 40000] = np.argmin(((px[:, None, :] - seeds[None, :, :]) ** 2).sum(-1), axis=1)
    return seeds, ink, owner, ys, xs


def _order(kind, seeds, width, height, rng):
    """When each patch leaves (0-1 within the break-up), in the exit's own order."""
    n = len(seeds)
    jitter = np.array([rng.random() for _ in range(n)]) * 0.42
    x, y = seeds[:, 0] / max(1, width), seeds[:, 1] / max(1, height)
    if kind == 'fall':
        base = y  # from the top of the word down
    elif kind == 'gust':
        base = x  # the wind peels the word from its leading (left) end, so the stream stretches out ahead
    elif kind == 'scatter':
        base = np.hypot(x - 0.5, (y - 0.5) * 0.5) * 1.6  # from the middle outward
    elif kind == 'whirl':
        base = np.arctan2(y - 0.5, x - 0.5) / math.tau + 0.5  # round the word
    else:  # flutter: everywhere at once, lightly
        base = np.array([rng.random() for _ in range(n)])
    base = (base - base.min()) / max(1e-6, base.max() - base.min())
    return np.clip(base * 0.62 + jitter, 0, 1)


def smoother_step(q):
    q = max(0.0, min(1.0, q))
    return q * q * q * (q * (q * 6 - 15) + 10)


KINDS = {'down': 'fall', 'fan': 'flutter', 'left': 'gust', 'radial': 'scatter', 'spiral': 'whirl'}


def paint_petal_exit(layer, sprite, x, y, amount, effect, seed, intensity=1.0, cache=None):
    """Draw the word at exit progress `amount` (0 the plain word, 1 gone)."""
    kind = KINDS.get(effect.trajectory, 'fall')
    key = ('petal-exit', sprite_key(sprite), seed)
    if cache is not None and key in cache:
        seeds, ink, owner, ys, xs, order = cache[key]
    else:
        seeds, ink, owner, ys, xs = _layout(sprite, seed)
        order = _order(kind, seeds, sprite.width, sprite.height, random.Random(seed))
        if cache is not None:
            cache[key] = (seeds, ink, owner, ys, xs, order)
    if len(seeds) == 0:
        return
    h = sprite.height
    blush = min(1.0, amount / 0.16)  # the beat: the word blushes pink and swells a touch before it comes apart
    swell = 1 + 0.02 * math.sin(math.pi * min(1.0, amount / 0.2))
    if kind == 'scatter':  # a quick swell at the centre triggers the burst
        swell += 0.13 * math.sin(math.pi * max(0.0, min(1.0, (amount - 0.16) / 0.09)))
    breakup = max(0.0, (amount - 0.18) / 0.6)  # patches leave between 0.14 and 0.76
    leave_at = order  # within the break-up
    gone = breakup >= leave_at  # per patch
    # What is left of the word: its patches that have not yet left, blushing.
    keep = ~gone[owner]
    word = np.asarray(sprite).copy()
    tint = np.array((255, 150, 190), np.float32)
    rgb = word[ys, xs, :3].astype(np.float32)
    word[ys, xs, :3] = (rgb + (tint - rgb) * 0.45 * blush).astype(np.uint8)
    word[ys[~keep], xs[~keep], 3] = 0
    left_word = Image.fromarray(word, 'RGBA')
    if abs(swell - 1) > 0.002:
        w2, h2 = round(sprite.width * swell), round(sprite.height * swell)
        left_word = left_word.resize((w2, h2), Image.Resampling.BICUBIC)
        layer.alpha_composite(left_word, (round(x - (w2 - sprite.width) / 2), round(y - (h2 - sprite.height) / 2)))
    else:
        layer.alpha_composite(left_word, (round(x), round(y)))
    # The petals in flight: each patch becomes three petals (about its own area), starting in the word's colour.
    pixels = np.asarray(sprite)
    solid = pixels[..., 3] > 220
    ink = tuple(int(v) for v in pixels[solid][:, :3].mean(axis=0)) if solid.any() else (255, 255, 255)
    size = max(10.0, h * 0.27) * min(1.4, max(0.6, intensity))
    rng = random.Random(seed * 31 + 7)
    for i, (sx, sy) in enumerate(seeds):
        start = 0.18 + 0.6 * leave_at[i]  # when this patch leaves
        for j in range(1 if kind == 'flutter' else 3):
            r = [rng.random() for _ in range(7)]
            if amount < start:
                continue
            s = (amount - start) / max(1e-6, 1 - start)  # its own flight, running to the last frame
            ox, oy = (r[5] - 0.5) * size * 0.6, (r[6] - 0.5) * size * 0.5
            speed = 0.6 + 0.8 * r[1]  # nearer petals are bigger and faster
            depth = 0.7 + 0.6 * r[1]
            W = sprite.width
            if kind == 'fall':  # varied fall speeds and a wide sway; near the bottom an updraft lifts them aside
                dx = math.sin(s * 5 + r[0] * 6) * h * 0.5 * s + (r[0] - 0.5) * h * 0.6 * s
                dy = h * 1.15 * speed * (0.25 * s + 0.75 * s * s)
                share = smoother_step((r[0] - 0.3) / 0.4)  # some petals ride the updraft fully, some part-way: a trail
                if share > 0:
                    lift = smoother_step((amount - 0.5) / 0.2)
                    curl = smoother_step((amount - 0.79) / 0.17)  # the hook holds at its peak first
                    hook = curl * math.pi * 0.95  # over the top and back down-left, as one band
                    dy -= (h * 1.15 * lift * speed - h * 0.55 * (1 - math.cos(hook))) * share
                    dx += (h * 0.9 * lift + h * 0.75 * math.sin(hook) - h * 0.25 * curl) * share
            elif kind == 'flutter':  # a big puff up well above the word, then a flipping flutter down
                lift = math.sin(math.pi * min(1.0, s * 1.5))
                dx = (r[0] - 0.5) * h * 2.0 * s * speed + math.sin(s * 11 + r[2] * 6) * h * 0.3 * s
                dy = -h * 0.7 * lift * (1 - 0.35 * s) + h * 0.35 * max(0.0, s - 0.55)  # a peak you can see
                dx += (
                    (1 if seed % 2 else -1) * W * 0.55 * smoother_step((amount - 0.42) / 0.4)
                )  # then the mass drifts off to one side
                dy -= h * 0.4 * smoother_step((amount - 0.42) / 0.4) - h * 0.7 * smoother_step(
                    (amount - 0.66) / 0.34
                )  # and flutters down
                if i < 3:  # the biggest few see-saw from side to side as they settle
                    rock = smoother_step((amount - 0.5) / 0.2)
                    dx += math.sin(amount * math.pi * 7 - i * 2.1) * h * 0.45 * rock
                    dy -= abs(math.cos(amount * math.pi * 7 - i * 2.1)) * h * 0.15 * rock
            elif kind == 'gust':  # a long thin stream swept off to the left, the first away far ahead
                # by time since it left, so the first away really are furthest ahead: a long stream
                elapsed = (amount - start) / 0.82
                dx = -(h * 0.6 + W * 0.55) * (0.85 + 0.3 * r[1]) * elapsed**1.2
                crest = smoother_step(elapsed / 0.6) - 0.35 * smoother_step(
                    (elapsed - 0.6) / 0.5
                )  # the lead end rises a word high, then breaks over
                dy_arc = -h * 0.6 * crest * min(1.0, elapsed * 1.6)
                dy_arc += (r[0] - 0.5) * h * 0.55 * crest  # a crest two or three petals deep
                dy = math.sin(s * 5 + sx / max(1, W) * 6) * h * 0.18 - h * 0.25 * s + (r[0] - 0.5) * h * 0.2 * s
                dy += dy_arc
            elif kind == 'scatter':  # a hard burst every way, up and down too, then a drift
                a = math.atan2((sy - h / 2) * 2.2, sx - W / 2) + (r[0] - 0.5) * 1.4
                if r[3] < 0.2:  # some fill the far arc of the hoop
                    a = -math.pi / 2 + (r[0] - 0.5) * 2.6
                reach = (
                    h * (0.68 + 0.45 * r[2]) * speed * (1 - (1 - min(1.0, s * 1.7)) ** 5)
                )  # a ring opening round the hole
                dx = math.cos(a) * reach * 1.15
                dy = (
                    math.sin(a) * reach * (0.6 if math.sin(a) > 0 else 1.0) - h * 0.2 * s + h * 0.2 * s * s
                )  # the ring stays in view
                dy = max(dy, -h * 0.65)
                depth *= 1 + 0.4 * math.sin(a)  # near (lower) arc big, far (upper) arc small
                turn = 0.26 * smoother_step((s - 0.3) / 0.7)  # the ring turns slowly as it eases
                dx, dy = dx * math.cos(turn) - dy * math.sin(turn), dx * math.sin(turn) + dy * math.cos(turn)
            else:  # whirl: a funnel orbiting a vertical axis through the word, tightening as it rises
                cx, cy = W / 2, h / 2
                spread = (i * 3 + j) * 2.399963  # the golden angle: petals evenly round the axis at every moment
                a = spread + s * math.tau * 0.7  # under a turn: the ring sweeps once round, not a blur
                squeeze = 0.6 * smoother_step((amount - 0.76) / 0.1) - 0.1 * smoother_step((amount - 0.86) / 0.06)
                rad = (W * 0.5 + h * 0.2) * (1 - 0.35 * s) * (1 - squeeze)  # a last quick tighten, springing back
                hx, hy = cx + math.cos(a) * rad, cy + math.sin(a) * (rad * 0.22 + h * 0.42 * s) - h * 1.25 * s
                arrive = smoother_step(s / 0.2)  # each petal swings out from its place onto the funnel
                dx, dy = (hx - sx) * arrive, (hy - sy) * arrive
                depth *= (
                    0.85 + 0.55 * ((math.sin(a) + 1) / 2) ** 2
                )  # the far side small, the near side big as it sweeps across
            flip = (
                math.cos(amount * math.pi * 5 + r[2] * math.pi) if kind == 'flutter' else math.cos(s * (6 + r[2] * 6))
            )
            if kind == 'flutter':
                flip = math.copysign(abs(flip) ** 2.2, flip)  # it lingers edge-on
            onset = 0.55 + 0.25 * r[3]  # each petal starts to shrink at its own moment
            tilt = 0.0
            if kind == 'fall' and r[0] > 0.75:  # the plume's leading top edge tips over, down-left
                tip = smoother_step((amount - 0.62) / 0.18)
                tilt = 140 * tip
                dx -= h * 0.45 * tip
                dy += h * 0.35 * tip
            if kind == 'flutter' and i < 3:
                onset = 0.9
                tilt = 55 * math.sin(amount * math.pi * 7 - i * 2.1) * smoother_step((amount - 0.5) / 0.2)
            fade = 1 - smoother_step((s - onset) / (1 - onset))
            if kind == 'gust':  # the stream keeps its petals while it travels; it thins out over the last part
                fade = 1 - smoother_step(
                    (amount - (0.9 - 0.25 * (start - 0.18) / 0.6)) / 0.1
                )  # sheds from the trailing end
            scale = (0.6 + 0.4 * min(1.0, s * 5)) * fade * depth
            if kind == 'whirl' and (i * 3 + j) % 2:  # half the ring thins away: a hollow ring with gaps
                scale *= 1 - smoother_step((amount - 0.5) / 0.18)
            if kind == 'whirl':
                scale *= 1 - 0.35 * s  # smaller late, so the ring stays hollow
            if kind == 'gust':  # the biggest petals ride the crest
                scale *= 1 + 0.45 * crest
            if scale <= 0.04:
                continue
            step = min(4, int(s * 22))  # the first frames of its flight it is still the letter's colour
            big = (3.0 if i < 3 else 1.5) if kind == 'flutter' else 1.0
            hue = (1 if r[1] > 0.55 else 4) if kind == 'scatter' and r[1] > 0.55 else i * 3 + j
            if kind == 'scatter':
                hue = 4 if math.sin(a) > 0.3 else (0 if math.sin(a) < -0.3 else hue)  # dark near, pale far
            if kind == 'whirl' and math.sin(a) < -0.3:
                hue = 0  # the far arc in a mid rose, so the hoop reads whole
            if kind == 'flutter' and i < 3:
                hue = 5  # the big three in the lightest pink  # a deep-rose ring edge
            piece = petal(round(size * big * (0.75 + 0.45 * r[3])), hue, True, ink, step)
            w = max(1, round(piece.width * scale * max(0.12, abs(flip))))
            hh = max(1, round(piece.height * scale))
            piece = piece.resize((w, hh), Image.Resampling.BICUBIC).rotate(
                (r[4] * 360 + s * 240 * (r[5] - 0.5) if not (kind == 'flutter' and i < 3) else 20) + tilt,
                Image.Resampling.BICUBIC,
                expand=True,
            )
            if kind == 'whirl' and math.sin(a) > 0.7 and arrive > 0.9:  # a smear behind the near side
                for k in (1,):
                    back = a - 0.55 * k
                    tx = cx + math.cos(back) * rad - sx
                    ty = cy + math.sin(back) * (rad * 0.22 + h * 0.42 * s) - h * 1.25 * s - sy
                    ghost = np.asarray(piece).copy()
                    ghost[..., 3] = np.where(ghost[..., 3] > 128, 130, 0).astype(np.uint8)  # hard-edged steps
                    layer.alpha_composite(
                        Image.fromarray(ghost, 'RGBA'),
                        (round(x + sx + ox + tx - piece.width / 2), round(y + sy + oy + ty - piece.height / 2)),
                    )
            layer.alpha_composite(
                piece, (round(x + sx + ox + dx - piece.width / 2), round(y + sy + oy + dy - piece.height / 2))
            )
