"""The 3D stage's wisp and camera move smoothly: no lurch when a glide between blocks starts or stops, no
bounce where a loop is spliced into the route, and no dead stop when a run ends."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cinema import compositor, lyrics


def second_differences(track):
    return [float(np.linalg.norm(c-2*b+a)) for a, b, c in zip(track, track[1:], track[2:])
            if a is not None and b is not None and c is not None]


class WispSmoothTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lines = [(1.+k*4.2, 'the quiet river carries every word') for k in range(8)]
        c = compositor(lyrics(*lines), duration=40., flow='stage')
        cls.stage = c.realtime
        cls.blocks = cls.stage.plan()
        cls.eyes, cls.heads = [], []
        for frame in range(40*30):
            t = frame/30
            eye = cls.stage.camera(t)[0]
            cls.eyes.append(eye)
            heads = [np.asarray(p) for p, opacity, _ in cls.stage.ribbon_heads(t, eye) if opacity > .05]
            cls.heads.append(heads[0] if heads else None)

    def test_camera_glides_ease_in_and_out(self):
        speeds = [float(np.linalg.norm(b-a)) for a, b in zip(self.eyes, self.eyes[1:])]
        self.assertLess(max(second_differences(self.eyes)), max(speeds)*.15)

    def test_wisp_head_never_jumps_or_bounces(self):
        speeds = [float(np.linalg.norm(b-a)) for a, b in zip(self.heads, self.heads[1:]) if a is not None and b is not None]
        self.assertLess(max(second_differences(self.heads)), float(np.median(speeds)))

    def test_runs_brake_to_a_stop(self):
        from realtime_typography import thread_distance
        for run in self.stage.ribbon:
            times, distances, _ = run['keys']
            cruise = (distances[-1]-distances[0])/(times[-1]-times[0])/30  # per frame
            final = thread_distance(run['keys'], times[-1])-thread_distance(run['keys'], times[-1]-1/30)
            self.assertLess(final, cruise*.05)  # all but stopped by the run's last frame


if __name__ == '__main__':
    unittest.main()
