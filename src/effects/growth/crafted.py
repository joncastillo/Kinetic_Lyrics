"""Crafted ornament letterings: the word made of a material, with ornament growing from it letter by letter.

Each lettering here is a painter registered with @crafted(id). It draws one frame from the shared material kit
(signed distance to the glyph, bevel shading, value noise) and a supersampled vector layer for the ornament
(scrolls, braid, pearls, gears and the like). Every painter follows the same shape so the family reads as one
family while each effect keeps its own beat:

- something is on screen from the first frames: the letters arrive in a relay, never fading in from nothing;
- the ornament grows out of the letters over the middle of the entrance, where it is visible in several
  sampled moments;
- a short settle at the end (a gleam, a last bead, a stitch pulled tight) locks the decorated word.

Every frame is a pure function of progress. The last frame is the decorated word, which the renderer holds."""

import math

import numpy as np
from PIL import Image, ImageDraw

from effects.materials.fx import (
    Canvas,
    bevel,
    bloom,
    coverage,
    environment,
    field,
    lambert,
    normals,
    rgb,
    shadow,
    sm,
    smooth,
    specular,
    sun,
)

PAINTERS = {}


def crafted(effect_id, pad=1.0, work_height=None):
    """Register a painter(F, canvas, t, intensity, letters) for an ornament lettering."""

    def register(function):
        PAINTERS[effect_id] = dict(pad=pad, paint=function, work_height=work_height)
        return function

    return register


# ---------------------------------------------------------------- frame assembly


def _letters(F, glyph_spans):
    """Per-pixel letter index and the letter count, from the renderer's glyph spans when it gives them (mapped
    into the working field), else from the gaps between ink columns."""
    def build():
        if glyph_spans:
            edges = sorted({max(0, min(F.W, round(F.P + a * F.scale))) for a, b in glyph_spans[1:]})
            index = np.zeros(F.W, int)
            for edge in edges:
                index[edge:] += 1
            count = len(edges) + 1
        else:
            from scipy.ndimage import label
            columns = F.ink.max(axis=0) > 0.3
            labels, count = label(columns)
            index = np.maximum.accumulate(labels)
            index = np.where(index == 0, 1, index) - 1
            count = max(1, count)
        return np.broadcast_to(index[None, :], F.ink.shape), count
    return F.memo(('crafted-letters', tuple(map(tuple, glyph_spans)) if glyph_spans else None), build)


def paint_crafted(layer, sprite, x, y, progress, effect, seed, intensity=1.0, cache=None, glyph_spans=None):
    """Paint the lettering at `progress` (0 nothing, 1 the decorated word)."""
    recipe = PAINTERS[effect.id]
    F = field(sprite, seed % 9973, recipe['pad'], cache, recipe['work_height'])
    canvas = Canvas(F)
    t = max(0.0, min(1.0, progress))
    recipe['paint'](F, canvas, t, intensity, _letters(F, glyph_spans))
    canvas.c *= sm(t, 0, 0.04)
    border = np.minimum(np.minimum(F.px, F.W - 1 - F.px), np.minimum(F.py, F.H - 1 - F.py))
    canvas.c *= smooth(border, 0, max(3.0, F.P * 0.35))[..., None]
    image = canvas.image()
    if F.scale < 1:
        image = image.resize((round(image.width / F.scale), round(image.height / F.scale)), Image.BICUBIC)
    left, top = round(x - F.P / F.scale), round(y - F.P / F.scale)
    crop = (max(0, -left), max(0, -top), min(image.width, layer.width - left), min(image.height, layer.height - top))
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        return
    layer.alpha_composite(image.crop(crop), (left + crop[0], top + crop[1]))


def held_crafted(sprite, effect, seed, intensity=1.0, cache=None, glyph_spans=None):
    """The finished lettering as a padded image, as (image, padding)."""
    key = ('crafted-held-v1', id(sprite), sprite.size, effect.id, seed, intensity, tuple(map(tuple, glyph_spans or ())))
    if cache is not None and key in cache:
        return cache[key]
    recipe = PAINTERS[effect.id]
    F = field(sprite, seed % 9973, recipe['pad'], cache, recipe['work_height'])
    padding = max(round(sprite.height * 0.7), math.ceil(F.P / F.scale) + 2)
    image = Image.new('RGBA', (sprite.width + 2 * padding, sprite.height + 2 * padding))
    paint_crafted(image, sprite, padding, padding, 1.0, effect, seed, intensity, cache, glyph_spans)
    if cache is not None:
        cache[key] = (image, padding)
    return image, padding


