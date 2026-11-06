"""The ornament letterings built on the crafted kit (see crafted.py for the shape every painter follows)."""

import math

import numpy as np

from effects.materials.fx import Canvas, mix

from effects.growth.crafted import (
    anchors,
    bloom,
    coverage,
    crafted,
    gleam,
    letter_boxes,
    merge,
    spring,
    stretch,
    matte,
    metal,
    partial,
    per_pixel,
    relay,
    rgb,
    rim,
    shadow,
    sm,
    smooth,
    star,
    stroke,
    sun,
    supersampled,
)


def sweep_angle(F, letters):
    """Each pixel's angle round its own letter's centre, 0-1 from the top clockwise: a needle sweeping round
    the outline reveals a band in this order."""
    boxes = letter_boxes(F, letters)
    cxs = np.array([(b[0] + b[2]) / 2 for b in boxes])
    cys = np.array([(b[1] + b[3]) / 2 for b in boxes])
    return (np.arctan2(F.py - per_pixel(cys, letters), F.px - per_pixel(cxs, letters)) / math.tau + 0.75) % 1


def letter_x(F, letters):
    """0-1 across each letter's own width."""
    boxes = letter_boxes(F, letters)
    x0 = per_pixel([b[0] for b in boxes], letters)
    x1 = per_pixel([b[2] for b in boxes], letters)
    return np.clip((F.px - x0) / np.maximum(1, x1 - x0), 0, 1)


def interior_points(F, letters, spacing, depth_min):
    """Points well inside each letter, at least `spacing` apart, deepest first: where gems and polyps sit."""
    index, count = letters

    def build():
        depth = np.clip(-F.sdf, 0, None)
        result = []
        for k in range(count):
            ys, xs = np.nonzero((index == k) & (depth > depth_min))
            if not len(xs):
                result.append([])
                continue
            order = np.argsort(-depth[ys, xs])
            chosen = []
            for i in order:
                p = (float(xs[i]), float(ys[i]))
                if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 > spacing * spacing for q in chosen):
                    chosen.append(p)
                if len(chosen) >= 24:
                    break
            result.append(chosen)
        return result
    return F.memo(('interior', count, round(spacing, 1), round(depth_min, 1)), build)


# ---------------------------------------------------------------- jewelled brocade

VELVET = rgb(206, 40, 82)  # crimson velvet, bright enough to hold on a dusk painting
BRAID = (236, 186, 86, 255)
BRAID_SHADE = (120, 76, 22, 240)
# one gem family per word, in a light and a deep tone, each clear of the crimson: sapphire, emerald, amethyst, topaz
GEM_FAMILIES = (((70, 130, 245), (28, 52, 160)), ((40, 196, 128), (12, 110, 70)),
                ((196, 96, 236), (110, 40, 150)), ((250, 196, 70), (190, 120, 20)))


def brocade_layout(F, letters):
    """Gems set into each letter, and gold tassels hanging from its foot."""
    boxes = letter_boxes(F, letters)
    points = interior_points(F, letters, F.u * 0.26, F.u * 0.055)

    def build():
        rng = np.random.default_rng(F.seed + 410)
        u = F.u
        gems, tassels = [], []
        for k, (box, inside) in enumerate(zip(boxes, points)):
            for n, p in enumerate(inside[:1]):  # one big stone per letter, set like a brooch
                gems.append(dict(point=p, size=u * 0.13,                                  birth=0.42 + 0.3 * k / max(1, len(boxes)) + n * 0.07, phase=rng.uniform(0, math.tau)))
            width = box[2] - box[0]
            for n in range(2 if width < u * 0.5 else 3):
                x = box[0] + width * (0.25 + 0.5 * n / max(1, (2 if width < u * 0.5 else 3) - 1)) + rng.uniform(-0.03, 0.03) * u
                tassels.append(dict(x=x, y=box[3] - u * 0.01, length=u * rng.uniform(0.2, 0.3), birth=0.5 + 0.25 * k / max(1, len(boxes)) + n * 0.03,
                                    phase=rng.uniform(0, math.tau)))
        return gems, tassels
    return F.memo('brocade-layout', build)


def gem(d, f, point, size, colour, alpha=255):
    """A faceted hexagonal gem with a dark setting and a glint."""
    x, y = point[0] * f, point[1] * f
    r = size * f
    d.ellipse((x - r * 1.18, y - r * 1.18, x + r * 1.18, y + r * 1.18), fill=(70, 46, 18, alpha))
    verts = [(x + math.cos(a) * r, y + math.sin(a) * r) for a in (k * math.pi / 3 - math.pi / 2 for k in range(6))]
    dark = tuple(round(c * 0.45) for c in colour)
    d.polygon(verts, fill=(*dark, alpha))
    for n in range(6):
        shade = 1.2 if n in (0, 5) else 0.95 if n in (1, 4) else 0.7
        c = tuple(min(255, round(v * shade)) for v in colour)
        d.polygon([(x, y), verts[n], verts[(n + 1) % 6]], fill=(*c, alpha))
    inner = [(x + (vx - x) * 0.5, y + (vy - y) * 0.5) for vx, vy in verts]
    d.polygon(inner, fill=(*tuple(min(255, round(v * 1.1 + 20)) for v in colour), alpha))
    g = max(1.0, r * 0.22)
    d.ellipse((x - r * 0.4 - g, y - r * 0.45 - g, x - r * 0.4 + g, y - r * 0.45 + g), fill=(255, 255, 245, alpha))


