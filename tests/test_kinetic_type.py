import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np
from PIL import Image, ImageDraw

from core.fonts import truetype
from effects.particles.catalog import discover_effects
from effects.particles.motion import paint_transition


def word(text='MOVE', size=80, font='Anton-Regular.ttf'):
    face = truetype(str(ROOT / 'assets' / 'fonts' / font), size)
    pad = 10
    sprite = Image.new('RGBA', (math.ceil(face.getlength(text)) + pad * 2, round(size * 1.4) + pad * 2))
    ImageDraw.Draw(sprite).text((pad, pad), text, font=face, fill=(240, 240, 240, 255))
    edges = [0] + [pad + round(face.getlength(text[:k])) for k in range(1, len(text))] + [sprite.width]
    return sprite, list(zip(edges, edges[1:]))


class KineticTypeTest(unittest.TestCase):
    def setUp(self):
        self.effects = {k: e for k, e in discover_effects()['entrance'].items() if e.family == 'kinetic'}

    def test_kinetic_family_is_curated_and_described(self):
        self.assertGreaterEqual(len(self.effects), 12)
        for effect in self.effects.values():
            self.assertTrue(effect.description)

    def test_every_style_lands_exactly_on_the_plain_word(self):
        for text, font in (
            ('MOVE', 'Anton-Regular.ttf'),
            ('tonight', 'DelaGothicOne-Regular.ttf'),
            ('I', 'ArchivoBlack-Regular.ttf'),
        ):
            sprite, spans = word(text, font=font)
            rest = Image.new('RGBA', (600, 300))
            rest.alpha_composite(sprite, (100, 80))
            for key, effect in self.effects.items():
                with self.subTest(effect=key, word=text):
                    layer = Image.new('RGBA', (600, 300))
                    paint_transition(
                        layer, sprite, 100, 80, 'entrance', 0.0, effect, 3, 1.0, 0.6, {}, glyph_spans=spans
                    )
                    self.assertEqual(layer.tobytes(), rest.tobytes())

    def test_frames_are_pure_functions_of_progress(self):
        sprite, spans = word()
        for key, effect in self.effects.items():
            with self.subTest(effect=key):
                frames = []
                for _ in range(2):
                    layer = Image.new('RGBA', (600, 300))
                    paint_transition(
                        layer, sprite, 100, 80, 'entrance', 0.55, effect, 3, 1.0, 0.6, {}, glyph_spans=spans
                    )
                    frames.append(layer.tobytes())
                self.assertEqual(frames[0], frames[1])
                self.assertIsNotNone(Image.frombytes('RGBA', (600, 300), frames[0]).getbbox())

    def test_words_near_the_frame_edge_and_extreme_intensities_do_not_fail(self):
        sprite, spans = word('Starlight')
        for key, effect in self.effects.items():
            for x, y, intensity in ((-40, -20, 0.4), (560, 250, 1.8)):
                with self.subTest(effect=key, x=x, intensity=intensity):
                    layer = Image.new('RGBA', (600, 300))
                    for amount in (0.95, 0.6, 0.3, 0.05):
                        paint_transition(
                            layer, sprite, x, y, 'entrance', amount, effect, 5, intensity, 0.6, {}, glyph_spans=spans
                        )

    def test_art_window_shows_the_artwork_through_the_letters(self):
        # The artwork is screen-printed into the letters: a dark painting and a bright one fill them differently.
        sprite, spans = word()
        fills = []
        ramp = Image.linear_gradient('L').resize((600, 300)).convert('RGBA')
        for art in (ramp, ramp.transpose(Image.Transpose.FLIP_TOP_BOTTOM)):
            layer = Image.new('RGBA', (600, 300))
            paint_transition(
                layer,
                sprite,
                100,
                80,
                'entrance',
                0.8,
                self.effects['kinetic-art-window'],
                3,
                1.0,
                0.6,
                {'backdrop': art},
                glyph_spans=spans,
            )
            fills.append(np.asarray(layer, np.float32))
        solid = (fills[0][..., 3] > 200) & (fills[1][..., 3] > 200)
        difference = np.abs(fills[0][..., :3] - fills[1][..., :3]).sum(axis=-1)[solid]
        self.assertGreater((difference > 120).sum(), 200)


