"""The LangGraph pipeline: routing, the artwork review pause and resuming after a failure."""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import pipeline.graph as pipeline_graph

TIMINGS = [dict(text='hello from the hills', words=[dict(text=w, start=.5+i*.4, end=.8+i*.4) for i, w in enumerate('hello from the hills'.split())]),
           dict(text='down to the sea', words=[dict(text=w, start=3+i*.4, end=3.3+i*.4) for i, w in enumerate('down to the sea'.split())])]


@unittest.skipUnless(shutil.which('ffprobe'), 'needs FFmpeg')
class PipelineGraphTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.audio = self.folder/'song.wav'
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=duration=5', str(self.audio)], check=True)
        (self.folder/'lyrics.txt').write_text('hello from the hills\ndown to the sea\n', encoding='utf-8')
        (self.folder/'timings.json').write_text(json.dumps(TIMINGS), encoding='utf-8')
        self.output = self.folder/'out'/'video.mp4'
        self.visited = []
        # Skip the audio analysis and the GPU/encoding steps; record the order steps run in.
        self.patches = [mock.patch.object(pipeline_graph, name, self.recorder(name, replacement))
                        for name, replacement in (('analyse', self.analyse), ('illustrate', None), ('direct', self.direct),
                                                  ('render', self.render), ('finish', None), ('subtitles', None))]
        self.patches.append(mock.patch.object(pipeline_graph, 'align', self.recorder('align', pipeline_graph.align)))
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()

    def recorder(self, name, function):
        def node(state, runtime):
            self.visited.append(name)
            return function(state, runtime) if function else {}
        node.__name__ = name
        return node

    def analyse(self, state, runtime):
        return dict(theme=dict(name='minimal'), melody=None, rhythm=None)

    def direct(self, state, runtime):
        return dict(plan=dict(scenes=[]))

    def render(self, state, runtime):
        return dict(replacements_pending=False)

    def args(self, **overrides):
        values = dict(lyrics=self.folder/'lyrics.txt', timings=self.folder/'timings.json', alignment_audio=None,
                      style_reference=[], renderer='editorial', no_illustrations=True, illustrations=None,
                      review_artwork=False, image_seed=42, illustration_lines=2)
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_routes_by_renderer(self):
        pipeline_graph.run(self.args(), self.audio, self.output)
        self.assertEqual(self.visited, ['align', 'analyse', 'illustrate', 'direct', 'render', 'finish'])
        self.visited.clear()
        pipeline_graph.run(self.args(renderer='ass'), self.audio, self.output)
        self.assertEqual(self.visited, ['align', 'analyse', 'subtitles'])

    def test_review_pauses_until_approval(self):
        def illustrate(state, runtime):
            return dict(illustrations=['art.png'], review_artwork=True)
        approval = self.output.parent/pipeline_graph.APPROVAL
        before_approval = []
        def approve():
            while 'illustrate' not in self.visited:
                time.sleep(.02)
            time.sleep(.3)
            before_approval.extend(self.visited)
            approval.touch()
        with mock.patch.object(pipeline_graph, 'illustrate', self.recorder('illustrate', illustrate)):
            approver = threading.Thread(target=approve)
            approver.start()
            pipeline_graph.run(self.args(), self.audio, self.output, poll=.02)
            approver.join()
        self.assertEqual(before_approval, ['align', 'analyse', 'illustrate'], 'nothing runs while waiting for approval')
        self.assertEqual(self.visited, ['align', 'analyse', 'illustrate', 'direct', 'render', 'finish'])

    def test_resume_continues_from_the_failed_step(self):
        def broken(state, runtime):
            raise ValueError('typography model unavailable')
        with mock.patch.object(pipeline_graph, 'direct', self.recorder('direct', broken)):
            with self.assertRaises(ValueError):
                pipeline_graph.run(self.args(), self.audio, self.output)
        self.visited.clear()
        values = pipeline_graph.run(self.args(), self.audio, self.output, resume=True)
        self.assertEqual(self.visited, ['direct', 'render', 'finish'])
        self.assertEqual(values['data'][0]['text'], 'hello from the hills')
        self.visited.clear()
        pipeline_graph.run(self.args(), self.audio, self.output, resume=True)
        self.assertEqual(self.visited[0], 'align', 'a finished run starts again from the beginning')

    def test_replaced_audio_is_not_resumed(self):
        def broken(state, runtime):
            raise ValueError('typography model unavailable')
        with mock.patch.object(pipeline_graph, 'direct', self.recorder('direct', broken)):
            with self.assertRaises(ValueError):
                pipeline_graph.run(self.args(), self.audio, self.output)
        # A different track saved under the same name.
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=660:duration=5', str(self.audio)], check=True)
        self.visited.clear()
        pipeline_graph.run(self.args(), self.audio, self.output, resume=True)
        self.assertEqual(self.visited[0], 'align')

    def test_video_step_runs_after_illustrations_when_a_model_is_chosen(self):
        def illustrate(state, runtime):
            return dict(illustrations=['art.png'], review_artwork=False)
        clips = {'abc': 'frames'}
        with mock.patch.object(pipeline_graph, 'illustrate', self.recorder('illustrate', illustrate)), \
             mock.patch('video_generation.step.animate', return_value=clips) as animate:
            values = pipeline_graph.run(self.args(video_model='Lightricks/LTX-2.5-Diffusers'), self.audio, self.output)
        animate.assert_called_once()
        self.assertEqual(values['video_clips'], clips)
        self.assertEqual(self.visited, ['align', 'analyse', 'illustrate', 'direct', 'render', 'finish'])

    def test_render_repeats_while_replacements_are_queued(self):
        outcomes = iter([True, False])
        def render(state, runtime):
            return dict(replacements_pending=next(outcomes))
        with mock.patch.object(pipeline_graph, 'render', self.recorder('render', render)):
            pipeline_graph.run(self.args(), self.audio, self.output)
        self.assertEqual(self.visited[-3:], ['render', 'render', 'finish'])


if __name__ == '__main__':
    unittest.main()
