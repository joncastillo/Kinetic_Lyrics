import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from timing_repair import collapsed_lines, transcript_timing


class TimingRepairTest(unittest.TestCase):
    def test_collapsed_line_is_detected(self):
        data = [dict(words=[dict(start=89.72, end=89.8) for _ in range(5)])]
        self.assertEqual(collapsed_lines(data), [0])

    def test_transcript_times_preserve_supplied_words(self):
        lines = ['People writing songs that voices never share', 'And no one dared']
        heard = [dict(word=word, start=start, end=end) for word, start, end in [
            ('People', 89.4, 90.6), ('writing', 90.6, 91.3), ('songs', 91.3, 92.3),
            ('that', 92.6, 93.9), ('voices', 93.9, 94.8), ('never', 94.8, 95.6),
            ('share', 95.6, 96.), ('no', 97.3, 98.5), ('one', 98.5, 98.9),
            ('dared', 98.9, 99.4)]]
        repaired = transcript_timing(lines, heard)
        self.assertEqual(repaired[0]['words'][0]['start'], 89.4)
        self.assertEqual(repaired[0]['words'][-1]['end'], 96.)
        self.assertEqual(repaired[1]['words'][0]['text'], 'And')
        self.assertGreaterEqual(repaired[1]['words'][0]['start'], 96.)
        self.assertEqual(collapsed_lines(repaired), [])

    def test_unrelated_transcription_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'did not match enough'):
            transcript_timing(['People writing songs that voices never share'],
                              [dict(word='instrumental', start=1., end=2.)])


if __name__ == '__main__':
    unittest.main()
