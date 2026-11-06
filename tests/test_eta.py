"""Time left: every step still to do, in its own units, at this computer's measured speeds."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio import eta

EDIT = 'Qwen/Qwen-Image-Edit-2511'


def song(images=6, painted=2, made=0, **state):
    root = Path(tempfile.mkdtemp())
    folder = root/'project'
    art = folder/'art'
    art.mkdir(parents=True)
    manifest = art/'illustrations.json'
    manifest.write_text(json.dumps(dict(prompts=['p']*images)), encoding='utf-8')
    for i in range(painted):
        (art/f'{i:03d}.raw.png').write_bytes(b'png')
    summary = dict(sections=dict(seconds=[10.]*images), video=dict(model='ltx', made=made, total=images))
    return SimpleNamespace(folder=folder, manifest=lambda: manifest, pipeline_summary=lambda: summary,
                           config=dict(image_model=EDIT, steps=40, video_model='ltx'),
                           state=dict(dict(status='running', stage='illustrations', queued_actions=[]), **state))


class EtaTest(unittest.TestCase):
    def test_a_run_in_its_images_counts_every_step_still_to_come(self):
        job = song()
        left = dict(eta.estimate(job, now=1000.)['parts'])
        self.assertEqual(left['Images'], 4*240, 'four images left at the default image time')
        self.assertEqual(left['AI video'], 60*9, 'six 10 s clips at 9 s of work per clip second')
        self.assertEqual(left['Final cut'], 6*40)
        self.assertIn('Kinetic text', left)
        self.assertNotIn('Timing and prompts', left, 'those steps are done')

    def test_the_video_workers_own_time_left_is_used_while_it_runs(self):
        job = song(painted=6, made=2, status='complete', action='animate', animating=[2, 3, 4, 5],
                   detail=dict(stage='video', eta_seconds=600), detail_at=1000.)
        left = dict(eta.estimate(job, now=1100.)['parts'])
        self.assertEqual(left['AI video'], 500, 'counted down since the worker said 600 s')
        self.assertEqual(left['Final cut'], 4*40)

    def test_measured_speeds_replace_the_defaults(self):
        job = song()
        eta.measure_image(job, 30.)
        eta.measure_image(job, 40.)
        self.assertEqual(dict(eta.estimate(job, now=1000.)['parts'])['Images'], round(4*34.))
        eta.measure_action(job, 'animate', 300., [0, 1])  # 20 s of clip in 300 s
        self.assertEqual(dict(eta.estimate(job, now=1000.)['parts'])['AI video'], 60*15)

    def test_each_queued_item_is_timed_and_each_job_loads_its_model_once(self):
        job = song(painted=6, made=6, status='complete', queued_actions=[
            dict(action='regenerate', index=8), dict(action='regenerate', index=9),
            dict(action='animate', index=2, indices=[2, 3])])
        result = eta.estimate(job, now=1000.)
        left = dict(result['parts'])
        self.assertEqual(left['Images'], 60+2*240, 'one image-model load for the batch, then each image')
        self.assertEqual(left['AI video'], 90+2*10*9, 'one LTX load, then each clip by its own length')
        self.assertEqual(result['items'], {'images:8': 240, 'images:9': 240, 'animation:2': 90, 'animation:3': 90})

    def test_nothing_running_has_no_estimate(self):
        self.assertIsNone(eta.estimate(song(status='complete')))


if __name__ == '__main__':
    unittest.main()
