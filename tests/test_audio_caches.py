"""Analysis caches are reused for the same audio and redone when the track is replaced."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from audio import melody, rhythm


class AudioCacheTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.audio = self.folder/'audio.mp3'
        self.audio.write_bytes(b'first track')

    def test_rhythm_is_redone_for_a_new_track(self):
        separations = []
        def separate(audio, folder):
            separations.append(Path(audio).read_bytes())
            return self.folder
        with mock.patch.object(rhythm, 'separate', separate), mock.patch.object(rhythm, 'onsets', lambda path, kick_only=False: [[1., .5]]):
            rhythm.ensure_rhythm(self.audio, self.folder)
            rhythm.ensure_rhythm(self.audio, self.folder)
            self.assertEqual(len(separations), 1, 'the same track reuses its onsets')
            self.audio.write_bytes(b'second track')
            rhythm.ensure_rhythm(self.audio, self.folder)
        self.assertEqual(separations, [b'first track', b'second track'])

    def test_stems_older_than_the_track_are_separated_again(self):
        from models.separation import demucs
        stems = self.folder/'stems'
        stems.mkdir()
        for name in demucs.STEMS:
            (stems/f'{name}.wav').write_bytes(b'stem')
        old = time.time()-60
        for name in demucs.STEMS:
            os.utime(stems/f'{name}.wav', (old, old))
        with mock.patch.object(demucs.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=1, stderr='demucs not installed')
            self.assertIsNone(demucs.separate(self.audio, self.folder))
        run.assert_called_once()

    def test_melody_cache_follows_the_vocal_stem(self):
        data = [dict(text='la la', words=[dict(text='la', start=1., end=1.5), dict(text='la', start=1.6, end=2.)])]
        vocals = self.folder/'vocals.wav'
        vocals.write_bytes(b'first vocals')
        calls = []
        def analyze(path, data):
            calls.append(Path(path).read_bytes())
            return dict(version=melody.VERSION, lines=[[{}, {}]])
        with mock.patch.object(melody, 'analyze', analyze):
            melody.ensure_melody(data, self.folder)
            melody.ensure_melody(data, self.folder)
            self.assertEqual(len(calls), 1, 'unchanged timings and vocals reuse the saved melody')
            vocals.write_bytes(b'second vocals')
            melody.ensure_melody(data, self.folder)
        self.assertEqual(calls, [b'first vocals', b'second vocals'])


if __name__ == '__main__':
    unittest.main()
