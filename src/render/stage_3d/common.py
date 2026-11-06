"""Shared constants and helpers: fonts, sprites, pictures, shapes and routes."""

from __future__ import annotations
import colorsys
import itertools
from render.scene_fonts import font_cache as lru_cache
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from render.scene_fonts import first_font
from render.realtime import role_font
from render.thread_path import monotone_keys, settle_keys

FOV = 38.0
BLOCK_WIDTH = 4.0
FILL_WIDTH, FILL_HEIGHT = 0.74, 0.72
REFERENCE = 200
OVERSAMPLE = 1.25
FONT_LIMITS = (16, 440)
MOVE, MOVE_LEAD = 1.8, 1.1
# The ribbon's route is rounded over this many seconds of travel either side of each point, so a loop spliced
# in at an angle (or any other corner) turns smoothly instead of making the wisp bounce back in one frame.
ROUND_TIME = 0.15
# The wisps' swim is measured across the route's direction over this many seconds of travel either way, so on
# a tight turn the swim swings across the route gradually instead of flipping sides within a frame.
TURN_TIME = 0.35
CRUISE = 0.14
DEPTHS = (-1.2, 0.6)
VIEW_TILT = 0.55
ENTRY, ENTRY_LEAD, LETTER_STAGGER = 0.38, 0.08, 0.035
PARTICLE_ENTRY, GROW_ENTRY = 0.6, 1.4
EFFECT_FONT = 280
GROW_ROOM, EFFECT_ROOM = 0.9, 0.25
ACCENT = (239, 76, 84)
STAGE_FONTS = {
    'thin': ('DMSerifDisplay-Regular.ttf', 'DejaVuSerif.ttf'),
    'heavy': ('BricolageGrotesque[opsz,wdth,wght].ttf', 'DejaVuSans-Bold.ttf'),
    'sweet': ('Fraunces[SOFT,WONK,opsz,wght].ttf', 'DejaVuSerif-Bold.ttf'),
}
COLUMN_GAP, COLUMN_LIMIT = 0.018, 0.32
BOUNCE_ENTRY, BOUNCE_STAGGER = 0.55, 0.045
ROLL_RANGE, ZOOM_RANGE = (5.0, 12.0), (0.9, 0.96)
CONTRAST_LEADING = 0.42
HOP, SWAY = 0.07, 3.0
PATTERNS = 5
ENTRANCES = ('flip', 'swing', 'rise', 'drop')
MOTIONS = ('wave', 'pulse', 'tilt')
OLD_BLOCK, DIM_TIME = 0.45, 1.0
DRAW_REACH = 3.0
EXTRUDE_LAYERS, EXTRUDE_DEPTH = 7, 0.07
ORNAMENT_SIZE, FLOAT_SIZE = 1.12, 0.9
SLOT_PICTURE = 1.45  # a picture beside a word is drawn larger than its slot, overlapping its neighbours a little
BACKDROP_TINT = 0.62
MOTES = 36
SHAPE_DEPTHS = (-3.2, -0.6)
SHAPE_REACH = 1.5
BANDS, BAND_WIDTH, BAND_STEP, BAND_OPACITY = 3, 0.05, 0.09, 0.42
DUET_LENGTH = (12.0, 18.0)  # how long the partner's one visit lasts
# Shares of the visit: flying in, trailing the main wisp, joining it, the helix, and leaving.
DUET_ENTER, DUET_FOLLOW, DUET_JOIN, DUET_HELIX, DUET_LEAVE = 0.15, 0.32, 0.12, (0.55, 0.74), 0.85
RIBBON_DEPTH, RIBBON_SWING, RIBBON_REACH = -0.12, 1.6, 28.0
TEXTURE_LIMIT = 220


def normalized(vector):
    vector = np.asarray(vector, dtype=float)
    return vector / (np.linalg.norm(vector) or 1.0)


@lru_cache(maxsize=256)
def stage_font(name, size):
    """The stage's extra faces (thin, heavy, sweet), or the real-time role fonts."""
    if name == 'sculpture':
        return first_font(('BricolageGrotesque[opsz,wdth,wght].ttf',), size)
    if name not in STAGE_FONTS:
        return role_font(name, size)
    return first_font(STAGE_FONTS[name], size) or role_font('content', size)