# ---------------------------------------------------------------- shared helpers


def relay(t, count, start, span, each):
    """Local 0-1 progress of every letter: letter k begins at start + span * k / count and takes `each`."""
    k = np.arange(max(1, count))
    begins = start + span * k / max(1, count)
    return np.clip((t - begins) / max(1e-6, each), 0, 1)


def per_pixel(values, letters):
    index, _ = letters
    return np.asarray(values, dtype=float)[np.clip(index, 0, len(values) - 1)]


def letter_boxes(F, letters):
    """(x0, y0, x1, y1) of each letter's ink in the working field."""
    index, count = letters

    def build():
        boxes = []
        inked = F.ink > 0.3
        for k in range(count):
            own = inked & (index == k)
            ys, xs = np.nonzero(own)
            boxes.append((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(xs) else F.box)
        return boxes
    return F.memo(('crafted-boxes', count), build)


def stretch(F, layer, letters, sy, anchor='bottom'):
    """Scale every letter of `layer` (a Canvas) vertically by its own factor in `sy` (one per letter), about
    its foot ('bottom') or its top ('top'), so letters can unroll, spring and pop. A factor of 0 hides the
    letter. Works on the premultiplied canvas in place."""
    from effects.materials.fx import warp
    index, count = letters
    sy = np.asarray(sy, dtype=float)
    if np.allclose(sy, 1):
        return
    boxes = letter_boxes(F, letters)
    base = per_pixel([b[3] if anchor == 'bottom' else b[1] for b in boxes], letters)
    s = per_pixel(np.maximum(sy, 1e-3), letters)
    dy = (F.py - base) * (1 - 1 / s)
    layer.c = warp(F, layer.c, np.zeros_like(dy), dy)
    hidden = per_pixel(sy <= 1e-3, letters) > 0.5
    layer.c[hidden] = 0


def merge(canvas, layer):
    """Lay a premultiplied Canvas `layer` over `canvas`."""
    a = np.clip(layer.c[..., 3:4], 0, 1)
    canvas.c = layer.c + canvas.c * (1 - a)


def spring(q, keys=((0, 0.0), (0.55, 1.1), (0.78, 0.97), (1, 1.0))):
    """Piecewise-smooth keyframes for a 0-1 progress, overshooting and settling."""
    q = max(0.0, min(1.0, q))
    for (q0, v0), (q1, v1) in zip(keys, keys[1:]):
        if q <= q1:
            return v0 + (v1 - v0) * sm(q, q0, q1)
    return keys[-1][1]


def supersampled(F, draw_fn, factor=2):
    """Draw with PIL at `factor` times the working resolution; returns antialiased float (rgb, alpha)."""
    big = Image.new('RGBA', (F.W * factor, F.H * factor))
    draw_fn(ImageDraw.Draw(big), factor)
    small = big.resize((F.W, F.H), Image.LANCZOS)
    rgba = np.asarray(small, dtype=float) / 255
    return rgba[..., :3], rgba[..., 3]


def fill(colour, alpha=255, shade=1.0):
    return tuple(int(np.clip(v * shade, 0, 1) * 255) for v in colour) + (alpha,)


def partial(points, amount):
    """The first `amount` (0-1) of a polyline, ending part way along a segment."""
    end = max(0.0, min(len(points) - 1, amount * (len(points) - 1)))
    whole = int(end)
    chosen = list(points[: whole + 1])
    if whole < len(points) - 1:
        a, b = points[whole], points[whole + 1]
        f = end - whole
        chosen.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    return chosen


def stroke(d, f, points, width, colour, shadow_colour=None, highlight=None, cap=True):
    """A tapering ornament stroke: dark shadow pass, body, and a thin highlight along its upper edge."""
    if len(points) < 2:
        return
    pts = [(px * f, py * f) for px, py in points]
    w = max(1, round(width * f))
    if shadow_colour is not None:
        d.line([(px + f, py + f * 1.2) for px, py in pts], fill=shadow_colour, width=w + 2 * f, joint='curve')
    d.line(pts, fill=colour, width=w, joint='curve')
    if cap:
        r = w / 2
        for px, py in (pts[0], pts[-1]):
            d.ellipse((px - r, py - r, px + r, py + r), fill=colour)
    if highlight is not None and w > f:
        d.line([(px - f * 0.4, py - f * 0.6) for px, py in pts], fill=highlight, width=max(1, w // 3), joint='curve')


def metal(F, tint, width, light=None, roughness=0.0):
    """Polished metal letters: a bevelled solid under a studio environment, keyed by tint and bevel width."""
    def build():
        height = bevel(F.sdf, width)
        if roughness:
            height = height + F.fbm(0.03, 3, 77) * width * roughness
        n = normals(height)
        env = environment(n)
        colour = env * np.asarray(tint) + specular(n, sun() if light is None else light, 70)[..., None] * 1.1
        return np.clip(colour, 0, 1)
    return F.memo(('crafted-metal', tuple(tint), round(width, 2), roughness), build)


def matte(F, albedo, width, light=None, ambient=0.3):
    """Soft-shaded matte letters (enamel, velvet, paper, bark)."""
    def build():
        n = normals(bevel(F.sdf, width))
        diffuse = lambert(n, sun() if light is None else light)
        colour = np.asarray(albedo) * (0.35 + 0.8 * diffuse)[..., None] + ambient * np.array((0.5, 0.56, 0.68)) * 0.3
        return np.clip(colour, 0, 1)
    return F.memo(('crafted-matte', tuple(np.round(albedo, 3)), round(width, 2), ambient), build)


def rim(F, cov, width=0.022, colour=(0.08, 0.05, 0.03), alpha=0.85):
    """A thin dark edge just outside the covered letters, so light materials read on light paintings."""
    from scipy.ndimage import maximum_filter
    size = max(3, int(round(F.u * width)) * 2 + 1)
    grown = maximum_filter(np.asarray(cov, dtype=float), size=size)
    return np.asarray(colour), np.clip(grown - cov, 0, 1) * alpha


def gleam(F, t, start, end, width=0.09, slant=0.35):
    """A bright band sweeping the word left to right between `start` and `end` of the entrance (0-1 per pixel)."""
    if not start < t < end:
        return 0.0
    sweep = -0.25 + 1.5 * sm(t, start, end)
    return np.exp(-(((F.xn + F.yn * slant - sweep) / width) ** 2))


def anchors(F, letters, where):
    """A point on each letter's ink: its 'top', 'bottom', 'left' or 'right' extreme, nearest the middle."""
    index, count = letters

    def build():
        points = []
        inked = F.ink > 0.4
        for k in range(count):
            ys, xs = np.nonzero(inked & (index == k))
            if not len(xs):
                points.append((F.cx, F.cy))
                continue
            cx, cy = xs.mean(), ys.mean()
            if where == 'top':
                score = ys * 3 + np.abs(xs - cx)
            elif where == 'bottom':
                score = -ys * 3 + np.abs(xs - cx)
            elif where == 'left':
                score = xs * 3 + np.abs(ys - cy)
            else:
                score = -xs * 3 + np.abs(ys - cy)
            i = int(np.argmin(score))
            points.append((float(xs[i]), float(ys[i])))
        return points
    return F.memo(('crafted-anchors', count, where), build)


def curl(start, direction, radius, turns=1.4, hand=1, count=40, tighten=0.1):
    """A volute: from `start` it bends away along `direction` and coils into a spiral that tightens to
    `tighten` of its radius. Returns the polyline."""
    dx, dy = math.cos(direction), math.sin(direction)
    nx, ny = -dy * hand, dx * hand
    cx, cy = start[0] + dx * radius + nx * radius * 0.0, start[1] + dy * radius + ny * radius * 0.0
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    points = []
    for i in range(count):
        s = i / (count - 1)
        angle = a0 + hand * s * turns * math.tau
        r = radius * (1 - (1 - tighten) * s**0.9)
        points.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
    return points


def leaf(d, f, point, direction, length, width, colour, shadow_colour=None):
    """A pointed leaf shape along `direction` from `point`."""
    dx, dy = math.cos(direction), math.sin(direction)
    nx, ny = -dy, dx
    shape = []
    for s in (k / 10 for k in range(11)):
        w = width * math.sin(math.pi * s) ** 0.8
        shape.append(((point[0] + dx * length * s + nx * w) * f, (point[1] + dy * length * s + ny * w) * f))
    for s in (k / 10 for k in range(10, -1, -1)):
        w = width * math.sin(math.pi * s) ** 0.8
        shape.append(((point[0] + dx * length * s - nx * w) * f, (point[1] + dy * length * s - ny * w) * f))
    if shadow_colour is not None:
        d.polygon([(px + f, py + f) for px, py in shape], fill=shadow_colour)
    d.polygon(shape, fill=colour)


def star(d, f, point, size, colour, points_=4):
    """A sparkle: a thin four-point star."""
    px, py = point
    for k in range(points_):
        a = k * math.pi / points_
        d.line([((px - math.cos(a) * size) * f, (py - math.sin(a) * size) * f), ((px + math.cos(a) * size) * f, (py + math.sin(a) * size) * f)],
               fill=colour, width=max(1, round(f * 0.9)))


# ---------------------------------------------------------------- gold filigree

GOLD = rgb(255, 196, 92)
GOLD_LIGHT = (255, 232, 170, 255)
GOLD_BODY = (226, 172, 72, 255)
GOLD_DARK = (84, 48, 14, 230)


def scrolls(F, letters, seed_offset=0, count_each=2):
    """The filigree layout: a volute from each letter's top and foot (alternating hands), with a smaller inner
    curl, and where each leaf sits along it."""
    boxes = letter_boxes(F, letters)
    tops, feet = anchors(F, letters, 'top'), anchors(F, letters, 'bottom')

    def build():
        rng = np.random.default_rng(F.seed + 300 + seed_offset)
        u = F.u
        result = []
        many = len(boxes) > 5
        for k, (box, top, foot) in enumerate(zip(boxes, tops, feet)):
            # one volute per letter on long words, alternating top and foot; both on short words
            pairs = ((top, -math.pi / 2), (foot, math.pi / 2))
            for n, (anchor, base_dir) in enumerate(pairs):
                if many and n != k % 2:
                    continue
                hand = 1 if (k + n) % 2 else -1
                direction = base_dir + hand * rng.uniform(0.25, 0.55)
                radius = u * rng.uniform(0.3, 0.44)
                path = curl(anchor, direction, radius, turns=rng.uniform(1.25, 1.5), hand=hand, tighten=0.12)
                inner = curl(anchor, direction - hand * 0.9, radius * 0.5, turns=1.0, hand=-hand, tighten=0.22, count=24)
                birth = 0.28 + 0.3 * k / max(1, len(boxes)) + n * 0.06 + rng.uniform(0, 0.04)
                result.append(dict(path=path, inner=inner, birth=birth, width=u * 0.05, leaves=(0.3, 0.52), hand=hand))
        return result
    return F.memo(('filigree-scrolls', seed_offset), build)


@crafted('gold-filigree-lettering', pad=0.95)
def gold_filigree(F, canvas, t, intensity, letters):
    """Each letter is traced by a bright gold wire that sweeps round its outline, then floods solid from the rim
    inward; volutes unfurl from the top and foot of every letter, sprouting leaves and ending in a bead; a gleam
    sweeps the finished word."""
    index, count = letters
    u = F.u
    light = sun(-2.2, 0.8)
    # every letter is traced and flooded together (the volutes carry the relay), unlike the brocade's wipe
    trace = per_pixel(relay(t, count, 0.0, 0.06, 0.2), letters)
    flood = per_pixel(relay(t, count, 0.1, 0.06, 0.3), letters)
    # the wire: a band on the outline, revealed by a sweep round each letter's centre, starting at the top
    boxes = letter_boxes(F, letters)
    cxs = np.array([(b[0] + b[2]) / 2 for b in boxes])
    cys = np.array([(b[1] + b[3]) / 2 for b in boxes])
    angle = (np.arctan2(F.py - per_pixel(cys, letters), F.px - per_pixel(cxs, letters)) / math.tau + 0.75) % 1
    band = smooth(u * 0.036 - np.abs(F.sdf), 0, u * 0.014)
    swept = smooth(trace * 1.06 - angle, 0, 0.03)
    head = np.exp(-(((angle - trace * 1.06) / 0.04) ** 2)) * (trace < 1) * (trace > 0)
    depth = np.clip(-F.sdf, 0, None)
    dmax = max(2.0, float(depth.max()))
    solid = smooth(flood * dmax * 1.15 - depth, -u * 0.012, u * 0.012) * (flood > 0)
    cov = coverage(F.sdf)
    letter_cov = cov * np.maximum(solid, band * swept)

    # ornament behind the letters
    layout = scrolls(F, letters)

    def draw(d, f):
        for s in layout:
            grown = sm(t, s['birth'], s['birth'] + 0.34)
            if grown <= 0:
                continue
            pts = partial(s['path'], grown)
            stroke(d, f, pts, s['width'] * (0.8 + 0.2 * grown), GOLD_BODY, GOLD_DARK, GOLD_LIGHT)
            inner_grown = sm(t, s['birth'] + 0.12, s['birth'] + 0.4)
            if inner_grown > 0:
                stroke(d, f, partial(s['inner'], inner_grown), s['width'] * 0.6, GOLD_BODY, GOLD_DARK, GOLD_LIGHT)
            for n, at in enumerate(s['leaves']):
                open_ = sm(grown, at + 0.05, at + 0.25)
                if open_ <= 0:
                    continue
                i = round(at * (len(s['path']) - 1))
                a, b = s['path'][max(0, i - 1)], s['path'][min(len(s['path']) - 1, i + 1)]
                tangent = math.atan2(b[1] - a[1], b[0] - a[0])
                side = tangent - s['hand'] * (1.1 + 0.3 * n)
                leaf(d, f, s['path'][i], side, u * 0.14 * open_, u * 0.045 * open_, GOLD_BODY, GOLD_DARK)
            # the bead at the growing tip, left at the end of the coil
            tip = pts[-1]
            r = s['width'] * (0.9 if grown >= 1 else 0.7) * f
            d.ellipse((tip[0] * f - r, tip[1] * f - r, tip[0] * f + r, tip[1] * f + r), fill=GOLD_LIGHT)
        # sparkles on the coils as the word settles
        twinkle = sm(t, 0.84, 0.9) * (1 - sm(t, 0.94, 1.0))
        if twinkle > 0:
            for n, s in enumerate(layout):
                if n % 2:
                    continue
                star(d, f, s['path'][-1], u * 0.07 * twinkle, (255, 250, 230, round(255 * twinkle)))

    orn_rgb, orn_a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(orn_a, F, 0.03, 0.05, 0.03, 0.4))
    canvas.over(orn_rgb, orn_a)

    # the letters: polished gold with a dark rim, the wire white-hot at its head
    body = metal(F, GOLD, u * 0.07, light)
    canvas.over(np.zeros(3), shadow(letter_cov, F, 0.04, 0.07, 0.04, 0.5))
    colour, alpha = rim(F, letter_cov, 0.02, (0.16, 0.09, 0.03), 0.9)
    canvas.over(colour, alpha)
    wire = np.clip(band * swept - solid, 0, 1)
    canvas.over(np.array((1.0, 0.93, 0.72)), cov * wire)
    canvas.over(body, cov * solid)
    canvas.add(np.array((1.0, 0.9, 0.6)) * (head * band * cov)[..., None] * 1.5 + bloom(np.array((1.0, 0.8, 0.4)) * (head * band * cov)[..., None], F, 0.05, 0.8))
    shine = gleam(F, t, 0.8, 0.97)
    if np.any(shine):
        canvas.add(np.ones(3) * (shine * cov * solid * 0.7)[..., None])


import effects.growth.ornaments  # noqa: E402,F401  (registers the other ornament letterings)
import effects.growth.inked  # noqa: E402,F401  (registers the ink and thread letterings)
import effects.growth.blossom  # noqa: E402,F401  (registers the petal letterings)