@crafted('jeweled-brocade-lettering', pad=0.8)
def jeweled_brocade(F, canvas, t, intensity, letters):
    """Each letter unrolls downward like a velvet banner from its top edge, from the middle of the word outward,
    overshooting and settling; a gold braid is stitched round it by a needle flash; gems of one family (ruby,
    sapphire, emerald or amethyst, by word) snap into their settings with a glint, and tassels drop and swing."""
    index, count = letters
    u = F.u
    light = sun(-2.1, 0.75)
    middle = (count - 1) / 2
    order = np.abs(np.arange(count) - middle) / max(1, middle) if count > 1 else np.zeros(1)
    local = np.clip((t + 0.06 - order * 0.26) / 0.24, 0, 1)
    unroll = [spring(q, ((0, 0.0), (0.6, 1.12), (0.82, 0.96), (1, 1.0))) if q > 0 else 0.0 for q in local]
    needle = per_pixel(np.clip((t - 0.1 - order * 0.26) / 0.26, 0, 1), letters)
    cov = coverage(F.sdf)
    angle = sweep_angle(F, letters)
    braid_band = smooth(u * 0.05 - F.sdf, 0, u * 0.012) * smooth(F.sdf + u * 0.012, 0, u * 0.012)
    stitched = smooth(needle * 1.06 - angle, 0, 0.03)
    needle_head = np.exp(-(((angle - needle * 1.06) / 0.035) ** 2)) * (needle < 1) * (needle > 0)
    # velvet: a soft nap with a slight sheen, darker toward the edges; folds ripple while it unrolls
    nap = 0.86 + 0.14 * F.fbm(0.05, 3, 411)
    body = matte(F, VELVET, u * 0.05, light, ambient=0.32) * nap[..., None]
    depth = np.clip(-F.sdf, 0, None)
    body = body * (0.72 + 0.28 * smooth(depth, 0, u * 0.06))[..., None]
    rolling = per_pixel([1 - q for q in local], letters)
    folds = 1 - 0.25 * rolling * (0.5 + 0.5 * np.sin(F.py / (u * 0.06)))
    body = body * folds[..., None]
    twist = 0.5 + 0.5 * np.sin((F.px + F.py) / (u * 0.014))
    braid = mix(rgb(120, 72, 20), rgb(246, 200, 104), twist**1.4)
    braid_cov = braid_band * stitched

    banner = Canvas(F)
    banner.over(np.zeros(3), shadow(cov, F, 0.04, 0.07, 0.04, 0.5))
    colour, alpha = rim(F, cov, 0.018, (0.12, 0.05, 0.03), 0.85)
    banner.over(colour, alpha)
    banner.over(body, cov)
    banner.over(braid, braid_cov)
    banner.add(np.array((1.0, 0.95, 0.8)) * (needle_head * braid_band)[..., None] * 1.4)
    stretch(F, banner, letters, unroll, anchor='top')
    merge(canvas, banner)

    gems, tassels = brocade_layout(F, letters)
    family = GEM_FAMILIES[F.seed % len(GEM_FAMILIES)]

    def draw(d, f):
        for ts in ():  # (no tassels: they read as drips)
            drop = sm(t, ts['birth'], ts['birth'] + 0.2)
            if drop <= 0:
                continue
            swing = 0.55 * math.sin(t * 16 + ts['phase']) * (1 - sm(t, ts['birth'] + 0.15, 1.0)) + 0.08 * math.sin(t * 5 + ts['phase'])
            length = ts['length'] * drop
            pts = [(ts['x'], ts['y'])]
            for n in range(1, 7):
                s_ = n / 6
                pts.append((ts['x'] + math.sin(swing * s_) * length * s_, ts['y'] + math.cos(swing * s_) * length * s_))
            stroke(d, f, pts, u * 0.016, BRAID, BRAID_SHADE, cap=False)
            end = pts[-1]
            r = u * 0.028 * drop * f
            d.ellipse((end[0] * f - r, end[1] * f - r, end[0] * f + r, end[1] * f + r), fill=(90, 56, 14, 255))
            d.ellipse((end[0] * f - r * 0.8, end[1] * f - r * 0.8, end[0] * f + r * 0.6, end[1] * f + r * 0.6), fill=BRAID)
            for k in range(4):  # the fringe
                a = swing + (k - 1.5) * 0.35
                fx, fy = end[0] + math.sin(a) * u * 0.1 * drop, end[1] + math.cos(a) * u * 0.1 * drop
                d.line([(end[0] * f, end[1] * f), (fx * f, fy * f)], fill=BRAID, width=max(1, round(f * u * 0.008)))
        for n, g in enumerate(gems):
            pop = sm(t, g['birth'], g['birth'] + 0.14)
            if pop <= 0:
                continue
            size = g['size'] * pop * (1 + 0.4 * math.sin(math.pi * pop))
            gem(d, f, g['point'], size, family[n % 2])
            glint = sm(t, g['birth'] + 0.08, g['birth'] + 0.14) * (1 - sm(t, g['birth'] + 0.2, g['birth'] + 0.3))
            if glint > 0:
                star(d, f, g['point'], u * 0.12 * glint, (255, 252, 236, round(255 * glint)))

    orn_rgb, orn_a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(orn_a, F, 0.03, 0.05, 0.03, 0.4))
    canvas.over(orn_rgb, orn_a)
    shine = gleam(F, t, 0.82, 0.97, 0.08)
    if np.any(shine):
        canvas.add(np.array((1.0, 0.9, 0.7)) * (shine * braid_cov * 0.9 + shine * cov * 0.15)[..., None])


# ---------------------------------------------------------------- pearl lace

# deep satin bodies, one per word (plum, teal, oxblood, navy), so the ivory pearls hold on dusk and on paper
SATINS = (rgb(104, 34, 88), rgb(18, 92, 98), rgb(116, 22, 34), rgb(30, 42, 104))
PEARL = ((238, 226, 220), (255, 250, 246), (182, 166, 160))


def bead_layout(F, letters):
    """Pearl slots round each letter's outline as (x, y, s), s the 0-1 place along that letter's strand from
    its top, and the swags hung under the baseline between neighbouring letters."""
    from skimage.measure import find_contours
    index, count = letters

    def build():
        u = F.u
        gap = u * 0.1
        strands = []
        for k in range(count):
            own = F.ink * (index == k)
            beads = []
            for loop in (c for c in find_contours(own, 0.5) if len(c) > 8):
                pts = loop[:, ::-1]
                top = int(np.argmin(pts[:, 1] * 3 + np.abs(pts[:, 0] - pts[:, 0].mean())))
                pts = np.roll(pts, -top, axis=0)
                run = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
                for d in np.linspace(0, run[-1], max(3, int(run[-1] / gap)), endpoint=False):
                    i = min(len(run) - 2, int(np.searchsorted(run, d, 'right') - 1))
                    f = (d - run[i]) / max(1e-6, run[i + 1] - run[i])
                    beads.append(tuple(pts[i] + (pts[i + 1] - pts[i]) * f))
            strands.append([(x, y, j / max(1, len(beads))) for j, (x, y) in enumerate(beads)])
        feet = anchors(F, letters, 'bottom')
        base = F.box[3] - u * 0.04
        swags = [((feet[k][0], base), (feet[k + 1][0], base)) for k in range(count - 1)]
        if count == 1:
            swags.append(((F.box[0] - u * 0.1, base), (F.box[2] + u * 0.1, base)))
        return strands, swags
    return F.memo(('pearl-beads', count), build)


def pearl(d, f, point, size, alpha=255, glint=0.0, shade=PEARL):
    x, y = point[0] * f, point[1] * f
    r = size * f
    d.ellipse((x - r * 1.05, y - r * 0.75, x + r * 1.05, y + r * 1.25), fill=(50, 36, 40, round(alpha * 0.4)))
    d.ellipse((x - r, y - r, x + r, y + r), fill=(*shade[2], alpha))
    d.ellipse((x - r * 0.92, y - r * 0.95, x + r * 0.75, y + r * 0.7), fill=(*shade[0], alpha))
    d.ellipse((x - r * 0.6, y - r * 0.65, x + r * 0.1, y - r * 0.05), fill=(*shade[1], alpha))
    g = max(0.8, r * 0.22)
    d.ellipse((x - r * 0.4 - g, y - r * 0.45 - g, x - r * 0.4 + g, y - r * 0.45 + g), fill=(255, 255, 255, alpha))
    if glint > 0:
        star(d, f, point, size * 3.0 * glint, (255, 255, 250, round(255 * glint)))


def swing(q):
    """A swag dropping on its thread: falls past its rest, swings back once, settles."""
    return spring(q, ((0, 0.0), (0.4, 1.3), (0.65, 0.85), (0.85, 1.05), (1, 1.0)))


def lit(tone, amount):
    return tuple(tuple(min(255, round(c + (255 - c) * amount)) for c in shade) for shade in tone)