def text_sprite(text, role, size, color):
    """Text drawn with its baseline at (pad, pad+ascent) over a soft dark halo; returns (image, pad, ascent)."""
    font = stage_font(role, size)
    ascent, descent = font.getmetrics()
    pad = max(6, round(size * 0.14))
    width = max(1, math.ceil(font.getlength(text)))
    shape = Image.new('L', (width + pad * 2, ascent + descent + pad * 2))
    ImageDraw.Draw(shape).text((pad, pad + ascent), text, font=font, fill=255, anchor='ls')
    halo = shape.filter(ImageFilter.GaussianBlur(max(2, size * 0.07))).point(lambda a: min(255, round(a * 1.4)))
    image = Image.new('RGBA', shape.size, (0, 0, 0, 0))
    if role != 'sculpture':
        image.putalpha(halo.point(lambda a: round(a * 0.55)))
    image.alpha_composite(Image.merge('RGBA', (*Image.new('RGB', shape.size, color).split(), shape)))
    return image, pad, ascent


def letter_fills(accent, count, rng):
    """Subtle woven grain with a shared scene color and independent, slow letter drift."""
    patterns = list(range(PATTERNS))
    rng.shuffle(patterns)
    fills = []
    for k in range(count):
        fills.append(
            dict(
                texture_tones(accent),
                pattern=patterns[k % PATTERNS],
                angle=rng.uniform(0.0, math.pi),
                speed=rng.uniform(0.4, 0.8) * rng.choice((-1, 1)),
                seed=rng.uniform(0.0, 50.0),
            )
        )
    return fills


