"""Final cut: sections whose clips changed are rebuilt into the finished video without a Rebuild click."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio.job_process import ProcessWork


def job(folder, status='complete', queued=()):
    return SimpleNamespace(folder=Path(folder), state=dict(status=status, queued_actions=list(queued)))


class FinalCutTest(unittest.TestCase):
    def test_changed_sections_are_queued_once_after_what_is_already_queued(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'video.mp4').write_bytes(b'mp4')
            work = job(folder, queued=[dict(action='clip-effects', index=2), dict(action='patch', index=3)])
            ProcessWork.queue_final_cut(work, [3, 1, 2, 1])
            self.assertEqual(work.state['queued_actions'], [dict(action='clip-effects', index=2), dict(action='patch', index=3),
                                                            dict(action='patch', index=1), dict(action='patch', index=2)])

    def test_a_queued_re_render_after_a_timing_edit_takes_the_clips_in_instead(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'video.mp4').write_bytes(b'mp4')
            work = job(folder, queued=[dict(action='rerender', index=0, reason='timings')])
            ProcessWork.queue_final_cut(work, [1, 2])
            self.assertEqual(work.state['queued_actions'], [dict(action='rerender', index=0, reason='timings')])

    def test_nothing_is_queued_before_the_first_video_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            work = job(folder)
            ProcessWork.queue_final_cut(work, [0])
            self.assertEqual(work.state['queued_actions'], [])
            (Path(folder)/'video.mp4').write_bytes(b'mp4')
            running = job(folder, status='running')
            ProcessWork.queue_final_cut(running, [0])
            self.assertEqual(running.state['queued_actions'], [])



if __name__ == '__main__':
    unittest.main()
