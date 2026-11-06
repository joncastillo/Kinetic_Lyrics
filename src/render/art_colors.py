"""Text colours drawn from the artwork behind each line.

The AI typography director picks a palette for every line, and with it a role: light or dark ink, and an accent
that is warm or cool. With "match the artwork" on, each line keeps that role but takes its actual colours from the
painting on screen while it is sung: the ink is tinted with the painting's dominant hue and pushed until it reads
clearly on the area behind the words, and the accent is one of the painting's own vivid colours, adjusted to stand
out from both. Song-wide colours typed in the instructions still win.
"""
from __future__ import annotations

import colorsys

from effects.colors import contrast, luminance
from core.color import rgb_hex as to_hex, hex_rgb as from_hex

INK_CONTRAST = 4.5      # body text on the painting
ACCENT_CONTRAST = 3.    # hero words in the accent
INK_TINT = .14          # how much of the painting's hue the ink takes


def mix(a, b, share):
    return tuple(x+(y-x)*share for x, y in zip(a, b))


def image_palette(image, count=8):
    """[(rgb, share)] of the painting's main colours, most common first."""
    small = image.convert('RGB').resize((96, max(1, round(96*image.height/max(1, image.width)))))
    quantised = small.quantize(colors=count, method=1)
    palette = quantised.getpalette()
    counts = sorted(quantised.getcolors(), reverse=True)
    total = sum(n for n, _ in counts) or 1
    return [(tuple(palette[i*3:i*3+3]), n/total) for n, i in counts]


def saturation(rgb):
    return colorsys.rgb_to_hls(*(v/255 for v in rgb))[2]


def until_readable(color, behind, target, towards):
    """Move `color` towards white or black until it has `target` contrast with `behind` (or as far as it goes)."""
    for step in range(21):
        candidate = mix(color, towards, step/20)
        if contrast(candidate, behind) >= target:
            return candidate
    return towards


def vivid_readable(rgb, behind, lighter):
    """The colour made saturated, then only its lightness moved (up for light ink, down for dark) until it reaches
    ACCENT_CONTRAST on `behind`; None when it cannot. Unlike mixing with white, it keeps its colour."""
    h, l, s = colorsys.rgb_to_hls(*(v/255 for v in rgb))
    s = max(s, .7)
    for step in range(34):
        level = min(.92, l+step*.02) if lighter else max(.1, l-step*.02)
        candidate = tuple(v*255 for v in colorsys.hls_to_rgb(h, level, s))
        if contrast(candidate, behind) >= ACCENT_CONTRAST:
            return candidate
    return None


def matched_palette(base, colors, behind):
    """(background, gradient, ink, accent) hex colours for a line whose director palette was `base`, from the
    painting's `colors` (see image_palette), readable on `behind`, the average colour behind the words."""
    base_ink = from_hex(base[2])
    light_ink = luminance(base_ink) > .4
    dominant = max(colors, key=lambda c: c[1])[0] if colors else (128, 128, 128)
    white, black = (255, 255, 255), (0, 0, 0)
    pole, other = (white, black) if light_ink else (black, white)
    ink = mix(pole, dominant, INK_TINT)
    if contrast(ink, behind) < INK_CONTRAST:
        ink = until_readable(ink, behind, INK_CONTRAST, pole)
    if contrast(ink, behind) < INK_CONTRAST:  # the director's light ink on a pale sky: flip to dark, and back
        flipped = until_readable(mix(other, dominant, INK_TINT), behind, INK_CONTRAST, other)
        if contrast(flipped, behind) > contrast(ink, behind):
            ink, pole = flipped, other
    warm = colorsys.rgb_to_hsv(*(v/255 for v in from_hex(base[3])))[0]
    def accent_score(entry):
        rgb, share = entry
        hue = colorsys.rgb_to_hsv(*(v/255 for v in rgb))[0]
        closeness = 1-min(abs(hue-warm), 1-abs(hue-warm))*2  # keep the director's warm or cool choice when it can
        return saturation(rgb)*(share**.35)*(.6+.4*closeness)
    vivid = sorted(colors, key=accent_score, reverse=True)
    accent = None
    for rgb, _ in vivid[:4]:
        candidate = vivid_readable(rgb, behind, pole == white)
        if candidate and contrast(candidate, ink) >= 1.25:
            accent = candidate
            break
    if accent is None:  # nothing vivid in the painting: the complement of its main colour
        h, l, _ = colorsys.rgb_to_hls(*(v/255 for v in dominant))
        complement = tuple(v*255 for v in colorsys.hls_to_rgb((h+.5) % 1, l, .8))
        accent = (vivid_readable(complement, behind, pole == white)
                  or until_readable(from_hex(base[3]), behind, ACCENT_CONTRAST, pole))
    # Backdrops and word boxes sit behind the ink: the painting's own deep (or pale) tone.
    deep = min(colors, key=lambda c: luminance(c[0]))[0] if light_ink else max(colors, key=lambda c: luminance(c[0]))[0]
    background = until_readable(mix(deep, other, .45), ink, INK_CONTRAST, other)
    gradient = mix(background, dominant, .35)
    return to_hex(background), to_hex(gradient), to_hex(ink), to_hex(accent)


def accent_set(colors, ink, count, min_contrast):
    """Up to `count` of the painting's own colours, distinct in hue and made vivid, each moved in lightness (away from
    the ink) until it stands out from the ink by `min_contrast`: word glows, traced shapes, the wisp."""
    ink = from_hex(ink) if isinstance(ink, str) else ink
    lighter = luminance(ink) < .4                     # dark ink: glows go light; light ink: they go deep
    ranked = sorted(colors, key=lambda c: saturation(c[0])*(c[1]**.35), reverse=True)
    chosen, hues = [], []
    for rgb, _ in ranked:
        h, l, s = colorsys.rgb_to_hls(*(v/255 for v in rgb))
        if any(min(abs(h-other), 1-abs(h-other)) < .07 for other in hues):
            continue
        s = max(s, .65)
        for step in range(30):
            level = min(.9, l+step*.02) if lighter else max(.12, l-step*.02)
            candidate = tuple(v*255 for v in colorsys.hls_to_rgb(h, level, s))
            if contrast(candidate, ink) >= min_contrast:
                chosen.append(to_hex(candidate))
                hues.append(h)
                break
        if len(chosen) == count:
            break
    while chosen and len(chosen) < count:            # a painting with few distinct hues repeats them
        chosen.append(chosen[len(chosen) % max(1, len(hues))])
    return chosen