def texture_tones(accent):
    """Three close tones of the scene accent, with no unrelated white or hue shift."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in accent))
    tone = lambda s, v: tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h, s, v))  # noqa: E731
    return dict(deep=tone(s, v * 0.78), middle=tone(s * 0.95, v * 0.9), light=tone(s * 0.85, min(1.0, v * 1.04)))


def elastic(value):
    """0 to 1 with a springy overshoot that settles: letters pop in and wobble into place."""
    value = max(0.0, min(1.0, value))
    return 1 - math.exp(-6 * value) * math.cos(value * math.pi * 3.2)


ORNAMENTS = ('ring', 'halo', 'orbit', 'sparkle')


@lru_cache(maxsize=256)
def ornament_image(kind, step, size=256):
    """A floating line ornament drawn on by `step`/24: a ring, a double halo of beads, an orbit with its
    travelling bead, or a four-point sparkle; thin luminous strokes with a soft glow."""
    from PIL import ImageFilter

    image = Image.new('L', (size, size))
    draw = ImageDraw.Draw(image)
    c, r, w = size / 2, size * 0.42, max(2, size // 80)
    sweep = 360 * step / 24
    if kind == 'ring':
        draw.arc((c - r, c - r, c + r, c + r), -90, -90 + sweep, fill=255, width=w)
    elif kind == 'halo':
        draw.arc((c - r, c - r, c + r, c + r), -90, -90 + sweep, fill=255, width=w)
        inner = r * 0.78
        draw.arc((c - inner, c - inner, c + inner, c + inner), 90, 90 + sweep * 0.85, fill=170, width=max(1, w // 2))
        for k in range(int(12 * step / 24)):
            a = math.radians(-90 + k * 30)
            bx, by = c + math.cos(a) * r * 0.89, c + math.sin(a) * r * 0.89
            draw.ellipse((bx - w * 1.3, by - w * 1.3, bx + w * 1.3, by + w * 1.3), fill=230)
    elif kind == 'orbit':
        box = (c - r, c - r * 0.45, c + r, c + r * 0.45)
        draw.arc(box, -90, -90 + sweep, fill=210, width=max(1, w // 2 * 2))
        a = math.radians(-90 + sweep)
        bx, by = c + math.cos(a) * r, c + math.sin(a) * r * 0.45
        draw.ellipse((bx - w * 2.4, by - w * 2.4, bx + w * 2.4, by + w * 2.4), fill=255)
    else:
        reach = r * step / 24
        for angle in (0, 90, 180, 270):
            a = math.radians(angle)
            tip = (c + math.cos(a) * reach, c + math.sin(a) * reach)
            side = (math.cos(a + math.pi / 2) * w * 1.6, math.sin(a + math.pi / 2) * w * 1.6)
            draw.polygon([(c + side[0], c + side[1]), tip, (c - side[0], c - side[1])], fill=255)
        draw.ellipse((c - w * 2, c - w * 2, c + w * 2, c + w * 2), fill=255)
    glow = image.filter(ImageFilter.GaussianBlur(size / 40))
    alpha = Image.eval(Image.merge('L', (image,)), lambda v: v)
    combined = Image.fromarray(
        np.clip(np.asarray(alpha, dtype=float) + np.asarray(glow, dtype=float) * 1.4, 0, 255).astype('uint8')
    )
    result = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    result.putalpha(combined)
    return result


def shape_image(kind, filled=True, size=128, progress=1.0):
    """The portion of a solid shape swept out by the traveling dot; no perimeter stroke."""
    image = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(image)
    sides = {'triangle': 3, 'square': 4, 'hexagon': 6}[kind]
    centre, radius = size / 2, size * 0.47
    points = [
        (
            centre + radius * math.cos(math.pi + 2 * math.pi * k / sides),
            centre - radius * math.sin(math.pi + 2 * math.pi * k / sides),
        )
        for k in range(sides + 1)
    ]
    progress = max(0.0, min(1.0, progress))
    count = min(sides - 1, int(progress * sides))
    fraction = progress * sides - count
    a, b = points[count], points[count + 1]
    tip = (a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction)
    if progress > 0:
        draw.polygon([(centre, centre)] + points[: count + 1] + [tip], fill=(255, 255, 255, 255))
    return image


def shifted(color, amount):
    """An RGB colour (0..1) with its hue turned by `amount` of a full turn."""
    h, l, s = colorsys.rgb_to_hls(*(float(v) for v in color[:3]))
    return colorsys.hls_to_rgb((h + amount) % 1.0, l, s)


def band_image(width=8, height=64):
    """A band across its width: soft translucent body with a thin bright crest along one edge."""
    column = Image.new('L', (1, height))
    for y in range(height):
        u = y / (height - 1)
        body = math.sin(math.pi * u) ** 0.6 * 120
        crest = 255 * math.exp(-(((u - 0.18) / 0.04) ** 2))
        column.putpixel((0, y), round(min(255, body + crest * 0.8)))
    image = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    image.putalpha(column.resize((width, height)))
    return image


def gradient(top, bottom, height=256):
    column = Image.new('RGB', (1, height))
    for y in range(height):
        u = y / (height - 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * u) for a, b in zip(top, bottom)))
    return column.resize((4, height))


def soft_dot(size=64):
    dot = Image.new('L', (size, size))
    ImageDraw.Draw(dot).ellipse((size * 0.3, size * 0.3, size * 0.7, size * 0.7), fill=255)
    dot = dot.filter(ImageFilter.GaussianBlur(size * 0.1))
    image = Image.new('RGBA', (size, size), (255, 248, 230, 0))
    image.putalpha(dot)
    return image


def route_table(run):
    """Cached (segment starts, ends, cumulative distances, cruising speed) for looking up points on a run."""
    if '_route' not in run:
        starts = np.array([p for p, _ in run['segments']], dtype=float)
        ends = np.array([q for _, q in run['segments']], dtype=float)
        edges = np.concatenate([[0.0], np.cumsum(np.linalg.norm(ends - starts, axis=1))])
        times, distances, _ = run['keys']
        cruise = (distances[-1] - distances[0]) / max(1e-6, times[-1] - times[0]) if len(times) > 1 else 0.0
        run['_route'] = (starts, ends, edges, cruise)
    return run['_route']


def route_point(run, distance):
    """The point `distance` along the run's route."""
    starts, ends, edges, _ = route_table(run)
    k = int(np.clip(np.searchsorted(edges, distance, side='right') - 1, 0, len(starts) - 1))
    span = edges[k + 1] - edges[k]
    return starts[k] + (ends[k] - starts[k]) * (
        0.0 if span <= 1e-9 else min(1.0, max(0.0, (distance - edges[k]) / span))
    )


