"""Motion beats for the video step: one per part, developing across a section, never fatal when missing."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.motion import CONTINUE, FALLBACK, GUARDRAILS, motion_beats, part_prompt
from video_generation import generation, step
from video_generation.catalog import video_spec

CLIPS = [dict(index=0, scene='A man on a rocky shore.', lyrics='Wise men say', seconds=25., parts=3),
         dict(index=4, scene='Two hands on a rock.', lyrics='Take my hand', seconds=6., parts=1)]


def reply(clips):
    return dict(message=dict(content=json.dumps(dict(clips=clips))))


class MotionBeatsTest(unittest.TestCase):
    def test_one_beat_per_part_padded_or_trimmed(self):
        answer = reply([dict(index=0, beats=['He turns.', 'He steps forward.']),        # one short
                        dict(index=4, beats=['They grip tighter.', 'Extra beat.'])])     # one too many
        beats = motion_beats('model', CLIPS, request=lambda payload: answer)
        self.assertEqual(beats[0], ['He turns.', 'He steps forward.', 'He steps forward.'])
        self.assertEqual(beats[4], ['They grip tighter.'])

    def test_request_describes_every_clip_and_frees_the_gpu_afterwards(self):
        seen = {}
        def request(payload):
            seen.update(payload)
            return reply([])
        motion_beats('qwen', CLIPS, request=request)
        sent = json.loads(seen['messages'][1]['content'])
        self.assertEqual([c['parts'] for c in sent], [3, 1])
        self.assertEqual(seen['keep_alive'], 0, 'the video model needs the GPU next')

    def test_failure_or_no_model_falls_back_without_raising(self):
        def broken(payload):
            raise RuntimeError('ollama down')
        self.assertEqual(motion_beats('model', CLIPS, request=broken), {})
        self.assertEqual(motion_beats(None, CLIPS, request=broken), {})
        self.assertEqual(motion_beats('model', CLIPS, request=lambda p: dict(message=dict(content='not json'))), {})

    def test_later_parts_continue_the_shot_instead_of_restating_the_painting(self):
        beat = dict(time='5-10 s', camera='tilts up to the sky', in_frame='no one', action='Clouds drift over.')
        first = part_prompt('A woman and her dog on a track.', beat, first=True)
        later = part_prompt('A woman and her dog on a track.', beat, first=False)
        self.assertIn('A woman and her dog', first)
        self.assertNotIn('A woman and her dog', later, 'restating them puts them back in wherever the camera looks')
        self.assertIn(CONTINUE, later)
        self.assertIn('Camera: tilts up to the sky. In frame: no one.', later)
        self.assertIn('nobody new appears', later)

    def test_request_gives_each_clip_a_timeline(self):
        seen = {}
        def request(payload):
            seen.update(payload)
            return reply([])
        motion_beats('qwen', CLIPS, request=request)
        sent = json.loads(seen['messages'][1]['content'])
        self.assertEqual(sent[0]['timeline'], ['0-8 s', '8-17 s', '17-25 s'])
        self.assertIn('cast', json.dumps(seen['format']))

    def test_the_storyboard_reaches_every_part_and_reversals_are_ruled_out(self):
        answer = reply([dict(index=0, cast='one woman; one bulldog', shot='a slow push-in, then a tilt up to the sky',
                             beats=[dict(time='0-8 s', camera='pushes in', in_frame='both', action='They walk.')]*3)])
        seen = {}
        def request(payload):
            seen.update(payload)
            return answer
        beats = motion_beats('model', CLIPS[:1], request=request)
        self.assertTrue(all(b['shot'] == 'a slow push-in, then a tilt up to the sky' for b in beats[0]))
        self.assertIn('Shot plan: a slow push-in', part_prompt('scene', beats[0][1], first=False))
        rules = seen['messages'][0]['content']
        self.assertIn('never reverse a move', rules)
        self.assertIn('storyboard', rules)

    def test_part_prompt_has_scene_beat_and_guardrails(self):
        self.assertEqual(part_prompt('A shore.', 'Waves break.'), 'A shore. Waves break. '+GUARDRAILS)
        self.assertIn(FALLBACK, part_prompt('A shore.', None))


class PartsTest(unittest.TestCase):
    def test_parts_for_matches_how_the_worker_splits_a_clip(self):
        spec = dict(video_spec('Lightricks/LTX-2.5-Diffusers'), chunk_frames=33)
        for frames in (25, 33, 41, 65, 81, 200):
            used = []
            def fake(pipe, spec, image, prompt, seed, torch, num_frames=None):
                used.append(prompt)
                return np.zeros((num_frames, 2, 2, 3), np.uint8)
            with mock.patch('video_generation.models.animate', fake):
                _, parts = generation.animate_length(None, spec, Image.new('RGB', (2, 2)),
                                                     ['p%d' % n for n in range(9)], 1, frames, None)
            self.assertEqual(parts, step.parts_for(frames, spec), frames)
            self.assertEqual(used, ['p%d' % n for n in range(parts)], 'part n uses prompt n')

    def test_progress_is_reported_before_every_part_and_at_the_end(self):
        spec = dict(video_spec('Lightricks/LTX-2.5-Diffusers'), chunk_frames=33)
        calls = []
        fake = lambda pipe, spec, image, prompt, seed, torch, num_frames=None: np.zeros((num_frames, 2, 2, 3), np.uint8)
        with mock.patch('video_generation.models.animate', fake):
            _, parts = generation.animate_length(None, spec, Image.new('RGB', (2, 2)), 'p', 1, 81, None,
                                                 on_part=lambda part, done: calls.append((part, done)))
        self.assertEqual(parts, 3)
        self.assertEqual(calls, [(1, 0), (2, 33), (3, 65), (4, 89)], 'one call per part, then the finished clip')

    def test_clip_prompts_give_each_part_its_beat(self):
        item = dict(scene='A shore.', beats=['Waves rise.', 'Gulls lift off.'], parts=3)
        prompts = generation.clip_prompts(item)
        self.assertEqual(len(prompts), 3)
        self.assertIn('Waves rise.', prompts[0])
        self.assertIn('Gulls lift off.', prompts[1])
        self.assertIn('Gulls lift off.', prompts[2], 'the last beat carries on')
        self.assertIn(FALLBACK, generation.clip_prompts(dict(scene='A shore.', parts=1))[0])


if __name__ == '__main__':
    unittest.main()
