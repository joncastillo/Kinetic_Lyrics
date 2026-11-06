"""The seven letters-spin entrances, each its own choreography on the kinetic toolkit.

Every letter grows in over the first frames (never pops), stays within about a word height or so of the word,
keeps its effect's own colour until it locks, and the last frame is the plain word. Each effect has its own
relay order and colour treatment so they do not read as one family."""

import math

import numpy as np
from PIL import Image, ImageDraw

from effects.kinetic import staggered, style
from effects.kinetic.easing import clamp, keyframes, pulse, smooth, smoother, window
from effects.kinetic.glyphs import colored, crisp, darker, draw_glyph, ink_color, safe_paste, solid_only
from effects.kinetic.styles import bounds, outlined, varied_accent

SETTLE = [(0, 0.0), (0.5, 1.06), (0.66, 0.98), (0.82, 1.01), (1, 1.0)]  # arrive, overshoot, settle, lock


def appear(p):
    """Everything grows in over the first frames rather than popping on."""
    return 0.25 + 0.75 * smoother(clamp(p / 0.12))


def held(glyph, q, color, lock=0.82):
    """The letter in a flat colour until it locks, then its own ink (crisp)."""
    if q >= lock:
        return crisp(glyph.image, q)
    return colored(solid_only(glyph.image), color)


def glinted(image, color, sweep):
    """`image` filled flat with `color`, a broad hard-edged white band crossing it at `sweep` (0 left, 1 right)."""
    face = colored(solid_only(image), color)
    if 0 < sweep < 1:
        a = np.asarray(face).copy()
        cols = np.arange(a.shape[1])[None, :] + np.arange(a.shape[0])[:, None] * 0.35  # a slanted band
        centre = (a.shape[1] + a.shape[0] * 0.35) * sweep
        band = np.abs(cols - centre) < a.shape[1] * 0.34
        a[..., :3][band] = (255, 252, 236)
        face = Image.fromarray(a, 'RGBA')
    return face


def tile(image, top, ink, amount=1.0):
    """The letter printed in `ink` on a flat `top`-coloured tile (a lettered domino); the tile shrinks into the
    letter as `amount` falls to 0."""
    box = solid_only(image).getbbox() or (0, 0, image.width, image.height)
    base = Image.new('RGBA', image.size)
    if amount <= 0.02:
        base.alpha_composite(colored(solid_only(image), ink))
        return base
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    box = (
        cx - (cx - box[0]) * amount,
        cy - (cy - box[1]) * amount,
        cx + (box[2] - cx) * amount,
        cy + (box[3] - cy) * amount,
    )
    pad = max(1, round((box[3] - box[1]) * 0.1))
    ImageDraw.Draw(base).rectangle(
        (
            max(0, box[0] - pad * 0.2),
            max(0, box[1] - pad),
            min(image.width, box[2] + pad * 0.2),
            min(image.height, box[3] + pad),
        ),
        fill=(*top, 255),
    )
    base.alpha_composite(colored(solid_only(image), ink))
    return base


def disc(r, gold, rim, sweep):
    """A coin face 2r across: a bevelled rim round a gold face, a hard bright diagonal glint at `sweep`."""
    size = max(2, round(2 * r))
    out = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(out)
    draw.ellipse((0, 0, size - 1, size - 1), fill=(*darker(rim, 0.3), 255))
    ring = size * 0.06
    draw.ellipse((ring, ring, size - 1 - ring, size - 1 - ring), fill=(*rim, 255))
    inset = size * 0.13  # a minted rim: dark edge, raised gold band, then the face
    draw.ellipse((inset, inset, size - 1 - inset, size - 1 - inset), fill=(*gold, 255))
    if 0 < sweep < 1:
        a = np.asarray(out).copy()
        cols = np.arange(size)[None, :] + np.arange(size)[:, None] * 0.6
        centre = -size * 0.3 + size * 1.9 * sweep
        off = np.abs(cols - centre)
        solid = a[..., 3] > 0
        a[..., :3][(off < size * 0.2) & solid] = darker(gold, 0.3)  # a deeper gold either side, so the glint pops
        a[..., :3][(off < size * 0.12) & solid] = (255, 255, 255)
        out = Image.fromarray(a, 'RGBA')
    return out


def squash(q, start, end, amount=0.22):
    """(sx, sy) of a landing squash between `start` and `end` of the letter's own progress."""
    hit = pulse(window(q, start, end))
    return 1 + amount * hit, 1 - amount * hit


