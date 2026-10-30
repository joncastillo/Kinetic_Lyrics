"""Masked reveal and cartoon pop are visible before the vocal cue."""
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class WordMotionTest(unittest.TestCase):
    def test_mask_rises_and_cartoon_title_overshoots(self):
        from kinetic_effects import mask_rise, cartoon_scale

        sprite = Image.new('RGBA', (20, 20), '#ffffff')
        self.assertEqual(mask_rise(sprite, 0).getbbox(), None)
        self.assertEqual(mask_rise(sprite, 1).getbbox(), sprite.getbbox())
        self.assertGreater(mask_rise(sprite, .5).getchannel('A').getbbox()[1], 0)
        self.assertLess(cartoon_scale(0), 1)
        self.assertGreater(cartoon_scale(.7), 1)
        self.assertEqual(cartoon_scale(1), 1)

    def test_first_word_enters_before_its_cue(self):
        from kinetic_director import Compositor, rules_plan
        from kinetic_lyrics import theme_for

        data = [dict(text='THUNDER', words=[dict(text='THUNDER', start=1., end=1.6)])]
        for mode in ('mask-rise', 'cartoon-pop'):
            c = Compositor(data, rules_plan(data, theme_for('bright')), 640, 360, 3.,
                           reading_flow='realtime', text_animation=mode, entrance_effect='none', exit_effect='none',
                           kinetic=dict(camera='still', fade=False, traces=False, geometry=0., backdrop_rate=0., frames=0.))
            before = c.frame(.3)
            entering = c.frame(.85)
            self.assertNotEqual(before.tobytes(), entering.tobytes(), mode)


if __name__ == '__main__':
    unittest.main()
