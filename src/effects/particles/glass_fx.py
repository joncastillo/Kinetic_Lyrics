"""Glass and liquid-chrome entrances and exits: bold coloured facets, letter relays, a beat before every break-up.

Glass pieces are big facets cut from the word (a Voronoi split, a spider web of cracks, or whole letters), each with
a coloured face, a two-tone rim (deep inside, light outside, so it reads on navy and on cream) and its own slice of
the word's ink. The glass colour is a saturated mid-tone stepped by the word's seed, so neighbouring words differ.
In flight a facet is glass; as it locks it clears to the word's own ink, so a coloured entrance still lands on the
plain word. Relays run letter by letter (letters are found from the gaps between columns of ink). Every frame is a
pure function of progress.

Entrances (p = 1 - amount): something moves from the first frame, every facet has landed by 0.78, the facets
clear under a glint by 0.93, and from 0.95 the plain word is drawn.
Exits (a = amount): the word is intact and readable through the beat (to about 0.2), comes apart with its own
choreography, and every piece has dissolved by 0.94. Nothing travels much further than 1.5 word heights.
"""

import math
import random
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from effects.particles.cache import sprite_key

# saturated mid-tones that hold on navy and cream alike; one per word, stepped by seed
GLASS_PALETTE = ((34, 180, 228), (132, 96, 240), (36, 196, 140), (250, 150, 48), (236, 72, 150), (62, 112, 248))
LOCK_END = 0.95  # entrances: from here the plain word is drawn


def _mix(a, b, f):
    return tuple(round(x + (y - x) * f) for x, y in zip(a, b))


