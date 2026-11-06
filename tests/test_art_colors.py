"""Text colours matched to the artwork: readable, true to the painting, and true to the director's choices."""
import colorsys
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.typography import PALETTES
from effects.colors import contrast, luminance
from render.art_colors import ACCENT_CONTRAST, INK_CONTRAST, from_hex, image_palette, matched_palette
from render.typography_settings import kinetic_options


def painting(*bands):
    image = Image.new('RGB', (300, 60*len(bands)))
    for k, color in enumerate(bands):
        image.paste(color, (0, 60*k, 300, 60*(k+1)))
    return image


class ArtColorsTest(unittest.TestCase):
    def test_ink_and_accent_are_readable_on_a_dark_sea(self):
        sea = painting((14, 40, 80), (20, 70, 120), (230, 120, 40))
        background, gradient, ink, accent = matched_palette(PALETTES['midnight'], image_palette(sea), (16, 50, 95))
        self.assertGreaterEqual(contrast(from_hex(ink), (16, 50, 95)), INK_CONTRAST)
        self.assertGreaterEqual(contrast(from_hex(accent), (16, 50, 95)), ACCENT_CONTRAST)
        hue = colorsys.rgb_to_hsv(*(v/255 for v in from_hex(accent)))[0]
        self.assertLess(min(abs(hue-.07), 1-abs(hue-.07)), .08, 'the accent is the painting\'s own orange')

    def test_light_ink_on_a_bright_sky_flips_to_dark(self):
        sky = painting((250, 236, 200), (240, 210, 150))
        _, _, ink, accent = matched_palette(PALETTES['midnight'], image_palette(sky), (246, 226, 180))
        self.assertLess(luminance(from_hex(ink)), .2)
        self.assertGreaterEqual(contrast(from_hex(ink), (246, 226, 180)), INK_CONTRAST)
        self.assertLess(luminance(from_hex(accent)), luminance((246, 226, 180)), 'the accent darkens with the ink')

    def test_the_option_is_off_by_default(self):
        self.assertFalse(kinetic_options({})['match_art_colors'])
        self.assertTrue(kinetic_options(dict(match_art_colors=True))['match_art_colors'])

    def test_the_compositor_keeps_instruction_colours_over_matched_ones(self):
        from render.compositor import Compositor
        compositor = Compositor.__new__(Compositor)
        compositor.ink_override, compositor.accent_override = (255, 0, 0), None
        scene = dict(palette='midnight', art_colors=('#000000', '#111111', '#EEEEEE', '#33AAFF'))
        self.assertEqual(compositor.scene_palette(scene), ('#000000', '#111111', '#FF0000', '#33AAFF'))

    def test_glows_come_from_the_painting_and_stand_out_from_the_ink(self):
        from render.art_colors import accent_set
        sunset = painting((20, 60, 110), (240, 140, 40), (90, 160, 80))
        glows = accent_set(image_palette(sunset), '#F4F2EE', 3, 1.5)
        self.assertEqual(len(glows), 3)
        for glow in glows:
            self.assertGreaterEqual(contrast(from_hex(glow), (244, 242, 238)), 1.5)
        hues = sorted(round(colorsys.rgb_to_hsv(*(v/255 for v in from_hex(g)))[0], 2) for g in glows)
        self.assertEqual(len(set(hues)), 3, 'three different colours of the painting')


if __name__ == '__main__':
    unittest.main()
