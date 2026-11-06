"""Queued work runs model by model, and the header shows it in the order it will run."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio.job_queue import next_in_queue, queue_plan


def queued(*kinds):
    return [dict(action=kind, index=n) for n, kind in enumerate(kinds)]


class QueueOrderTest(unittest.TestCase):
    def test_images_go_before_animations_whatever_ran_last(self):
        waiting = queued('regenerate', 'patch', 'animate')
        self.assertEqual(next_in_queue(waiting, 'video'), 0, 'a queued image is made before any animation')
        self.assertEqual(next_in_queue(waiting, 'image'), 0)
        self.assertEqual(next_in_queue(waiting, None), 0, 'nothing ran yet: first in, first out')
        self.assertEqual(next_in_queue(queued('patch', 'animate'), 'video'), 1, 'no image work: the video model again')
        self.assertEqual(next_in_queue(queued('patch', 'rerender'), 'video'), 0, 'no work for that model: in order')

    def test_a_reference_goes_before_every_image(self):
        waiting = queued('animate', 'verify', 'regenerate', 'reference', 'regenerate')
        self.assertEqual(next_in_queue(waiting, 'video'), 3, 'the reference first: the images that show it wait for it')
        self.assertEqual(queue_plan(waiting), ['reference', 'verify', 'regenerate', 'animate'])

    def test_the_plan_runs_queued_images_before_the_next_animation(self):
        waiting = queued('regenerate', 'animate', 'regenerate', 'patch', 'patch', 'rerender')
        self.assertEqual(queue_plan(waiting, 'animate'), ['animate', 'regenerate', 'animate', 'patch', 'rerender'],
                         'running animation, then the images (batched), then the queued animation, then the rebuilds '
                         'one by one, then the re-render')

    def test_an_idle_job_starts_with_the_first_queued(self):
        self.assertEqual(queue_plan(queued('verify', 'animate', 'regenerate')), ['verify', 'regenerate', 'animate'],
                         'verify then the other image work on the same model, then the video')


if __name__ == '__main__':
    unittest.main()
