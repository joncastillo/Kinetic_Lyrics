"""Effect samples drawn ahead of time, and a cache key that survives commits outside the drawing code."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from effects.particles import preview


class PrerenderTest(unittest.TestCase):
    def test_every_sample_is_drawn_once_for_the_settings(self):
        catalog = dict(entrance={'a': 'A', 'b': 'B'}, exit={'c': 'C'})
        with mock.patch('effects.particles.catalog.discover_effects', return_value=catalog), \
                mock.patch('render.text_effects.TEXT_ANIMATIONS', ['ai', 'mixed', 'fade', 'slide']), \
                mock.patch('direction.scene_catalog.scene_catalog', return_value={'s1': {}, 's2': {}}), \
                mock.patch.object(preview, 'render_preview') as effect, \
                mock.patch.object(preview, 'render_text_preview') as text, \
                mock.patch.object(preview, 'render_scene_preview') as scene:
            drawn = preview.prerender('serif', 'bold', 1.5, .8, 1.2)
        self.assertEqual(drawn, 7)
        self.assertEqual([c.args for c in text.call_args_list], [('fade', 'serif', 'bold', 1.5, 1.2), ('slide', 'serif', 'bold', 1.5, 1.2)],
                         'the AI and mixed choices have no sample of their own')
        self.assertEqual([c.args[0] for c in scene.call_args_list], ['s1', 's2'])
        self.assertEqual([c.args[:2] for c in effect.call_args_list], [('A', 'entrance'), ('B', 'entrance'), ('C', 'exit')])
        self.assertEqual(effect.call_args_list[0].args[2:], (.8, 1.2, 'serif', 'bold', 1.5))

    def test_drawing_waits_while_a_job_runs_and_one_failure_does_not_stop_the_rest(self):
        state = dict(busy=True, waits=0)

        def wait():
            state['waits'] += 1
            state['busy'] = False
        with mock.patch('effects.particles.catalog.discover_effects', return_value=dict(entrance={}, exit={'c': 'C'})), \
                mock.patch('render.text_effects.TEXT_ANIMATIONS', ['fade']), \
                mock.patch('direction.scene_catalog.scene_catalog', return_value={}), \
                mock.patch.object(preview, 'render_preview') as effect, \
                mock.patch.object(preview, 'render_text_preview', side_effect=RuntimeError('no font')):
            drawn = preview.prerender(busy=lambda: state['busy'], wait=wait)
        self.assertEqual((state['waits'], drawn), (1, 1))
        self.assertEqual(effect.call_count, 1)

    def test_settings_are_queued_once(self):
        with mock.patch.object(preview, '_WARM_QUEUE', None), mock.patch.object(preview, '_WARMED', set()):
            self.assertFalse(preview.request_prerender(), 'nothing queued before the warm-up thread exists')
            import queue
            with mock.patch.object(preview, '_WARM_QUEUE', queue.Queue()) as waiting:
                self.assertTrue(preview.request_prerender('serif', 'auto', 1.25, 1, 1))
                self.assertFalse(preview.request_prerender('serif', 'auto', 1.25, 1.0, 1.0), 'the same settings again')
                self.assertEqual(waiting.get_nowait(), ('serif', 'auto', 1.25, 1., 1.))


if __name__ == '__main__':
    unittest.main()
