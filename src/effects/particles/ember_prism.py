"""The ember and prism cinematic effects: an entrance and an exit each.

Ember forge: a stream of embers rises from under the word and welds each letter together from its foot up; the
letters are white-hot where they have just formed, cool through orange and dull red behind the front, and are the
plain word once the last one has cooled. Sparks spit from the front.

Ember to ash: heat creeps up the letters from the foot; patches come away from the bottom up as glowing embers
that rise, cool to grey ash flakes and drift off.

Prismatic helix: every letter arrives as a stack of thin slices riding a helix down into place, each slice split
into red and cyan copies that converge as it locks with a white flash; a prism glint then sweeps the word.

Prismatic singularity: the letters' colours split apart, a point of light ignites at the centre of the word, and
the slices spiral into it, nearest first; the point swells, flashes a ring and winks out.

Every frame is a pure function of progress. Entrances end on the plain word; exits start on it and leave nothing."""

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from effects.growth.assets import glyph_ranges
from effects.particles.cache import sprite_key

HOT = ((255, 252, 230), (255, 196, 70), (240, 92, 24), (120, 28, 18))  # white-hot, yellow, orange, dull red


def smoother(q):
    q = max(0.0, min(1.0, q))
    return q * q * q * (q * (q * 6 - 15) + 10)


def smooth(q):
    q = max(0.0, min(1.0, q))
    return q * q * (3 - 2 * q)


def _ink(sprite):
    pixels = np.asarray(sprite)
    solid = pixels[..., 3] > 220
    return pixels[solid][:, :3].mean(axis=0) if solid.any() else np.array((235.0, 235.0, 235.0))


def _heat_colour(temperature):
    """Blackbody-ish ramp for an array of temperatures (0 cold .. 1 white-hot): returns (H, W, 3)."""
    t = np.clip(temperature, 0, 1)[..., None]
    stops = np.array(HOT[::-1], np.float32)  # dull red .. white-hot
    pos = t * 3
    i = np.clip(np.floor(pos), 0, 2).astype(int)
    f = pos - i
    return stops[i[..., 0]] * (1 - f) + stops[np.minimum(i[..., 0] + 1, 3)] * f


def _letters(sprite, glyph_spans):
    ranges = glyph_ranges(sprite, glyph_spans)
    return ranges if ranges else [(0, sprite.width)]


def _ink_rows(sprite):
    alpha = np.asarray(sprite.getchannel('A'))
    rows = np.nonzero((alpha > 120).any(axis=1))[0]
    return (int(rows[0]), int(rows[-1]) + 1) if len(rows) else (0, sprite.height)


def _geometry(sprite, seed, glyph_spans, cache, tag):
    key = (tag, sprite_key(sprite), seed, tuple(map(tuple, glyph_spans or ())))
    if cache is not None and key in cache:
        return cache[key]
    letters = _letters(sprite, glyph_spans)
    top, bottom = _ink_rows(sprite)
    rng = np.random.default_rng(seed * 17 + 3)
    parts = dict(letters=letters, top=top, bottom=bottom, ink=_ink(sprite), rng=rng.random((len(letters), 48, 6)))
    if cache is not None:
        cache[key] = parts
    return parts


# ---------------------------------------------------------------- ember forge (entrance)


