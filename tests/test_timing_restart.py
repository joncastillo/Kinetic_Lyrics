import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from kinetic_lyrics import timing_text_matches


class TimingRestartTest(unittest.TestCase):
    def test_edited_lyrics_invalidate_saved_timings(self):
        saved = [{'text': 'first line'}, {'text': 'second line'}]
        self.assertTrue(timing_text_matches(saved, ['first line', 'second line']))
        self.assertFalse(timing_text_matches(saved, ['first line']))
        self.assertFalse(timing_text_matches(saved, ['first line', 'changed line']))


if __name__ == '__main__':
    unittest.main()
