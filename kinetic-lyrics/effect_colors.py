"""Base colour of each entrance recipe, so lettering is never paired with a background of the same colour.

Recipes that keep the glyph's own ink are marked 'ink'; material and particle lettering (gold,
maple, frost...) carries its own colour, measured once from a rendered sample and stored in
particles/colors.json. Regenerate with `python effect_colors.py` after adding recipes.
"""
import json
from functools import lru_cache
from pathlib import Path

COLORS_PATH = Path(__file__).with_name('particles')/'colors.json'
PROBE = (128, 128, 128)
MIN_CONTRAST = 1.8


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


def measure(effect):
    """Mean colour of the formed lettering drawn from a neutral grey word, or 'ink' if it keeps the glyph colour."""
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
    opaque = pixels[pixels[..., 3] > 160][:, :3]
    if not len(opaque):
        return 'ink'
    mean = opaque.mean(0)
    if np.abs(mean-np.array(PROBE)).max() < 18:
        return 'ink'
    return '#%02X%02X%02X' % tuple(round(v) for v in mean)


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


def readable_effect(current, candidates, ink, background, avoid=()):
    """Keep the chosen recipe unless it would blend into the background; then use the
    candidate with the best contrast, preferring ones not used on neighbouring lines."""
    if contrast(base_color(current, ink), background) >= MIN_CONTRAST:
        return current
    ranked = sorted(candidates, key=lambda e: (contrast(base_color(e, ink), background), e not in avoid), reverse=True)
    return ranked[0] if ranked else current


if __name__ == '__main__':
    from particle_catalog import discover_effects
    result = {name: measure(effect) for name, effect in sorted(discover_effects()['entrance'].items())}
    COLORS_PATH.write_text(json.dumps(result, indent=1, sort_keys=True), encoding='utf-8')
    print(json.dumps(result, indent=1))
