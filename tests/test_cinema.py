"""Black hole sun: short chunks of hairline and heavy words, drawn one chunk at a time from time alone."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


def lyrics(*lines):
    data = []
    for start, text in lines:
        words, t = [], start
        for word in text.split():
            words.append(dict(text=word, start=round(t, 3), end=round(t+.4, 3)))
            t += .5
        data.append(dict(text=text, words=words))
    return data


def compositor(data, duration=8., flow='cinema'):
    from kinetic_director import Compositor, rules_plan
    from kinetic_lyrics import theme_for
    return Compositor(data, rules_plan(data, theme_for('bright')), 360, 640, duration, reading_flow=flow,
                      entrance_effect='none', exit_effect='none', kinetic=dict(fade=False))


class CinemaTest(unittest.TestCase):
    def test_lines_split_into_short_chunks_with_one_heavy_word(self):
        from cinema_typography import CinemaTypography
        c = compositor(lyrics((1., 'black hole sun'), (3.5, 'and wash away the rain')))
        self.assertIsInstance(c.realtime, CinemaTypography)
        chunks = c.realtime.plan()
        self.assertEqual([[w['text'] for w in chunk['words']] for chunk in chunks][0], ['BLACK', 'HOLE'])
        self.assertEqual([w['weight'] for w in chunks[0]['words']], ['thin', 'heavy'])
        for chunk in chunks:
            self.assertLessEqual(len(chunk['words']), 3)
            self.assertLessEqual(sum(w['weight'] == 'heavy' for w in chunk['words']), 1)
        for a, b in zip(chunks, chunks[1:]):
            self.assertLessEqual(a['end'], b['start'])  # one chunk on screen at a time

    def test_frames_show_words_only_while_sung_and_repeat_exactly(self):
        c = compositor(lyrics((1., 'black hole sun')))
        empty = np.asarray(c.frame(.3)).astype(int)
        held = np.asarray(c.frame(1.6)).astype(int)
        self.assertGreater(np.abs(held-empty).max(), 100)
        self.assertTrue(np.array_equal(held, np.asarray(c.frame(1.6))))

    def test_scene_mix_films_a_section_in_the_cinema_scene(self):
        from scene_catalog import scene_catalog
        from scene_mix import SceneMix
        self.assertEqual(scene_catalog()['black-hole-sun']['camera'], 'cinema')
        c = compositor(lyrics((1., 'black hole sun')), flow='mixed')
        mix = SceneMix(c, flows=[dict(start=0, end=1, scene='black-hole-sun')])
        self.assertEqual(mix.engine(0).__class__.__name__, 'CinemaTypography')
        self.assertEqual(mix.frame(1.9).size, (360, 640))


if __name__ == '__main__':
    unittest.main()
