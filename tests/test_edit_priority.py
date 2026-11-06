"""In-image edits yield at saved-image boundaries and cannot leave a stale GPU reservation."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from models.gpu import edit_priority
from models.gpu.lifecycle import ModelSession


class EditPriorityTest(unittest.TestCase):
    def test_checker_yields_gpu_and_models_until_edit_queue_clears(self):
        session=ModelSession();session.lock=mock.Mock();session.release=mock.Mock();session.unload_vision=mock.Mock()
        with mock.patch.object(edit_priority,'pending',return_value=True),mock.patch.object(edit_priority,'acquire') as acquire:
            session.yield_for_edits()
        session.release.assert_called_once();session.unload_vision.assert_called_once();session.lock.release.assert_called_once();acquire.assert_called_once_with(session.lock)
    def test_windows_reader_cannot_kill_priority_publisher(self):
        with mock.patch.object(edit_priority, 'write_json_atomic', side_effect=[PermissionError('busy'), None]) as write, \
                mock.patch.object(edit_priority.time, 'sleep'):
            self.assertTrue(edit_priority.publish(True))
            self.assertEqual(write.call_count, 2)
        with mock.patch.object(edit_priority, 'write_json_atomic', side_effect=PermissionError('busy')), \
                mock.patch.object(edit_priority.time, 'sleep'):
            self.assertFalse(edit_priority.publish(True))
    def test_lease_expires_after_studio_stops(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(edit_priority, 'MARKER', Path(directory)/'lease.json'):
            with mock.patch.object(edit_priority.time, 'time', return_value=100):
                edit_priority.publish(True)
                self.assertTrue(edit_priority.pending())
                with self.assertRaises(edit_priority.YieldToEdits):
                    edit_priority.checkpoint()
            with mock.patch.object(edit_priority.time, 'time', return_value=106):
                self.assertFalse(edit_priority.pending())

    def test_new_priority_after_acquiring_lock_releases_it_again(self):
        lock = mock.Mock()
        with mock.patch.object(edit_priority, 'pending', side_effect=[False, True, False, False]):
            edit_priority.acquire(lock)
        self.assertEqual(lock.acquire.call_count, 2)
        lock.release.assert_called_once()

    def test_reference_batch_releases_weights_then_gpu_and_resumes(self):
        session = ModelSession()
        session.lock = mock.Mock()
        events = []
        session.release = lambda: events.append('release weights')
        session.unload_vision = lambda: events.append('unload vision')
        session.lock.release.side_effect = lambda: events.append('release GPU')
        generate = mock.Mock(side_effect=[edit_priority.YieldToEdits(), 'finished'])
        with mock.patch.object(edit_priority, 'checkpoint'), \
                mock.patch.object(edit_priority, 'acquire', side_effect=lambda lock: events.append('reacquire GPU')):
            self.assertEqual(session.run_generation(generate, 'manifest', 'cache'), 'finished')
        self.assertEqual(events, ['release weights', 'unload vision', 'release GPU', 'reacquire GPU'])
        self.assertEqual(generate.call_count, 2)
