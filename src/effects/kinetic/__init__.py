"""Graphic kinetic-type entrances: whole letters stretch, stack, multiply, peel and stamp into place.

Unlike the particle families, these move intact glyphs the way a motion designer animates a title card: letters
trade proportions on a hard offset extrusion, coloured copies fold down into the word, a letter unspools a chain
of echoes, a sticker peels away, a comic burst pops behind the word. Every pose is a pure function of progress
(0 = nothing yet, 1 = the plain word), and at 1 every offset, scale and decoration is exactly zero, so the
hand-over to the held word is seamless.
"""
import math
import random

from PIL import Image

from effects.kinetic.easing import clamp

STYLES = {}


def style(name):
    def register(function):
        STYLES[name] = function
        return function
    return register


def stretch(piece, sx, sy):
    """`piece` scaled by (sx, sy); unchanged at unit scale so rest frames are exact."""
    if abs(sx-1) < .004 and abs(sy-1) < .004:
        return piece
    width, height = max(1, round(piece.width*sx)), max(1, round(piece.height*sy))
    return piece.resize((width, height), Image.Resampling.BICUBIC)


def extruded(piece, depth, angle, color, far=None, taper=0., steps=None):
    """A hard, flat extrusion of `piece` along `angle` (radians) for `depth` pixels, drawn behind it, shading
    from `color` next to the face to `far` at the back. Returns the image and where the original's top-left
    now sits inside it."""
    from effects.kinetic.glyphs import solid_only
    if depth < .6:
        return piece, 0, 0
    dx, dy = math.cos(angle), math.sin(angle)
    pad_x, pad_y = math.ceil(abs(dx)*depth)+1, math.ceil(abs(dy)*depth)+1
    out = Image.new('RGBA', (piece.width+pad_x, piece.height+pad_y))
    ox = pad_x if dx < 0 else 0
    oy = pad_y if dy < 0 else 0
    mask = solid_only(piece).getchannel('A')
    count = steps or max(2, min(28 if taper else 64, math.ceil(depth)))
    far = far or color
    for k in range(count, 0, -1):
        t = k/count
        tone = tuple(round(a+(b-a)*t) for a, b in zip(color, far))
        layer_mask = mask
        shrink = 1-taper*t
        if taper and shrink < .995:  # deeper slices shrink toward a vanishing point: perspective depth
            w, h = max(1, round(piece.width*shrink)), max(1, round(piece.height*shrink))
            layer_mask = Image.new('L', piece.size)
            layer_mask.paste(mask.resize((w, h), Image.Resampling.BILINEAR), ((piece.width-w)//2, (piece.height-h)//2))
        solid = Image.new('RGBA', piece.size, (*tone, 0))
        solid.putalpha(layer_mask)
        out.alpha_composite(solid, (round(ox+dx*depth*t), round(oy+dy*depth*t)))
    out.alpha_composite(piece, (ox, oy))
    return out, ox, oy


def staggered(progress, index, count, stagger):
    """Per-letter local progress: the last letter starts `stagger` later than the first; each takes 1-stagger."""
    if count <= 1:
        return clamp(progress)
    delay = stagger*index/(count-1)
    return clamp((progress-delay)/max(1e-6, 1-stagger))


def paint_kinetic(layer, sprite, x, y, progress, effect, seed, intensity=1., cache=None, glyph_spans=None):
    """Draw `sprite` (its top-left at x, y) at entrance `progress` in the recipe's kinetic style."""
    from effects.kinetic.glyphs import faded, glyph_pieces, safe_paste
    from effects.kinetic import styles  # noqa: F401  registers the styles
    from effects.kinetic import letters  # noqa: F401  registers the letters-spin entrances
    progress = clamp(progress)
    if progress >= .999:
        safe_paste(layer, sprite, x, y)
        return
    painter = STYLES.get(effect.id.removeprefix('kinetic-'))
    if painter is None:
        safe_paste(layer, faded(sprite, progress), x, y)
        return
    key = ('kinetic-glyphs', sprite.size, sprite.tobytes()[::997], tuple(glyph_spans or ()))
    if cache is not None and key in cache:
        pieces = cache[key]
    else:
        pieces = glyph_pieces(sprite, glyph_spans)
        if cache is not None:
            cache[key] = pieces
    rng = random.Random(seed*7919+len(pieces)*31+sum(map(ord, effect.id)))
    names = painter.__code__.co_varnames
    extra = {k: v for k, v in (('cache', cache), ('seed', seed)) if k in names}
    painter(layer, sprite, x, y, progress, effect, pieces, rng, max(.3, min(2., float(intensity))), **extra)
