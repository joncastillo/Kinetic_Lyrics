"""Sung phrases are measured from any song format: soundfile reads WAV, FFmpeg decodes the rest (m4a, mp3)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from core.timing_repair import read_mono, voiced_phrases  # noqa: E402


class ReadMonoTest(unittest.TestCase):
    def test_an_m4a_song_is_decoded_and_its_phrases_found(self):
        with tempfile.TemporaryDirectory() as folder:
            song = Path(folder)/'song.m4a'
            # two seconds of tone, two of silence, two of tone
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
                            '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono', '-filter_complex',
                            '[1]atrim=duration=2[q];[0][q][0]concat=n=3:v=0:a=1', '-c:a', 'aac', str(song)], check=True)
            samples, rate = read_mono(song)
            self.assertAlmostEqual(len(samples)/rate, 6, delta=.3)
            self.assertEqual(len(voiced_phrases(song, gap=.5)), 2)


if __name__ == '__main__':
    unittest.main()
