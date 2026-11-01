import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from studio.server import Job
from video_generation.clips import clip_folder

MODEL = 'Lightricks/LTX-2.5-Diffusers'
DIGEST = 'ab'*32


class GalleryAnimationTest(unittest.TestCase):
    def job(self, folder, model=MODEL):
        return SimpleNamespace(folder=folder, config={'video_model': model} if model else {},
                               url=lambda path: '/files/job/'+path.relative_to(folder).as_posix())

    def test_finished_clip_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            clip = clip_folder(folder, MODEL, DIGEST)
            clip.mkdir(parents=True)
            (clip/'clip.mp4').write_bytes(b'mp4')
            (clip/'clip.json').write_text(json.dumps({}), encoding='utf-8')
            self.assertEqual(Job.animation(self.job(folder), DIGEST),
                             dict(url='/files/job/'+(clip/'clip.mp4').relative_to(folder).as_posix(), parts=None, total=None, segments=[]))

    def test_unfinished_or_other_model_or_none_chosen_is_not(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            clip = clip_folder(folder, MODEL, DIGEST)
            clip.mkdir(parents=True)
            (clip/'clip.mp4').write_bytes(b'mp4')          # still being written: no clip.json yet
            self.assertIsNone(Job.animation(self.job(folder), DIGEST))
            (clip/'clip.json').write_text('{}', encoding='utf-8')
            self.assertIsNone(Job.animation(self.job(folder, 'MiniMaxAI/MiniMax-H3'), DIGEST))
            self.assertIsNone(Job.animation(self.job(folder, None), DIGEST))


if __name__ == '__main__':
    unittest.main()