@crafted('pearl-lace-lettering', pad=0.85)
def pearl_lace(F, canvas, t, intensity, letters):
    """Pearls are threaded round each letter's outline, popping on one after another from the top of the letter
    like a strand being strung; the ivory satin body then rises inside the bead border, and pearl swags drop
    under the baseline from letter to letter, swing once and settle, before a glint runs along the strands."""
    index, count = letters
    u = F.u
    light = sun(-2.0, 0.8)
    strands, swags = bead_layout(F, letters)
    order = np.argsort(np.argsort([abs(k - (count - 1) / 2) for k in range(count)]))  # middle letters first
    threads = [min(1.0, max(0.0, (t - 0.04 - 0.22 * order[k] / max(1, count)) / 0.36)) for k in range(count)]
    boxes = letter_boxes(F, letters)
    y0 = per_pixel([b[1] for b in boxes], letters)
    y1 = per_pixel([b[3] for b in boxes], letters)
    yl = np.clip((y1 - F.py) / np.maximum(1, y1 - y0), 0, 1)  # 0 at the foot, 1 at the top
    rise = per_pixel([sm(q, 0.55, 1.0) * 1.15 for q in threads], letters)
    cov = coverage(F.sdf) * smooth(rise - yl, 0, 0.08)
    satin = SATINS[F.seed % len(SATINS)]
    body = matte(F, satin, u * 0.05, light, ambient=0.4)
    sheen = 0.5 + 0.5 * np.sin(F.px / (u * 0.35) + F.py / (u * 0.2))
    body = mix(body, np.clip(np.asarray(satin) * 1.8 + 0.1, 0, 1), (sheen * 0.35)[..., None])
    body = body * (0.94 + 0.06 * np.sin(F.py / (u * 0.018)))[..., None]
    front = np.exp(-(((yl - rise) / 0.035) ** 2)) * coverage(F.sdf) * (rise > 0) * (rise < 1.1)
    drop = sm(t, 0.5, 0.86)
    shine = sm(t, 0.72, 0.76) * (1 - sm(t, 0.95, 0.99))
    sweep = (t - 0.72) / 0.22 * 1.3 - 0.15  # a glint streak running round every strand

    def draw(d, f):
        for k, beads in enumerate(strands):
            q = threads[k]
            if q <= 0:
                continue
            for x, y, s in beads:
                local = (q * 1.12 - s) / 0.12
                if local <= 0:
                    continue
                size = u * 0.052 * spring(local, ((0, 0.0), (0.5, 1.35), (0.8, 0.94), (1, 1.0)))
                lead = max(0.0, 1 - local) * 0.9  # the newest pearls flash white as they land
                glint = shine * max(0.0, 1 - abs(s - sweep) / 0.09)
                needle = q < 1 and local < 0.35  # the strand's head: a bright pearl with a star, like a needle
                if needle:
                    size *= 1.4
                    glint = max(glint, 0.55)
                size *= 1 + 0.3 * glint  # the glint lifts the pearls it passes
                pearl(d, f, (x, y), size, 255, min(1.0, glint), lit(PEARL, lead) if lead > 0 else PEARL)
        if drop <= 0:
            return
        for j, (a, b) in enumerate(swags):
            q = min(1.0, max(0.0, (drop - 0.08 * j / max(1, len(swags))) / 0.85))
            if q <= 0:
                continue
            span = math.hypot(b[0] - a[0], b[1] - a[1])
            sag = min(u * 0.5, span * 0.36) * swing(q)  # a round scallop, never a V
            n = max(5, int(span / (u * 0.055)))
            shown = n * min(1.0, q * 3)  # the strand pays out from its middle
            for i in range(n + 1):
                if abs(i - n / 2) > shown / 2 + 0.5:
                    continue
                s_ = i / n
                x = a[0] + (b[0] - a[0]) * s_
                y = a[1] + (b[1] - a[1]) * s_ + sag * math.sin(math.pi * s_)
                pearl(d, f, (x, y), u * (0.026 + 0.018 * math.sin(math.pi * s_)), 255)
            centre = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + sag + u * 0.09)
            pearl(d, f, centre, u * 0.065 * sm(q, 0.25, 0.5), 255, shine * 0.8)  # a drop pearl at the low point

    orn_rgb, orn_a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(cov, F, 0.03, 0.06, 0.04, 0.42))
    colour, alpha = rim(F, np.maximum(cov, orn_a), 0.022, (0.3, 0.14, 0.18), 0.9)  # dark rose, so ivory holds on cream
    canvas.over(colour, alpha)
    canvas.over(body, cov)
    canvas.add(np.array((1.0, 0.7, 0.9)) * front[..., None] * 0.6)
    canvas.over(np.zeros(3), shadow(orn_a, F, 0.015, 0.035, 0.02, 0.4))
    canvas.over(orn_rgb, orn_a)


# ---------------------------------------------------------------- luminous coral

CORAL = rgb(64, 196, 186)  # a luminous turquoise reef with magenta fans, far from the brocade's crimson
CORAL_DEEP = rgb(22, 104, 118)
BRANCH = (222, 72, 150, 255)
BRANCH_SHADE = (90, 18, 60, 220)
BRANCH_LIGHT = (255, 176, 214, 255)
POLYP = np.array((0.75, 1.0, 0.6))


def coral_layout(F, letters):
    """Fan-coral branches growing from each letter's top (and a few feet), and the polyps on the letters."""
    tops, feet = anchors(F, letters, 'top'), anchors(F, letters, 'bottom')
    polyps = interior_points(F, letters, F.u * 0.11, F.u * 0.03)

    def build():
        rng = np.random.default_rng(F.seed + 620)
        u = F.u
        segments = []

        def grow(start, direction, length, width, birth, level):
            pts = []
            for i in range(10):
                s = i / 9
                bend = direction + math.sin(s * 3 + level) * 0.25
                pts.append((start[0] + math.cos(bend) * length * s, start[1] + math.sin(bend) * length * s))
            segments.append(dict(points=pts, width=width, birth=birth, span=0.16 - level * 0.03, tip=level >= 1))
            if level < 1:  # fewer, stouter branches
                for frac, side in ((0.6, -1), (0.85, 1)):
                    grow(pts[round(frac * 9)], direction + side * rng.uniform(0.5, 0.9) + (0.15 if side == 0 else 0),
                         length * rng.uniform(0.5, 0.7), width * 0.65, birth + (0.16 - level * 0.03) * frac, level + 1)

        for k, (top, foot) in enumerate(zip(tops, feet)):
            birth = 0.3 + 0.3 * k / max(1, len(tops))
            if k % 2 == 0 or len(tops) < 3:  # one stout fan on every other letter, above it only
                grow(top, -math.pi / 2 + rng.uniform(-0.35, 0.35), u * rng.uniform(0.3, 0.4), u * 0.065, birth, 0)
        return segments
    return F.memo('coral-layout', build), polyps