@style('letters-spin-above')
def flip_drop(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """The letters wait in a row above the word, small and swaying; left to right each drops, turning head over
    heels to flash its coral back face, and lands on the baseline with a hard squash."""
    back_color = (255, 176, 156)  # a light back face, so the letter still reads as it turns
    count = len(pieces)
    height = max(g.height for g in pieces)
    grow = 0.55 + 0.45 * smoother(clamp(p / 0.1))  # the waiting row is already a good size
    for i, g in enumerate(pieces):
        q = staggered(p, i, count, 0.45)
        fall = smooth(window(q, 0, 0.45))
        dy = -height * 1.15 * (1 - fall)
        # the flip is the hero: big (about 1.3x) while it turns, settling to size as it lands
        size = keyframes(q, [(0, 0.85), (0.12, 1.3), (0.38, 1.3), (0.5, 1.0), (1, 1.0)], ease=smooth) * grow
        theta = keyframes(
            q,
            [
                (0, 0.0),
                (0.08, 0.0),
                (0.15, math.pi),  # quickly through edge-on, then the light back face held toward us
                (0.26, math.pi),
                (0.33, 2 * math.pi),
                (1, 2 * math.pi),
            ],
        )
        turn = math.cos(theta)
        sway = (1 - smoother(window(q, 0, 0.3))) * (8 if i % 2 else -8)
        sx = keyframes(q, [(0, 1.0), (0.45, 1.0), (0.5, 1.15), (0.6, 1.15), (0.72, 1.0), (1, 1.0)], ease=smooth)
        sy = keyframes(q, [(0, 1.0), (0.45, 1.0), (0.5, 0.8), (0.6, 0.8), (0.72, 1.0), (1, 1.0)], ease=smooth)
        edge = max(2, round(height * 0.05))
        if turn < 0:  # the back face: light, with a dark edge, so the letter still reads as it turns
            image = outlined(g.image, back_color, (170, 50, 50), edge)
        elif q < 0.45:
            image = outlined(g.image, (255, 112, 100), (170, 50, 50), edge)
        else:
            image = held(g, q, (236, 72, 72), 0.45)
        thick = height * 0.3 * abs(math.sin(theta)) * size
        draw_glyph(
            layer,
            g,
            x,
            y,
            size * sx,
            size * max(0.06, abs(turn)) * sy,
            angle=sway,
            dy=dy,
            anchor='middle' if q < 0.45 else 'bottom',
            extrude=(thick, -math.pi / 2 if math.sin(theta) > 0 else math.pi / 2, (214, 86, 80))
            if thick >= 0.6
            else None,
            image=image,
        )


@style('letters-spin-below')
def coin_rise(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """Gold coins: from the middle of the word outward, each letter rises from just below the baseline spinning
    about its upright, its thick gold edge seen edge-on for frames at a time, overshoots high and settles."""
    gold, edge = (255, 214, 80), (236, 172, 40)
    count = len(pieces)
    height = max(g.height for g in pieces)
    middle = (count - 1) / 2
    grow = appear(p)
    for i, g in enumerate(pieces):
        q = staggered(p, round(abs(i - middle) * 2), max(2, count), 0.4)
        rise = keyframes(q, [(0, 0.0), (0.45, 1.15), (0.62, 0.96), (0.8, 1.01), (1, 1.0)], ease=smooth)
        # the spin lingers edge-on (quarter turns) so the thick edge reads
        theta = keyframes(
            q,
            [
                (0, 0.0),
                (0.3, 0.0),
                (0.5, 2 * math.pi),  # face-on as it rises, one quick spin just before it lands
                (1, 2 * math.pi),
            ],
        )
        turn = math.cos(theta)
        depth = height * 0.26 * abs(math.sin(theta)) * min(1.4, intensity) * grow
        size = (0.75 + 0.25 * smoother(window(q, 0, 0.45))) * grow
        # a hard glint crosses the coin, lingering mid-face for a few frames
        sweep = keyframes(
            q,
            [
                (0, 0.0),
                (0.08, 0.0),
                (0.16, 0.42),
                (0.26, 0.58),
                (0.32, 1.0),
                (0.5, 1.0),
                (0.51, 0.0),
                (0.53, 0.4),
                (0.59, 0.6),
                (0.63, 1.0),
                (1, 1.0),
            ],
        )  # a glint as it rises, and a bold one as it lands
        shrink = 1 - smoother(window(q, 0.6, 0.74))  # the coin shrinks into the plain letter as it settles
        dy = height * 0.95 * (1 - rise)
        if shrink > 0.02:
            r = g.height * 0.5 * size * shrink  # a coin a little taller than the struck letter on it
            face = disc(r, gold, edge, sweep)
            fw = max(1, round(face.width * max(0.1, abs(turn))))
            face = face.resize((fw, face.height), Image.Resampling.BICUBIC)
            cx0 = x + g.left + g.width / 2
            cy0 = y + g.bottom + dy - g.height * size / 2
            if depth >= 0.6:  # the coin's thick edge
                thick = colored(face, darker(edge, 0.25))
                safe_paste(layer, thick, cx0 - fw / 2 + depth, cy0 - face.height / 2)
            safe_paste(layer, face, cx0 - fw / 2, cy0 - face.height / 2)
        struck = 0.66 + 0.34 * (1 - shrink)  # the letter sits small on its coin, growing to full size as it lands
        draw_glyph(
            layer,
            g,
            x,
            y,
            size * struck * max(0.1, abs(turn)),
            size * struck * (1 - 0.14 * (1 - abs(turn))),  # a disc in perspective
            dy=dy - g.height * size * (1 - struck) / 2,  # centred on the coin
            anchor='bottom',
            image=glinted(g.image, darker(gold, 0.35), sweep)
            if shrink > 0.02
            else crisp(g.image, q),  # glint crosses it too
        )


@style('letters-spin-left')
def roll_in(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """Wheels: one at a time, last letter first, each rolls in from the left in teal, turning as far as it
    travels with a hard smear behind it, and brakes with a forward lean before it locks upright."""
    teal = (40, 214, 190)
    count = len(pieces)
    height = max(g.height for g in pieces)
    radius = height * 0.5
    grow = appear(p)
    for i in range(count - 1, -1, -1):  # the leading letters roll in first and the rest follow behind them
        g = pieces[i]
        q = staggered(p, count - 1 - i, count, 0.42)  # few roll at once, so the wheels never tangle
        travel = keyframes(q, [(0, 0.0), (0.6, 1.03), (0.78, 0.995), (1, 1.0)], ease=smooth)
        dx = -math.pi * radius * 0.6 * (1 - travel)
        roll = smoother(window(q, 0, 0.42))  # it rolls, then slides its last stretch upright and readable
        angle = -360 * (1 - roll)  # the letter turns with its wheel, upright again before it brakes
        lean = -16 * pulse(window(q, 0.5, 0.82))
        if q <= 0:
            continue
        wheel = max(g.width, g.height) * 0.7 * grow * (1 - smoother(window(q, 0.45, 0.66)))
        if wheel > 1.5:  # the wheel: a solid dark-teal disc with a bright rim, shrinking into the letter as it brakes
            wx, wy = x + g.left + g.width / 2 + dx, y + (g.top + g.bottom) / 2
            ImageDraw.Draw(layer).ellipse(
                (wx - wheel, wy - wheel, wx + wheel, wy + wheel),
                fill=(*darker(teal, 0.45), 255),
                outline=(*teal, 255),
                width=max(2, round(wheel * 0.12)),
            )
        streak = g.width * 1.4 * (1 - roll) * grow  # a motion streak a letter and more long, gone as it brakes
        if streak > 2:
            cx0, cy0 = x + g.left + g.width / 2 + dx, y + (g.top + g.bottom) / 2
            band = height * 0.42 * grow
            trail = Image.new('RGBA', layer.size)
            ImageDraw.Draw(trail).polygon(
                [
                    (cx0 - g.width * 0.2, cy0 - band / 2),
                    (cx0 - g.width * 0.2, cy0 + band / 2),
                    (cx0 - streak - g.width * 0.3, cy0),
                ],
                fill=(*darker(teal, 0.3), 150),
            )
            layer.alpha_composite(trail)
        draw_glyph(
            layer,
            g,
            x,
            y,
            grow,
            grow,
            angle=angle + lean,
            dx=dx,
            anchor='middle',
            image=held(g, q, (214, 255, 246), 0.62),
        )
        skid = pulse(window(q, 0.45, 0.85))  # a skid mark under the slot as it brakes
        if skid > 0.05:
            sx0 = x + g.left + g.width / 2 + dx
            base = y + g.bottom + height * 0.08
            thick = height * 0.11 * skid
            ImageDraw.Draw(layer).polygon(
                [(sx0 + g.width * 0.3, base - thick), (sx0 + g.width * 0.3, base), (sx0 - g.width * 1.8 * skid, base)],
                fill=(*darker(teal, 0.4), 255),
            )


@style('letters-spin-right')
def domino_stand(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """Dominoes: the letters lie on their sides on the baseline as violet tiles, each with its letter printed on
    it; left to right, in a quick relay, each swings straight up onto its foot and the tile shrinks into the
    plain letter. (No overshoot past upright: a rotation that reverses reads as flicker.)"""
    count = len(pieces)
    height = max(g.height for g in pieces)
    left_edge, _, right_edge, _ = bounds(pieces)
    mid = (left_edge + right_edge) / 2
    grow = 0.35 + 0.65 * smoother(clamp(p / 0.12))  # grows in over the first frames, never pops on
    for i, g in enumerate(pieces):
        q = staggered(p, i, count, 0.4)  # a quick relay, left to right
        stand = keyframes(q, [(0, 0.0), (0.5, 1.0), (1, 1.0)], ease=smooth)
        tip = math.radians(20) * (1 - stand)  # tipped back a little too: its underside shows
        narrow = 0.82 + 0.18 * smoother(window(q, 0.45, 0.7))  # each tile narrower than its slot: a gap
        lying = 1 + 0.4 * (1 - stand)  # bigger while lying down, so the sideways letter reads
        sy = math.cos(tip) * grow * lying
        sx = narrow * grow * lying
        depth = height * 0.3 * math.sin(tip) * grow  # a thick underside
        spread = (g.left + g.width / 2 - mid) * 0.3 * (1 - stand)  # lying tiles spread apart, each with a gap
        fallen = 82 * (1 - stand)  # lying on its side, swinging straight up
        draw_glyph(
            layer,
            g,
            x,
            y,
            sx,
            sy,
            angle=fallen,
            dx=spread,
            anchor='bottom',
            extrude=(depth, -math.pi / 2, (80, 52, 196)) if depth >= 0.6 else None,
            image=tile(g.image, (112, 82, 232), (236, 230, 255), 1 - smoother(window(q, 0.5, 0.72)))
            if q < 0.7
            else crisp(g.image, q),
        )


@style('letters-spin-diagonal')
def whip_in(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """The letters whip in one after another on a diagonal from the upper right, each trailing three hard
    accent copies that it catches up with; as the copies collapse into it the letter squashes hard, then snaps
    upright."""
    ink = ink_color(sprite)
    accent = varied_accent(ink, rng, seed)
    tints = [tuple(round(c + (255 - c) * k) for c in accent) for k in (0.5, 0.25, 0.0)]
    count = len(pieces)
    height = max(g.height for g in pieces)
    grow = appear(p)
    frame = pulse(window(p, 0.68, 0.84))  # the impact: an outlined offset frame of the whole word
    if frame > 0.08:
        off = height * 0.07 * frame
        safe_paste(
            layer, outlined(sprite, accent, darker(accent, 0.6), max(1, round(height * 0.035))), x + off, y + off
        )
    for i, g in enumerate(pieces):
        q = staggered(p, i, count, 0.4)

        def place(at):
            travel = keyframes(clamp(at), [(0, 0.0), (0.45, 1.05), (0.6, 0.98), (0.75, 1.0), (1, 1.0)], ease=smooth)
            d = height * 1.25 * (1 - travel)
            return d * 1.0, -d * 0.32

        for k, tint in zip((3, 2, 1), tints):  # the copies lag behind and catch up
            if k != 1 or q > 0.5:  # fewer copies on paper and on the last letters
                continue
            cx, cy = place(q - 0.1 * k)
            lx, ly = place(q)
            if abs(cx - lx) + abs(cy - ly) < 1.0:
                continue
            draw_glyph(
                layer,
                g,
                x,
                y,
                grow,
                grow,
                angle=-14 * (1 - q),
                dx=cx,
                dy=cy,
                image=outlined(g.image, tint, darker(tint, 0.6), 1),
            )
        dx, dy = place(q)
        lean = -16 * (1 - smoother(window(q, 0.3, 0.75)))
        sx, sy = squash(q, 0.42, 0.62, 0.4)
        flash = pulse(window(q, 0.42, 0.56))  # one bright hard-edged impact frame as the copies collapse in
        face = (
            outlined(g.image, accent, darker(accent, 0.6), max(1, round(height * 0.03)))
            if flash > 0.5 and i < count * 2 / 3
            else crisp(g.image, q)
        )
        trail = height * 1.2 * (1 - smoother(window(q, 0.35, 0.55)))  # a solid accent smear back up its path
        draw_glyph(
            layer,
            g,
            x,
            y,
            sx * grow,
            sy * grow,
            angle=lean,
            dx=dx,
            dy=dy,
            image=face,
            extrude=(trail, -0.31, darker(accent, 0.25)) if trail >= 0.6 else None,
        )


@style('letters-spin-scatter')
def magnet(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """The letters start scattered close around the word, tilted, in hot orange; nearest first, a magnet pulls
    each home, the letter stretching long along its path for a few frames before it lands with a squash."""
    hot = (255, 110, 40)
    count = len(pieces)
    height = max(g.height for g in pieces)
    starts = []
    for i in range(
        count
    ):  # each from straight above or below its own slot, alternately, so no path crosses a neighbour's
        r = height * rng.uniform(0.85, 1.2)
        starts.append((rng.uniform(-0.12, 0.12) * height, r * (-1 if i % 2 else 1), rng.uniform(-30, 30)))
    order = sorted(range(count), key=lambda i: math.hypot(*starts[i][:2]))
    rank = {i: n for n, i in enumerate(order)}
    starts = [
        (sx0 * (1 - 0.45 * rank[i] / max(1, count - 1)), sy0 * (1 - 0.45 * rank[i] / max(1, count - 1)), tilt)
        for i, (sx0, sy0, tilt) in enumerate(starts)
    ]  # the later arrivals start nearer home
    grow = appear(p)
    for i, g in enumerate(pieces):
        q = staggered(p, rank[i], count, 0.58)
        pull = keyframes(q, SETTLE, ease=smooth)
        sx0, sy0, tilt = starts[i]
        path = math.degrees(math.atan2(-sy0, sx0))  # the direction it is pulled in
        stretch = keyframes(q, [(0, 0.3), (0.1, 1.0), (0.38, 1.0), (0.5, 0.0), (1, 0.0)], ease=smooth) * (
            1 - smoother(window(p, 0.6, 0.7))
        )  # every letter at true height after .7
        sx, sy = squash(q, 0.5, 0.74, 0.3)
        size = (0.85 + 0.15 * smoother(window(q, 0, 0.5))) * grow
        # stretched along its path: turn to the path, stretch, and turn back as it lands
        angle = tilt * (1 - pull) + (path - tilt) * stretch * 0.0
        long_x = abs(math.cos(math.radians(path)))
        if stretch > 0.6 and 0.05 < q and pull < 0.95:  # a hard streak back along its path while it is pulled
            cx0, cy0 = x + g.left + g.width / 2 + sx0 * (1 - pull), y + (g.top + g.bottom) / 2 + sy0 * (1 - pull)
            back = math.copysign(g.height * size * (1 + 0.85 * stretch) / 2 * 0.9, sy0)  # the trailing edge
            cy0 += back
            tail = math.copysign(g.height * 0.5 * stretch * (1 - pull), sy0)  # short, fading as it nears its slot
            half = g.width * 0.32 * stretch
            ImageDraw.Draw(layer).polygon(
                [(cx0 - half, cy0), (cx0 + half, cy0), (cx0, cy0 + tail)], fill=(255, 176, 110, 255)
            )
        draw_glyph(
            layer,
            g,
            x,
            y,
            size * sx * (1 + 1.1 * stretch * long_x),
            size * sy * (1 + 1.1 * stretch * (1 - long_x)) / (1 + 0.25 * stretch),
            angle=angle,
            dx=sx0 * (1 - pull),
            dy=sy0 * (1 - pull),
            anchor='middle',
            image=held(g, q, hot, 0.8),
        )
        click = (
            window(q, 0.5, 0.64) if p < 0.74 else 1.0
        )  # the click: a thick ring snaps out tight round the slot and is gone
        if 0 < click < 1:
            cx0, cy0 = x + g.left + g.width / 2, y + (g.top + g.bottom) / 2
            rr = g.height * (0.42 + 0.22 * smoother(click))
            weight = max(2, round(g.height * 0.11 * (1 - click)))
            draw = ImageDraw.Draw(layer)
            draw.ellipse((cx0 - rr, cy0 - rr, cx0 + rr, cy0 + rr), outline=(*hot, 255), width=weight)
            inner = rr - weight
            if weight > 3:
                draw.ellipse(
                    (cx0 - inner, cy0 - inner, cx0 + inner, cy0 + inner), outline=(255, 236, 200, 255), width=1
                )


@style('letters-spin-spiral')
def orbit(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """A planet's ring: the letters ride a tilted elliptical orbit drawn around the word, large in front and
    small and dark behind it; one after another each drops out of orbit into its slot and locks."""
    ring = (140, 110, 255)
    count = len(pieces)
    left, top, right, bottom = bounds(pieces)
    cx, cy = (left + right) / 2, (top + bottom) / 2 + (bottom - top) * 0.3  # a low orbit: its front passes below
    rx, ry = (right - left) * 0.55, (bottom - top) * 0.68  # a flatter, tilted ring
    spin = p * math.tau * 0.6  # just over half a turn: an orbit you can follow
    grow = appear(p)
    # the ring flattens into an underline swoosh beneath the word as the last letters land, then draws away
    flat = smoother(window(p, 0.3, 0.48))
    away = smoother(window(p, 0.68, 0.86))
    rcy = cy + (bottom + (bottom - top) * 0.3 - cy) * smoother(window(p, 0.3, 0.5))  # down under the baseline
    ring_cy = rcy + (bottom + (bottom - top) * 0.12 - rcy) * flat
    ring_rx, ring_ry = (
        rx * grow * (1 - 0.25 * flat) * (1 - 0.25 * smoother(window(p, 0.3, 0.5))) * (1 - away),
        ry * grow * (1 - flat),
    )
    weight = max(3, round((bottom - top) * 0.08))  # a bold two-tone band: a darker under-edge, then the accent
    under = max(2, round(weight * 0.4))

    def band(start, end):
        """The ring's arc from `start` to `end` degrees (0..180 is the front, below; 180..360 the back)."""
        if ring_rx <= 2:
            return
        draw = ImageDraw.Draw(layer)
        for shade, lift in ((darker(ring, 0.45), 0), (ring, under)):
            if ring_ry > 1.5:
                box = (x + cx - ring_rx, y + ring_cy - ring_ry - lift, x + cx + ring_rx, y + ring_cy + ring_ry - lift)
                draw.arc(box, start, end, fill=(*shade, 255), width=weight)
            elif start == 0:  # flat: the swoosh, drawn once, in front
                ly = y + ring_cy - lift
                draw.line((x + cx - ring_rx, ly, x + cx + ring_rx, ly), fill=(*shade, 255), width=weight)

    draws = []
    for i, g in enumerate(pieces):
        q = staggered(p, i, count, 0.14)
        phi = math.tau * i / count + spin
        depth = math.sin(phi)  # +1 in front, -1 behind
        land = keyframes(q, [(0, 0.0), (0.25, 0.0), (0.45, 1.04), (0.55, 0.99), (1, 1.0)], ease=smooth)
        gx, gy = g.left + g.width / 2, (g.top + g.bottom) / 2
        ox, oy = (cx + rx * math.cos(phi) - gx) * grow, (rcy + ry * depth - gy) * grow
        size = (
            (0.82 + 0.22 * depth - 0.25 * smoother(window(p, 0.3, 0.5))) * (1 - land) + land
        ) * grow  # real depth: small behind, big in front
        sx, sy = squash(q, 0.55, 0.72, 0.16)
        color = (
            ring if depth >= 0 or land > 0.3 else darker(ring, 0.25)
        )  # a mid tone behind, bright again as it drops in
        draws.append(
            (
                depth * (1 - land) + land,
                g,
                size * sx,
                size * sy,
                ox * (1 - land),
                oy * (1 - land),
                held(g, q, color, 0.36),
            )
        )
    ordered = sorted(draws, key=lambda d: d[0])  # back of the ring first
    for _, g, sx, sy, dx, dy, image in [d for d in ordered if d[0] < 0]:  # riders on the back of the orbit
        draw_glyph(layer, g, x, y, sx, sy, dx=dx, dy=dy, anchor='middle', image=image)
    band(180, 360)  # the back arc crosses the bodies of the riders behind
    for _, g, sx, sy, dx, dy, image in [d for d in ordered if d[0] >= 0]:  # riders in front, and landed letters
        draw_glyph(layer, g, x, y, sx, sy, dx=dx, dy=dy, anchor='middle', image=image)
    band(0, 180)  # the front arc passes over the riders in front: they are threaded on the ring
