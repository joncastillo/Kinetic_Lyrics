"""Cancel asks a worker to stop and only forces what has not left in time: a kill in the middle of GPU work reset the
display driver and turned Chrome white."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from core.stopping import STOP_ENV, STOPPED_CODE, Stopped, check_stop, stop_at_steps, stop_requested
from studio import server

SRC = str(Path(__file__).resolve().parent.parent/'src')
POLITE = ('import time\nfrom core.stopping import check_stop\nprint("up", flush=True)\n'
          'while True:\n    check_stop()\n    time.sleep(.02)\n')
STUBBORN = 'import time\nprint("up", flush=True)\ntime.sleep(60)\n'


def worker(code, stop_file):
    process = subprocess.Popen([sys.executable, '-c', code], env=dict(os.environ, PYTHONPATH=SRC, **{STOP_ENV: str(stop_file)}),
                               stdout=subprocess.PIPE, text=True)
    process.stop_file = stop_file
    process.stdout.readline()
    return process


class RequestTest(unittest.TestCase):
    def setUp(self):
        self.file = Path(tempfile.mkdtemp())/'.stop'

    def env(self):
        return mock.patch.dict(os.environ, {STOP_ENV: str(self.file)})

    def test_without_a_request_nothing_happens(self):
        with self.env():
            self.assertFalse(stop_requested())
            check_stop()
        with mock.patch.dict(os.environ):
            os.environ.pop(STOP_ENV, None)
            self.assertFalse(stop_requested())

    def test_a_request_leaves_past_any_except_exception(self):
        self.file.write_text('stop')
        with self.env(), self.assertRaises(Stopped) as caught:
            try:
                check_stop()
            except Exception:  # noqa: BLE001 (what the workers' "carry on" handlers do)
                self.fail('the stop was taken for a failure')
        self.assertEqual(caught.exception.code, STOPPED_CODE)

    def test_every_step_of_a_pipeline_checks(self):
        hooks = []
        pipe = SimpleNamespace(transformer=SimpleNamespace(register_forward_pre_hook=hooks.append))
        stop_at_steps(pipe)
        self.assertEqual(len(hooks), 1)
        self.file.write_text('stop')
        with self.env(), self.assertRaises(Stopped):
            hooks[0](pipe.transformer, ())
        stop_at_steps(SimpleNamespace())  # a pipeline with no transformer is left alone


class FinishStopTest(unittest.TestCase):
    def setUp(self):
        self.file = Path(tempfile.mkdtemp())/'.stop'

    def test_a_worker_that_leaves_is_never_forced(self):
        process = worker(POLITE, self.file)
        server.request_stop(process)
        began = time.monotonic()
        with mock.patch.object(server, 'force_stop') as force:
            server.finish_stop([process], grace=20)
        self.assertLess(time.monotonic()-began, 15)
        force.assert_not_called()
        self.assertEqual(process.returncode, STOPPED_CODE)

    def test_a_worker_that_does_not_leave_is_forced_after_the_grace(self):
        process = worker(STUBBORN, self.file)
        server.request_stop(process)
        began = time.monotonic()
        server.finish_stop([process], grace=.5)
        self.assertGreaterEqual(time.monotonic()-began, .4)
        self.assertIsNotNone(process.poll())

    def test_cancel_returns_at_once_and_the_worker_stops_behind_it(self):
        process = worker(POLITE, self.file)
        job = SimpleNamespace(state=dict(status='running', action=None), cancelled=False, generation=0, folder=self.file.parent,
                              action_process=None, process=process, save=lambda: None)
        with mock.patch.object(server, 'force_stop') as force, mock.patch('artwork.queue.queue_path', return_value=self.file.parent/'q'):
            server.stop_job(job, keep_queue=True, background=True)
            self.assertEqual(job.state['status'], 'cancelled')
            self.assertEqual(process.wait(timeout=20), STOPPED_CODE)
        force.assert_not_called()


if __name__ == '__main__':
    unittest.main()