def steady_tangent(run, distance):
    """The route's direction at `distance`, measured from TURN_TIME of travel behind to TURN_TIME ahead."""
    starts, ends, edges, cruise = route_table(run)
    reach = max(1e-3, cruise * TURN_TIME)
    chord = route_point(run, min(edges[-1], distance + reach)) - route_point(run, max(0.0, distance - reach))
    if np.linalg.norm(chord) > 1e-6:
        return normalized(chord)
    k = int(np.clip(np.searchsorted(edges, distance, side='right') - 1, 0, len(starts) - 1))
    return normalized(ends[k] - starts[k])


def rounded_run(run):
    """The run's route resampled evenly and averaged along its length over ROUND_TIME of travel either side,
    which rounds every corner (a spliced-in loop's entry and exit included). Timing keys and fill distances
    are remapped to the rounded lengths, so the head still passes each point at the time it was planned."""
    segments = run['segments']
    times, distances, _ = run['keys']
    if len(segments) < 2 or len(times) < 2:
        return run
    starts = np.array([p for p, _ in segments], dtype=float)
    ends = np.array([q for _, q in segments], dtype=float)
    lengths = np.linalg.norm(ends - starts, axis=1)
    edges = np.concatenate([[0.0], np.cumsum(lengths)])
    total = edges[-1]
    cruise = (distances[-1] - distances[0]) / max(1e-6, times[-1] - times[0])
    radius = cruise * ROUND_TIME
    if total <= 0 or radius <= 0:
        return run
    step = radius / 3
    grid = np.linspace(0.0, total, max(2, int(total / step) + 1))
    which = np.clip(np.searchsorted(edges, grid, side='right') - 1, 0, len(segments) - 1)
    u = np.clip((grid - edges[which]) / np.maximum(lengths[which], 1e-9), 0.0, 1.0)[:, None]
    points = starts[which] + (ends[which] - starts[which]) * u
    reach = max(1, round(radius / (grid[1] - grid[0])))
    rounded = points
    for _ in range(2):  # two passes weight neighbours as a triangle, so even the acceleration turns smoothly
        padded = np.concatenate([np.repeat(rounded[:1], reach, 0), rounded, np.repeat(rounded[-1:], reach, 0)])
        summed = np.concatenate([np.zeros((1, points.shape[1])), np.cumsum(padded, axis=0)])
        rounded = (summed[2 * reach + 1 :] - summed[: -2 * reach - 1]) / (2 * reach + 1)
    rounded[0], rounded[-1] = points[0], points[-1]  # the route still starts and ends where it did
    remapped = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(rounded, axis=0), axis=1))])
    remap = lambda d: float(np.interp(d, grid, remapped))  # noqa: E731
    pieces = which[:-1]
    fills = [
        dict(fill, start_distance=remap(fill['start_distance']), end_distance=remap(fill['end_distance']))
        for fill in run['shape_fills']
    ]
    return dict(
        run,
        segments=list(zip(rounded[:-1], rounded[1:])),
        colors=[run['colors'][k] for k in pieces],
        paint=[run['paint'][k] for k in pieces],
        keys=settle_keys(monotone_keys(list(times), [remap(d) for d in distances])),
        shape_fills=fills,
    )


_ARTWORK_TOKENS = itertools.count()


def artwork_token(compositor):
    """A number for this compositor's artwork. The GL stage (and its texture cache) is shared by every stage in the
    process, and backdrops are cached by slot, so the slot alone could hand one song's painting to another."""
    if getattr(compositor, '_artwork_token', None) is None:
        compositor._artwork_token = next(_ARTWORK_TOKENS)
    return compositor._artwork_token