def paint_ember_forge(layer, sprite, x, y, progress, seed, intensity, cache, glyph_spans):
    g = _geometry(sprite, seed, glyph_spans, cache, 'ember-forge')
    letters, top, bottom = g['letters'], g['top'], g['bottom']
    n = len(letters)
    w, h = sprite.size
    ink_h = max(1, bottom - top)
    p = max(0.0, min(1.0, progress))
    if p >= 1:
        layer.alpha_composite(sprite, (round(x), round(y)))
        return
    pixels = np.asarray(sprite).astype(np.float32)
    alpha = pixels[..., 3]
    yy = np.arange(h)[:, None]
    up = np.clip((bottom - yy) / ink_h, 0, 1.2)  # 0 at the foot of the letters, 1 at their top
    cols = np.arange(w)[None, :]
    level = np.zeros((1, w), np.float32)
    temp_gain = np.zeros((1, w), np.float32)
    for k, (left, right) in enumerate(letters):
        local = max(0.0, min(1.0, (p - 0.28 * k / max(1, n)) / 0.5))
        fill = smooth(local)
        on = (cols >= left) & (cols < right)
        level = np.where(on, fill * 1.06, level)
        temp_gain = np.where(on, 1.0, temp_gain)
    revealed = np.clip((level - up) / 0.04 + 0.5, 0, 1)
    # temperature: white-hot at the front, cooling with distance behind it, and everything cooling toward the end
    behind = np.clip(level - up, 0, None)
    temperature = np.clip(1 - behind * 1.1, 0.35, 1) * (1 - smoother((p - 0.66) / 0.32))
    temperature = np.where(level > 0, temperature, 0)
    heat = _heat_colour(temperature)
    glow_t = np.clip(temperature * 1.15, 0, 1) ** 1.2
    rgb = pixels[..., :3] * (1 - glow_t[..., None]) + heat * glow_t[..., None]
    # a dark skin on the molten metal: the outermost pixels of a hot letter go deep red, so it reads on cream
    inner = np.asarray(sprite.getchannel('A').filter(ImageFilter.MinFilter(5))).astype(np.float32) / 255
    skin = (alpha / 255 - inner).clip(0, 1) * glow_t
    rgb = rgb * (1 - skin[..., None] * 0.75) + np.array((110, 24, 12), np.float32) * skin[..., None] * 0.75
    # a dark skin at the hot edge so molten letters read on light paintings too
    seam = np.exp(-(((level - up) / 0.035) ** 2)) * (level > 0) * (level < 1.05)
    rgb = rgb * (1 - seam[..., None]) + np.array((255, 248, 210), np.float32) * seam[..., None]
    out = np.dstack([rgb, alpha * np.maximum(revealed, seam * (alpha > 120))]).clip(0, 255).astype(np.uint8)
    word = Image.fromarray(out, 'RGBA')
    # glow around the hot parts
    hot_alpha = (alpha * np.maximum(revealed * glow_t, seam * 1.4) / 255).clip(0, 1)
    glow = Image.fromarray(np.dstack([heat, hot_alpha * 255]).clip(0, 255).astype(np.uint8), 'RGBA')
    pad = round(h * 0.4)
    canvas = Image.new('RGBA', (w + 2 * pad, h + 2 * pad))
    canvas.alpha_composite(glow, (pad, pad))
    canvas = canvas.filter(ImageFilter.GaussianBlur(h * 0.07))
    canvas.putalpha(canvas.getchannel('A').point(lambda a: min(255, round(a * 1.1))))
    # embers streaming up into the front, and sparks spitting off it
    draw = ImageDraw.Draw(canvas)
    rnd = g['rng']
    for k, (left, right) in enumerate(letters):
        start_k = 0.28 * k / max(1, n)
        for i in range(36):
            r = rnd[k, i]
            birth = start_k - 0.12 + 0.5 * r[0]
            life = 0.16 + 0.1 * r[1]
            age = p - birth
            if not 0 < age < life or p > 0.92:
                continue
            s = age / life
            tx = left + (right - left) * r[2]
            local = max(0.0, min(1.0, (p - start_k) / 0.5))
            target_y = bottom - smooth(local) * ink_h
            sx = tx + (r[3] - 0.5) * h * 0.4
            sy = bottom + h * (0.35 + 0.5 * r[4])
            bend = (r[5] - 0.5) * h * 0.5

            def at(s_):
                s_ = max(0.0, s_)
                return (sx + (tx - sx) * smoother(s_) + bend * math.sin(math.pi * s_),
                        sy + (target_y - sy) * (1 - (1 - s_) ** 2))
            px, py = at(s)
            heat_i = 1 - 0.4 * s
            colour = tuple(int(v) for v in _heat_colour(np.array([[heat_i]]))[0, 0])
            width = max(2, round(h * 0.035 * (0.6 + 0.6 * r[1])))
            for step in range(4):  # a streak that tapers from the hot head back along its curve
                a0, a1 = at(s - 0.045 * step), at(s - 0.045 * (step + 1))
                draw.line([(pad + a1[0], pad + a1[1]), (pad + a0[0], pad + a0[1])],
                          fill=(*colour, round(230 * (1 - step / 4))), width=max(1, round(width * (1 - step / 5))))
            head = width * 0.55
            draw.ellipse((pad + px - head, pad + py - head, pad + px + head, pad + py + head), fill=(255, 250, 220, 255))
        for i in range(36, 48):  # sparks off the front
            r = rnd[k, i]
            birth = start_k + 0.1 + 0.4 * r[0]
            age = p - birth
            life = 0.08 + 0.06 * r[1]
            if not 0 < age < life or p > 0.9:
                continue
            s = age / life
            local = max(0.0, min(1.0, (p - start_k) / 0.5))
            fy = bottom - smooth(local) * ink_h
            fx = left + (right - left) * r[2]
            ang = -math.pi / 2 + (r[3] - 0.5) * 2.2
            dist = h * 0.3 * s * (0.6 + 0.8 * r[4])
            px, py = fx + math.cos(ang) * dist, fy + math.sin(ang) * dist + h * 0.25 * s * s
            colour = (255, 220, 120) if s < 0.5 else (240, 120, 40)
            draw.line([(pad + px, pad + py), (pad + px - math.cos(ang) * h * 0.04, pad + py - math.sin(ang) * h * 0.04)],
                      fill=(*colour, round(255 * (1 - s))), width=max(1, round(h * 0.01)))
    layer.alpha_composite(canvas, (round(x) - pad, round(y) - pad))
    layer.alpha_composite(word, (round(x), round(y)))