@crafted('luminous-coral-lettering', pad=0.8)
def luminous_coral(F, canvas, t, intensity, letters):
    """Knobbly coral letters grow up from their feet with a ragged front; fan-coral branches sprout from the
    letter tops in magenta; then the polyps light up cyan in a wave along the word and the branch tips glow."""
    index, count = letters
    u = F.u
    light = sun(-2.0, 0.7)
    middle = (count - 1) / 2
    order = np.abs(np.arange(count) - middle) / max(1, middle) if count > 1 else np.zeros(1)
    grown = per_pixel(np.clip((t + 0.04 - order * 0.2) / 0.28, 0, 1), letters)
    boxes = letter_boxes(F, letters)
    cxs = per_pixel([(b[0] + b[2]) / 2 for b in boxes], letters)
    cys = per_pixel([(b[1] + b[3]) / 2 for b in boxes], letters)
    reach = per_pixel([math.hypot(b[2] - b[0], b[3] - b[1]) / 2 for b in boxes], letters)
    up = np.hypot(F.px - cxs, F.py - cys) / np.maximum(1, reach)  # 0 at the heart of the letter, 1 at its corners
    knob = 0.1 * F.fbm(0.06, 3, 621)
    revealed = smooth(grown * 1.14 - up + knob, 0, 0.08)
    cov = coverage(F.sdf) * revealed
    # knobbly coral: a bumpy bevel, warm pink tops and deeper crevices
    from effects.materials.fx import bevel, lambert, normals, specular
    height = bevel(F.sdf, u * 0.07) + F.fbm(0.05, 2, 622) * u * 0.012 * smooth(-F.sdf, 0, u * 0.04)
    n = normals(height)
    bumps = 0.5 + 0.5 * F.fbm(0.05, 3, 623)
    albedo = mix(CORAL_DEEP, CORAL, smooth(bumps, 0.45, 0.55))  # two clean tones, not speckle
    lit = per_pixel([sm(t, 0.6 + 0.26 * k / max(1, count), 0.64 + 0.26 * k / max(1, count)) for k in range(count)], letters)
    albedo = mix(albedo, np.array(rgb(150, 250, 214)), (lit * 0.7)[..., None])  # each letter steps up to mint in turn
    body = albedo * (0.4 + 0.75 * lambert(n, light))[..., None] + specular(n, light, 30)[..., None] * 0.25
    body = np.clip(body, 0, 1)

    segments, polyps = coral_layout(F, letters)
    wave = [sm(t, 0.56 + 0.26 * (p[0] - F.box[0]) / max(1, F.box[2] - F.box[0]), 0.64 + 0.26 * (p[0] - F.box[0]) / max(1, F.box[2] - F.box[0]))
            for inside in polyps for p in inside]
    points = [p for inside in polyps for p in inside]

    def draw(d, f):
        for seg in segments:
            g = sm(t, seg['birth'], seg['birth'] + seg['span'])
            if g <= 0:
                continue
            pts = partial(seg['points'], g)
            stroke(d, f, pts, seg['width'] * (0.7 + 0.3 * g), BRANCH, BRANCH_SHADE, BRANCH_LIGHT)
            if seg['tip'] and g >= 1:
                lit = sm(t, seg['birth'] + seg['span'] + 0.1, seg['birth'] + seg['span'] + 0.2)
                if lit > 0:
                    end = pts[-1]
                    r = u * 0.04 * lit * f
                    d.ellipse((end[0] * f - r, end[1] * f - r, end[0] * f + r, end[1] * f + r), fill=(200, 255, 245, round(255 * lit)))
        for p, w in zip(points, wave):
            if w <= 0:
                continue
            r = u * 0.018 * (0.6 + 0.4 * w) * f
            d.ellipse((p[0] * f - r, p[1] * f - r, p[0] * f + r, p[1] * f + r), fill=(180, 255, 240, round(255 * w)))

    orn_rgb, orn_a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(orn_a, F, 0.03, 0.05, 0.03, 0.4))
    canvas.over(orn_rgb, orn_a)
    canvas.over(np.zeros(3), shadow(cov, F, 0.04, 0.07, 0.04, 0.5))
    colour, alpha = rim(F, cov, 0.018, (0.3, 0.06, 0.1), 0.85)
    canvas.over(colour, alpha)
    canvas.over(body, cov)
    front = np.exp(-(((up - knob - grown * 1.14) / 0.05) ** 2)) * coverage(F.sdf) * (grown > 0) * (grown < 1)
    canvas.add(np.array((1.0, 0.85, 0.8)) * front[..., None] * 0.7)
    # the polyps glow: a cyan light on and around each lit polyp
    glow = np.zeros((F.H, F.W))
    for p, w in zip(points, wave):
        if w > 0:
            x0, y0_, x1, y1_ = int(max(0, p[0] - u * 0.12)), int(max(0, p[1] - u * 0.12)), int(min(F.W, p[0] + u * 0.12)), int(min(F.H, p[1] + u * 0.12))
            if x1 > x0 and y1_ > y0_:
                px, py = F.px[y0_:y1_, x0:x1], F.py[y0_:y1_, x0:x1]
                glow[y0_:y1_, x0:x1] = np.maximum(glow[y0_:y1_, x0:x1], np.exp(-((px - p[0]) ** 2 + (py - p[1]) ** 2) / (u * 0.045) ** 2) * w)
    if np.any(glow):
        canvas.add(POLYP * glow[..., None] * 0.6, 0.4)


# ---------------------------------------------------------------- bamboo

CULM = rgb(118, 168, 76)
CULM_DEEP = rgb(52, 104, 46)
NODE = rgb(228, 232, 190)
LEAF = ((60, 128, 52, 255), (104, 168, 70, 255), (150, 200, 96, 255))


def telescope(q, segments):
    """Bamboo grows one internode at a time: each segment shoots up quickly, then the next begins."""
    q = max(0.0, min(1.0, q)) * segments
    whole = math.floor(q)
    return min(1.0, (whole + sm(q - whole, 0, 1)) / segments)


def telescope_array(q, segments):
    q = np.clip(q, 0, 1) * segments
    whole = np.floor(q)
    frac = q - whole
    return np.minimum(1.0, (whole + frac * frac * (3 - 2 * frac)) / segments)


def sprays(F, letters):
    """Leaf sprays at a node on the side of each letter: where, which way, and their leaves."""
    boxes = letter_boxes(F, letters)

    def build():
        rng = np.random.default_rng(F.seed + 700)
        u = F.u
        out = []
        for k, b in enumerate(boxes):
            side = 1 if k % 2 == 0 else -1
            y = b[1] + u * rng.uniform(0.06, 0.16)  # high on the letter's shoulder
            x = b[2] if side > 0 else b[0]
            leaves = [dict(angle=rng.uniform(-1.25, -0.45), length=u * rng.uniform(0.48, 0.62), tone=int(rng.integers(1, 3)))
                      for _ in range(int(rng.integers(2, 4)))]
            out.append(dict(x=float(x), y=float(y), side=side, leaves=leaves))
        return out
    return F.memo('bamboo-sprays', build)


