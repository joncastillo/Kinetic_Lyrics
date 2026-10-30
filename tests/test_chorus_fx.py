"""Chorus accents follow section labels and lyric imagery without changing verses."""
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class ChorusFXTest(unittest.TestCase):
    def test_lyric_motifs_and_section_windows(self):
        from render.chorus_fx import chorus_windows, motif_for

        self.assertEqual(motif_for('I give you my heart'), 'heart')
        self.assertEqual(motif_for('Leaves in the wind'), 'leaf')
        self.assertEqual(motif_for('Every flower blooms'), 'flower')
        self.assertEqual(motif_for('Petals in spring'), 'petal')
        self.assertEqual(motif_for('Stars over the night'), 'star')
        self.assertEqual(motif_for('Dance with me'), 'confetti')
        self.assertEqual(motif_for('We are here again'), 'none')
        data = [dict(text='quiet verse', section_id=0, section_label='Verse',
                     words=[dict(text='quiet', start=0., end=.5)]),
                dict(text='love and hearts', section_id=1, section_label='Chorus',
                     words=[dict(text='love', start=1., end=1.5)]),
                dict(text='back to quiet', section_id=2, section_label='Verse',
                     words=[dict(text='quiet', start=1.8, end=2.3)])]
        self.assertEqual(chorus_windows(data), [(1., 1.8, 1, 'heart')])

    def test_glowing_shapes_and_lights_are_time_pure(self):
        from render.chorus_fx import ChorusFX

        data = [dict(text='Stars in the sky', section_id=0, section_label='Chorus',
                     words=[dict(text='Stars', start=1., end=2.5)])]
        effect = ChorusFX(data, [[1.2, .8], [1.7, .9]], 1.)
        base = Image.new('RGB', (640, 360), '#14203A')
        first = effect.paint(base, 1.48)
        self.assertNotEqual(first.tobytes(), base.convert('RGBA').tobytes())
        self.assertEqual(first.tobytes(), effect.paint(base, 1.48).tobytes())
        self.assertIs(effect.paint(base, .5), base)
        self.assertIs(effect.paint(base, 3.3), base)

    def test_chorus_overlay_reaches_other_reading_flows(self):
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for

        words = [dict(text='Shining', start=1., end=1.4),
                 dict(text='stars', start=1.5, end=1.9)]
        data = [dict(text='Shining stars', words=words, section_id=0, section_label='Chorus')]
        def frame(strength):
            c = Compositor(data, rules_plan(data, theme_for('bright')), 640, 360, 4.,
                           reading_flow='cinema', entrance_effect='none', exit_effect='none',
                           rhythm=dict(drums=[[1.2, .9]]), kinetic=dict(fade=False, chorus_fx=strength))
            return c.frame(1.6)
        self.assertNotEqual(frame(1.).tobytes(), frame(0.).tobytes())


if __name__ == '__main__':
    unittest.main()
