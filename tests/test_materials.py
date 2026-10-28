"""Material entrances and exits: every recipe is catalogued, deterministic, and starts and ends where it should."""
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from material_fx import held, paint
from material_recipes import RECIPES
from particle_catalog import discover_effects
from particle_motion import paint_transition


def word_sprite(text='Silk', size=72):
    font = ImageFont.truetype('C:/Windows/Fonts/georgiab.ttf', size)
    box = font.getbbox(text)
    sprite = Image.new('RGBA', (box[2]-box[0]+20, box[3]-box[1]+24))
    ImageDraw.Draw(sprite).text((10-box[0], 12-box[1]), text, font=font, fill=(236, 230, 220, 255))
    return sprite


def frame(effect, phase, t, sprite, cache=None):
    layer = Image.new('RGBA', (sprite.width+240, sprite.height+240))
    paint(layer, sprite, 120, 120, phase, t, effect, 5, 1., {} if cache is None else cache)
    return np.asarray(layer).astype(int)


class MaterialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = discover_effects()
        cls.sprite = word_sprite()

    def effects(self, phase):
        return [e for e in self.catalog[phase].values() if e.id in RECIPES]

    def test_every_recipe_is_catalogued_with_a_short_description(self):
        found = {e.id: e for phase in ('entrance', 'exit') for e in self.catalog[phase].values()
                 if e.family == 'material' or e.id in RECIPES}
        self.assertEqual(set(found), set(RECIPES))
        for effect_id, effect in found.items():
            self.assertEqual(RECIPES[effect_id]['phase'], 'entrance' if effect.trajectory == 'grow' else 'exit')
            self.assertTrue(effect.description, effect_id)

    def test_entrances_build_from_nothing_to_the_held_word(self):
        for effect in self.effects('entrance'):
            with self.subTest(effect.id):
                cache = {}
                self.assertLess(frame(effect, 'entrance', 0., self.sprite, cache)[..., 3].max(), 40)
                formed = frame(effect, 'entrance', 1., self.sprite, cache)
                self.assertGreater((formed[..., 3] > 128).sum(), 400)
                image, padding = held(self.sprite, effect, 5, 1., cache)
                layer = Image.new('RGBA', (self.sprite.width+240, self.sprite.height+240))
                layer.alpha_composite(image, (120-padding, 120-padding))
                self.assertLess(np.abs(np.asarray(layer).astype(int)-formed).max(), 3)

    def test_exits_leave_nothing_behind(self):
        for effect in self.effects('exit'):
            with self.subTest(effect.id):
                cache = {}
                early = frame(effect, 'exit', .02, self.sprite, cache)
                self.assertGreater((early[..., 3] > 128).sum(), 400)
                self.assertLess((frame(effect, 'exit', 1., self.sprite, cache)[..., 3] > 60).sum(), 30)

    def test_frames_depend_only_on_progress(self):
        effect = self.catalog['entrance']['marble-chisel-reveal']
        first = frame(effect, 'entrance', .4, self.sprite)
        frame(effect, 'entrance', .8, self.sprite)
        self.assertTrue(np.array_equal(first, frame(effect, 'entrance', .4, self.sprite)))

    def test_exit_runs_through_paint_transition(self):
        effect = self.catalog['exit']['paper-burn']
        layer = Image.new('RGBA', (400, 300))
        paint_transition(layer, self.sprite, 100, 100, 'exit', .5, effect, 3, 1., .6, {}, paced=False)
        self.assertGreater(np.asarray(layer)[..., 3].max(), 0)

    def test_large_sprites_run_at_capped_resolution(self):
        effect = self.catalog['entrance']['mucha-silk-lettering']
        big = word_sprite('Silk', 280)
        result = frame(effect, 'entrance', 1., big)
        self.assertGreater((result[..., 3] > 128).sum(), 5000)


if __name__ == '__main__':
    unittest.main()
