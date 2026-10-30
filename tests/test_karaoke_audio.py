"""Karaoke exports the instrument stems on the original song timeline."""
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class KaraokeAudioTest(unittest.TestCase):
    def test_instrumental_mix_is_cached_and_time_aligned(self):
        from rhythm import audio_for_mode

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stems = root/'stems'
            stems.mkdir()
            for name, frequency in [('drums', 180), ('bass', 110), ('other', 330)]:
                with wave.open(str(stems/f'{name}.wav'), 'wb') as file:
                    file.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                    file.writeframes(b''.join(struct.pack('<h', round(2000*math.sin(2*math.pi*frequency*i/8000)))
                                              for i in range(8000)))
            original = root/'original.wav'
            original.write_bytes(b'original is used for alignment')
            self.assertEqual(audio_for_mode(original, root), original)
            instrumental = audio_for_mode(original, root, 'karaoke')
            self.assertTrue(instrumental.is_file())
            with wave.open(str(instrumental), 'rb') as file:
                self.assertEqual(file.getnframes()/file.getframerate(), 1.)
                self.assertNotEqual(file.readframes(8), bytes(8*file.getnchannels()*file.getsampwidth()))
            modified = instrumental.stat().st_mtime_ns
            self.assertEqual(audio_for_mode(original, root, 'karaoke'), instrumental)
            self.assertEqual(instrumental.stat().st_mtime_ns, modified)


if __name__ == '__main__':
    unittest.main()
