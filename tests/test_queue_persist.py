"""Cancel stops only the running work; the queue stays, and single items come out with their x."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio import server
from studio.job_routes import JobRoutes


class FakeJob:
    def __init__(self, folder, **state):
        self.folder, self.cancelled, self.generation = Path(folder), False, 0
        self.action_process = self.process = None
        self.state = dict(dict(status='complete', action=None, queued_actions=[], animating=[]), **state)
        self.requeued = []
        self.saved = 0

    def queue_missing_clips(self):
        self.requeued.append(list(self.state['animating']))
        self.state['queued_actions'].append(dict(action='animate', index=3, indices=[3, 4], segments={}))

    def clip_folder_for(self, index):
        folder = self.folder/f'clip-{index}'
        folder.mkdir(exist_ok=True)
        return folder

    def save(self):
        self.saved += 1


def routes():
    handler = SimpleNamespace(respond=lambda value, code=200: value)
    return handler


class QueuePersistTest(unittest.TestCase):
    def test_cancel_keeps_the_queue_and_puts_the_batch_back(self):
        folder = tempfile.mkdtemp()
        job = FakeJob(folder, action='animate', animating=[2, 3, 4], queued_actions=[dict(action='regenerate', index=8)])
        server.stop_job(job, keep_queue=True)
        self.assertEqual(job.state['status'], 'cancelled')
        self.assertTrue(job.cancelled, 'the kept queue waits for Run queue')
        self.assertEqual(job.requeued, [[]], 'the batch is put back after it stopped counting as running')
        self.assertEqual([q['action'] for q in job.state['queued_actions']], ['regenerate', 'animate'])

    def test_a_new_run_still_clears_the_queue(self):
        job = FakeJob(tempfile.mkdtemp(), action='animate', queued_actions=[dict(action='regenerate', index=8)])
        server.stop_job(job)
        self.assertEqual(job.state['queued_actions'], [])

    def test_the_x_takes_out_one_item(self):
        job = FakeJob(tempfile.mkdtemp(), status='complete', animating=[5, 6], queued_actions=[
            dict(action='regenerate', index=8), dict(action='animate', index=3, indices=[3, 4]),
            dict(action='patch', index=4), dict(action='rerender', index=0)])
        with mock.patch('artwork.queue.update_queue'):
            JobRoutes._job_queue_remove(routes(), job, 'queue-remove', dict(group='animation', index=3), {})
            JobRoutes._job_queue_remove(routes(), job, 'queue-remove', dict(group='images', index=8), {})
            JobRoutes._job_queue_remove(routes(), job, 'queue-remove', dict(group='song', action='rerender'), {})
            JobRoutes._job_queue_remove(routes(), job, 'queue-remove', dict(group='animation', index=6), {})
        self.assertEqual(job.state['queued_actions'], [dict(action='animate', index=4, indices=[4]), dict(action='patch', index=4)])
        self.assertTrue((job.folder/'clip-6'/'skip').is_file(), 'the running batch skips it')
        self.assertEqual(job.state['animating'], [5])


if __name__ == '__main__':
    unittest.main()
