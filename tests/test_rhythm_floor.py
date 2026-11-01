import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from rhythm import VERSION, floor_drum_events, rhythm_for


class RhythmFloorTest(unittest.TestCase):
    def test_only_one_regular_pulse_track_is_kept(self):
        kicks = [[1 + i*.5, .9] for i in range(8)]
        extra_drums = [[1.25 + i*.5, .6] for i in range(8)]
        events = sorted(kicks + extra_drums)
        self.assertEqual([t for t, _ in floor_drum_events(events)], [t for t, _ in kicks])

    def test_quiet_but_regular_kicks_still_pulse(self):
        kicks = [[1 + i*.5, .2] for i in range(8)]
        self.assertEqual([t for t, _ in floor_drum_events(kicks)], [t for t, _ in kicks])
        self.assertTrue(all(weight >= .6 for _, weight in floor_drum_events(kicks)))

    def test_irregular_drums_do_not_pulse(self):
        self.assertEqual(floor_drum_events([[1., .9], [1.48, .9], [2.2, .9], [2.9, .9]]), [])

    def test_old_cached_onsets_are_rebuilt_for_rerender(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder/'video.rhythm.json').write_text(json.dumps(dict(version=VERSION-1, drums=[[1., 1.]])))
            (folder/'config.json').write_text(json.dumps(dict(audio='song.wav')))
            fresh = dict(version=VERSION, drums=[])
            with patch('rhythm.ensure_rhythm', return_value=fresh) as rebuild:
                self.assertEqual(rhythm_for(folder), fresh)
            rebuild.assert_called_once_with('song.wav', folder)


if __name__ == '__main__':
    unittest.main()
