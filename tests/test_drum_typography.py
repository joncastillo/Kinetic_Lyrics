"""Drum impacts are timed to the separated stem and settle back to the normal frame."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class DrumTypographyTest(unittest.TestCase):
    def test_ranked_hit_selection_and_modes(self):
        from drum_typography import impact_kind
        from rhythm import pulse

        events = [[1., .2], [2., .8], [2.25, .5]]
        self.assertIsNone(pulse(events, 1.1, .18).hit)
        ordinal, age, strength = pulse(events, 2.1, .18).hit
        self.assertEqual((ordinal, strength), (1, .8))
        self.assertAlmostEqual(age, .1)
        ordinal, age, strength = pulse(events, 2.3, .18).hit
        self.assertEqual((ordinal, strength), (2, .5))
        self.assertAlmostEqual(age, .05)
        self.assertGreater(pulse(events, 2.3, .18).level, 0.)
        self.assertEqual(impact_kind(3, .5), 'shake')
        self.assertEqual([impact_kind(i, 1.) for i in range(4)], ['pixels', 'squash', 'echo', 'shake'])

    def test_regular_thumps_shake_background_without_empty_edges(self):
        from PIL import Image
        from drum_typography import shake_background
        from rhythm import four_floor_hits, pulse

        events = [[t, .8] for t in (1., 1.5, 2., 2.5)]
        self.assertEqual(four_floor_hits(events), frozenset(range(4)))
        self.assertEqual(four_floor_hits([[1., .8], [1.48, .8], [2.2, .8], [2.9, .8]]), frozenset())
        background = Image.new('RGBA', (640, 360), '#4269A4')
        background.paste('#E9BD57', (180, 100, 460, 260))
        shaken = shake_background(background, pulse(events, 2.53, .18).hit, .9)
        self.assertNotEqual(shaken.tobytes(), background.tobytes())
        self.assertEqual(shaken.getchannel('A').getextrema(), (255, 255))
        self.assertEqual(shake_background(background, None, .9).tobytes(), background.tobytes())

    def test_rendered_impact_is_repeatable_and_recovers(self):
        from kinetic_director import Compositor, rules_plan
        from kinetic_lyrics import theme_for

        words = [dict(text=w, start=1+i*.5, end=1.4+i*.5)
                 for i, w in enumerate('We feel the thunder'.split())]
        data = [dict(text='We feel the thunder', words=words, section_id=0, section_label='Chorus')]
        def make(reactivity, glows=None):
            return Compositor(data, rules_plan(data, theme_for('bright')), 640, 360, 5.,
                              reading_flow='realtime', entrance_effect='none', exit_effect='none',
                              rhythm=dict(drums=[[2.8, 1.]]), kinetic=dict(fade=False, drum_reactivity=reactivity,
                                                                           glows=['drums'] if glows is None else glows,
                                                                           glow_words=0.))

        reactive, plain = make(.8), make(0.)
        impacted = np.asarray(reactive.frame(2.9))
        self.assertTrue(np.array_equal(impacted, np.asarray(reactive.frame(2.9))))
        self.assertFalse(np.array_equal(impacted, np.asarray(plain.frame(2.9))))
        self.assertFalse(np.array_equal(impacted, np.asarray(make(.8, []).frame(2.9))))
        self.assertTrue(np.array_equal(np.asarray(reactive.frame(3.4)), np.asarray(plain.frame(3.4))))

    def test_drum_impact_is_reserved_for_chorus(self):
        from kinetic_director import Compositor, rules_plan
        from kinetic_lyrics import theme_for

        words = [dict(text='Thunder', start=1., end=2.)]
        data = [dict(text='Thunder', words=words, section_id=0, section_label='Verse')]
        def frame(amount):
            c = Compositor(data, rules_plan(data, theme_for('bright')), 640, 360, 3.,
                           reading_flow='realtime', entrance_effect='none', exit_effect='none',
                           rhythm=dict(drums=[[1.5, 1.]]), kinetic=dict(fade=False,
                           drum_reactivity=amount, glows=[], glow_words=0.))
            return c.frame(1.6)
        self.assertTrue(np.array_equal(np.asarray(frame(.8)), np.asarray(frame(0.))))


if __name__ == '__main__':
    unittest.main()
