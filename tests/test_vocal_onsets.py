import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class VocalOnsetsAndTimingTest(unittest.TestCase):
    def test_repair_zero_durations_fixes_chronological_and_zero_duration(self):
        from kinetic_lyrics import repair_zero_durations, validate

        data = [
            {
                'text': 'Line one',
                'words': [
                    {'text': 'Line', 'start': 10.0, 'end': 10.5},
                    {'text': 'one', 'start': 10.5, 'end': 11.0},
                ],
            },
            {
                'text': 'Line two',
                'words': [
                    # Inverted / earlier start than previous line's end
                    {'text': 'Line', 'start': 10.4, 'end': 11.2},
                    # Zero duration
                    {'text': 'two', 'start': 11.2, 'end': 11.2},
                ],
            },
        ]

        lines = ['Line one', 'Line two']
        repaired = repair_zero_durations(data, duration=20.0)
        self.assertEqual(repaired, 2)
        # Should now pass validation
        validate(data, lines, duration=20.0)

        # First word of line 2 clamped to previous (10.5)
        self.assertGreaterEqual(float(data[1]['words'][0]['start']), 10.5)
        # Second word of line 2 has positive duration
        self.assertGreater(float(data[1]['words'][1]['end']), float(data[1]['words'][1]['start']))

    def test_refine_line_starts_never_moves_start_backwards(self):
        from vocal_onsets import refine_line_starts
        from unittest.mock import patch

        # Construct short-duration word where word['end'] - 0.12 < word['start']
        data = [
            {
                'text': 'Short word',
                'words': [
                    {'text': 'Short', 'start': 90.42, 'end': 90.50, 'onset': 'aligned', 'onset_version': 0},
                    {'text': 'word', 'start': 90.42, 'end': 90.50},
                ],
            }
        ]

        # Mock vocal_stem and audio analysis to simulate an onset detected at 90.48
        with patch('vocal_onsets.vocal_stem', return_value=Path('dummy.wav')), \
             patch('vocal_onsets.read_mono', return_value=([0.0] * 1000, 100)), \
             patch('vocal_onsets.loudness', return_value=[0.0] * 1000), \
             patch('vocal_onsets.rising_edge', return_value=90.48):
            moved = refine_line_starts(data, Path('dummy.mp3'), Path('.'))

        # Because max_start was constrained by word['end']-0.08 and word[1]['start'],
        # the start must NOT have been moved backwards to 90.38
        self.assertEqual(moved, 0)
        self.assertEqual(data[0]['words'][0]['start'], 90.42)


if __name__ == '__main__':
    unittest.main()