def leaf_shape(d, f, root, angle, length, width, tone):
    dx_, dy_ = math.cos(angle), math.sin(angle)
    nx_, ny_ = -dy_, dx_
    shape = []
    for s_ in (k / 8 for k in range(9)):
        ww = width * math.sin(math.pi * s_) ** 0.7
        shape.append(((root[0] + dx_ * length * s_ + nx_ * ww) * f, (root[1] + dy_ * length * s_ + length * 0.15 * s_ * s_ + ny_ * ww) * f))
    for s_ in (k / 8 for k in range(8, -1, -1)):
        ww = width * math.sin(math.pi * s_) ** 0.7
        shape.append(((root[0] + dx_ * length * s_ - nx_ * ww) * f, (root[1] + dy_ * length * s_ + length * 0.15 * s_ * s_ - ny_ * ww) * f))
    d.polygon([(px + f, py + f) for px, py in shape], fill=(16, 34, 14, 130))
    d.polygon(shape, fill=tone)
    d.line(shape[:9], fill=(200, 230, 150, 160), width=max(1, f // 2))


@crafted('bamboo-lettering', pad=0.8)
def bamboo(F, canvas, t, intensity, letters):
    """The letters are bamboo: each shoots up internode by internode, every joint popping past its height and
    springing back, pale jade with cream node rings; then leaf sprays unfurl from a node on the side of each
    letter and flutter once in a breeze before they settle."""
    index, count = letters
    u = F.u
    light = sun(-2.2, 0.7)
    rank = np.argsort(np.argsort([-abs(k - (count - 1) / 2) for k in range(count)]))  # the outer letters first, closing in
    local = [min(1.0, max(0.0, (t - 0.22 * rank[k] / max(1, count)) / 0.5)) for k in range(count)]
    segs = 4
    # each joint overshoots as it lands: a little stretch that springs back
    pops = []
    for q in local:
        x = q * segs
        frac = x - math.floor(x)
        pops.append(1 + 0.18 * math.sin(math.pi * min(1.0, frac / 0.6)) * (q < 1) if q > 0 else 1.0)
    revealed = 1.0  # the whole letter is there, stretched up from its foot joint by joint
    from effects.materials.fx import bevel, lambert, normals, specular
    ring_d = ((F.box[3] - F.py) / (u * 0.34)) % 1
    ring = smooth(0.1 - np.abs(ring_d - 0.5), 0, 0.03)  # bold, hard-edged cream node bands
    height = bevel(F.sdf, u * 0.09) + u * 0.014 * ring * smooth(-F.sdf, 0, u * 0.03)
    n = normals(height)
    fibres = 1 + 0.07 * F.noise(0.02, 701, (0.25, 6.0))
    jade, jade_deep = rgb(176, 222, 120), rgb(98, 162, 78)
    albedo = mix(jade_deep, jade, 0.55 + 0.25 * F.fbm(0.2, 2, 702)) * fibres[..., None]
    albedo = mix(albedo, NODE, np.clip(ring * 1.2, 0, 1))
    albedo = mix(albedo, rgb(34, 72, 30), smooth(0.04 - np.abs(ring_d - 0.65), 0, 0.015))  # a dark groove under each node
    body = albedo * (0.4 + 0.8 * lambert(n, light))[..., None] + specular(n, light, 40)[..., None] * 0.35
    layer = Canvas(F)
    cov = coverage(F.sdf) * revealed
    layer.over(np.zeros(3), shadow(cov, F, 0.04, 0.07, 0.04, 0.5))
    colour, alpha = rim(F, cov, 0.02, (0.06, 0.16, 0.06), 0.95)
    layer.over(colour, alpha)
    layer.over(np.clip(body, 0, 1), cov)
    heights = [telescope(q, segs) * pops[k] for k, q in enumerate(local)]
    stretch(F, layer, letters, heights, 'bottom')
    merge(canvas, layer)
    breeze = math.sin(max(0.0, t - 0.7) / 0.3 * math.pi * 2) * (1 - sm(t, 0.75, 1.0)) * 0.3
    tufts = sprays(F, letters)

    def draw(d, f):
        for k, sp in enumerate(tufts):
            q = sm(t, local_start(k) + 0.22, local_start(k) + 0.42)
            if q <= 0:
                continue
            root = (sp['x'], sp['y'])
            for j, lf in enumerate(sp['leaves']):
                droop = lf['angle'] + breeze * (1 + 0.3 * j)
                angle = (-math.pi / 2) * (1 - q) + (droop if sp['side'] > 0 else math.pi - droop) * q
                tone = LEAF[lf['tone']]
                leaf_shape(d, f, root, angle, lf['length'] * q ** 0.6, u * 0.085 * q, (int(tone[0] * 0.8), int(tone[1] * 0.8), int(tone[2] * 0.8), 255))

    def local_start(k):
        return 0.22 * rank[k] / max(1, count) + 0.18 + 0.05 * (k % 3)

    orn_rgb, orn_a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(orn_a, F, 0.03, 0.05, 0.04, 0.35))
    canvas.over(orn_rgb, orn_a)


# ---------------------------------------------------------------- latin cross

ENAMEL = rgb(236, 222, 192)  # warm ivory, so it does not wash out on cream paper
CROSS_GOLD = rgb(255, 200, 96)


def cross_geometry(F):
    """Signed distance to a trefoil-tipped Latin cross above the word, with its key points."""
    def build():
        x0, y0, x1, y1 = F.box
        u = F.u
        cx, foot = (x0 + x1) / 2, y0 - u * 0.06
        tall = u * (0.5 if x1 - x0 < u * 0.6 else 0.75)  # never towering over a short word or a lone letter
        top = max(u * 0.1, foot - tall)
        bar = top + (foot - top) * 0.3
        half, arm = u * 0.06, (foot - top) * 0.34

        def box(px, py, hx, hy):
            qx, qy = np.abs(F.px - px) - hx, np.abs(F.py - py) - hy
            return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0)

        def disc(px, py, r):
            return np.hypot(F.px - px, F.py - py) - r

        sdf = np.minimum(box(cx, (top + foot) / 2, half, (foot - top) / 2), box(cx, bar, arm, half))
        lobe = half * 1.3
        for ex, ey, dx, dy in ((cx, top, 0, -1), (cx - arm, bar, -1, 0), (cx + arm, bar, 1, 0)):
            sdf = np.minimum(sdf, disc(ex + dx * lobe * 0.35, ey + dy * lobe * 0.35, lobe))
            for side in (-1, 1):
                sdf = np.minimum(sdf, disc(ex + side * dy * lobe * 0.95 - dx * lobe * 0.35, ey + side * dx * lobe * 0.95 - dy * lobe * 0.35, lobe * 0.78))
        sdf = np.minimum(sdf, box(cx, foot - half * 0.6, half * 2.0, half * 0.6))
        return sdf, dict(cx=cx, bar=bar, top=top, foot=foot, half=half, arm=arm)
    return F.memo('latin-cross', build)


