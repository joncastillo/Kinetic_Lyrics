"""Timeline editor edits: word timing, lyric text and illustration start times."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from timeline import apply_edits, checked_art_times, illustration_starts, rewrite_lyrics, tighten_line_starts


def song():
    return [dict(text='hello there', section_id=0, words=[dict(text='hello', start=1., end=1.4, onset='measured'), dict(text='there', start=1.5, end=2.)]),
            dict(text='good night', section_id=1, words=[dict(text='good', start=3., end=3.3), dict(text='night', start=3.4, end=4.)])]


def edits(data):
    return [[dict(text=w['text'], start=w['start'], end=w['end']) for w in line['words']] for line in data]


class ApplyEditsTest(unittest.TestCase):
    def test_text_and_times_change_and_other_fields_stay(self):
        lines = edits(song())
        lines[1][0].update(text='Goodbye', start=2.9)
        result = apply_edits(song(), lines, 10.)
        self.assertEqual(result[1]['text'], 'Goodbye night')
        self.assertEqual(result[1]['words'][0]['start'], 2.9)
        self.assertEqual(result[1]['words'][0]['onset'], 'manual')
        self.assertEqual(result[1]['section_id'], 1)
        self.assertEqual(result[0]['words'][0]['onset'], 'measured')

    def test_word_count_must_not_change(self):
        lines = edits(song())
        lines[0].pop()
        with self.assertRaises(ValueError):
            apply_edits(song(), lines, 10.)

    def test_starts_stay_in_order(self):
        lines = edits(song())
        lines[1][0].update(start=1.2, end=1.6)
        with self.assertRaises(ValueError):
            apply_edits(song(), lines, 10.)

    def test_word_needs_length_and_text(self):
        lines = edits(song())
        lines[0][1]['end'] = 1.51
        with self.assertRaises(ValueError):
            apply_edits(song(), lines, 10.)
        lines = edits(song())
        lines[0][1]['text'] = ' ,, '
        with self.assertRaises(ValueError):
            apply_edits(song(), lines, 10.)

    def test_manual_start_survives_tightening(self):
        lines = edits(song())
        lines[1][0].update(start=2.)
        result = tighten_line_starts(apply_edits(song(), lines, 10.))
        self.assertEqual(result[1]['words'][0]['start'], 2.)


class ArtTimesTest(unittest.TestCase):
    def test_valid_times(self):
        self.assertEqual(checked_art_times([0, 2.5, 7], 3, 10.), [0., 2.5, 7.])

    def test_rejects_wrong_count_order_or_range(self):
        for times in ([0, 1], [0, 3, 2], [0, 1, 11], [0, 1, float('nan')]):
            with self.assertRaises(ValueError):
                checked_art_times(times, 3, 10.)

    def test_default_starts(self):
        self.assertEqual(illustration_starts([2., 4., 6., 8., 10.], 3, 2), [1., 5., 9.])
        self.assertEqual(illustration_starts([2., 4., 6.], 2, 1, line_groups=[[0, 1], [2]]), [2., 6.])


class LyricsTest(unittest.TestCase):
    def test_labels_and_blank_lines_stay(self):
        source = '[Verse]\nhello there\n\n[Chorus]\ngood night\n'
        self.assertEqual(rewrite_lyrics(source, ['hello you', 'good night']), '[Verse]\nhello you\n\n[Chorus]\ngood night\n')


if __name__ == '__main__':
    unittest.main()
