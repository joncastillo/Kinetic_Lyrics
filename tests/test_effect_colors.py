"""Every effect can be coloured by the AI director: coloured ids, the recolour, and the director's colour choice."""

import json
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def word_sprite():
    sprite = Image.new('RGBA', (220, 90))
    ImageDraw.Draw(sprite).rectangle((20, 20, 200, 70), fill=(246, 244, 238, 255))
    return sprite


class EffectColourTest(unittest.TestCase):
    def test_a_coloured_id_is_the_effect_with_its_colour(self):
        from effects.particles.catalog import discover_effects, split_color, with_color

        catalog = discover_effects()['entrance']
        self.assertIn('glass-prism@#3fa9ff', catalog)
        effect = catalog['glass-prism@#3FA9FF']
        self.assertEqual((effect.id, effect.color), ('glass-prism', '#3fa9ff'))
        self.assertIsNone(catalog['glass-prism'].color)
        self.assertEqual(split_color(with_color('glass-prism@#111111', '#22AA44')), ('glass-prism', '#22aa44'))
        self.assertEqual(with_color('none', '#22aa44'), 'none')

    def test_a_coloured_entrance_still_lands_on_the_plain_word(self):
        from effects.particles.catalog import discover_effects
        from effects.particles.motion import paint_transition

        catalog = discover_effects()['entrance']
        sprite = word_sprite()
        for name in ('glass-prism', 'kinetic-pop-extrude'):
            plain, coloured = Image.new('RGBA', (400, 200)), Image.new('RGBA', (400, 200))
            paint_transition(plain, sprite, 90, 50, 'entrance', 0.0, catalog[name], 3, 1.0, 0.6, {})
            paint_transition(coloured, sprite, 90, 50, 'entrance', 0.0, catalog[name + '@#2fd67a'], 3, 1.0, 0.6, {})
            self.assertEqual(plain.tobytes(), coloured.tobytes(), name)

    def test_the_colour_shows_while_the_effect_plays(self):
        from effects.particles.catalog import discover_effects
        from effects.particles.motion import paint_transition

        catalog = discover_effects()['entrance']
        sprite = word_sprite()
        plain, coloured = Image.new('RGBA', (400, 200)), Image.new('RGBA', (400, 200))
        paint_transition(plain, sprite, 90, 50, 'entrance', 0.6, catalog['kinetic-pop-extrude'], 3, 1.0, 0.6, {})
        paint_transition(coloured, sprite, 90, 50, 'entrance', 0.6, catalog['kinetic-pop-extrude@#2fd67a'], 3, 1.0, 0.6, {})
        self.assertNotEqual(plain.tobytes(), coloured.tobytes())
        rgb = np.asarray(coloured)[..., :3].reshape(-1, 3)
        greenish = ((rgb[:, 1] > rgb[:, 0] + 40) & (rgb[:, 1] > rgb[:, 2] + 20)).sum()
        self.assertGreater(greenish, 50)

    def test_a_decorated_lettering_keeps_its_colour_at_rest(self):
        from effects.particles.catalog import discover_effects
        from effects.particles.motion import paint_transition

        catalog = discover_effects()['entrance']
        grown = next((e for e in catalog.values() if e.trajectory == 'grow'), None)
        if grown is None:
            self.skipTest('no decorated lettering in the catalogue')
        sprite = word_sprite()
        plain, coloured = Image.new('RGBA', (400, 200)), Image.new('RGBA', (400, 200))
        paint_transition(plain, sprite, 90, 50, 'entrance', 0.0, catalog[grown.id], 3, 1.0, 0.6, {})
        paint_transition(coloured, sprite, 90, 50, 'entrance', 0.0, catalog[grown.id + '@#3fa9ff'], 3, 1.0, 0.6, {})
        self.assertNotEqual(plain.tobytes(), coloured.tobytes())

    def test_the_director_chooses_a_readable_colour_for_each_line(self):
        from direction.effects import choose
        from effects.particles.catalog import discover_effects, split_color

        catalog = discover_effects()['entrance']
        ids = ['glass-prism', 'kinetic-pop-extrude']
        data = [dict(text='hold me close'), dict(text='until the morning'), dict(text='old answer')]
        contexts = [dict(meaning='', scene='')] * 3
        navy = [((20, 28, 50), 1.0)]
        backdrops = [navy, navy, navy]
        lists = [ids, ids, ids]

        def request(payload):
            return dict(message=dict(content=json.dumps({
                '0': dict(effect='kinetic-pop-extrude', color='#FF5A4E'),  # readable on navy: kept
                '1': dict(effect='glass-prism', color='#141c30'),  # navy on navy: replaced
                '2': 'glass-prism',  # the older answer shape, an id alone
            })))

        chosen = [split_color(c) for c in choose(data, contexts, backdrops, lists, catalog, 'test', request)]
        self.assertEqual(chosen[0], ('kinetic-pop-extrude', '#ff5a4e'))
        self.assertEqual(chosen[1][0], 'glass-prism')
        self.assertNotEqual(chosen[1][1], '#141c30')
        self.assertIsNotNone(chosen[1][1])
        self.assertEqual(chosen[2][0], 'glass-prism')
        self.assertIsNotNone(chosen[2][1])
        unattended = choose(data, contexts, backdrops, lists, catalog, 'test', None)
        self.assertTrue(all(split_color(c)[1] for c in unattended))


if __name__ == '__main__':
    unittest.main()