@crafted('catholic-cross-lettering', pad=1.3)
def latin_cross(F, canvas, t, intensity, letters):
    """A gold Latin cross draws itself up above the word and lights; twelve hard-edged beams shoot out from the
    crossing, and as the light reaches each letter (the one under the cross first, then outward) it pops up in
    ivory enamel with a gold rim, then gold leaf is swept across it; a ruby sets at the crossing and the beams
    retract into a halo."""
    from effects.materials.fx import bevel, environment, lambert, normals, specular
    index, count = letters
    u = F.u
    sdf, g = cross_geometry(F)
    light = sun(-2.0, 0.8)
    height = max(1, g['foot'] - g['top'])
    rise = sm(t, 0.0, 0.26)
    cross_reveal = smooth(rise * 1.1 - (g['foot'] - F.py) / height, 0, 0.06)
    cross_cov = coverage(sdf) * cross_reveal
    groove = np.exp(-(((sdf + g['half'] * 0.5) / (g['half'] * 0.12)) ** 2))
    cn = normals(bevel(sdf, g['half'] * 0.95) - g['half'] * 0.18 * groove)
    gold = np.clip((environment(cn) * CROSS_GOLD + specular(cn, light, 90)[..., None] * 1.2) * (1 - 0.25 * groove)[..., None], 0, 1)
    lit = smooth(t - 0.18 - 0.2 * np.clip((g['foot'] - F.py) / height, 0, 1), 0, 0.1)
    # beams: twelve hard-edged tapered spokes that shoot out, turn a little, and retract
    dx, dy = F.px - g['cx'], F.py - g['bar']
    r = np.hypot(dx, dy) / u
    phi = np.arctan2(dy, dx)
    shoot = sm(t, 0.18, 0.34)
    retract = 1 - sm(t, 0.62, 0.78)
    length = min(1.3, 0.3 * (F.box[2] - F.box[0]) / u) * shoot * retract  # short words get shorter beams
    wave = np.cos(phi * 12 + t * 0.8)
    length = length * (0.65 + 0.35 * (np.cos(phi * 6) > 0))  # long and short rays alternate, not a stock star
    width_at = 0.035 + 0.05 * np.clip(1 - r / np.maximum(1e-3, length), 0, 1)  # wide at the root, a point at the tip
    beams = smooth(wave - np.cos(width_at * 12), 0, 0.004) * smooth(length - r, 0, 0.02) * smooth(r, 0.05, 0.12)
    halo = np.exp(-((r / (0.16 + 0.1 * shoot)) ** 2)) * sm(t, 0.18, 0.3)
    canvas.over(np.array((1.0, 0.9, 0.62)), beams * 0.85)
    canvas.add(np.array((1.0, 0.86, 0.56)) * (halo * 0.6)[..., None] + bloom(np.array((1.0, 0.8, 0.5)) * (halo * 0.6 + beams * 0.3)[..., None], F, 0.06, 0.4), 0.4)
    canvas.over(np.array((0.2, 0.1, 0.0)), shadow(cross_cov, F, 0.03, 0.05, 0.03, 0.4))
    colour, alpha = rim(F, cross_cov, 0.016, (0.22, 0.11, 0.02), 0.95)
    canvas.over(colour, alpha)
    canvas.over(mix(np.array((1.0, 0.97, 0.86)), gold, lit), cross_cov)
    canvas.add(bloom(np.array((1.0, 0.9, 0.6)) * (cross_cov * (1 - lit))[..., None], F, 0.04, 1.0))
    gem_r = np.hypot(dx, dy) / (g['half'] * 1.05)
    gem_n = np.stack((dx / (g['half'] * 1.05) * 0.8, dy / (g['half'] * 1.05) * 0.8, np.sqrt(np.clip(1 - gem_r**2, 0, 1)) + 0.2), -1)
    gem_n = gem_n / np.linalg.norm(gem_n, axis=-1, keepdims=True)
    ruby = np.clip(mix(rgb(110, 0, 20), rgb(230, 30, 60), lambert(gem_n, light)) + specular(gem_n, light, 120)[..., None] * 1.5, 0, 1)
    set_ = sm(t, 0.52, 0.62)
    canvas.over(ruby, smooth(1 - gem_r, 0, 0.15) * set_ * (1 + 0.3 * math.sin(math.pi * set_)))
    # the letters: each pops up in ivory and gold as the light reaches it, the one under the cross first
    boxes = letter_boxes(F, letters)
    centres = np.array([(b[0] + b[2]) / 2 for b in boxes])
    span = max(1.0, (F.box[2] - F.box[0]) / 2)
    when = 0.08 + 0.4 * np.abs(centres - g['cx']) / span
    local = np.clip((t - when) / 0.16, 0, 1)
    pops = [spring(q, ((0, 0.0), (0.5, 1.08), (0.75, 0.97), (1, 1.0))) if q > 0 else 0.0 for q in local]
    ln = normals(bevel(F.sdf, u * 0.05))
    enamel = mix(ENAMEL, rgb(255, 250, 236), lambert(ln, light)) + specular(ln, light, 60)[..., None] * 0.35
    inner = smooth(-F.sdf, 0, 1.0) * (1 - smooth(-F.sdf, u * 0.035, u * 0.05))
    letter = np.clip(mix(enamel, environment(ln) * CROSS_GOLD * 0.85 + specular(ln, light, 70)[..., None], inner), 0, 1)
    flash = per_pixel(np.exp(-(((local - 0.35) / 0.15) ** 2)) * (local > 0), letters)
    # then gold leaf is laid across each letter, a bright front sweeping left to right in the same relay
    gild = per_pixel(np.clip((t - when - 0.2) / 0.22, 0, 1), letters)
    across = letter_x(F, letters) * 0.75 + np.clip((F.py - F.box[1]) / max(1, F.box[3] - F.box[1]), 0, 1) * 0.25
    laid = smooth(gild * 1.15 - across, 0, 0.01)  # a hard line, not a fade
    edge = np.exp(-(((gild * 1.15 - across - 0.025) / 0.025) ** 2)) * (gild > 0) * (gild < 1)
    leaf = np.clip(environment(ln) * CROSS_GOLD * 1.05 + specular(ln, light, 50)[..., None] * 0.6, 0, 1)
    letter = mix(letter, mix(leaf, letter, inner * 0.5), laid * 0.9)
    flash = flash + edge * 1.3  # a white-hot burnishing edge leads the gold
    lcov = coverage(F.sdf)
    word = Canvas(F)
    word.over(np.array((0.2, 0.1, 0.0)), shadow(lcov, F, 0.03, 0.06, 0.04, 0.45))
    colour, alpha = rim(F, lcov, 0.018, (0.24, 0.13, 0.03), 0.95)
    word.over(colour, alpha)
    word.over(np.clip(letter + flash[..., None] * 0.5, 0, 1), lcov)
    stretch(F, word, letters, pops, anchor='bottom')
    merge(canvas, word)
    # the cross flares each time a letter takes its gold, so the light hands off from cross to word
    pulse = float(np.sum(np.exp(-(((t - when - 0.3) / 0.035) ** 2))))
    canvas.add(np.array((1.0, 0.92, 0.7)) * (cross_cov * min(1.0, pulse) * 0.55)[..., None]
               + bloom(np.array((1.0, 0.85, 0.5)) * (cross_cov * min(1.0, pulse))[..., None], F, 0.05, 0.6), 0.6)


# ---------------------------------------------------------------- clockwork

BRASS = rgb(226, 178, 86)
BRASS_DARK = (74, 50, 18, 240)
BRASS_FILL = (214, 168, 78, 255)
BRASS_LIGHT = (255, 232, 170, 255)
STEEL_FILL = (176, 186, 196, 255)


def gear(d, f, centre, radius, teeth, angle, colour, spokes=5):
    """A brass gear: toothed rim, dark outline, hub and spokes, a highlight arc."""
    cx, cy = centre[0] * f, centre[1] * f
    r = radius * f
    pts = []
    for n in range(teeth * 4):
        a = angle + n / (teeth * 4) * math.tau
        rr = r if n % 4 in (1, 2) else r * 0.8
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    d.polygon([(px + f, py + f * 1.5) for px, py in pts], fill=(20, 14, 6, 120))
    d.polygon(pts, fill=BRASS_DARK)
    inner = [(cx + (px - cx) * 0.88, cy + (py - cy) * 0.88) for px, py in pts]
    d.polygon(inner, fill=colour)
    hole = r * 0.58
    d.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=BRASS_DARK)
    d.ellipse((cx - hole * 0.92, cy - hole * 0.92, cx + hole * 0.92, cy + hole * 0.92), fill=(0, 0, 0, 0))
    for k in range(spokes):
        a = angle + k / spokes * math.tau
        d.line([(cx, cy), (cx + math.cos(a) * hole, cy + math.sin(a) * hole)], fill=colour, width=max(2, round(r * 0.16)))
    hub = r * 0.2
    d.ellipse((cx - hub * 1.3, cy - hub * 1.3, cx + hub * 1.3, cy + hub * 1.3), fill=BRASS_DARK)
    d.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=colour)
    d.ellipse((cx - hub * 0.4, cy - hub * 0.4, cx + hub * 0.4, cy + hub * 0.4), fill=(40, 28, 10, 255))
    d.arc((cx - r * 0.84, cy - r * 0.84, cx + r * 0.84, cy + r * 0.84), 200, 290, fill=BRASS_LIGHT, width=max(1, round(r * 0.06)))