class DisplayFontTest(unittest.TestCase):
    def test_bundled_display_fonts_are_selectable_and_load(self):
        from render.typography_settings import DISPLAY_FONTS, FONT_FAMILIES, selected_font, typography_options

        for family in DISPLAY_FONTS:
            self.assertIn(family, FONT_FAMILIES)
            self.assertEqual(typography_options(dict(font_family=family))['font_family'], family)
            for style in ('regular', 'bold', 'italic'):
                path = selected_font(family, style)
                self.assertTrue(Path(path).is_file(), path)
                self.assertGreater(truetype(path, 40).getlength('Ag'), 0)

    def test_variable_fonts_open_at_their_display_weight(self):
        thin = truetype(str(ROOT / 'assets' / 'fonts' / 'BigShouldersDisplay[wght].ttf'), 100)
        mask = thin.getmask('O')
        ink = sum(1 for v in mask if v > 128) / max(1, mask.size[0] * mask.size[1])
        self.assertGreater(ink, 0.35)  # Thin (the file's default instance) inks far less of its box

    def test_realtime_hero_words_use_the_chosen_font(self):
        from render.realtime import role_font, use_display_font
        from render.typography_settings import selected_font

        try:
            use_display_font(selected_font('shrikhand', 'auto'))
            self.assertIn('Shrikhand', role_font('hero', 60).getname()[0])
            self.assertNotIn('Shrikhand', role_font('function', 60).getname()[0])
        finally:
            use_display_font(None)


class PosterSceneTest(unittest.TestCase):
    def test_poster_scenes_are_in_the_catalog(self):
        from direction.scene_catalog import scene_catalog

        catalog = scene_catalog()
        self.assertEqual(
            (catalog['proportion-stack']['camera'], catalog['proportion-stack']['layout']), ('poster', 'stack')
        )
        self.assertEqual((catalog['word-wall']['camera'], catalog['word-wall']['layout']), ('poster', 'wall'))
        for scene, layout in (
            ('word-seal', 'seal'),
            ('title-grid', 'grid'),
            ('word-blink', 'blink'),
            ('camera-tour', 'tour'),
            ('word-spiral', 'spiral'),
            ('type-drum', 'drum'),
            ('receding-stack', 'recede'),
            ('horizon-rise', 'horizon'),
            ('accordion-fold', 'fold'),
            ('type-ribbon', 'ribbon'),
            ('counter-dive', 'dive'),
            ('halftone-bloom', 'halftone'),
            ('word-search', 'search'),
            ('type-mobile', 'mobile'),
            ('stamp-collage', 'stamp'),
            ('misregistration', 'register'),
            ('block-drop', 'drop'),
        ):
            self.assertEqual((catalog[scene]['camera'], catalog[scene]['layout']), ('poster', layout))

    def test_every_poster_layout_draws_the_sung_line(self):
        from render.poster import PosterTypography
        from direction.scene_catalog import POSTER_LAYOUTS

        class Stub:
            data = [
                dict(
                    words=[
                        dict(text=w, start=1 + i * 0.4, end=1.3 + i * 0.4)
                        for i, w in enumerate('hold me close until morning'.split())
                    ]
                )
            ]
            duration = 6.0

        for layout in POSTER_LAYOUTS:
            with self.subTest(layout=layout):
                engine = PosterTypography(Stub(), layouts={0: layout})
                line = engine.plan()[0]
                screen = Image.new('RGBA', (480, 270), (20, 30, 50, 255))
                from render.poster import PAINTERS

                getattr(engine, PAINTERS[layout])(screen, line, 2.0)
                self.assertGreater(len(set(screen.convert('RGB').get_flattened_data())), 3)

    def test_stack_swells_the_sung_row(self):
        from render.poster import PosterTypography, rows_of

        class Stub:
            data = [
                dict(
                    words=[
                        dict(text=w, start=1 + i * 0.4, end=1.3 + i * 0.4)
                        for i, w in enumerate('golden light upon the water'.split())
                    ]
                )
            ]
            duration = 6.0

        engine = PosterTypography(Stub())
        line = engine.plan()[0]
        self.assertEqual([r['text'] for r in rows_of(line['words'])][:2], ['GOLDEN', 'LIGHT'])
        heights = engine.stack_heights(line, 1.5)
        self.assertEqual(max(range(len(heights)), key=heights.__getitem__), 1)  # LIGHT, sung from 1.4 s
        self.assertAlmostEqual(sum(heights), 1.0)


class WispFinaleTest(unittest.TestCase):
    def test_the_ribbon_flares_then_bursts_into_fading_sparks(self):
        from render.wisp_finale import BURST_TIME, paint_finale, ribbon_strength

        self.assertEqual(ribbon_strength(-1), 1.0)
        self.assertGreater(ribbon_strength(0.05), 1.0)
        self.assertEqual(ribbon_strength(1.0), 0.0)
        strand = [(100 + k * 4, 150 - k, (120, 220, 90)) for k in range(60)]
        counts = []
        for age in (0.05, 0.6, BURST_TIME - 0.05, BURST_TIME + 0.1):
            layer = Image.new('RGBA', (500, 300))
            paint_finale(layer, strand, age, 7, 6.0)
            counts.append(int((np.asarray(layer)[..., 3] > 40).sum()))
        self.assertGreater(counts[0], 0)
        self.assertGreater(counts[0], counts[2])
        self.assertEqual(counts[3], 0)


if __name__ == '__main__':
    unittest.main()
