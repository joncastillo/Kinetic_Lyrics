"""The storyline: written before the images, timed per segment, and mapped onto the video's real parts."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.story import BATCH, fallback, normalise, validate_import, write_story

LTX = dict(frames=121, chunk_frames=121, fps=24)


class StoryTest(unittest.TestCase):

    def test_beats_are_ordered_and_cover_the_clip_without_gaps(self):
        segment = normalise(dict(characters='a woman', environment='a beach at dusk', camera='slow push-in',
                                 beats=[dict(start=8, end=9, action='She waves.'), dict(start=3, end=20, action='Waves roll.'),
                                        dict(start=1, end=2, action='')]), 12)
        self.assertEqual([(b['start'], b['end']) for b in segment['beats']], [(0., 8.), (8., 12.)])


    def test_the_director_writes_in_batches_and_gaps_get_a_plain_story(self):
        calls = []
        def request(payload):
            asked = json.loads(payload['messages'][1]['content'])['write']
            calls.append([s['index'] for s in asked])
            return dict(message=dict(content=json.dumps(dict(segments=[
                dict(index=s['index'], characters='no one', environment='hills', camera='push in',
                     beats=[dict(start=0, end=s['seconds'], camera='', action='Grass sways.')]) for s in asked if s['index'] != 2]))))
        segments = [dict(index=i, scene=f'scene {i}', lyrics='la la', seconds=10.) for i in range(BATCH+2)]
        story = write_story('director', segments, request)
        self.assertEqual(calls, [list(range(BATCH)), [BATCH, BATCH+1]])
        self.assertEqual(story[0]['environment'], 'hills')
        self.assertEqual(story[2], fallback(2, 10., 'scene 2'), 'a segment it skipped gets the plain story')

    def test_an_import_must_match_the_song(self):
        with self.assertRaises(ValueError):
            validate_import(dict(segments=[{}]*3), 4)
        validate_import(dict(segments=[{}]*4), 4)


    def test_long_multi_paragraph_story_is_not_truncated(self):
        import tempfile
        from direction.story import story_text
        paragraph1 = "First paragraph of the long narrative story detailing the setting, atmosphere, and initial discovery. " * 30
        paragraph2 = "Second paragraph continuing the narrative without being cut off mid-sentence or mid-paragraph. " * 30
        long_story = f"{paragraph1}\n\n{paragraph2}"
        self.assertGreater(len(long_story), 5000)

        seen = []
        def request(payload):
            seen.append(payload['messages'][0]['content'])
            return dict(message=dict(content=json.dumps(dict(segments=[]))))

        write_story('director', [dict(index=0, scene='s', lyrics='l', seconds=5.)], request, story=long_story)
        self.assertTrue(any(long_story in content for content in seen))

        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as f:
            f.write(long_story)
            f_path = Path(f.name)
        try:
            self.assertEqual(story_text(f_path), long_story)
            seen_from_file = []
            def request_file(payload):
                seen_from_file.append(payload['messages'][0]['content'])
                return dict(message=dict(content=json.dumps(dict(segments=[]))))
            write_story('director', [dict(index=0, scene='s', lyrics='l', seconds=5.)], request_file, story=str(f_path))
            self.assertTrue(any(long_story in content for content in seen_from_file))
        finally:
            f_path.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()


class StoryContinuityTest(unittest.TestCase):
    def test_later_batches_see_the_segments_already_written(self):
        from direction import story as stories
        sent = []

        def request(payload):
            asked = json.loads(payload['messages'][1]['content'])
            if 'write' not in asked:  # the one-go call: answer nothing, so the batches have to write it
                return dict(message=dict(content=json.dumps(dict(title='', plot='', segments=[]))))
            sent.append(asked)
            return dict(message=dict(content=json.dumps(dict(segments=[
                dict(index=s['index'], characters=f'Mara in a red coat (segment {s["index"]})', environment='a rainy pier',
                     camera='slow push-in', beats=[dict(start=0, end=5, camera='wide', action=f'Mara walks on ({s["index"]})')])
                for s in asked['write']]))))

        segments = [dict(index=i, scene=f'scene {i}', lyrics=f'line {i}', seconds=5.) for i in range(stories.BATCH+2)]
        stories.write_story('director', segments, request=request)
        self.assertEqual(sent[0]['story_so_far'], [])
        later = sent[1]['story_so_far']
        self.assertEqual([e['index'] for e in later], list(range(stories.BATCH)))
        self.assertIn('red coat', later[-1]['characters'])
        self.assertIn(f'Mara walks on ({stories.BATCH-1})', later[-1]['ends_with'])

    def test_the_whole_story_is_written_in_one_call(self):
        from direction import story as stories
        calls = []

        def request(payload):
            asked = json.loads(payload['messages'][1]['content'])
            calls.append(asked)
            return dict(message=dict(content=json.dumps(dict(title='The Pier', plot='A clue, a chase, a solved case.', segments=[
                dict(index=s['index'], moment=f'moment {s["index"]}', characters='Mara and her bulldog', environment='a pier',
                     camera='static low angle', beats=[dict(start=0, end=s['seconds'], camera='still', action='Mara looks up.')])
                for s in asked['segments']]))))

        segments = [dict(index=i, lyrics=f'line {i}', seconds=6.) for i in range(stories.BATCH*3)]
        written = stories.write_story('director', segments, request=request, story='A detective solves a crime.')
        self.assertEqual(len(calls), 1)
        self.assertEqual([w['moment'] for w in written], [f'moment {i}' for i in range(stories.BATCH*3)])

    def test_segments_last_from_their_first_line_to_the_next(self):
        from direction.story import segments_for_groups
        data = [dict(text=f'l{i}', words=[dict(start=10.+i*4, end=12.+i*4)]) for i in range(4)]
        got = segments_for_groups(['a', 'b'], [[0, 1], [2, 3]], data)
        self.assertEqual([round(g['seconds'], 1) for g in got], [18., 10.])   # 0 -> 18 s, then 18 s -> 24+4 s