def gear_train(F, letters):
    """Gears along the top of the word, meshing neighbours turning opposite ways, and two small ones below."""

    def build():
        rng = np.random.default_rng(F.seed + 800)
        u = F.u
        x0, y0, x1, y1 = F.box
        gears = []
        x = x0 + u * 0.12
        k = 0
        while x < x1 + u * 0.05 and k < 7:  # big and small gears alternate along the top of the word
            radius = u * (0.3 if k % 2 == 0 else 0.19)
            if k:
                x += gears[-1]['radius'] + radius - u * 0.02
            teeth = 12 if k % 2 == 0 else 8
            gears.append(dict(centre=(x, y0 - radius * 0.62 + (u * 0.06 if k % 2 else 0)), radius=radius, teeth=teeth,
                              speed=(1 if k % 2 == 0 else -1) * (12 if k % 2 == 0 else 18) / teeth, phase=rng.uniform(0, 1),
                              birth=0.3 + 0.06 * k, colour=BRASS_FILL if k % 3 != 2 else STEEL_FILL))
            k += 1
        for k, bx in enumerate(np.linspace(x0 + u * 0.35, x1 - u * 0.35, 2 if x1 - x0 > u * 1.2 else 1)):
            radius = u * 0.15
            gears.append(dict(centre=(bx, y1 + radius * 0.7), radius=radius, teeth=8, speed=(-1 if k else 1) * 2.2, phase=rng.uniform(0, 1),
                              birth=0.5 + 0.08 * k, colour=STEEL_FILL))
        return gears
    return F.memo('gear-train', build)


@crafted('clockwork-lettering', pad=0.75)
def clockwork(F, canvas, t, intensity, letters):
    """Brass plates stamp down letter by letter with a flash at the leading edge and riveted seams; a train of
    gears pops in along the top of the word and meshes, neighbours turning opposite ways, with two small gears
    below; a glint sweeps the finished brass."""
    index, count = letters
    u = F.u
    light = sun(-2.3, 0.75)
    stamp = per_pixel(relay(t, count, 0.0, 0.34, 0.1), letters)
    boxes = letter_boxes(F, letters)
    y0 = per_pixel([b[1] for b in boxes], letters)
    y1 = per_pixel([b[3] for b in boxes], letters)
    down = np.clip((F.py - y0) / np.maximum(1, y1 - y0), 0, 1)
    revealed = smooth(stamp * 1.08 - down, 0, 0.05)
    cov = coverage(F.sdf) * revealed
    brushed = 1 + 0.05 * F.noise(0.01, 801, (6.0, 0.25))  # fine horizontal brushing
    body = np.clip(metal(F, BRASS, u * 0.06, light) * brushed[..., None], 0, 1)
    # rivets spaced along the stroke centres
    rivets = interior_points(F, letters, u * 0.17, u * 0.04)
    gears = gear_train(F, letters)

    def draw(d, f):
        for gr in gears:
            pop = sm(t, gr['birth'], gr['birth'] + 0.16)
            if pop <= 0:
                continue
            size = gr['radius'] * pop * (1 + 0.3 * math.sin(math.pi * pop))
            gear(d, f, gr['centre'], size, gr['teeth'], (gr['phase'] + t * gr['speed']) * math.tau / gr['teeth'] * 2, gr['colour'])
        for k, inside in enumerate(rivets):
            for p in inside:
                shown = sm(t, 0.36 + 0.3 * k / max(1, count), 0.44 + 0.3 * k / max(1, count))
                if shown <= 0:
                    continue
                r = u * 0.022 * shown * f
                x, y = p[0] * f, p[1] * f
                d.ellipse((x - r * 1.3, y - r * 1.3, x + r * 1.3, y + r * 1.3), fill=(70, 46, 14, 255))
                d.ellipse((x - r, y - r, x + r, y + r), fill=BRASS_FILL)
                d.ellipse((x - r * 0.6, y - r * 0.7, x + r * 0.1, y - r * 0.05), fill=BRASS_LIGHT)

    orn_rgb, orn_a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(orn_a, F, 0.03, 0.05, 0.03, 0.4))
    # gears behind the letters, rivets in front: split the ornament layer by whether a pixel is on the lettering
    on_letter = cov > 0.5
    canvas.over(orn_rgb, orn_a * (~on_letter))
    canvas.over(np.zeros(3), shadow(cov, F, 0.04, 0.07, 0.04, 0.5))
    colour, alpha = rim(F, cov, 0.018, (0.14, 0.08, 0.02), 0.9)
    canvas.over(colour, alpha)
    canvas.over(body, cov)
    canvas.over(orn_rgb, orn_a * on_letter)
    front = np.exp(-(((down - stamp * 1.08) / 0.03) ** 2)) * coverage(F.sdf) * (stamp > 0) * (stamp < 1)
    canvas.add(np.array((1.0, 0.95, 0.8)) * front[..., None] * 1.2)
    shine = gleam(F, t, 0.84, 0.98, 0.07)
    if np.any(shine):
        canvas.add(np.ones(3) * (shine * cov * 0.8)[..., None])


# ---------------------------------------------------------------- folded paper

PAPERS = (rgb(242, 128, 104), rgb(90, 176, 178), rgb(246, 196, 84), rgb(52, 84, 168), rgb(132, 110, 180), rgb(160, 206, 120))


def facets(F, letters, size, seed, palette_size=len(PAPERS)):
    """Voronoi facets over the word: per pixel its facet id, centre, a per-facet palette index, shade, tilt and
    birth (a wave left to right with a little scatter)."""
    def build():
        ids, d1, edge, points = F.cells(size, seed)
        rng = np.random.default_rng(F.seed * 7 + seed)
        n = len(points)
        x0, x1 = F.box[0], F.box[2]
        order = np.clip((points[:, 0] - x0) / max(1, x1 - x0), -0.1, 1.1)
        birth = order * 0.5 + rng.uniform(0, 0.08, n)
        palette = rng.integers(0, palette_size, n)
        shade = rng.uniform(0.82, 1.12, n)
        tilt = rng.uniform(-1, 1, (n, 2))
        centre = points[ids]
        return dict(ids=ids, edge=edge, birth=birth[ids], palette=palette[ids], shade=shade[ids],
                    gx=tilt[ids, 0], gy=tilt[ids, 1], cx=centre[..., 0], cy=centre[..., 1])
    return F.memo(('facets', round(size, 3), seed, palette_size), build)


