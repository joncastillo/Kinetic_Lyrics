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

    def test_unheard_backing_lines_are_spread_over_the_gap(self):
        from timing_repair import spread_collapsed
        line = lambda text, start, end: dict(text=text, words=[dict(text=w, start=start, end=end) for w in text.split()])
        data = [line('You and I will fall in love', 10., 10.),
                line('(You and I will fall in love)', 10., 10.05),
                line('People say that love is a game', 10.05, 10.1)]
        data[0]['words'] = [dict(text=w, start=8. + i * .4, end=8.3 + i * .4) for i, w in enumerate(data[0]['text'].split())]
        data[2]['words'] = [dict(text=w, start=16. + i * .4, end=16.3 + i * .4) for i, w in enumerate(data[2]['text'].split())]
        self.assertEqual(spread_collapsed(data), [1])
        self.assertEqual(collapsed_lines(data), [])
        backing = data[1]['words']
        self.assertGreaterEqual(backing[0]['start'], round(data[0]['words'][-1]['end'], 3))
        self.assertLessEqual(backing[-1]['end'], 16.)
        self.assertEqual([w['start'] for w in backing], sorted(w['start'] for w in backing))

    def test_failed_timing_opens_on_valid_draft_timings(self):
        import tempfile
        from kinetic_lyrics import lyrics_lines, validate
        from timeline_data import word_timings
        folder = Path(tempfile.mkdtemp())
        (folder/'lyrics.txt').write_text('[Verse 1]\nPut your head on my shoulder\nHold me in your arms, baby\n'
                                         '\n[Outro]\n(Tell me that you love me, too)\n', encoding='utf-8')
        draft = word_timings(folder, 120.)
        validate(draft, lyrics_lines(folder/'lyrics.txt'), 120.)  # the pipeline would accept it as saved timings
        self.assertEqual(collapsed_lines(draft), [])
        with self.assertRaisesRegex(ValueError, 'not ready'):
            word_timings(folder)

    def test_unrelated_transcription_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'did not match enough'):
            transcript_timing(['People writing songs that voices never share'],
                              [dict(word='instrumental', start=1., end=2.)])


if __name__ == '__main__':
    unittest.main()