# ---------------------------------------------------------------- ember to ash (exit)

BREAK_AT, LAST_AT = 0.14, 0.62


def _patches(sprite, seed, size):
    alpha = np.asarray(sprite.getchannel('A'))
    ys, xs = np.nonzero(alpha > 0)
    if len(xs) == 0:
        return None
    sy, sx = np.nonzero(alpha > 120)
    if len(sx) == 0:
        sy, sx = ys, xs
    rng = np.random.default_rng(seed)
    count = int(min(150, max(8, len(sx) / (size * size * 0.8))))
    pick = rng.choice(len(sx), size=min(count, len(sx)), replace=False)
    seeds = np.stack([sx[pick], sy[pick]], axis=1).astype(np.float32)
    owner = np.empty(len(xs), int)
    for start in range(0, len(xs), 12000):
        px = np.stack([xs[start : start + 12000], ys[start : start + 12000]], axis=1).astype(np.float32)
        owner[start : start + 12000] = np.argmin(((px[:, None, :] - seeds[None, :, :]) ** 2).sum(-1), axis=1)
    return seeds, owner, ys, xs


def paint_ember_ash(layer, sprite, x, y, amount, seed, intensity, cache):
    w, h = sprite.size
    key = ('ember-ash', sprite_key(sprite), seed)
    if cache is not None and key in cache:
        parts = cache[key]
    else:
        patches = _patches(sprite, seed, h * 0.18)
        if patches is None:
            return
        seeds, owner, ys, xs = patches
        rng = np.random.default_rng(seed * 31 + 7)
        order = (1 - seeds[:, 1] / max(1, h)) * 0.7 + rng.random(len(seeds)) * 0.3
        order = (order - order.min()) / max(1e-6, order.max() - order.min())
        parts = (seeds, owner, ys, xs, order, rng.random((len(seeds), 3, 6)), _ink(sprite))
        if cache is not None:
            cache[key] = parts
    seeds, owner, ys, xs, order, randoms, ink = parts
    starts = BREAK_AT + (LAST_AT - BREAK_AT) * order
    gone = amount >= starts
    # the remaining word: heat creeps up to each patch before it goes
    word = np.asarray(sprite).astype(np.float32)
    rgb = word[ys, xs, :3]
    heat = np.clip(1 - (starts[owner] - amount) / 0.16, 0, 1)
    hot = _heat_colour(heat * 0.85)
    rgb = rgb * (1 - heat[:, None] * 0.95) + hot * heat[:, None] * 0.95
    word[ys, xs, :3] = rgb
    word[ys[gone[owner]], xs[gone[owner]], 3] = 0
    pad = round(h * 0.6)
    canvas = Image.new('RGBA', (w + 2 * pad, h + 2 * pad))
    glow = Image.new('RGBA', canvas.size)
    gd = ImageDraw.Draw(glow)
    flakes = ImageDraw.Draw(canvas)
    for i, (sx, sy) in enumerate(seeds):
        if amount < starts[i]:
            continue
        for j in range(3):
            r = randoms[i, j]
            e = amount - starts[i] - j * 0.02
            if e <= 0:
                continue
            life = min(0.75, 0.97 - starts[i])
            s = e / life
            if s >= 1:
                continue
            rise = h * (0.6 * e + 2.2 * e * e) * (0.8 + 0.4 * r[1])
            sway = math.sin(e * 9 + r[2] * math.tau) * h * (0.08 + 0.25 * e) + (r[3] - 0.5) * h * 0.6 * e
            px, py = pad + sx + sway, pad + sy - rise
            temp = max(0.0, 1 - s / 0.45)
            fade = 1 - smoother((s - 0.55) / 0.45)
            if temp > 0:  # a glowing ember with a short streak behind it
                colour = tuple(int(v) for v in _heat_colour(np.array([[temp]]))[0, 0])
                width = max(1, round(h * 0.03 * (0.6 + 0.6 * r[4])))
                gd.line([(px - sway * 0.08, py + h * 0.08), (px, py)], fill=(*colour, round(230 * fade)), width=width)
                gd.ellipse((px - width, py - width, px + width, py + width), fill=(*colour, round(255 * fade)))
            ash = min(1.0, s / 0.5)
            if ash > 0.05:  # a grey flake tumbling in the updraught
                size = h * 0.035 * (0.7 + 0.6 * r[5]) * (1 + 0.6 * s)
                angle = r[0] * math.tau + s * 9
                squash = 0.3 + 0.7 * abs(math.cos(angle * 1.3))
                grey = 70 + 80 * r[4]
                corners = [(px + math.cos(angle + k * math.pi / 2) * size * (1 if k % 2 else squash),
                            py + math.sin(angle + k * math.pi / 2) * size * (1 if k % 2 else squash)) for k in range(4)]
                flakes.polygon(corners, fill=(int(grey), int(grey * 0.96), int(grey * 0.96), round(220 * fade * ash)))
    glow_blur = glow.filter(ImageFilter.GaussianBlur(h * 0.05))
    glow_blur.putalpha(glow_blur.getchannel('A').point(lambda a: round(a * 0.7)))
    layer.alpha_composite(glow_blur, (round(x) - pad, round(y) - pad))
    layer.alpha_composite(canvas, (round(x) - pad, round(y) - pad))
    layer.alpha_composite(glow, (round(x) - pad, round(y) - pad))
    layer.alpha_composite(Image.fromarray(word.clip(0, 255).astype(np.uint8), 'RGBA'), (round(x), round(y)))