class Palette:
    def __init__(self, seed):
        base = GLASS_PALETTE[seed % len(GLASS_PALETTE)]
        self.base = base
        self.face_light = _mix(base, (255, 255, 255), 0.55)
        self.face_deep = base
        self.rim_dark = tuple(round(c * 0.4) for c in base)
        self.rim_light = _mix(base, (255, 255, 255), 0.88)
        self.glow = _mix(base, (255, 255, 255), 0.35)
        # the dispersion pair, by word: plum and ultramarine, teal and amber, or a darker and a lighter cut of the body
        self.fringe_red, self.fringe_blue = (((160, 28, 120), (40, 80, 230)), ((20, 140, 150), (240, 150, 30)),
                                            (tuple(round(c * 0.5) for c in base), _mix(base, (255, 255, 255), 0.65)))[(seed // 2) % 3]


@dataclass
class Shard:
    ink: Image.Image  # the word's own pixels in this cell, drop shadow included
    glass: Image.Image  # the same cell as a glass facet: coloured face and two-tone rim
    rim: Image.Image  # the rim alone, for cracks that draw on over the intact word
    center: tuple  # in sprite coordinates
    r: tuple  # eight random values in 0..1
    letter: int = 0  # which letter it belongs to
    u: float = 0.0  # the letter's place in the word, 0 first .. 1 last
    lu: float = 0.0  # the facet's own place along the word, 0..1


def clamp01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else float(v)


def smooth(v):
    v = clamp01(v)
    return v * v * (3 - 2 * v)


def ease_out(v):
    v = clamp01(v)
    return 1 - (1 - v) ** 3


def ease_in(v):
    v = clamp01(v)
    return v * v * v


def back_out(v, k=1.4):
    v = clamp01(v)
    u = v - 1
    return 1 + u * u * ((k + 1) * u + k)


_LUTS = {}


def _shade(image, brightness):
    """The image's colour scaled by `brightness`; its alpha untouched (ImageEnhance would scale alpha too)."""
    key = round(brightness * 40)
    if key == 40:
        return image
    table = _LUTS.get(key)
    if table is None:
        b = key / 40
        table = [min(255, round(i * b)) for i in range(256)] * 3 + list(range(256))
        _LUTS[key] = table
    return image.point(table)


def _alpha(image, value):
    if value >= 1:
        return image
    result = image.copy()
    result.putalpha(image.getchannel('A').point(lambda a: round(a * max(0.0, value))))
    return result


def _tinted(image, colour):
    """A flat `colour` in the image's alpha."""
    result = Image.new('RGBA', image.size, (*colour, 0))
    result.putalpha(image.getchannel('A'))
    return result


def _paste(layer, image, left, top):
    """alpha_composite that tolerates a destination left of or above the layer."""
    if image is None:
        return
    if left < 0 or top < 0:
        cl, ct = max(0, -left), max(0, -top)
        if cl >= image.width or ct >= image.height:
            return
        image = image.crop((cl, ct, image.width, image.height))
        left, top = left + cl, top + ct
    if left >= layer.width or top >= layer.height:
        return
    layer.alpha_composite(image, (left, top))


def _place(surface, image, cx, cy, alpha=1.0):
    if image is None or alpha <= 0.01:
        return
    if alpha < 1:
        image = _alpha(image, alpha)
    _paste(surface, image, round(cx - image.width / 2), round(cy - image.height / 2))


# ---------------------------------------------------------------- letters and tessellations

def _letters(sprite):
    """Letter spans (x0, x1) from the gaps between columns of ink; a connected script is one letter."""
    alpha = np.asarray(sprite.getchannel('A'))
    columns = (alpha > 150).any(axis=0)
    spans = []
    start = None
    for x, on in enumerate(columns):
        if on and start is None:
            start = x
        elif not on and start is not None:
            spans.append((start, x))
            start = None
    if start is not None:
        spans.append((start, len(columns)))
    narrow = max(2, sprite.height * 0.04)
    merged = []
    for span in spans:  # a flyspeck column run joins its neighbour
        if merged and (span[1] - span[0] < narrow or merged[-1][1] - merged[-1][0] < narrow) and span[0] - merged[-1][1] < narrow:
            merged[-1] = (merged[-1][0], span[1])
        else:
            merged.append(span)
    return merged or [(0, sprite.width)]


def _clip_rect(polygon, width, height):
    from effects.particles.motion import _clip
    for nx, ny, limit in ((1, 0, width), (-1, 0, 0), (0, 1, height), (0, -1, 0)):
        polygon = _clip(polygon, nx, ny, limit)
        if len(polygon) < 3:
            return []
    return polygon


def _voronoi(size, count, seed):
    from effects.particles.motion import fracture_cells
    return fracture_cells(size, count, seed)


def _web(size, origin, rng, spokes=9, rings=3):
    """A spider web of cracks from `origin`: jittered spokes and rings, so the cells are wedges and chips."""
    width, height = size
    ox, oy = origin
    reach = math.hypot(max(ox, width - ox), max(oy, height - oy)) * 1.02
    angles = [k * math.tau / spokes + rng.uniform(-0.3, 0.3) * math.tau / spokes for k in range(spokes)]
    fractions = [0.0] + [0.12 * 1.6 ** j for j in range(rings) if 0.12 * 1.6 ** j < 1.7] + [2.5]  # rings out past the far end, so no letter is one chip
    radii = [[f * reach * (1 if f in (0.0, 2.5) else rng.uniform(0.78, 1.22)) for _ in range(spokes)] for f in fractions]

    def point(i, j):
        a = angles[i % spokes]
        return ox + math.cos(a) * radii[j][i % spokes], oy + math.sin(a) * radii[j][i % spokes]

    cells = []
    for i in range(spokes):
        for j in range(len(fractions) - 1):
            polygon = [point(i, j), point(i + 1, j), point(i + 1, j + 1), point(i, j + 1)]
            if j == 0:
                polygon = polygon[1:]  # the inner ring is a fan of triangles
            polygon = _clip_rect(polygon, width, height)
            if polygon:
                cells.append(polygon)
    return cells


def _split_by_letters(cells, spans, width):
    """Cut every cell at the letter boundaries, so no shard belongs to two letters."""
    from effects.particles.motion import _clip
    bounds = [0.0] + [(spans[k][1] + spans[k + 1][0]) / 2 for k in range(len(spans) - 1)] + [float(width)]
    out = []
    for polygon in cells:
        for left, right in zip(bounds, bounds[1:]):
            piece = _clip(polygon, -1, 0, -left)
            if len(piece) >= 3:
                piece = _clip(piece, 1, 0, right)
            if len(piece) >= 3:
                out.append(piece)
    return out


def _letter_cells(size, spans):
    width, height = size
    cells = []
    for k, (x0, x1) in enumerate(spans):
        left = 0 if k == 0 else (spans[k - 1][1] + x0) / 2
        right = width if k == len(spans) - 1 else (x1 + spans[k + 1][0]) / 2
        cells.append([(float(left), 0.0), (float(right), 0.0), (float(right), float(height)), (float(left), float(height))])
    return cells


def _face(size, palette):
    """A glass face: lit at the top left, saturated at the bottom right."""
    w, h = size
    g = (np.arange(w, dtype=np.float32)[None, :] / max(1, w - 1) + np.arange(h, dtype=np.float32)[:, None] / max(1, h - 1)) / 2
    light, deep = np.array(palette.face_light, np.float32), np.array(palette.face_deep, np.float32)
    rgb = light[None, None, :] + (deep - light)[None, None, :] * g[..., None]
    stripe = np.exp(-((g - 0.38) / 0.07) ** 2)[..., None]  # a specular stripe across the face
    rgb = rgb + (255 - rgb) * stripe * 0.6
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = rgb.clip(0, 255)
    return Image.fromarray(out, 'RGBA')


def _cut(sprite, polygon, rng, palette, glyph_rim=False):
    width, height = sprite.size
    left = max(0, math.floor(min(x for x, y in polygon)))
    top = max(0, math.floor(min(y for x, y in polygon)))
    right = min(width, math.ceil(max(x for x, y in polygon)))
    bottom = min(height, math.ceil(max(y for x, y in polygon)))
    if right <= left or bottom <= top:
        return None
    points = [(px - left, py - top) for px, py in polygon]
    piece = sprite.crop((left, top, right, bottom))
    mask = Image.new('L', piece.size)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    alpha = ImageChops.multiply(piece.getchannel('A'), mask)
    if alpha.getbbox() is None:
        return None
    piece.putalpha(alpha)
    solid = alpha.point(lambda v: 255 if v > 150 else 0)  # the rim sits on the letters, not on their soft shadow
    rim = Image.new('RGBA', piece.size)
    if glyph_rim:  # a whole letter: a dark edge just inside the glyph, a light line inside that
        thick = 5 if height >= 90 else 3
        inner = solid.filter(ImageFilter.MinFilter(thick))
        edge = ImageChops.subtract(solid, inner)
        dark = Image.new('RGBA', piece.size, (*palette.rim_dark, 255))
        dark.putalpha(edge)
        rim.alpha_composite(dark)
        inner2 = inner.filter(ImageFilter.MinFilter(thick))
        light = Image.new('RGBA', piece.size, (*palette.rim_light, 255))
        light.putalpha(ImageChops.subtract(inner, inner2))
        rim.alpha_composite(light)
    else:
        draw = ImageDraw.Draw(rim)
        draw.line(points + points[:1], fill=(*palette.rim_dark, 255), width=3)
        draw.line(points + points[:1], fill=(*palette.rim_light, 255), width=1)
        rim.putalpha(ImageChops.multiply(rim.getchannel('A'), solid))
    glass = _face(piece.size, palette)
    glass.putalpha(alpha)
    glass.alpha_composite(rim)
    return Shard(piece, glass, rim, ((left + right) / 2, (top + bottom) / 2), tuple(rng.random() for _ in range(8)))


def _assign_letters(shards, spans, width):
    n = len(spans)
    mids = [(a + b) / 2 for a, b in spans]
    for sh in shards:
        k = min(range(n), key=lambda i: abs(mids[i] - sh.center[0]))
        sh.letter = k
        sh.u = k / (n - 1) if n > 1 else 0.5
        sh.lu = sh.center[0] / max(1, width)
    return shards


def _shards(sprite, effect, seed, intensity, cache):
    key = ('glass-fx-v2', sprite_key(sprite), effect.id, seed, round(intensity, 2))
    if cache is not None and key in cache:
        return cache[key]
    rng = random.Random(seed * 7 + 3)
    width, height = sprite.size
    scale = max(0.5, min(1.6, intensity))
    palette = Palette(seed)
    spans = _letters(sprite)
    n = len(spans)
    kind = effect.id
    glyph_rim = False
    if kind in ('glass-shatter', 'glass-impact'):
        x0, x1 = spans[0]
        origin = ((x0 + x1) / 2, height * rng.uniform(0.4, 0.6)) if kind == 'glass-shatter' else (x0 + (x1 - x0) * 0.25, height * rng.uniform(0.4, 0.6))
        cells = _web(sprite.size, origin, rng, spokes=max(8, round(11 * scale)), rings=4 + max(1, round(width / height)))
        cells = _split_by_letters(cells, spans, width)
    elif kind in ('glass-fan', 'glass-sweep'):
        cells = _letter_cells(sprite.size, spans)
        glyph_rim = True
    else:
        per = {'glass-mosaic': 7, 'glass-prism': 6, 'glass-spiral': 6, 'glass-cascade': 5, 'glass-vortex': 5, 'glass-assemble': 3}.get(kind, 5)
        floor = 10 if kind == 'glass-assemble' else 5  # a short word still needs enough facets to dress the hoop
        count = max(floor, min(90, round(per * n * (0.6 + 0.4 * effect.density) * scale)))
        cells = _voronoi(sprite.size, count, seed)
        if kind == 'glass-assemble':  # each letter rides the hoop whole, so no facet spans two letters
            cells = _split_by_letters(cells, spans, width)
    shards = [s for s in (_cut(sprite, polygon, rng, palette, glyph_rim) for polygon in cells) if s is not None]
    shards = _assign_letters(shards, spans, width)
    if cache is not None:
        cache[key] = shards
    return shards


# ---------------------------------------------------------------- drawing helpers

def _surface(sprite, pad):
    return Image.new('RGBA', (sprite.width + 2 * pad, sprite.height + 2 * pad))


def _glint(surface, origin, sprite_size, c, width, strength, colour=(255, 255, 255), band_slope=0.55, hard=False):
    """A diagonal band of light across whatever solid ink is drawn on the surface, within the word's box;
    `hard` makes it a crisp bar instead of a soft band."""
    if strength <= 0.01:
        return
    ox, oy = origin
    W, H = sprite_size
    region = surface.crop((ox, oy, ox + W, oy + H))
    alpha = np.asarray(region.getchannel('A'), np.float32) / 255
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    u = (xx + band_slope * yy) / (W + band_slope * H)
    band = (np.abs(u - c) < width).astype(np.float32) if hard else np.exp(-((u - c) / width) ** 2)
    a = (alpha > 0.75) * band * strength * 255
    out = np.zeros((H, W, 4), np.uint8)
    out[..., :3] = colour
    out[..., 3] = a.clip(0, 255)
    surface.alpha_composite(Image.fromarray(out, 'RGBA'), (ox, oy))


def _flash(surface, origin, sprite_size, centre, radius, strength, colour=(255, 255, 255)):
    """A radial burst of light over the solid ink drawn on the surface, centred on `centre` (sprite coordinates)."""
    if strength <= 0.01:
        return
    ox, oy = origin
    W, H = sprite_size
    region = surface.crop((ox, oy, ox + W, oy + H))
    alpha = np.asarray(region.getchannel('A'), np.float32) / 255
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d2 = ((xx - centre[0]) ** 2 + (yy - centre[1]) ** 2) / max(1.0, radius * radius)
    a = (alpha > 0.75) * np.exp(-d2 * 2.2) * strength * 255
    out = np.zeros((H, W, 4), np.uint8)
    out[..., :3] = colour
    out[..., 3] = a.clip(0, 255)
    surface.alpha_composite(Image.fromarray(out, 'RGBA'), (ox, oy))


def _glow(width, height, colour, strength):
    """A soft elliptical glow with a clean falloff (a blurred RGBA disc would bleed black at its edge)."""
    w, h = max(3, round(width)), max(3, round(height))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d2 = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = colour
    out[..., 3] = (np.exp(-d2 * 3.5) * strength * 255).clip(0, 255)
    return Image.fromarray(out, 'RGBA')


def _ball(radius, palette):
    """A hard glass ball: a shaded sphere with a highlight."""
    r = max(3, round(radius))
    size = r * 2 + 2
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dx, dy = (xx - size / 2) / r, (yy - size / 2) / r
    d2 = dx * dx + dy * dy
    inside = d2 <= 1
    nz = np.sqrt(np.clip(1 - d2, 0, 1))
    lit = np.clip(-dx * 0.45 - dy * 0.6 + nz * 0.7, 0, 1)
    deep, light = np.array(palette.rim_dark, np.float32), np.array(palette.face_light, np.float32)
    rgb = deep + (light - deep) * lit[..., None] ** 1.6
    dot = np.exp(-(((dx + 0.35) ** 2 + (dy + 0.4) ** 2) / 0.03))[..., None]  # the specular dot
    rgb = rgb + (255 - rgb) * dot
    rgb = np.where((d2 > 0.8)[..., None], deep * 0.75, rgb)  # a hard dark rim, like the facets'
    out = np.zeros((size, size, 4), np.uint8)
    out[..., :3] = rgb.clip(0, 255)
    out[..., 3] = inside * 255
    return Image.fromarray(out, 'RGBA')


def _finish(layer, surface, x, y, pad):
    _paste(layer, surface, round(x) - pad, round(y) - pad)


def _facet(sh, tint, brightness, ax=0.0, ay=0.0, az=0.0, depth=1.0):
    """A shard's picture: ink blended toward glass by `tint`, shaded, then tumbled in 3D."""
    from effects.particles.motion import tumble
    image = sh.ink if tint <= 0.01 else sh.glass if tint >= 0.99 else Image.blend(sh.ink, sh.glass, tint)
    image = _shade(image, brightness)
    if abs(ax) + abs(ay) + abs(az) > 0.004 or abs(depth - 1) > 0.004:
        image = tumble(image, ax, ay, az, depth)
    return image


def _squashed(image, sx, sy):
    if abs(sx - 1) < 0.005 and abs(sy - 1) < 0.005:
        return image
    return image.resize((max(1, round(image.width * sx)), max(1, round(image.height * sy))), Image.Resampling.BICUBIC)


def _draw_sorted(surface, items):
    for _, image, cx, cy, alpha in sorted(items, key=lambda item: item[0]):
        _place(surface, image, cx, cy, alpha)


def _clear_and_lock(p, land, hold=0.06, length=0.09):
    """How far a landed facet has cleared to ink: it holds as glass a moment, then clears quickly."""
    return smooth((p - land - hold) / length)


# ---------------------------------------------------------------- entrances

def _e_assemble(surface, sprite, pad, p, shards, effect, seed, intensity, palette):
    """Facets hang on a ring round the word, turning slowly, then the ring collapses onto the word letter by
    letter; each facet flashes as it locks and the last letter lands with an overshoot."""
    W, H = sprite.size
    h = H
    appear = smooth(p / 0.08)
    direction = 1 if seed % 2 else -1
    ring_x, ring_y = 0.575 * W + 0.15 * h, 0.6 * h * min(1.2, effect.spread / 1.65)  # a hoop close round the word
    items = []
    spans = _letters(sprite)
    mids = [(x0 + x1) / 2 for x0, x1 in spans]
    q = clamp01((p - 0.72) / 0.16)
    pulse = 0.06 * math.sin(math.pi * q)  # the whole word swells a little once the last letter lands
    wide = 0.34 * math.sin(math.tau * q) * (1 - q)  # and squashes wide, then stretches tall, then settles
    for sh in shards:
        r = sh.r
        depart = 0.1 + 0.3 * sh.u
        land = depart + 0.36
        s = clamp01((p - depart) / (land - depart))
        e = back_out(s, 1.1)
        # each letter rides the hoop as a small glass letter (its facets kept together, at a third of its size),
        # the letters spaced round the hoop and turning with it, then flies in and grows to full size in turn
        lx, ly = mids[sh.letter], H / 2
        # in reading order along the front (lower) arc of the hoop, left to right, sliding round as it turns
        a = math.pi * 0.88 - sh.u * math.pi * 0.76 + direction * 1.6 * min(p, depart)
        seat = (W / 2 + math.cos(a) * ring_x, H / 2 + math.sin(a) * ring_y)
        size = 0.66 + 0.34 * clamp01(e)
        jitter = 0.0  # the riding letter stays whole
        home_x = seat[0] + (lx - seat[0]) * e + (sh.center[0] - lx) * size + (r[1] - 0.5) * jitter
        home_y = seat[1] + (ly - seat[1]) * e + (sh.center[1] - ly) * size + (r[2] - 0.5) * jitter
        cx = pad + home_x + (sh.center[0] - W / 2) * (pulse + wide)
        cy = pad + home_y + (sh.center[1] - H / 2) * (pulse - wide)
        ax, ay, az = 0.0, 0.0, 0.0  # the riding letters face the camera
        depth = size * (1 + pulse)
        clear = _clear_and_lock(p, land, 0.04, 0.06)
        tint = 0.95 * (1 - clear)
        flash = math.sin(math.pi * clamp01((s - 0.8) / 0.2)) + 0.6 * math.sin(math.pi * clamp01((p - land - 0.03) / 0.07))
        b = (0.85 + 0.35 * abs(math.cos(ax) * math.cos(ay)) + 0.45 * flash) * (1 - clear) + clear + 0.3 * pulse
        image = _facet(sh, tint, b, ax, ay, az, depth)
        if image is not None and abs(wide) > 0.005:
            image = _squashed(image, 1 + wide, 1 - wide)
        items.append((depth, image, cx, cy, appear))
    # the hoop the facets hang on: a thin glass ellipse, a bright arc running round it so the turn reads in a
    # still, thinning away as the letters leave it
    left = 1 - smooth((p - 0.12) / 0.5)
    if left > 0.02:
        hoop = Image.new('RGBA', surface.size)
        draw = ImageDraw.Draw(hoop)
        spin = direction * 6.0 * min(p, 0.4)
        points = [(pad + W / 2 + math.cos(k / 96 * math.tau) * ring_x, pad + H / 2 + math.sin(k / 96 * math.tau) * ring_y) for k in range(97)]
        for k in range(96):
            a = k / 96 * math.tau
            lit = math.cos(a - spin - math.pi * 0.75)  # the bright arc, travelling round with the facets
            glow = max(0.0, lit) ** 3
            colour = _mix(palette.rim_dark, palette.face_light, 0.2 + 0.8 * glow)
            width = max(2, round(h * (0.02 + 0.035 * glow)))
            draw.line([points[k], points[k + 1]], fill=(*colour, round(255 * appear * left * (0.6 + 0.4 * glow))), width=width)
        surface.alpha_composite(hoop)
    _draw_sorted(surface, items)
    k = clamp01((p - 0.82) / 0.12)
    _glint(surface, (pad, pad), sprite.size, -0.25 + 1.5 * k, 0.16, 0.9 * math.sin(math.pi * k))


def _e_mosaic(surface, sprite, pad, p, shards, effect, seed, intensity, palette):
    """A stream of tiles pours in on an arc (from the left, above or the right, by word) and each turns over to
    set, letter by letter from the left; a letter pops as its last tile lands, and a light follows the wave."""
    W, H = sprite.size
    h = H
    appear = smooth(p / 0.08)
    way = seed % 3  # 0 from the upper left, 1 from high above leaning left, 2 from the upper right
    dirx = (-1, -0.55, 1)[way]
    spans = _letters(sprite)
    mids = [(a + b) / 2 for a, b in spans]
    items = []
    for sh in shards:
        r = sh.r
        start = 0.42 * sh.u
        land = start + 0.34
        s = clamp01((p - start) / 0.34)
        e = 0.12 * smooth(p / max(start, 1e-6)) if p < start else 0.12 + 0.88 * ease_out(s)
        # the stream: later tiles further back along one curve, so the stream is a visible arc of tiles
        along = 0.35 + 0.65 * sh.u + 0.2 * r[1]
        ox = -dirx * along * h
        oy = -(0.5 + 0.3 * r[2]) * h - 0.15 * h * along * (1 - abs(dirx))
        cx = pad + sh.center[0] + ox * (1 - e)
        cy = pad + sh.center[1] + oy * (1 - e) - h * 0.25 * math.sin(math.pi * e)
        cx += (1 if way != 2 else -1) * max(h * 0.6, W * 0.45) * math.sin(math.pi * (1 - e))  # the stream bows: an arc, not a column
        sign = 1 if r[4] > 0.5 else -1
        ay = sign * 0.85 * (1 - e)
        az = (r[3] - 0.5) * 1.4 * (1 - e)
        pop = 0.3 * math.sin(math.pi * clamp01((p - land) / 0.1))  # the letter pops as its tiles set
        next_land = 0.42 * min(1.0, (sh.letter + 1) / max(1, len(spans) - 1)) + 0.34
        ripple = math.sin(math.pi * clamp01((p - next_land) / 0.13)) if sh.letter < len(spans) - 1 else 0.0
        mid = mids[sh.letter]
        cx += (sh.center[0] - mid) * pop
        rock = 0.17 * ripple * (1 if sh.letter % 2 else -1)  # a set letter rocks about ten degrees as one rigid piece
        if abs(rock) > 0.002:
            lx, ly = sh.center[0] - mid, sh.center[1] - H / 2
            cx += lx * (math.cos(rock) - 1) - ly * math.sin(rock)
            cy += lx * math.sin(rock) + ly * (math.cos(rock) - 1)
            az += rock
        cy += (sh.center[1] - H / 2) * pop - h * 0.04 * ripple
        depth = 1 + 0.3 * (1 - e) + pop
        clear = _clear_and_lock(p, land, 0.08 + (0.06 if sh.letter == 0 else 0.0), 0.07)
        tint = 0.95 * (1 - clear)
        flash = math.sin(math.pi * clamp01((s - 0.75) / 0.25))
        b = (0.55 + 0.7 * math.cos(ay) + 0.4 * flash) * (1 - clear) + clear
        items.append((depth, _facet(sh, tint, b, 0.0, ay, az, depth), cx, cy, appear))
    _draw_sorted(surface, items)
    front = (p - 0.34) / 0.42  # the letter now landing, in u
    k = clamp01((p - 0.3) / 0.12) * (1 - smooth((p - 0.86) / 0.09))
    _glint(surface, (pad, pad), sprite.size, max(-0.3, min(1.3, front * 0.9 - 0.05)), 0.13, 0.75 * k)


def _e_prism(surface, sprite, pad, p, shards, effect, seed, intensity, palette):
    """Facets rise with crimson and ultramarine fringes that snap together as each letter lands and flashes."""
    W, H = sprite.size
    h = H
    appear = smooth(p / 0.08)
    direction = math.radians((180 if seed % 2 else 0) + (seed % 3 - 1) * 25)  # from beside the word, never below it
    dirx, diry = math.cos(direction), math.sin(direction)
    whiteout = 0.0
    flood = 0.9 if 0.655 <= p < 0.735 else 0.0  # two hard frames of the glass colour through the whole word
    items = []
    for sh in shards:
        r = sh.r
        start = 0.48 * sh.u
        land = start + 0.28
        s = clamp01((p - start) / 0.28)
        e = 0.1 * smooth(p / max(start, 1e-6)) if p < start else 0.1 + 0.9 * back_out(s, 1.5)
        reach = h * (0.4 + 0.3 * r[2]) * min(1.1, effect.spread / 1.9)
        # unflown facets wait scattered, not parked as a second word under the first
        ox = dirx * reach + (r[1] - 0.5) * h * 0.9 * (1 - s) + (r[1] - 0.5) * h * 0.1
        oy = diry * reach + (r[3] - 0.5) * h * 0.5 * (1 - s)
        cx = pad + sh.center[0] + ox * (1 - e)
        cy = pad + sh.center[1] + oy * (1 - e)
        ax, ay = (r[4] - 0.5) * 2.5 * (1 - s) * effect.spin, (r[5] - 0.5) * 2 * (1 - s) * effect.spin
        depth = 1 + 0.25 * (1 - s)
        clear = _clear_and_lock(p, land, 0.04, 0.1)
        tint = 0.95 * (1 - clear)
        flash = math.sin(math.pi * clamp01((p - land) / 0.1))  # three frames, relayed by letter
        b = (0.8 + 0.3 * abs(math.cos(ay)) + 0.6 * flash) * (1 - clear) + clear + whiteout
        image = _facet(sh, tint, b, ax, ay, 0.0, depth)
        split = h * 0.05 * (1 - smooth(s))
        if split > 0.5 and image is not None:
            items.append((depth - 0.01, _tinted(image, palette.fringe_red), cx + split * 0.3, cy + split, appear))
            items.append((depth - 0.01, _tinted(image, palette.fringe_blue), cx - split * 0.3, cy - split, appear))
        items.append((depth, image, cx, cy, appear))
    _draw_sorted(surface, items)
    if flood > 0:  # the word splits into its two fringe colours for one frame, top and bottom, nudged apart
        ox, oy = pad, pad
        region = surface.crop((ox, oy, ox + W, oy + H))
        solid = np.asarray(region.getchannel('A'), np.float32) > 190
        out = np.zeros((H, W, 4), np.uint8)
        rows = np.arange(H)[:, None] < H * 0.5
        out[..., :3] = np.where(rows[..., None], np.array(palette.fringe_red), np.array(palette.fringe_blue))
        out[..., 3] = (solid * 255 * flood).astype(np.uint8)
        surface.alpha_composite(Image.fromarray(out, 'RGBA'), (ox, oy))
    k = clamp01((p - 0.82) / 0.12)
    strength = 0.8 * math.sin(math.pi * k)
    c = -0.25 + 1.5 * k
    _glint(surface, (pad, pad), sprite.size, c + 0.07, 0.06, strength * 0.8, palette.fringe_red)
    _glint(surface, (pad, pad), sprite.size, c, 0.06, strength * 0.8, (255, 255, 255))
    _glint(surface, (pad, pad), sprite.size, c - 0.07, 0.06, strength * 0.8, palette.fringe_blue)


def _e_spiral(surface, sprite, pad, p, shards, effect, seed, intensity, palette):
    """A corkscrew: the facets ride one coil that screws in along the word's axis from the left (or the right, by
    word), the near side of each turn bright and large, the far side dark and small; the coil tightens onto each
    letter in turn and the letters lock in order."""
    W, H = sprite.size
    h = H
    appear = smooth(p / 0.08)
    direction = 1 if seed % 2 else -1  # which end it screws in from
    items = []
    for sh in shards:
        r = sh.r
        u = sh.lu if direction > 0 else 1 - sh.lu
        start = 0.08 + 0.34 * u
        land = start + 0.34
        s = clamp01((p - start) / 0.34)
        e = ease_out(s)
        clear = _clear_and_lock(p, land, 0.03, 0.07)
        tint = 0.95 * (1 - clear)
        flash = math.sin(math.pi * clamp01((s - 0.8) / 0.2))
        # along the axis: it screws in from beyond the near end, a word height and a half out
        back = (1 - e) * (h * 1.0 + max(0.35 * W, 1.5 * h) * (1 - u))  # a short word still gets a long coil
        theta = u * math.tau * 2.2 - p * math.tau * 2.2 + (r[1] - 0.5) * 0.35
        R = h * 0.42 * (1 - e) * min(1.1, effect.spread / 2.1)
        cx = pad + sh.center[0] - direction * back
        cy = pad + H / 2 + (sh.center[1] - H / 2) * e + math.sin(theta) * R
        near = (math.cos(theta) + 1) / 2  # the near side of the turn
        depth = 1 + (0.45 + 0.9 * near - 1) * (1 - e)
        ay = (r[5] - 0.5) * 1.6 * (1 - e) * effect.spin
        az = theta * 0.25 * (1 - e)
        b = (0.4 + 0.9 * near + 0.5 * flash) * (1 - clear) + clear
        items.append((depth, _facet(sh, tint, b, 0.0, ay, az, depth), cx, cy, appear))
    # the coil itself: a thin glass spring along the facets' path, near side bright and thick, far side dark and
    # thin; it shortens as the letters land
    spring = Image.new('RGBA', surface.size)
    draw = ImageDraw.Draw(spring)
    previous = None
    for k in range(161):
        u = k / 160
        s = clamp01((p - 0.08 - 0.34 * u) / 0.34)
        e = ease_out(s)
        fade = (1 - e) * appear
        x_word = (u if direction > 0 else 1 - u) * W
        back = (1 - e) * (h * 1.0 + max(0.35 * W, 1.5 * h) * (1 - u))
        theta = u * math.tau * 2.2 - p * math.tau * 2.2
        R = h * 0.42 * (1 - e) * min(1.1, effect.spread / 2.1)
        point = (pad + x_word - direction * back, pad + H / 2 + math.sin(theta) * R)
        near = (math.cos(theta) + 1) / 2
        if previous is not None and fade > 0.03:
            colour = _mix(palette.rim_dark, palette.face_light, near)
            draw.line([previous, point], fill=(*colour, round(230 * fade * (0.45 + 0.55 * near))), width=max(1, round(h * (0.012 + 0.03 * near))))
        previous = point
    surface.alpha_composite(spring)
    _draw_sorted(surface, items)
    k = clamp01((p - 0.82) / 0.12)
    _glint(surface, (pad, pad), sprite.size, -0.25 + 1.5 * k, 0.16, 0.9 * math.sin(math.pi * k))


def _e_sweep(surface, sprite, pad, p, shards, effect, seed, intensity, palette):
    """Whole letters tumble ahead of a glass pane that sweeps across and squeegees each into place with a squash."""
    W, H = sprite.size
    h = H
    appear = smooth(p / 0.08)
    q = clamp01(p / 0.55)
    X = -0.6 * h + (W + 1.5 * h) * (0.5 * q + 0.5 * (1 - (1 - q) ** 2)) + max(0.0, p - 0.55) * h  # moving from frame one
    chase = -0.3 * h + (W + 1.2 * h) * clamp01((p - 0.44) / 0.36)  # a highlight stripe chases the pane and locks each letter
    items = []
    for sh in shards:
        r = sh.r
        s = clamp01((X - sh.center[0] + 0.35 * h) / (0.9 * h))
        e = ease_out(s)
        ox = (0.15 + 0.35 * r[1]) * h
        oy = (r[2] - 0.5) * h * 0.9
        arc = math.sin(math.pi * e) * h * 0.2 * (1 if r[6] > 0.5 else -1)  # one arc per letter on its way in
        cx = pad + sh.center[0] + ox * (1 - e)
        cy = pad + sh.center[1] + oy * (1 - e) + arc
        az = (r[3] - 0.5) * 1.2 * (1 - e) + 0.25 * (1 - e)
        ay = (r[5] - 0.5) * 0.6 * (1 - e)  # never so edge-on that a letter thins to an outline
        settle = 0.05 * math.sin(math.pi * clamp01((p - 0.8) / 0.1))  # one small settle at the end
        depth = 1 + 0.2 * (1 - e) + settle
        over = (X - sh.center[0]) / (0.8 * h)  # the squash as the pane passes over, then a small rebound
        if over < 1:
            squash = 0.25 * math.sin(math.pi * clamp01(over))
        else:
            squash = -0.22 * math.sin(math.pi * clamp01((over - 1) / 0.55))  # the rebound: it stretches tall
        clear = smooth((chase - sh.center[0]) / (0.25 * h))
        tint = 1.0 * (1 - clear)
        lock = math.sin(math.pi * clamp01((chase - sh.center[0] - 0.15 * h) / (0.35 * h)))
        depth += 0.14 * lock  # each letter locks with a pop
        b = (0.8 + 0.25 * abs(math.cos(ay)) + 0.5 * max(0.0, squash) * 4) * (1 - clear) + clear
        image = _facet(sh, tint, b, 0.0, ay, az, depth)
        if image is not None and tint > 0.01:
            image = Image.blend(image, _tinted(image, palette.base), 0.55 * tint)
        if image is not None and lock > 0.05:  # and flashes an edge in its glass colour as it locks
            image = image.copy()
            image.alpha_composite(_alpha(_tinted(sh.rim, palette.base), lock))
        if image is not None and abs(squash) > 0.01:
            image = _squashed(image, 1 + 0.4 * squash, 1 - squash)
            if squash < -0.01:  # the rebound: stretched tall and leaning with the pane for a moment
                slant = 0.35 * (-squash / 0.22) * min(1.0, max(0.5, (sh.ink.width - 0.12 * h) / (0.45 * h)))  # narrow letters lean less
                image = image.transform((image.width + round(abs(slant) * image.height), image.height), Image.Transform.AFFINE,
                                        (1, slant, -slant * image.height, 0, 1, 0), resample=Image.Resampling.BICUBIC)
            cy += h * 0.2 * squash
        items.append((depth, image, cx, cy, appear))
    _draw_sorted(surface, items)
    g = clamp01((p - 0.44) / 0.3)
    bar = 0.5 * h / max(1, W)  # a crisp white bar about half a letter wide leads the snap to ink
    _glint(surface, (pad, pad), sprite.size, (chase / max(1, W)) * 0.85 + 0.05, bar, 1.0 if 0.02 < g < 0.98 else 0.0, palette.base, band_slope=0.15, hard=True)
    # the pane: a tilted slab, its body in the word's glass colour, a bright leading edge and a specular streak
    k = smooth(p / 0.05) * (1 - smooth((X - W - 0.1 * h) / (0.35 * h)))
    if k > 0.01:
        pane = Image.new('RGBA', surface.size)
        draw = ImageDraw.Draw(pane)
        mid = pad + H / 2
        top, bottom = mid - 0.78 * h, mid + 0.78 * h
        lead, back, tilt = pad + X, pad + X - 0.45 * h, 0.12 * h
        quad = [(back + tilt, top), (lead + tilt, top), (lead - tilt, bottom), (back - tilt, bottom)]
        draw.polygon(quad, fill=(*palette.base, round(205 * k)))
        draw.line([(lead + tilt, top), (lead - tilt, bottom)], fill=(*palette.rim_light, round(240 * k)), width=4)
        draw.line([(lead + tilt - 5, top), (lead - tilt - 5, bottom)], fill=(*palette.rim_dark, round(200 * k)), width=2)
        draw.line([(back + tilt, top), (back - tilt, bottom)], fill=(*palette.rim_dark, round(230 * k)), width=3)
        streak = back + 0.25 * h
        draw.line([(streak + tilt, top + 0.1 * h), (streak - tilt, bottom - 0.1 * h)], fill=(255, 255, 255, round(140 * k)), width=2)
        surface.alpha_composite(pane)


ENTRANCES = {'glass-assemble': _e_assemble, 'glass-mosaic': _e_mosaic, 'glass-prism': _e_prism,
             'glass-spiral': _e_spiral, 'glass-sweep': _e_sweep}


# ---------------------------------------------------------------- exits

def _x_shatter(surface, sprite, pad, a, shards, effect, seed, intensity, palette):
    """A crack star opens on the first letter and spreads letter by letter; the web bulges, then blasts outward."""
    W, H = sprite.size
    h = H
    rng = random.Random(seed * 7 + 3)
    spans = _letters(sprite)
    origin = ((spans[0][0] + spans[0][1]) / 2, H * rng.uniform(0.4, 0.6))
    reach = max(1.0, math.hypot(max(origin[0], W - origin[0]), max(origin[1], H - origin[1])))
    biggest = max(1.0, max(sh.ink.width * sh.ink.height for sh in shards))
    items = []
    for sh in shards:
        r = sh.r
        dist = math.hypot(sh.center[0] - origin[0], sh.center[1] - origin[1]) / reach
        size = sh.ink.width * sh.ink.height / biggest
        # the crack star opens on the first letter; each later letter cracks on its own frame, a beat before it breaks
        crack_at = 0.03 + 0.1 * sh.u + 0.03 * dist
        crack = clamp01((a - crack_at) / 0.04)
        bulge = smooth((a - crack_at - 0.06) / 0.08)
        s = clamp01((a - 0.15 - 0.09 * sh.u - 0.04 * dist - 0.03 * r[0]) / 0.6)
        e = ease_out(s)
        lean = (((sh.letter * 7 + seed) % 5) / 4 - 0.5) * 1.8  # each letter's burst leans its own way, not a neat halo
        angle = math.atan2(sh.center[1] - origin[1], sh.center[0] - origin[0]) + (r[1] - 0.5) * 0.5 + lean
        travel = h * (0.45 + 0.5 * r[2]) * min(1.1, effect.spread / 1.65) * e + h * 0.06 * bulge
        cx = pad + sh.center[0] + math.cos(angle) * travel * 1.1
        cy = pad + sh.center[1] + math.sin(angle) * travel * 0.8 + h * 0.45 * s * s
        ax, ay, az = (r[4] - 0.5) * 3 * s * effect.spin, (r[5] - 0.5) * 3 * s * effect.spin, (r[6] - 0.5) * 4 * s
        depth = 1 + 0.4 * s * (r[7] - 0.3)
        fade = smooth((s - 0.35 - 0.45 * size ** 0.5) / 0.25)  # the smallest shards go first
        tint = 0.9 * crack
        flash = math.sin(math.pi * clamp01((a - crack_at) / 0.12))
        hit = math.sin(math.pi * clamp01(s / 0.1))  # the instant it breaks: a white flash through its shards
        b = 0.8 + 0.4 * abs(math.cos(ax) * math.cos(ay)) * tint + (1 - tint) * 0.2 + 0.5 * flash + 0.9 * hit
        if s <= 0:
            image = _facet(sh, tint, b)
            if crack > 0.01 and tint < 0.9:
                image = image.copy()
                image.alpha_composite(_alpha(sh.rim, crack))
                image.alpha_composite(_alpha(_tinted(sh.rim, palette.rim_dark), 0.8 * crack))
        else:
            image = _facet(sh, tint, b, ax, ay, az, depth * (1 - 0.2 * fade))
        items.append((depth, image, cx, cy, 1 - fade))
    _draw_sorted(surface, items)
    solid = sprite.getchannel('A').point(lambda v: 255 if v > 150 else 0)
    n = len(spans)
    for k, (x0, x1) in enumerate(spans):  # the break: a bright, slightly oversized white silhouette of the letter
        u = k / (n - 1) if n > 1 else 0.5
        burst = math.sin(math.pi * clamp01((a - 0.14 - 0.09 * u) / 0.06))
        if burst < 0.05:
            continue
        glyph = solid.crop((max(0, x0 - 2), 0, min(W, x1 + 2), H))
        white = Image.new('RGBA', glyph.size, (255, 255, 255, 0))
        white.putalpha(glyph.point(lambda v, b=burst: round(v * 0.9 * b)))
        grow = 1 + 0.12 * burst
        white = _squashed(white, grow, grow)
        _place(surface, white, pad + (x0 + x1) / 2, pad + H / 2)
    k = math.sin(math.pi * clamp01((a - 0.02) / 0.2))
    _flash(surface, (pad, pad), sprite.size, origin, h * 0.7, 0.95 * k)


def _x_impact(surface, sprite, pad, a, shards, effect, seed, intensity, palette):
    """A glass ball strikes the first letter; a crack front rolls across and the letters are knocked off one by
    one along the impact direction, each tilting in the plane as it goes."""
    W, H = sprite.size
    h = H
    rng = random.Random(seed * 7 + 3)
    spans = _letters(sprite)
    origin = (spans[0][0] + (spans[0][1] - spans[0][0]) * 0.25, H * rng.uniform(0.4, 0.6))
    gap = min(0.1, 0.5 / max(1, len(spans) - 1))  # one letter knocked off every two frames
    items = []
    for sh in shards:
        r = sh.r
        start = 0.16 + gap * sh.letter + 0.02 * r[0]
        crack = clamp01((a - start + 0.07) / 0.04)
        s = clamp01((a - start) / 0.34)
        e = ease_out(s)
        dx = h * (1.0 + 0.5 * r[2]) * min(1.1, effect.spread / 2.4) * e * 1.2  # flung a word height
        dy = (r[3] - 0.5) * h * 0.5 * s + h * 0.4 * s * s + (1 if (sh.letter + seed) % 2 else -1) * h * 0.55 * e
        depth = 1 / (1 + 0.2 * s)
        az = ((r[6] - 0.5) * 1.2 + 0.35) * s * effect.spin  # an in-plane spin, under about 50 degrees
        fade = smooth((s - 0.4 - 0.25 * min(1.0, sh.ink.width * sh.ink.height / (0.12 * h * h)) ** 0.5) / 0.28)  # gone in the air, big pieces last
        tint = 0.9 * crack
        flash = math.sin(math.pi * clamp01((a - 0.09) / 0.14)) * max(0.0, 1 - sh.u * 2.5)
        b = 0.8 + 0.35 * abs(math.cos(az * 0.5)) * tint + (1 - tint) * 0.2 + 0.6 * flash
        shake = 0.0
        if s <= 0:
            image = _facet(sh, tint, b)
            if crack > 0.01 and tint < 0.9:
                image = image.copy()
                image.alpha_composite(_alpha(sh.rim, crack))
            windup = math.sin(math.pi * clamp01((a - start + 0.06) / 0.06))  # it braces just before it is struck
            if windup > 0.02 and image is not None:
                image = _squashed(image, 1 - 0.12 * windup, 1 + 0.08 * windup)
            if sh.letter > 0:  # the survivors jolt once each time a letter ahead of them is hit
                last_hit = 0.16 + gap * (sh.letter - 1)
                k = clamp01((a - last_hit) / 0.08)
                shake = math.sin(math.pi * k) * h * 0.22 * (1 if sh.letter % 2 else -1)
        else:
            image = _facet(sh, tint, b, 0.0, 0.0, az, depth)
        items.append((-s, image, pad + sh.center[0] + dx + abs(shake), pad + sh.center[1] + dy + shake, 1 - fade))
    _draw_sorted(surface, items)
    # the projectile: a hard glass ball from within a word height to the left, then a flash through the first letter
    t = clamp01(a / 0.1)
    if a < 0.5:
        bx = pad + origin[0] - h * 1.2 * (1 - t) ** 1.2
        by = pad + origin[1] - h * 0.15 * (1 - t)
        ball = _ball(min(h * 0.13, 0.45 * (spans[0][1] - spans[0][0])), palette)  # never dwarfs a thin first letter
        if t < 1:
            trail = Image.new('RGBA', surface.size)
            ImageDraw.Draw(trail).line([(bx - h * 0.5 * (1 - t), by + h * 0.06 * (1 - t)), (bx, by)], fill=(*palette.glow, 150), width=max(2, round(h * 0.03)))
            surface.alpha_composite(trail)
            _place(surface, ball, bx, by)
        else:  # it carries on through the word and out to the right, slowing, dropping and fading
            after = (a - 0.1) / 0.4
            bx += (W + 1.2 * h) * ease_out(after)
            by -= h * 0.9 * math.sin(math.pi * min(1.0, after * 1.2)) * after  # it glances off and arcs away
            _place(surface, ball, bx, by, 1 - smooth((after - 0.6) / 0.4))
    k = math.sin(math.pi * clamp01((a - 0.08) / 0.18))
    if k > 0.01:
        _flash(surface, (pad, pad), sprite.size, origin, h * 0.8, 0.95 * k)


def _x_cascade(surface, sprite, pad, a, shards, effect, seed, intensity, palette):
    """Frost sweeps down and across the word, then the facets let go from the top left and pour away."""
    W, H = sprite.size
    h = H
    box = sprite.getchannel('A').point(lambda v: 255 if v > 150 else 0).getbbox() or (0, 0, W, H)
    top, span = box[1], max(1, box[3] - box[1])
    items = []
    for sh in shards:
        r = sh.r
        v = clamp01((sh.center[1] - top) / span)
        order = 0.5 * v + 0.5 * sh.u
        frost = clamp01((a - 0.02 - 0.24 * (0.85 * sh.u + 0.15 * v)) / 0.04)  # the frost relays across the word, letter by letter
        start = 0.1 + 0.48 * order + 0.08 * r[0]
        speed = 0.6 + 0.7 * r[2]
        tau = max(0.0, a - start) / 0.32
        dy = h * 1.3 * tau * tau * speed
        floor = top + span + 0.3 * h - sh.center[1]  # it lands on a floor below the word, bounces once, then fades
        over = max(0.0, dy - floor) / h
        if over > 0:
            hop = 0.95 if r[2] > 0.55 else 0.15  # the bigger, faster facets take a visible hop
            dy = floor - h * hop * math.sin(math.pi * min(1.0, over / 0.5)) * max(0.0, 1 - over / 0.5)
        dx = ((sh.lu - 0.5) * 0.9 + (r[1] - 0.5) * 0.4) * h * tau  # the fall fans out from the middle
        az = (r[3] - 0.5) * 3.0 * tau
        ay = (r[5] - 0.5) * 2.0 * tau
        depth = 1 + 0.3 * tau * r[6]
        gone = smooth((over - 0.3 - 0.25 * sh.u) / 0.25)  # the bed fades letter by letter
        late = smooth((a - 0.86) / 0.07)
        alpha = (1 - gone) * (1 - late)
        tint = 0.85 * frost
        release = smooth(tau * 6)  # a glint as it lets go
        b = 1 + 0.2 * frost + 0.4 * math.sin(math.pi * release)
        if tau <= 0:
            image = _facet(sh, tint, b)
            rim = math.sin(math.pi * frost) if frost < 1 else 0.0
            if rim > 0.02 and image is not None:  # the frost front: a hard white rim on the facet as it turns
                image = image.copy()
                image.alpha_composite(_alpha(_tinted(sh.rim, (255, 255, 255)), rim))
        else:
            image = _facet(sh, tint, b, 0.0, ay, az, depth)
            if image is not None and tau > 0.05:  # a short streak above, where it was a moment ago
                items.append((tau - 0.5, _alpha(image, 0.3 * alpha), pad + sh.center[0] + dx, pad + sh.center[1] + dy - h * 0.5 * tau * speed, 1.0))
        items.append((tau, image, pad + sh.center[0] + dx, pad + sh.center[1] + dy, alpha))
    _draw_sorted(surface, items)


def _x_fan(surface, sprite, pad, a, shards, effect, seed, intensity, palette):
    """Whole letters squeeze together, fan open about a pivot below the word like a hand of cards, keep spreading,
    and leave one by one from one end of the arc to the other."""
    from core.imaging import turn
    W, H = sprite.size
    h = H
    below = seed % 2 == 0  # the pivot sits below the word (letters arch up) or above it (they hang down)
    reach = (0.4, 0.6, 0.8)[seed % 3] * h
    pivot = (W / 2, H + reach) if below else (W / 2, -reach)
    spread = math.radians((40, 47, 54)[(seed // 2) % 3]) * min(1.1, effect.spread / 2.7) * min(1.0, 2.4 * h / max(1, W))  # long words fan less, so the ends stay in frame
    from_left = (seed // 3) % 2 == 0
    items = []
    for sh in shards:
        r = sh.r
        u = (sh.center[0] - W / 2) / max(1.0, W / 2)  # -1..1
        seam = clamp01((a - 0.02 - 0.06 * abs(u)) / 0.05)
        squeeze = smooth((a - 0.06) / 0.08) * (1 - smooth((a - 0.17) / 0.06))
        s = clamp01((a - 0.17) / 0.36)
        e = back_out(s, 1.0)
        order = sh.u if from_left else 1 - sh.u
        fly = clamp01((a - 0.44 - 0.24 * order) / 0.22)
        wobble = 0.035 * math.sin(a * 9 + r[4] * math.tau) * smooth((a - 0.2) / 0.1)  # each letter sways a little
        angle = (spread * u * (e + 0.35 * max(0.0, a - 0.53)) + wobble) * (1 if below else -1)  # it keeps spreading while letters leave
        rx, ry = sh.center[0] - pivot[0], sh.center[1] - pivot[1]
        rx -= rx * 0.02 * squeeze
        grow = 1 + 0.2 * e  # the arc's radius grows as the fan opens
        rx, ry = rx * grow, ry * grow
        ca, sa = math.cos(angle), math.sin(angle)
        cx = pivot[0] + rx * ca - ry * sa
        cy = pivot[1] + rx * sa + ry * ca
        away = h * 1.6 * fly ** 1.5  # a departing letter flicks off along the arc's tangent, half a letter before it fades
        length = max(1.0, math.hypot(cx - pivot[0], cy - pivot[1]))
        tx, ty = -(cy - pivot[1]) / length, (cx - pivot[0]) / length
        flick = 1 if (from_left == below) else -1
        cx += tx * away * flick
        cy += ty * away * flick
        tint = 0.75 * clamp01(s * 2.5)
        flash = math.sin(math.pi * clamp01((s - 0.1) / 0.5)) * 0.3
        b = 0.95 + 0.3 * abs(math.sin(angle * 2.5 + r[4])) * tint + flash
        image = _facet(sh, tint, b)
        if seam > 0.01 and s < 0.3:
            image = image.copy()
            image.alpha_composite(_alpha(sh.rim, seam * (1 - s / 0.3)))
        if abs(angle) > 0.002:
            image = turn(image, -math.degrees(angle) - 25 * fly * flick)
        scale = 1 - 0.2 * fly
        image = _squashed(image, scale, scale)
        alpha = 1 - smooth((fly - 0.6) / 0.38)
        items.append((abs(u), image, pad + cx, pad + cy, alpha))
    _draw_sorted(surface, items)


def _x_vortex(surface, sprite, pad, a, shards, effect, seed, intensity, palette):
    """The word twists, then its facets whirl outward on a widening spiral, the outer ones flung off first."""
    W, H = sprite.size
    h = H
    direction = 1 if seed % 2 else -1
    C = (W / 2, H / 2)
    reach = max(1.0, math.hypot(W / 2, H / 2))
    spans = _letters(sprite)
    letter_rho = [math.hypot((x0 + x1) / 2 - C[0], 0) / reach for x0, x1 in spans]
    items = []
    for sh in shards:
        r = sh.r
        rx, ry = sh.center[0] - C[0], (sh.center[1] - C[1])
        rho = math.hypot(rx, ry) / reach
        seam = clamp01((a - 0.03 - 0.12 * rho) / 0.06)
        twist = math.radians(2 + 1.0 * (seed % 3)) * smooth(a / 0.3) * (1.3 - 0.6 * rho) * direction
        s = clamp01((a - 0.18 - 0.05 * r[0]) / 0.72)
        # a half turn or more: each letter turns as one for the first half turn (by its own distance from the
        # centre), then its facets shear apart
        cap = math.radians(70) * min(1.0, 1.6 * h / max(1, W))  # a long word turns less, so it stays in frame
        whole = direction * min(cap, effect.twist * 1.5 * (s ** 1.2) * (1.9 - 1.2 * letter_rho[sh.letter]))
        shear = smooth((s - 0.4) / 0.5)
        apart = direction * effect.twist * 1.5 * (shear ** 1.2) * (1.0 * (letter_rho[sh.letter] - rho) + 0.8)  # on it whirls
        spin = whole + apart + twist
        grow = 1 + 0.8 * smooth(s) * (0.6 + 0.4 * r[2])  # the spiral widens as it turns
        # after the shear the facets are drawn onto one circle round the word's centre, so the whirl is round
        phi0, rad0 = math.atan2(ry, rx), math.hypot(rx, ry)
        rad = rad0 + (0.55 * reach - rad0) * shear
        ca, sa = math.cos(phi0 + spin), math.sin(phi0 + spin)
        ex = rad * ca * grow
        ey = rad * sa * grow * (1 - 0.3 * s - 0.3 * shear)  # the ring flattens to an edge-on ellipse: a whirl, not a halo
        cx, cy = pad + C[0] + ex, pad + C[1] + ey + h * 0.12 * s * s
        depth = 1 + 0.3 * s * (0.4 + r[7])
        az = spin * 0.8 + (r[6] - 0.5) * 1.5 * smooth((s - 0.4) / 0.5)
        ay = (r[5] - 0.5) * 2.0 * smooth((s - 0.4) / 0.5) * effect.spin
        fade_at = 0.62 - 0.15 * rho + 0.1 * r[3]  # outer facets go first, trailing off over the last quarter
        fade = smooth((s - fade_at) / 0.3)
        tint = 0.9 * clamp01(seam * 0.5 + s * 3)
        b = (0.95 + 0.35 * abs(math.cos(ay))) * tint + (1 - tint) * (1 + 0.15 * smooth(a / 0.2))
        if s <= 0:
            image = sh.ink
            if abs(twist) > 0.002:
                from effects.particles.motion import tumble
                image = tumble(image, 0.0, 0.0, twist, 1.0)
            if seam > 0.01 and image is not None:
                image = image.copy()
                image.alpha_composite(_alpha(sh.rim, seam))
        else:
            image = _facet(sh, tint, b, 0.0, ay, az, depth)
        items.append((-rho, image, cx, cy, 1 - fade))
    k = math.sin(math.pi * clamp01((a - 0.2) / 0.6))
    if k > 0.01:  # the eye of the whirl
        rad = h * 0.45 * (0.5 + 0.5 * k)
        _place(surface, _glow(rad * 2.4, rad * 1.2, palette.glow, 0.5 * k), pad + C[0], pad + C[1] + h * 0.08)
    _draw_sorted(surface, items)


EXITS = {'glass-shatter': _x_shatter, 'glass-impact': _x_impact, 'glass-cascade': _x_cascade, 'glass-fan': _x_fan,
         'glass-vortex': _x_vortex}


# ---------------------------------------------------------------- liquid chrome

CHROME_STOPS = ((0.0, (250, 252, 254)), (0.44, (204, 214, 224)), (0.49, (62, 70, 84)), (0.52, (84, 92, 108)),
                (0.56, (240, 243, 247)), (1.0, (160, 172, 186)))


def _chrome_rgb(liquid, horizon, phase, ripple, cast=None, cast_amount=0.14):
    """Mirror shading for a liquid coverage map: a silver sky-to-ground gradient with one thin dark horizon,
    rippled while the metal is moving, the top-left edges lit, and a faint colour cast per word."""
    H, W = liquid.shape
    yy = (np.arange(H, dtype=np.float32) / max(1, H))[:, None]
    xx = (np.arange(W, dtype=np.float32) / max(1, W))[None, :]
    v = yy + ripple * (np.sin(xx * 9 + phase) * 0.5 + np.sin(xx * 23 - phase * 1.7) * 0.2) - horizon + 0.5
    v = np.broadcast_to(v, (H, W)).ravel()
    keys = [k for k, _ in CHROME_STOPS]
    rgb = np.stack([np.interp(v, keys, [c[i] for _, c in CHROME_STOPS]) for i in range(3)], axis=-1).reshape(H, W, 3)
    gy, gx = np.gradient(liquid)
    lit = np.clip(-gy * 4 - gx * 2, -1, 1)[..., None]
    rgb = np.where(lit > 0, rgb + (255 - rgb) * lit * 0.9, rgb * (1 + lit * 0.25))  # a soft shaded edge, not a dark sliver
    sheen = np.exp(-((xx + 0.5 * yy - 0.6 - 0.25 * math.sin(phase * 0.5)) / 0.07) ** 2)  # a moving diagonal sheen
    rgb = rgb + (255 - rgb) * np.broadcast_to(sheen, (H, W))[..., None] * 0.45
    if cast is not None:
        rgb = rgb + (np.array(cast, np.float32) - rgb) * cast_amount
    return rgb.astype(np.float32)


def _chrome_layout(sprite, seed, intensity, cache):
    key = ('glass-fx-chrome-v2', sprite_key(sprite), seed, round(intensity, 2))
    if cache is not None and key in cache:
        return cache[key]
    A = np.asarray(sprite.getchannel('A'), np.float32) / 255
    letters = (A > 0.6).astype(np.float32)
    ys, xs = np.nonzero(letters)
    h = sprite.height
    rad = h * (0.06 + 0.015 * (seed % 3)) * max(0.7, min(1.3, intensity))  # drop size, and so their count, varies by word
    rng = np.random.default_rng(seed)
    sites = []
    if len(xs):
        for k in rng.permutation(len(xs)):
            px, py = float(xs[k]), float(ys[k])
            if all((px - sx) ** 2 + (py - sy) ** 2 >= (rad * 1.3) ** 2 for sx, sy, _ in sites):
                sites.append((px, py, tuple(rng.random(4))))
            if len(sites) >= 90:
                break
    bottoms = []
    if len(xs):
        for x0 in range(0, sprite.width, max(4, round(h * 0.1))):
            column = letters[:, x0:x0 + max(4, round(h * 0.1))]
            rows = np.nonzero(column.any(axis=1))[0]
            if len(rows):
                bottoms.append((x0 + column.shape[1] / 2, float(rows.max()), tuple(rng.random(4))))
    soft = np.asarray(Image.fromarray((letters * 255).astype(np.uint8), 'L').filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255
    top = float(ys.min()) if len(xs) else 0.0
    spans = _letters(sprite)
    n = len(spans)
    mids = np.array([(a + b) / 2 for a, b in spans], np.float32)
    column_u = np.zeros(sprite.width, np.float32)
    for x in range(sprite.width):  # each column's letter, as its place in the word
        k = int(np.argmin(np.abs(mids - x)))
        column_u[x] = k / (n - 1) if n > 1 else 0.5
    layout = dict(letters=letters, soft=soft, sites=sites, bottoms=bottoms, rad=rad, top=top, column_u=column_u,
                  phase=tuple(rng.random(3) * math.tau), horizon=0.6 + 0.06 * rng.random())
    if cache is not None:
        cache[key] = layout
    return layout


def _chrome_compose(liquid, rgb, shadow_alpha, shadow_shift):
    """An RGBA image from a coverage map and its shading, with a soft shadow beneath."""
    H, W = liquid.shape
    out = np.zeros((H, W, 4), np.float32)
    out[..., :3] = rgb
    out[..., 3] = liquid * 255
    image = Image.fromarray(out.clip(0, 255).astype(np.uint8), 'RGBA')
    if shadow_alpha is not None:
        shadow = np.zeros((H, W, 4), np.uint8)
        shadow[..., 3] = (shadow_alpha * 255).clip(0, 255).astype(np.uint8)
        base = Image.new('RGBA', (W, H))
        base.alpha_composite(Image.fromarray(shadow, 'RGBA'), (0, shadow_shift))
        base.alpha_composite(image)
        image = base
    return image


def _chrome_entrance(surface, sprite, pad, p, layout, effect, seed, intensity):
    """Mercury drops fly in and merge into a pool thinner than the word; the letters surface through it one by one."""
    W, H = sprite.size
    h = H
    SW, SH = surface.size
    field = Image.new('L', (SW, SH))
    draw = ImageDraw.Draw(field)
    grow = smooth(p / 0.06)
    for sx, sy, r in layout['sites']:
        arrive = 0.22 + 0.3 * r[0]
        s = clamp01(p / arrive)
        e = smooth(s)
        side = 1 if r[1] > 0.5 else -1
        puddle = layout['top'] + H * 0.62 + h * 0.35  # a flat pool of mercury a little below the word
        start = (sx + side * h * 0.25 * r[1], puddle + h * 0.05 * (r[2] - 0.5))
        cx = start[0] + (sx - start[0]) * e
        cy = start[1] + (sy - start[1]) * e - h * 0.18 * math.sin(math.pi * e)  # it climbs, overshoots a little, settles
        radius = layout['rad'] * (0.8 + 0.5 * r[3]) * grow * (1 + 0.5 * smooth((p - arrive) / 0.14))
        draw.ellipse((pad + cx - radius, pad + cy - radius, pad + cx + radius, pad + cy + radius), fill=255)
    F = np.asarray(field.filter(ImageFilter.GaussianBlur(h * 0.045)), np.float32) / 255
    letters = np.zeros((SH, SW), np.float32)
    letters[pad:pad + H, pad:pad + W] = layout['soft']
    k_col = np.zeros(SW, np.float32)  # the letters surface in order, first letter first, over four or five frames each
    u = layout['column_u']
    k_col[pad:pad + W] = np.clip((p - 0.3 - 0.2 * u) / 0.14, 0, 1)
    k_col[:pad] = k_col[pad]  # beyond the word's ends the pool drains with its nearest letter
    k_col[pad + W:] = k_col[pad + W - 1]
    k_col = k_col * k_col * (3 - 2 * k_col)
    pool = F * (1 - 0.6 * k_col[None, :])  # the pool drains away where a letter has surfaced
    blend = pool * (1 - k_col[None, :]) + letters * k_col[None, :]
    harden = 7 + 14 * smooth((p - 0.6) / 0.2)  # the metal hardens: its edges sharpen while the sheen wipes across
    liquid = np.clip((blend - 0.52) * harden, 0, 1)
    ripple = 0.03 * (1 - smooth((p - 0.6) / 0.2))
    rgb = _chrome_rgb(liquid, layout['horizon'] * H / SH + pad / SH, p * 7, ripple, Palette(seed).base, 0.32)
    k = smooth((p - 0.85) / 0.1)  # the metal cools to ink
    shadow = np.asarray(Image.fromarray((liquid * 255).astype(np.uint8), 'L').filter(ImageFilter.GaussianBlur(h * 0.04)), np.float32) / 255 * 0.55 * (1 - k)
    image = _chrome_compose(liquid, rgb, shadow, round(h * 0.035))
    if k > 0.001:  # the metal cools to the word's own ink
        word = Image.new('RGBA', surface.size)
        word.alpha_composite(sprite, (pad, pad))
        image = Image.blend(image, word, k)
    surface.alpha_composite(image)
    g = clamp01((p - 0.62) / 0.16)
    _glint(surface, (pad, pad), sprite.size, -0.2 + 1.4 * g, 0.16, 0.85 * math.sin(math.pi * g), Palette(seed).glow)


def _chrome_exit(surface, sprite, pad, a, layout, effect, seed, intensity):
    """The word turns to mirror, then melts letter by letter from the left into drips that pinch off and splash."""
    W, H = sprite.size
    h = H
    SW, SH = surface.size
    letters = layout['letters']
    k_chrome = smooth(a / 0.2)
    u = layout['column_u']
    sag = np.array([smooth((a - 0.18 - 0.3 * ux) / 0.32) for ux in u], np.float32) * 1.1 * min(1.1, effect.spread / 1.4)
    xs = np.arange(W, dtype=np.float32) / max(1, h)
    ph = layout['phase']
    noise = 0.5 + 0.5 * (np.sin(xs * 2.1 + ph[0]) * 0.5 + np.sin(xs * 4.7 + ph[1]) * 0.3 + np.sin(xs * 9.3 + ph[2]) * 0.2)
    stretch = 1 + sag * (0.35 + 0.65 * noise)
    top = layout['top']
    rows = np.arange(SH, dtype=np.float32)[:, None] - pad
    src = top + (rows - top) / stretch[None, :]
    src_i = np.clip(np.rint(src), -1, H).astype(int)
    padded = np.zeros((H + 2, W), np.float32)
    padded[1:H + 1] = letters
    stretched = np.zeros((SH, SW), np.float32)
    stretched[:, pad:pad + W] = padded[src_i + 1, np.arange(W)[None, :]]
    F = np.asarray(Image.fromarray((stretched * 255).astype(np.uint8), 'L').filter(ImageFilter.GaussianBlur(h * 0.03)), np.float32) / 255
    thr_col = np.full(SW, 0.5, np.float32)  # the metal thins and breaks up letter by letter too; counters hold till the thinning
    thr_col[pad:pad + W] = 0.5 + 0.58 * np.array([smooth((a - 0.48 - 0.2 * ux) / 0.32) for ux in u], np.float32)
    liquid = np.clip((F - thr_col[None, :]) * 10, 0, 1)
    if a < 0.3:  # through the beat the shape is the sprite's own
        exact = np.zeros((SH, SW), np.float32)
        exact[pad:pad + H, pad:pad + W] = np.asarray(sprite.getchannel('A'), np.float32) / 255
        mix = smooth((a - 0.2) / 0.1)
        liquid = exact * (1 - mix) + liquid * mix
    # drops pinch off the lower edges, fall, and splash flat on a floor a word height down
    drops = Image.new('L', (SW, SH))
    draw = ImageDraw.Draw(drops)
    floor = top + h * 0.95
    for bx, by, r in layout['bottoms']:
        column = min(W - 1, max(0, int(bx)))
        start = 0.3 + 0.28 * u[column] + 0.26 * r[0]
        tau = (a - start) / 0.4
        if tau <= 0:
            continue
        y = by + (by - top) * (stretch[column] - 1) + h * 1.7 * tau * tau
        x = bx + math.sin(tau * 5 + r[1] * math.tau) * h * 0.04
        size = h * 0.055 * (0.5 + 0.8 * r[2])
        if y >= floor:  # the splash: a short wide disc that spreads a little and thins away
            since = min(0.5, (y - floor) / h)
            rx_, ry_ = size * (1.3 + 1.2 * since), size * (0.6 - 0.9 * since)
            y = floor
        else:
            rx_ = ry_ = size
        fade = (1 - smooth((a - 0.86) / 0.07))
        if ry_ < 0.6 or fade < 0.02:
            continue
        draw.ellipse((pad + x - rx_, pad + y - ry_, pad + x + rx_, pad + y + ry_), fill=round(255 * fade))
    D = np.asarray(drops.filter(ImageFilter.GaussianBlur(h * 0.015)), np.float32) / 255
    liquid = np.maximum(liquid, np.clip((D - 0.4) * 7, 0, 1))
    rgb = _chrome_rgb(liquid, layout['horizon'] * H / SH + pad / SH, a * 6, 0.05 * smooth((a - 0.1) / 0.3), Palette(seed).base)
    if k_chrome < 1:
        word = np.zeros((SH, SW, 3), np.float32)
        word[pad:pad + H, pad:pad + W] = np.asarray(sprite, np.float32)[..., :3]
        rgb = rgb * k_chrome + word * (1 - k_chrome)
    shadow = np.asarray(Image.fromarray((liquid * 255).astype(np.uint8), 'L').filter(ImageFilter.GaussianBlur(h * 0.04)), np.float32) / 255 * 0.55
    if a < 0.3:
        own = np.zeros((SH, SW), np.float32)
        sprite_alpha = np.asarray(sprite.getchannel('A'), np.float32) / 255
        own[pad:pad + H, pad:pad + W] = sprite_alpha * (sprite_alpha < 0.75)
        mix = smooth((a - 0.2) / 0.1)
        shadow = own * (1 - mix) + shadow * mix
        shift = 0
    else:
        shift = round(h * 0.035)
    image = _chrome_compose(liquid, rgb, shadow, shift)
    surface.alpha_composite(image)
    g = clamp01((a - 0.03) / 0.22)
    _glint(surface, (pad, pad), sprite.size, -0.25 + 1.5 * g, 0.1, 0.85 * math.sin(math.pi * g))


# ---------------------------------------------------------------- entry point

def paint_glass(layer, sprite, x, y, phase, amount, effect, seed, intensity=1.0, cache=None):
    """Draw the word at `amount` (0 the plain word, 1 gone) for any glass or liquid-chrome effect."""
    kind = effect.id
    h = sprite.height
    chrome = kind.startswith('liquid-chrome')
    pad = math.ceil(h * (1.3 if chrome else 1.8)) + 8
    if phase == 'entrance':
        p = 1 - amount
        if p >= LOCK_END:
            _paste(layer, sprite, round(x), round(y))
            return
        surface = _surface(sprite, pad)
        if chrome:
            _chrome_entrance(surface, sprite, pad, p, _chrome_layout(sprite, seed, intensity, cache), effect, seed, intensity)
        else:
            painter = ENTRANCES.get(kind, _e_assemble)
            painter(surface, sprite, pad, p, _shards(sprite, effect, seed, intensity, cache), effect, seed, intensity, Palette(seed))
    else:
        a = amount
        if a >= 0.95:
            return
        surface = _surface(sprite, pad)
        if chrome:
            _chrome_exit(surface, sprite, pad, a, _chrome_layout(sprite, seed, intensity, cache), effect, seed, intensity)
        else:
            painter = EXITS.get(kind, _x_shatter)
            painter(surface, sprite, pad, a, _shards(sprite, effect, seed, intensity, cache), effect, seed, intensity, Palette(seed))
    _finish(layer, surface, x, y, pad)
