"""Video backdrops keep existing loops and crossfade only clips with a visible boundary jump."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from core.video_loop import LOOP_TAG, prepare_loop, probe, seamless


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'needs FFmpeg')
class VideoLoops(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        for name, source in [
            ('still', 'color=c=red:size=160x90:rate=30:duration=2'),
            ('moving', 'testsrc2=size=160x90:rate=30:duration=2'),
        ]:
            subprocess.run(
                [
                    'ffmpeg',
                    '-v',
                    'error',
                    '-y',
                    '-f',
                    'lavfi',
                    '-i',
                    source,
                    '-c:v',
                    'libx264',
                    '-pix_fmt',
                    'yuv420p',
                    str(cls.folder / (name + '.mp4')),
                ],
                check=True,
            )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_loop_detection_looks_at_the_frames(self):
        self.assertTrue(seamless(self.folder / 'still.mp4'))
        self.assertFalse(seamless(self.folder / 'moving.mp4'))

    def test_an_existing_loop_is_not_crossfaded_or_shortened(self):
        target = self.folder / 'still-loop.mp4'
        result = prepare_loop(self.folder / 'still.mp4', target)
        self.assertEqual(result, dict(loop=True, loop_detected=True, crossfaded=False))
        self.assertAlmostEqual(float(probe(target)[1]['duration']), 2.0, delta=0.05)

    def test_a_non_loop_is_crossfaded_and_marked(self):
        target = self.folder / 'moving-loop.mp4'
        result = prepare_loop(self.folder / 'moving.mp4', target)
        self.assertEqual(result, dict(loop=True, loop_detected=False, crossfaded=True))
        self.assertIn(LOOP_TAG, probe(target)[1]['tags']['comment'])
        self.assertTrue(seamless(target))
        # Reusing a loop from Image Maker does not apply another fade.
        reused = self.folder / 'reused.mp4'
        self.assertFalse(prepare_loop(target, reused)['crossfaded'])
        self.assertAlmostEqual(float(probe(target)[1]['duration']), float(probe(reused)[1]['duration']), delta=0.05)

    def test_a_generated_loop_can_have_an_exact_requested_duration(self):
        target = self.folder / 'exact-loop.mp4'
        result = prepare_loop(self.folder / 'still.mp4', target, seconds=5, crossfade=False)
        self.assertFalse(result['crossfaded'])
        self.assertAlmostEqual(float(probe(target)[1]['duration']), 5.0, delta=0.01)

    def test_a_no_dissolve_request_never_silently_fades_clouds(self):
        with self.assertRaisesRegex(ValueError, 'no crossfade was applied'):
            prepare_loop(self.folder / 'moving.mp4', self.folder / 'no-fade.mp4', crossfade=False)

    def test_invalid_video_is_an_actionable_error(self):
        source = self.folder / 'bad.mp4'
        source.write_text('not a video', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'video could not be read'):
            prepare_loop(source, self.folder / 'bad-loop.mp4')

    def test_renderer_loops_old_uploads_and_leaves_prepared_loops_alone(self):
        import numpy as np
        from artwork.video_art import FPS, VideoArt

        old = VideoArt(self.folder / 'moving.mp4', lambda image: image.copy())
        first = np.asarray(old.frame(0))
        self.assertGreater(old.loop_join, 0)
        period = (old.count - old.loop_join) / FPS
        self.assertTrue(np.array_equal(first, np.asarray(old.frame(period + 0.00001))))
        prepared = self.folder / 'prepared.mp4'
        prepare_loop(self.folder / 'moving.mp4', prepared)
        ready = VideoArt(prepared, lambda image: image.copy())
        ready.frame(0)
        self.assertEqual(ready.loop_join, 0)



if __name__ == '__main__':
    unittest.main()