# ---------------------------------------------------------------- prismatic helix (entrance)

SLICES = 5


def _iridescent(hue):
    """A saturated spectral colour for hue 0-1."""
    h6 = (hue % 1) * 6
    i = int(h6)
    f = h6 - i
    q, t = 1 - f, f
    rgb = [(1, t, 0), (q, 1, 0), (0, 1, t), (0, q, 1), (t, 0, 1), (1, 0, q)][i % 6]
    return tuple(int(60 + 195 * c) for c in rgb)


def _slice(sprite, left, right, top, bottom):
    return sprite.crop((left, top, right, bottom))


def _split(piece, shift, strength):
    """`piece` with red and cyan copies pulled apart by `shift` pixels (chromatic aberration)."""
    if shift < 0.5 or strength <= 0.02:
        return piece, 0
    pad = int(math.ceil(shift)) + 1
    out = Image.new('RGBA', (piece.width + 2 * pad, piece.height + 2 * pad))
    arr = np.asarray(piece).astype(np.float32)
    alpha = arr[..., 3:4] * strength * 0.8
    red = np.dstack([arr[..., :1] * 0 + 255, arr[..., 1:2] * 0 + 40, arr[..., 2:3] * 0 + 60, alpha]).astype(np.uint8)
    cyan = np.dstack([arr[..., :1] * 0 + 40, arr[..., 1:2] * 0 + 230, arr[..., 2:3] * 0 + 255, alpha]).astype(np.uint8)
    out.alpha_composite(Image.fromarray(red, 'RGBA'), (round(pad - shift), pad))
    out.alpha_composite(Image.fromarray(cyan, 'RGBA'), (round(pad + shift), pad))
    out.alpha_composite(piece, (pad, pad))
    return out, pad


