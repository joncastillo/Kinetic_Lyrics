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


def shake_background(screen, hit, shake, dim=0.):
    """Jolt the painted background on each four-on-the-floor kick the words react to.

    The frame is punched in (a quick zoom) and thrown sideways, so the shift never exposes an edge; `dim` darkens
    the background on the beat and lets it recover before the next kick."""
    if hit is None or (shake <= 0 and dim <= 0):
        return screen
    ordinal, age, strength = hit
    weight = .55+.45*strength
    width, height = screen.size
    side = min(width, height)
    energy = min(1., shake)*weight*math.exp(-age*7)
    reach = side*.045*energy
    dx = reach*math.cos(age*62+ordinal*1.7)
    dy = reach*.7*math.sin(age*79+ordinal*2.3)
    punch = .045*min(1., shake)*weight*math.exp(-age*9)
    darken = min(1., dim)*.6*weight*math.exp(-age*6)
    if abs(dx) < .5 and abs(dy) < .5 and punch < .002 and darken < .01:
        return screen
    if reach >= .5 or punch >= .002:
        # Zoom just enough to cover the throw, plus the punch, then crop back to the frame.
        scale = 1+2*(abs(dx)+abs(dy))/side+punch
        zoomed = screen.resize((math.ceil(width*scale), math.ceil(height*scale)), Image.Resampling.BILINEAR)
        left = (zoomed.width-width)/2-dx
        top = (zoomed.height-height)/2-dy
        left = round(min(max(0, left), zoomed.width-width))
        top = round(min(max(0, top), zoomed.height-height))
        screen = zoomed.crop((left, top, left+width, top+height))
    if darken >= .01:
        black = Image.new(screen.mode, screen.size, (0, 0, 0, 255) if screen.mode == 'RGBA' else (0, 0, 0))
        dimmed = Image.blend(screen, black, darken)
        if screen.mode == 'RGBA':
            dimmed.putalpha(screen.getchannel('A'))
        screen = dimmed
    return screen


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
