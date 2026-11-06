"""Glyph columns cut from a word sprite, colour helpers and the one transform every kinetic style draws with."""
from dataclasses import dataclass
import math

import numpy as np
from PIL import Image

# Bold, print-like accents (riso red, amber, lime, violet, orange, pink, teal) in an order where neighbours contrast.
ACCENTS = ((255, 46, 77), (255, 176, 46), (198, 255, 26), (127, 107, 255), (255, 92, 31), (244, 160, 200),
           (40, 200, 180))


@dataclass
class Glyph:
    image: Image.Image   # the full-height column of the sprite holding this letter
    left: int            # column position in the sprite
    top: int             # ink bounds inside the column
    bottom: int
    ink_left: int
    ink_right: int
    roundness: float     # how hollow and square the ink box is: high for O-like letters

    @property
    def width(self):
        return self.image.width

    @property
    def right(self):
        return self.left+self.image.width

    @property
    def center(self):
        return self.left+self.image.width/2

    @property
    def middle(self):
        return (self.top+self.bottom)/2

    @property
    def height(self):
        return max(1, self.bottom-self.top)


def glyph_pieces(sprite, spans=None):
    """Letters as full-height columns. Spans come from the caller's font metrics; without them the word is cut
    at the empty gaps between letters (or evenly when the letters touch)."""
    alpha = np.asarray(sprite.getchannel('A'))
    if not spans:
        ink = alpha.max(axis=0) > 24
        spans, start = [], None
        for column, on in enumerate(ink):
            if on and start is None:
                start = column
            elif not on and start is not None:
                spans.append((start, column))
                start = None
        if start is not None:
            spans.append((start, len(ink)))
        if not spans:
            spans = [(0, sprite.width)]
        # Fold the empty margins into the neighbouring letters so the columns tile the sprite.
        edges = [0]+[round((a[1]+b[0])/2) for a, b in zip(spans, spans[1:])]+[sprite.width]
        spans = list(zip(edges, edges[1:]))
    pieces = []
    for left, right in spans:
        left, right = max(0, int(left)), min(sprite.width, int(right))
        if right <= left:
            continue
        column = alpha[:, left:right]
        rows = np.nonzero(column.max(axis=1) > 24)[0]
        cols = np.nonzero(column.max(axis=0) > 24)[0]
        if len(rows) == 0:
            if pieces:  # a space or kerning sliver: join it to the previous letter
                previous = pieces[-1]
                image = sprite.crop((previous.left, 0, right, sprite.height))
                pieces[-1] = Glyph(image, previous.left, previous.top, previous.bottom, previous.ink_left,
                                   previous.ink_right, previous.roundness)
            continue
        box = column[rows[0]:rows[-1]+1, cols[0]:cols[-1]+1] > 128
        # O-like letters have an empty middle: the share of the central cross that is ink is low.
        h, w = box.shape
        centre = box[h//3:max(h//3+1, 2*h//3), w//3:max(w//3+1, 2*w//3)]
        hollow = 1-centre.mean() if centre.size else 0.
        aspect = min(w, h)/max(1, max(w, h))
        pieces.append(Glyph(sprite.crop((left, 0, right, sprite.height)), left, int(rows[0]), int(rows[-1])+1,
                            int(cols[0]), int(cols[-1])+1, hollow*aspect))
    if not pieces:
        pieces = [Glyph(sprite, 0, 0, sprite.height, 0, sprite.width, 0.)]
    # The first column takes the sprite's left margin; the last takes the right one.
    return pieces


def ink_color(sprite):
    """The word's fill colour: the median of its most opaque pixels."""
    data = np.asarray(sprite)
    solid = data[data[..., 3] > 235][:, :3]
    if len(solid) == 0:
        solid = data[data[..., 3] > 60][:, :3]
    if len(solid) == 0:
        return (240, 240, 240)
    return tuple(int(v) for v in np.median(solid, axis=0))


def luminance(color):
    r, g, b = (c/255 for c in color[:3])
    return .2126*r+.7152*g+.0722*b


def shade_color(color):
    """A deep, near-black shade of `color` for extrusions and knock-outs; light for very dark inks."""
    if luminance(color) < .18:
        return tuple(round(c+(245-c)*.75) for c in color[:3])
    return tuple(round(c*.16+18) for c in color[:3])


# Mid-tone, saturated inks that stay legible on dark paintings and on pale paper alike.
FILLS = ((238, 46, 72), (255, 96, 28), (122, 92, 255), (16, 168, 150), (226, 40, 150), (40, 110, 255))


def accent_palette(rng, count, fills=False):
    """`count` contrasting accents; `fills=True` keeps to colours that read as letter fills on any ground."""
    source = FILLS if fills else ACCENTS
    start = rng.randrange(len(source))
    step = rng.choice((2, 3)) if len(source) > 6 else 1
    return [source[(start+k*step) % len(source)] for k in range(count)]


def saturation(color):
    high, low = max(color[:3]), min(color[:3])
    return (high-low)/max(1, high)


def contrast_accent(ink, rng, exclude=()):
    """The accent that stands out most behind (or around) letters of colour `ink`: bright for dark words, deep
    for light ones, never close to the word's own hue."""
    light = luminance(ink) > .5
    deep = ((90, 50, 230), (210, 20, 70), (12, 120, 110), (230, 70, 10), (170, 20, 140))
    bright = ((198, 255, 26), (255, 196, 40), (90, 230, 210), (255, 150, 200), (255, 120, 60))
    options = [c for c in (deep if light else bright) if c not in exclude]
    rng.shuffle(options)
    def distance(c):
        return sum((a-b)**2 for a, b in zip(c, ink[:3]))
    return max(options, key=distance)


BRIGHTS = ((198, 255, 26), (255, 196, 40), (255, 150, 200), (90, 230, 210), (255, 120, 60), (170, 150, 255))
WARM_FILLS = ((238, 46, 72), (255, 96, 28), (226, 40, 150), (122, 92, 255))


def bright_accent(rng):
    """A light, loud sticker colour that carries dark print on any background."""
    return rng.choice(BRIGHTS)


def warm_fill(rng):
    """A saturated mid-tone that glows on dark paintings and still reads on paper."""
    return rng.choice(WARM_FILLS)


def far_fills(ink, count):
    """`count` print fills chosen to sit furthest in colour from the word's own ink."""
    def distance(c):
        return sum((a-b)**2 for a, b in zip(c, ink[:3]))
    return sorted((c for c in FILLS if c != (40, 110, 255)), key=distance, reverse=True)[:count]


def darker(color, amount):
    return tuple(round(c*(1-amount)) for c in color[:3])


def crisp(glyph_image, q, start=.82):
    """The letter's flat body while it moves (no soft drop shadow, so copies and extrusions read as print);
    the real sprite column, shadow and all, fades back in for the settle so the last frame is exact."""
    settle = 0. if q <= start else min(1., (q-start)/(1-start))
    if settle >= .999:
        return glyph_image
    flat = solid_only(glyph_image)
    return flat if settle <= 0 else Image.blend(flat, glyph_image, settle)


def faded(image, alpha):
    if alpha >= .999:
        return image
    result = image.copy()
    result.putalpha(result.getchannel('A').point(lambda a: round(a*max(0., alpha))))
    return result


def colored(image, color, alpha=1.):
    """`image`'s shape filled flat with `color`."""
    result = Image.new('RGBA', image.size, (*color[:3], 0))
    result.putalpha(image.getchannel('A').point(lambda a: round(a*max(0., min(1., alpha)))))
    return result


def silhouette(image, color):
    return colored(image, color, 1.)


def solid_only(image, threshold=200):
    """Only the letter body (drops the soft shadow halo), for flat print-like copies."""
    alpha = image.getchannel('A').point(lambda a: 255 if a >= threshold else round(a*a/threshold/1.2) if a > threshold*.5 else 0)
    result = image.copy()
    result.putalpha(alpha)
    return result


def draw_glyph(layer, glyph, x, y, sx=1., sy=1., angle=0., dx=0., dy=0., alpha=1., anchor='bottom',
               extrude=None, image=None):
    """Draw `glyph` scaled (sx, sy) and turned `angle` degrees about an anchor on its ink (bottom-centre or
    centre), moved by (dx, dy), optionally on a flat extrusion (depth px, angle rad, colour). At the identity
    pose this pastes the untouched column where it sits in the sprite."""
    from effects.kinetic import extruded, stretch
    source = image if image is not None else glyph.image
    ax = source.width/2
    ay = glyph.bottom if anchor == 'bottom' else glyph.middle
    piece = stretch(source, max(.02, sx), max(.02, sy))
    ax, ay = ax*piece.width/source.width, ay*piece.height/source.height
    if abs(angle) > .05:
        cx, cy = piece.width/2, piece.height/2
        theta = math.radians(angle)
        vx, vy = ax-cx, ay-cy
        piece = piece.rotate(angle, Image.Resampling.BICUBIC, expand=True)
        ax = piece.width/2+vx*math.cos(theta)+vy*math.sin(theta)
        ay = piece.height/2-vx*math.sin(theta)+vy*math.cos(theta)
    if extrude is not None and extrude[0] >= .6:
        piece, ox, oy = extruded(piece, *extrude)
        ax, ay = ax+ox, ay+oy
    if alpha < .999:
        piece = faded(piece, alpha)
    target_x = x+glyph.left+source.width/2+dx
    target_y = y+(glyph.bottom if anchor == 'bottom' else glyph.middle)+dy
    safe_paste(layer, piece, target_x-ax, target_y-ay)


def safe_paste(layer, piece, left, top):
    """alpha_composite that clips at the layer edges instead of failing on negative offsets."""
    left, top = round(left), round(top)
    if left >= layer.width or top >= layer.height or left+piece.width <= 0 or top+piece.height <= 0:
        return
    crop = (max(0, -left), max(0, -top), min(piece.width, layer.width-left), min(piece.height, layer.height-top))
    if crop != (0, 0, piece.width, piece.height):
        piece = piece.crop(crop)
    layer.alpha_composite(piece, (max(0, left), max(0, top)))