def _tinted(piece, colour, amount):
    if amount <= 0.02:
        return piece
    arr = np.asarray(piece).astype(np.float32)
    arr[..., :3] = arr[..., :3] * (1 - amount) + np.array(colour, np.float32) * amount
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA')


def _brightened(piece, amount):
    if amount <= 0.02:
        return piece
    arr = np.asarray(piece).astype(np.float32)
    arr[..., :3] = arr[..., :3] + (255 - arr[..., :3]) * amount
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), 'RGBA')


def _helix_point(cx, cy, h, hand, e, phase):
    """Where a letter is at eased progress `e` of its descent: a corkscrew down onto its place."""
    theta = (1 - e) * math.tau * 1.0 + phase
    radius = h * 0.26 * (1 - e)
    return cx + hand * math.cos(theta) * radius, cy - h * 0.8 * (1 - e) + math.sin(theta) * radius * 0.45, theta


def paint_prismatic_helix(layer, sprite, x, y, progress, seed, intensity, cache, glyph_spans):
    g = _geometry(sprite, seed, glyph_spans, cache, 'prism-helix')
    letters = g['letters']
    n = len(letters)
    w, h = sprite.size
    p = max(0.0, min(1.0, progress))
    if p >= 1:
        layer.alpha_composite(sprite, (round(x), round(y)))
        return
    hand = 1 if seed % 2 else -1
    pad = round(h * 0.6)
    canvas = Image.new('RGBA', (w + 2 * pad, h + 2 * pad))
    ribbons = Image.new('RGBA', canvas.size)
    rd = ImageDraw.Draw(ribbons)
    flying = []
    for k, (left, right) in enumerate(letters):
        piece = sprite.crop((left, 0, right, h))
        if piece.getbbox() is None:
            continue
        start_k = 0.32 * k / max(1, n)
        q = max(0.0, min(1.0, (p - start_k) / 0.46))
        cx, cy = left + (right - left) / 2, h / 2
        phase = k * 1.1 + seed * 0.4
        if q >= 1:
            flash = max(0.0, 1 - (p - start_k - 0.46) / 0.12)
            canvas.alpha_composite(_brightened(piece, flash * 0.85), (pad + left, pad))
            continue
        e = smoother(q)
        px, py, theta = _helix_point(cx, cy, h, hand, e, phase)
        depth = 0.78 + 0.32 * (0.5 + 0.5 * math.sin(theta))
        hue = k * 0.17 + p * 0.4
        tint = _iridescent(hue)
        shown = _tinted(piece, tint, 0.45 * (1 - e))
        shown = _brightened(shown, 0.25 * (1 - e))
        shown = shown.resize((max(1, round(shown.width * depth)), max(1, round(shown.height * depth))), Image.Resampling.BILINEAR)
        shown, spad = _split(shown, h * 0.06 * (1 - e), 1 - e)
        flying.append((depth, shown, pad + px - shown.width / 2, pad + py - shown.height / 2))
        # the light ribbon the letter leaves along its corkscrew: a band of spectral colours fading behind it
        for back in range(1, 10):
            e0 = smoother(max(0.0, q - (back - 1) * 0.045))
            e1 = smoother(max(0.0, q - back * 0.045))
            if e1 == e0:
                break
            a0 = _helix_point(cx, cy, h, hand, e0, phase)
            a1 = _helix_point(cx, cy, h, hand, e1, phase)
            fade = 1 - back / 10
            width = max(2, round(h * 0.05 * fade))
            for i, colour in enumerate((_iridescent(hue), _iridescent(hue + 0.33), _iridescent(hue + 0.66))):
                off = (i - 1) * h * 0.02
                rd.line([(pad + a0[0] + off, pad + a0[1]), (pad + a1[0] + off, pad + a1[1])], fill=(*colour, round(210 * fade)), width=width)
    glow = ribbons.filter(ImageFilter.GaussianBlur(h * 0.035))
    under = Image.new('RGBA', canvas.size)
    under.alpha_composite(glow)
    under.alpha_composite(ribbons)
    for depth, shown, px, py in sorted(flying, key=lambda f: f[0]):
        under.alpha_composite(shown, (round(px), round(py)))
    under.alpha_composite(canvas)
    # the prism glint: a slanted rainbow band sweeping the locked word
    if 0.74 < p < 0.97:
        sweep = (p - 0.74) / 0.23
        band = Image.new('RGBA', canvas.size)
        bd = ImageDraw.Draw(band)
        bx = -h * 0.5 + (w + h) * sweep
        for i, colour in enumerate(((255, 80, 80), (255, 220, 80), (80, 255, 160), (80, 160, 255), (200, 100, 255))):
            off = (i - 2) * h * 0.04
            bd.line([(pad + bx + off + h * 0.35, pad - h * 0.1), (pad + bx + off - h * 0.35, pad + h * 1.1)],
                    fill=(*colour, 190), width=max(2, round(h * 0.035)))
        bd.line([(pad + bx + h * 0.35, pad - h * 0.1), (pad + bx - h * 0.35, pad + h * 1.1)], fill=(255, 255, 255, 240), width=max(2, round(h * 0.03)))
        band = band.filter(ImageFilter.GaussianBlur(h * 0.012))
        mask = Image.new('L', canvas.size)
        mask.paste(sprite.getchannel('A'), (pad, pad))
        band.putalpha(Image.fromarray((np.asarray(band.getchannel('A')).astype(np.float32) * np.asarray(mask) / 255 * (1 - smoother((p - 0.9) / 0.07))).astype(np.uint8), 'L'))
        under.alpha_composite(band)
    layer.alpha_composite(under, (round(x) - pad, round(y) - pad))



