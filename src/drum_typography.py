"""Short, deterministic foreground and background impacts from the drum stem."""

import math

from PIL import Image


IMPACT_LIFE = .52


def impact_kind(ordinal, strength):
    """Keep ordinary hits small; reserve the larger transformations for the top-ranked thumps."""
    if strength < .68:
        return 'shake'
    return ('pixels', 'squash', 'echo', 'shake')[ordinal % 4]


def _opacity(sprite, opacity):
    if opacity >= .999:
        return sprite
    sprite = sprite.copy()
    sprite.putalpha(sprite.getchannel('A').point(lambda a: round(a*opacity)))
    return sprite


def _paste(layer, sprite, x, y):
    # Impacts can extend past the screen edge on large hero words.
    left, top = max(0, x), max(0, y)
    right, bottom = min(layer.width, x+sprite.width), min(layer.height, y+sprite.height)
    if right > left and bottom > top:
        layer.alpha_composite(sprite.crop((left-x, top-y, right-x, bottom-y)), (left, top))


def shake_background(screen, hit, reactivity):
    """Jolt the painted background on steady kick runs, filling edges from their own pixels."""
    if hit is None or reactivity <= 0:
        return screen
    ordinal, age, strength = hit
    energy = min(1., reactivity)*(.4+.6*strength)*math.exp(-age*11)
    reach = min(9., min(screen.size)*.012)*energy
    dx = round(reach*math.cos(age*69+ordinal*1.7))
    dy = round(reach*.65*math.sin(age*83+ordinal*2.3))
    if dx == 0 and dy == 0:
        return screen
    width, height = screen.size
    pad = max(abs(dx), abs(dy))
    extended = Image.new(screen.mode, (width+2*pad, height+2*pad))
    extended.paste(screen, (pad, pad))
    extended.paste(screen.crop((0, 0, 1, height)).resize((pad, height)), (0, pad))
    extended.paste(screen.crop((width-1, 0, width, height)).resize((pad, height)), (pad+width, pad))
    extended.paste(screen.crop((0, 0, width, 1)).resize((width, pad)), (pad, 0))
    extended.paste(screen.crop((0, height-1, width, height)).resize((width, pad)), (pad, pad+height))
    for x, y, source in ((0, 0, (0, 0)), (pad+width, 0, (width-1, 0)),
                         (0, pad+height, (0, height-1)),
                         (pad+width, pad+height, (width-1, height-1))):
        extended.paste(screen.getpixel(source), (x, y, x+pad, y+pad))
    return extended.crop((pad-dx, pad-dy, pad-dx+width, pad-dy+height))


def paint_impact(layer, sprite, x, y, spans, hit, reactivity, opacity=1.):
    """Draw a landed word with a brief shake, letter-pixel spring, squash or echo."""
    ordinal, age, strength = hit
    kind = impact_kind(ordinal, strength)
    energy = max(0., min(1., reactivity))*(.4+.6*strength)
    if energy <= 0 or age >= IMPACT_LIFE:
        _paste(layer, _opacity(sprite, opacity), round(x), round(y))
        return
    x, y = round(x), round(y)
    if kind == 'shake':
        motion = energy*math.exp(-age*10)
        dx = round(sprite.height*.12*motion*math.sin(age*83+ordinal))
        dy = round(sprite.height*.055*motion*math.cos(age*67+ordinal))
        if motion > .12:
            ghost = _opacity(sprite, opacity*motion*.28)
            _paste(layer, ghost, x-dx*2-2, y)
            _paste(layer, ghost, x+dx*2+2, y)
        _paste(layer, _opacity(sprite, opacity), x+dx, y+dy)
    elif kind == 'squash':
        spring = energy*math.exp(-age*9)*math.cos(age*24)
        width = max(1, round(sprite.width*(1+.09*spring)))
        height = max(1, round(sprite.height*(1-.17*spring)))
        shaped = sprite.resize((width, height), Image.Resampling.BICUBIC)
        _paste(layer, _opacity(shaped, opacity), x+round((sprite.width-width)/2), y+sprite.height-height)
    elif kind == 'echo':
        reach = round(sprite.height*.20*energy*math.exp(-age*7))
        ghost = _opacity(sprite, opacity*energy*.30*math.exp(-age*8))
        if reach:
            _paste(layer, ghost, x-reach, y)
            _paste(layer, ghost, x+reach, y)
        _paste(layer, _opacity(sprite, opacity), x, y)
    else:
        # Each letter has its own center, so tiles separate from the glyph they belong to
        # and recoil past their starting positions before settling exactly on the text.
        spring = energy*math.exp(-age*6)*math.sin(age*19)
        if abs(spring) < .012:
            _paste(layer, _opacity(sprite, opacity), x, y)
            return
        tile = max(4, min(11, round(sprite.height*.075)))
        for letter, (left, right) in enumerate(spans):
            center = (left+right)/2
            for sx in range(left, right, tile):
                for sy in range(0, sprite.height, tile):
                    box = (sx, sy, min(right, sx+tile), min(sprite.height, sy+tile))
                    piece = sprite.crop(box)
                    if not piece.getchannel('A').getbbox():
                        continue
                    cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
                    jitter = math.sin((sx*17+sy*31+letter*13)*.11)
                    dx = (cx-center)*.48+jitter*tile*.25
                    dy = (cy-sprite.height/2)*.32+math.cos((sx*11-sy*7+letter)*.17)*tile*.25
                    _paste(layer, _opacity(piece, opacity), x+sx+round(dx*spring), y+sy+round(dy*spring))
