"""Lyric-shaped wisp heads track the ribbon through turns without frame history."""
import math
import sys
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class WispFormsTest(unittest.TestCase):
    def test_lyric_forms_and_blending(self):
        from wisp_forms import form_for, forms_at

        for lyric, expected in [('the ball rolls', 'ball'), ('an airplane turns', 'airplane'),
                                ('the jet flies', 'jet'), ('a comet falls', 'comet'),
                                ('leaves drift', 'leaf'), ('the stars shine', 'star')]:
            self.assertEqual(form_for('unknown', lyric), expected)
        self.assertEqual(form_for('comet', 'the ball rolls'), 'comet')
        mixed = forms_at([(1., 'ball'), (2., 'jet')], 2.)
        self.assertEqual([kind for kind, _ in mixed], ['ball', 'jet'])
        self.assertAlmostEqual(sum(weight for _, weight in mixed), 1.)

    def test_heading_rotates_smoothly_around_a_bend(self):
        from wisp_forms import heading_at, paint_head

        points = [(100+50*math.cos(k*math.pi/36), 100+50*math.sin(k*math.pi/36))
                  for k in range(19)]
        piece = dict(points=points, color=(255, 255, 255), start=0.,
                     end=sum(math.dist(a, b) for a, b in zip(points, points[1:])))
        headings = [heading_at([piece], piece['end']*k/10) for k in range(1, 10)]
        self.assertLess(max(abs(b-a) for a, b in zip(headings, headings[1:])), .3)
        image = Image.new('RGBA', (200, 200))
        paint_head(ImageDraw.Draw(image), 100, 100, headings[4], 'airplane', 255, 15, 1.)
        self.assertIsNotNone(image.getbbox())


if __name__ == '__main__':
    unittest.main()