@crafted('folded-paper-lettering', pad=0.7)
def folded_paper(F, canvas, t, intensity, letters):
    """The letters are cut from coloured paper facets that unfold one by one in a wave across the word: each
    facet swings open on its own hinge, its darker back showing as it rises, then turns over to its lit face
    with a bright crease as it lies flat; the creases stay as fine lines."""
    u = F.u
    fac = facets(F, letters, 0.3, 31, 3)
    q = smooth(t + 0.04 - fac['birth'], 0, 0.14)  # how far each facet has opened, about four frames
    # where each pixel sits across its facet, from the hinge side (-1) to the free edge (+1)
    across = (F.px - fac['cx']) * fac['gx'] + (F.py - fac['cy']) * fac['gy']
    across = np.clip(across / (u * 0.13), -1, 1)
    swept = smooth(-1 + 2.3 * q - across, 0, 0.18)  # the facet unfolds from its hinge across to its free edge
    cov = coverage(F.sdf) * swept
    triad = np.array([PAPERS[(F.seed + k * 2) % len(PAPERS)] for k in range(3)])
    colours = triad[fac['palette']]
    grain = 1 + 0.05 * F.noise(0.012, 32)
    # the back of the paper while the facet is still rising, its face once it lies flat
    turned = smooth(q, 0.45, 0.6)
    back = colours * 0.45 + 0.08
    face = colours * (fac['shade'] * (1 + 0.16 * across))[..., None]
    crease_flash = np.exp(-(((q - 0.55) / 0.12) ** 2)) * (q > 0) * (q < 1)
    body = np.clip((back * (1 - turned)[..., None] + face * turned[..., None]) * grain[..., None]
                   + crease_flash[..., None] * 0.5, 0, 1)
    creases = smooth(1.4 - fac['edge'], 0, 1.0) * smooth(-F.sdf, 0, 1.5) * 0.5 * smooth(q, 0.5, 1)
    hinge = np.exp(-(((across + 1 - 2.3 * q) / 0.12) ** 2)) * (q > 0) * (q < 1) * coverage(F.sdf)
    canvas.over(np.zeros(3), shadow(cov, F, 0.04, 0.07, 0.04, 0.45))
    colour, alpha = rim(F, cov, 0.016, (0.22, 0.17, 0.16), 0.8)
    canvas.over(colour, alpha)
    canvas.over(body, cov)
    canvas.over(np.array((0.2, 0.14, 0.14)), creases * cov)
    canvas.over(np.array((0.15, 0.1, 0.1)), hinge * 0.5)  # the shadow under the edge still lifting


# ---------------------------------------------------------------- obsidian lattice (a geode)

AMETHYST = (rgb(150, 96, 214), rgb(186, 140, 238), rgb(120, 70, 186), rgb(214, 184, 250), rgb(168, 112, 226))
STONE = rgb(70, 62, 58)
VIOLET = np.array((0.72, 0.5, 1.0))


@crafted('obsidian-lattice-lettering', pad=0.6)
def obsidian_lattice(F, canvas, t, intensity, letters):
    """Each letter arrives as a rough lump of dark stone, cracks along glowing violet seams that spread from one
    point, and the crust crumbles away in chips to show faceted amethyst crystal inside, which catches a
    travelling sparkle as it locks."""
    index, count = letters
    u = F.u
    arrive = relay(t, count, 0.0, 0.3, 0.14)
    crack = relay(t, count, 0.12, 0.3, 0.16)
    crumble = relay(t, count, 0.26, 0.32, 0.2)
    # the crust: the letter swollen into a lumpy rock, popping in with a little spring
    lump = F.sdf - u * (0.07 + 0.03 * F.fbm(0.08, 3, 931))
    pop = per_pixel([spring(a, ((0, 0.0), (0.6, 1.12), (1, 1.0))) for a in arrive], letters)
    rock = coverage(lump + u * 0.12 * (1 - pop)) * (pop > 0)
    cells_ = F.cells(0.11, 932)
    ids, edge = cells_[0], cells_[2]
    step = max(3.0, 0.11 * u)
    jitter = ((ids * 0.618) % 1) * 0.35
    gone = per_pixel(crumble, letters)
    shrink = np.clip((gone - jitter) / 0.65, 0, 1)
    crust = rock * smooth(edge - shrink * step * 0.55, 0, 0.8) * (shrink < 1)
    # the cracks spread from each letter's centre along the cell seams
    boxes = letter_boxes(F, letters)
    cxs = per_pixel([(b[0] + b[2]) / 2 for b in boxes], letters)
    cys = per_pixel([(b[1] + b[3]) / 2 for b in boxes], letters)
    reach = np.hypot(F.px - cxs, F.py - cys) / u
    spread = per_pixel(crack, letters) * 0.9
    seams = smooth(1.2 - edge, 0, 0.8) * smooth(spread - reach, 0, 0.05) * crust
    # the crystal inside
    fac = facets(F, letters, 0.17, 933, len(AMETHYST))
    colours = np.array(AMETHYST)[fac['palette']]
    across = (F.px - fac['cx']) * fac['gx'] + (F.py - fac['cy']) * fac['gy']
    across = np.clip(across / (u * 0.08), -1, 1)
    gloss = np.clip(0.5 + 0.5 * across, 0, 1) ** 3
    body = np.clip(colours * (0.75 + 0.35 * fac['shade'] + 0.25 * across)[..., None] + gloss[..., None] * 0.35, 0, 1)
    crystal = coverage(F.sdf) * smooth(gone, 0.05, 0.3)
    facet_lines = smooth(1.2 - fac['edge'], 0, 0.8) * smooth(-F.sdf, 0, 1.5) * crystal
    stone_tex = 0.75 + 0.25 * F.fbm(0.03, 3, 934)
    stone = np.clip(np.asarray(STONE) * stone_tex[..., None] * (0.8 + 0.4 * np.clip(-F.Y * 0.8, -0.5, 0.5))[..., None], 0, 1)
    sparkle = gleam(F, t, 0.8, 0.97, 0.07)

    def draw(d, f):  # chips knocked off the crust fall away
        rng = np.random.default_rng(F.seed + 935)
        for k, b in enumerate(boxes):
            q = crumble[k]
            if not 0 < q < 1:
                continue
            for j in range(7):
                x = b[0] + (b[2] - b[0]) * rng.uniform(0, 1)
                y = b[1] + (b[3] - b[1]) * rng.uniform(0.1, 0.9)
                vx = (x - (b[0] + b[2]) / 2) / u * 0.5 + rng.uniform(-0.2, 0.2)
                a = max(0.0, q - j * 0.05)
                px, py = x + vx * u * a, y - u * 0.25 * a + u * 1.2 * a * a
                r = u * rng.uniform(0.035, 0.06) * (1 - a * 0.5)
                spin = rng.uniform(0, math.tau) + a * 5
                tone = tuple(int(v * 255 * rng.uniform(0.8, 1.1)) for v in STONE)
                d.polygon([((px + r * math.cos(spin + n * 2.2)) * f, (py + r * math.sin(spin + n * 2.2)) * f) for n in range(3)],
                          fill=(*[min(255, c) for c in tone], round(255 * (1 - a))))

    chips_rgb, chips_a = supersampled(F, draw)
    canvas.over(np.zeros(3), shadow(np.maximum(crust, crystal), F, 0.03, 0.06, 0.04, 0.5))
    colour, alpha = rim(F, crystal, 0.016, (0.2, 0.08, 0.3), 0.85)
    canvas.over(colour, alpha)
    canvas.over(body, crystal)
    canvas.add(np.array((1.0, 0.92, 1.0)) * (facet_lines * 0.35)[..., None], 0.2)
    canvas.over(stone, crust)
    canvas.add(VIOLET * seams[..., None] * 1.4 + bloom(VIOLET * seams[..., None], F, 0.03, 0.8), 0.4)
    canvas.over(chips_rgb, chips_a)
    if np.any(sparkle):
        canvas.add(np.array((1.0, 0.95, 1.0)) * (sparkle * (facet_lines + 0.3 * crystal))[..., None] * 0.9, 0.2)