# ---------------------------------------------------------------- prismatic singularity (exit)


def paint_prismatic_singularity(layer, sprite, x, y, amount, seed, intensity, cache, glyph_spans):
    g = _geometry(sprite, seed, glyph_spans, cache, 'prism-sing')
    letters, ink = g['letters'], g['ink']
    w, h = sprite.size
    a = max(0.0, min(1.0, amount))
    hand = 1 if seed % 2 else -1
    pad = round(h * 0.9)
    canvas = Image.new('RGBA', (w + 2 * pad, h + 2 * pad))
    trails = Image.new('RGBA', canvas.size)
    td = ImageDraw.Draw(trails)
    eye = (w / 2, h * 0.42)
    centre = (pad + eye[0], pad + eye[1])
    edges = np.linspace(0, h, SLICES + 1).round().astype(int)
    pieces = []
    for k, (left, right) in enumerate(letters):
        for j in range(SLICES):
            s_top, s_bottom = edges[j], edges[j + 1]
            piece = _slice(sprite, left, right, s_top, s_bottom)
            if piece.getbbox() is None:
                continue
            cx, cy = left + (right - left) / 2, (s_top + s_bottom) / 2
            dist = math.hypot(cx - eye[0], (cy - eye[1]) * 2) / max(1.0, w / 2)
            pieces.append((k, j, piece, cx, cy, dist))
    far = max(p_[5] for p_ in pieces) if pieces else 1.0

    def path(cx, cy, e):
        """Where a slice is at `e` along its fall: one inward spiral turn onto the eye."""
        ang0 = math.atan2(cy - eye[1], cx - eye[0])
        s_ = smoother(e)
        theta = ang0 + hand * s_ * math.tau * 0.85
        radius = math.hypot(cx - eye[0], cy - eye[1]) * (1 - s_)
        return centre[0] + math.cos(theta) * radius, centre[1] + math.sin(theta) * radius * 0.8, theta - ang0, s_

    absorbed = 0.0
    for k, j, piece, cx, cy, dist in pieces:
        start = 0.12 + 0.36 * (dist / max(1e-6, far))  # nearest the eye first; the last leaves by 0.48
        e = (a - start) / 0.26
        if e >= 1:
            absorbed += 1
            continue
        if e <= 0:
            shown = piece
            canvas.alpha_composite(shown, (round(pad + cx - shown.width / 2), round(pad + cy - shown.height / 2)))
            continue
        px, py, turn, s_ = path(cx, cy, e)
        tint = _iridescent(j / SLICES + k * 0.15 + a)
        # a spectral trail along the spiral behind the slice
        points = [path(cx, cy, max(0.0, e - b * 0.05))[:2] for b in range(8)]
        for b in range(7):  # a glowing ribbon that tapers from the slice back along its path
            fade = 1 - b / 7
            td.line([points[b + 1], points[b]], fill=(*tint, round(230 * fade)), width=max(1, round(h * 0.06 * fade * (1 - s_ * 0.5))))
        # the slice stretches along its path and shrinks as it nears the eye
        scale = max(0.06, 1 - s_ * 0.94)
        shown = _tinted(piece, tint, 0.6 * s_)
        shown = _brightened(shown, 0.45 * s_)
        shown = shown.resize((max(1, round(shown.width * scale * (1 + 1.2 * s_))), max(1, round(shown.height * scale * (1 - 0.4 * s_)))),
                             Image.Resampling.BILINEAR)
        shown = shown.rotate(math.degrees(-turn) * 0.8, Image.Resampling.BILINEAR, expand=True)
        canvas.alpha_composite(shown, (round(px - shown.width / 2), round(py - shown.height / 2)))
    glow = trails.filter(ImageFilter.GaussianBlur(h * 0.05))
    under = Image.new('RGBA', canvas.size)
    under.alpha_composite(glow)
    under.alpha_composite(glow)
    under.alpha_composite(trails)
    under.alpha_composite(canvas)
    canvas = under
    # the eye: a point of light that ignites early and swells as it feeds
    warm = tuple(int(255 * 0.6 + c * 0.4) for c in ink)
    ignite = smoother((a - 0.06) / 0.1)
    feed = absorbed / max(1, len(pieces))
    flat = math.sin(math.pi * max(0.0, min(1.0, (a - 0.6) / 0.12)))  # flattens over about four frames, then pops
    core = h * (0.04 + 0.1 * feed) * ignite * (1 - smoother((a - 0.72) / 0.05))
    cx, cy = centre
    if core > 0.3:
        rx, ry = core * (1 + 0.6 * flat), core * (1 - 0.55 * flat)  # squashes before it bursts
        od = ImageDraw.Draw(canvas)
        arm = 2.2
        star = [(cx + rx * arm, cy), (cx + rx * 0.3, cy - ry * 0.3), (cx, cy - ry * arm), (cx - rx * 0.3, cy - ry * 0.3),
                (cx - rx * arm, cy), (cx - rx * 0.3, cy + ry * 0.3), (cx, cy + ry * arm), (cx + rx * 0.3, cy + ry * 0.3)]
        od.polygon(star, fill=(*warm, 255))  # a hard four-point star
        od.ellipse((cx - rx * 0.55, cy - ry * 0.55, cx + rx * 0.55, cy + ry * 0.55), fill=(255, 255, 255, 255))
    # the payoff: the eye pops into a bright filled disc that opens into a ring and fades over five frames
    pop = (a - 0.72) / 0.18
    if 0 < pop < 1:
        flash = Image.new('RGBA', canvas.size)
        fd = ImageDraw.Draw(flash)
        fade = 1 - smoother(pop)
        if pop < 0.3:  # the filled disc
            disc = (h * 0.75 * smoother(pop) + h * 0.08) * 0.9
            fd.ellipse((cx - disc, cy - disc * 0.6, cx + disc, cy + disc * 0.6), fill=(255, 255, 255, round(230 * (1 - pop / 0.3))))
        for i, colour in enumerate((_iridescent(0.0), _iridescent(0.33), _iridescent(0.66))):  # hard rings, a frame apart
            q = max(0.0, min(1.0, (a - 0.72 - i * 0.03) / 0.16))
            if q <= 0 or q >= 1:
                continue
            rr = (w * 0.6 + h * 0.2) * smoother(q) ** 0.7 + h * 0.08  # out to the word's full width
            thick = max(1, round(h * 0.1 * (1 - q) ** 1.5))  # thins to a hairline, then is gone
            fd.ellipse((cx - rr, cy - rr * 0.5, cx + rr, cy + rr * 0.5), outline=(*colour, 255), width=thick)
        canvas.alpha_composite(flash)
    layer.alpha_composite(canvas, (round(x) - pad, round(y) - pad))
