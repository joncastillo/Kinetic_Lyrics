"""A storyline beat longer than a video part is split by the director, so a clip's parts do not repeat one action."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.story import ensure_split, load, long_beats, normalise, save, split_long_beats

SEGMENT = normalise(dict(index=0, moment='She feeds.', characters='a woman', environment='the hive', camera='close-up',
                         beats=[dict(start=0, end=4.5, action='She bites.'), dict(start=4.5, end=20, action='She pauses.')]), 20)
WINDOWS = [(0, 5.04), (5.04, 9.38), (9.38, 13.71), (13.71, 18.04), (18.04, 20)]


def reply(beats):
    return lambda payload: dict(message=dict(content=json.dumps(dict(segments=[dict(index=0, beats=beats)]))))


SPLIT = [dict(start=0, end=4.5, action='She bites.'), dict(start=4.5, end=9, action='She pulls back.'),
         dict(start=9, end=14, action='She drags him deeper.'), dict(start=14, end=20, action='She wraps him in silk.')]


class LongBeats(unittest.TestCase):


    def test_a_reply_no_better_is_ignored(self):
        segments = [dict(SEGMENT)]
        self.assertEqual(split_long_beats('m', segments, reply([dict(start=0, end=20, action='x')])), 0)
        self.assertEqual(segments[0]['beats'], SEGMENT['beats'])

    def test_a_saved_story_is_split_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp)/'illustrations.json'
            save(manifest, dict(segments=[dict(SEGMENT)]))
            calls = []
            import direction.story as story_module
            original = story_module.split_long_beats
            story_module.split_long_beats = lambda model, segments, **kw: calls.append(1) or original(model, segments, reply(SPLIT))
            try:
                ensure_split(manifest, load(manifest), 'm')
                ensure_split(manifest, load(manifest), 'm')
            finally:
                story_module.split_long_beats = original
            self.assertEqual(len(calls), 1)
            self.assertFalse(long_beats(load(manifest)['segments'][0]))



if __name__ == '__main__':
    unittest.main()
