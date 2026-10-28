"""Base colour of each entrance recipe, so lettering is never paired with a background of the same colour.

Recipes that keep the glyph's own ink are marked 'ink'; material and particle lettering (gold,
maple, frost...) carries its own colours, measured once from a rendered sample. particles/colors.json
holds the mean colour (the catalogue swatch); particles/palettes.json holds every colour covering a
real share of the lettering, because a mean hides light parts: brass gears average to brown but are
partly pale gold, which vanishes on a yellow scene. Readability is checked against all of them.
Regenerate both with `python src/effect_colors.py` after adding recipes.
"""
import json
from functools import lru_cache
from pathlib import Path
from project_paths import PROJECT_ROOT

COLORS_PATH = PROJECT_ROOT/'particles'/'colors.json'
PALETTES_PATH = COLORS_PATH.with_name('palettes.json')
PROBE = (128, 128, 128)
MIN_CONTRAST = 1.8
MIN_DELTA_E = 28
DOMINANT_SHARE = .12


def luminance(rgb):
    def channel(value):
        value /= 255
        return value/12.92 if value <= .03928 else ((value+.055)/1.055)**2.4
    r, g, b = (channel(v) for v in rgb)
    return .2126*r+.7152*g+.0722*b


def contrast(a, b):
    """WCAG contrast ratio between two RGB colours (1 = identical brightness, 21 = black on white)."""
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light+.05)/(dark+.05)


def to_lab(rgb):
    def linear(value):
        value /= 255
        return value/12.92 if value <= .04045 else ((value+.055)/1.055)**2.4
    r, g, b = (linear(v) for v in rgb)
    xyz = ((.4124*r+.3576*g+.1805*b)/.95047, .2126*r+.7152*g+.0722*b, (.0193*r+.1192*g+.9505*b)/1.08883)
    fx, fy, fz = (v**(1/3) if v > .008856 else 7.787*v+16/116 for v in xyz)
    return 116*fy-16, 500*(fx-fy), 200*(fy-fz)


def delta_e(a, b):
    import math
    return math.dist(to_lab(a), to_lab(b))


def readability(colors, backdrop):
    """How clearly lettering made of `colors` stands out from every dominant backdrop colour
    (backdrop: [(rgb, share)], largest first). 1 or more is readable."""
    relevant = [rgb for rgb, share in backdrop if share >= DOMINANT_SHARE] or [backdrop[0][0]]
    return min(min(contrast(color, rgb)/MIN_CONTRAST, delta_e(color, rgb)/MIN_DELTA_E) for color in colors for rgb in relevant)


def rendered_pixels(effect):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from particle_motion import paint_transition
    try:
        font = ImageFont.truetype('impact.ttf', 120)
    except OSError:
        font = ImageFont.load_default(120)
    sprite = Image.new('RGBA', (520, 180))
    ImageDraw.Draw(sprite).text((10, 10), 'LYRIC', font=font, fill=PROBE+(255,))
    layer = Image.new('RGBA', (1000, 600))
    paint_transition(layer, sprite, 240, 210, 'entrance', 0., effect, 3, 1., .6, {})
    pixels = np.asarray(layer, dtype=float)
    return pixels[pixels[..., 3] > 160][:, :3]


def measure(effect):
    """Mean colour of the formed lettering drawn from a neutral grey word, or 'ink' if it keeps the glyph colour."""
    import numpy as np
    opaque = rendered_pixels(effect)
    if not len(opaque):
        return 'ink'
    mean = opaque.mean(0)
    if np.abs(mean-np.array(PROBE)).max() < 18:
        return 'ink'
    return '#%02X%02X%02X' % tuple(round(v) for v in mean)


def measure_palette(effect, count=4):
    """The lettering's main colours as '#RRGGBB', each covering at least DOMINANT_SHARE of it."""
    from PIL import Image
    if measure(effect) == 'ink':
        return 'ink'
    opaque = rendered_pixels(effect)
    quantized = Image.fromarray(opaque.reshape(-1, 1, 3).astype('uint8')).quantize(count)
    palette = quantized.getpalette()
    found = sorted(quantized.getcolors(), reverse=True)
    return ['#%02X%02X%02X' % tuple(palette[i*3:i*3+3]) for n, i in found if n/len(opaque) >= DOMINANT_SHARE]


@lru_cache(maxsize=1)
def palettes():
    try:
        return json.loads(PALETTES_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def lettering_colors(effect, ink):
    """Every main colour of an effect's lettering (the line ink for recipes that keep it)."""
    value = palettes().get(getattr(effect, 'id', None)) or getattr(effect, 'base_color', 'ink')
    if value == 'ink':
        return [ink] if ink else []
    values = [value] if isinstance(value, str) else value
    return [tuple(int(v[i:i+2], 16) for i in (1, 3, 5)) for v in values]


@lru_cache(maxsize=1)
def colors():
    try:
        return json.loads(COLORS_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def base_color(effect_id, ink):
    """RGB the lettering will mostly show for this recipe, given the line's ink colour.
    Uses the catalogue metadata (Effect.base_color), falling back to the stored measurements."""
    from particle_catalog import discover_effects
    effect = discover_effects()['entrance'].get(effect_id)
    value = effect.base_color if effect is not None else colors().get(effect_id, 'ink')
    if value == 'ink':
        return ink
    return tuple(int(value[i:i+2], 16) for i in (1, 3, 5))


def readable_effect(current, candidates, ink, backdrop, avoid=()):
    """Keep the chosen recipe unless any of its colours would blend into the backdrop (an RGB colour,
    or [(rgb, share)] dominant colours); then use the most readable candidate, preferring ones not
    used on neighbouring lines."""
    from particle_catalog import discover_effects
    catalog = discover_effects()['entrance']
    if isinstance(backdrop[0], (int, float)):
        backdrop = [(tuple(backdrop), 1.)]

    def clarity(effect_id):
        effect = catalog.get(effect_id)
        found = lettering_colors(effect, ink) if effect else [ink]
        return readability(found, backdrop) if found else 1.
    if clarity(current) >= 1:
        return current
    ranked = sorted(candidates, key=lambda e: (min(1., clarity(e)), e not in avoid, clarity(e)), reverse=True)
    return ranked[0] if ranked else current


if __name__ == '__main__':
    from particle_catalog import discover_effects
    effects = sorted(discover_effects()['entrance'].items())
    result = {name: measure(effect) for name, effect in effects}
    COLORS_PATH.write_text(json.dumps(result, indent=1, sort_keys=True), encoding='utf-8')
    PALETTES_PATH.write_text(json.dumps({name: measure_palette(effect) for name, effect in effects}, indent=1, sort_keys=True), encoding='utf-8')
    print(f'Measured {len(result)} entrance effects.')
