import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

from studio.job_queue import ActionQueue


class Job(ActionQueue):
    def __init__(self, folder, state):
        self.folder, self.state = Path(folder), state

    def clip_folder_for(self, index):
        path = self.folder/'clips'/str(index)
        path.mkdir(parents=True, exist_ok=True)
        return path


class ReplaceLeavesAnimationTest(unittest.TestCase):
    def test_a_replaced_picture_leaves_the_animation_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            job = Job(folder, dict(action=None, queued_actions=[
                dict(action='animate', index=2, indices=[2, 5]), dict(action='clip-effects', index=5),
                dict(action='animate', index=7)]))
            job.leave_animation(5)
            self.assertEqual(job.state['queued_actions'], [dict(action='animate', index=2, indices=[2]),
                                                           dict(action='animate', index=7)])

    def test_the_running_batch_stops_its_clip(self):
        with tempfile.TemporaryDirectory() as folder:
            job = Job(folder, dict(action='animate', animating=[3, 4], queued_actions=[]))
            job.leave_animation(4)
            self.assertTrue((Path(folder)/'clips'/'4'/'skip').is_file())
            self.assertEqual(job.state['animating'], [3])
            job.leave_animation(9)
            self.assertFalse((Path(folder)/'clips'/'9').exists(), 'a picture not being animated is left alone')


if __name__ == '__main__':
    unittest.main()
