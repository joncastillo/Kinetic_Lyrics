"""The stretch of the video a painting's rebuild replaces."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio.worker import section_span


class SectionSpanTest(unittest.TestCase):
    def test_the_first_painting_is_rebuilt_from_the_start_of_the_video(self):
        # its clip plays through the intro; starting at the first lyric left the old still there
        self.assertEqual(section_span([3.39, 10.02, 20.28], 0, 60.), (0., 10.92))

    def test_a_later_painting_is_rebuilt_from_its_own_start(self):
        self.assertEqual(section_span([3.39, 10.02, 20.28], 1, 60.), (10.02, 21.18))

    def test_the_last_painting_runs_to_the_end(self):
        self.assertEqual(section_span([3.39, 10.02], 1, 60.), (10.02, 60.))

    def test_a_section_never_passes_the_end_of_the_video(self):
        self.assertEqual(section_span([3.39, 59.5, 59.8], 1, 60.), (59.5, 60.))


if __name__ == '__main__':
    unittest.main()
