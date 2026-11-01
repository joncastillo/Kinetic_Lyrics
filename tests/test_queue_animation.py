"""A replaced, regenerated or repaired illustration is queued for the video step once the job has clips."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio.server import Job
from video_generation.clips import clip_folder, image_digest

MODEL = 'Lightricks/LTX-2.5-Diffusers'


class QueueAnimationTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        art = self.folder/'video.artwork'/'abc'
        art.mkdir(parents=True)
        self.manifest = art/'illustrations.json'
        self.manifest.write_text(json.dumps(dict(prompts=['a', 'b'])), encoding='utf-8')
        for i, colour in enumerate(((200, 0, 0), (0, 0, 200))):
            Image.new('RGB', (8, 8), colour).save(art/f'{i:03d}.png')
        self.images = [art/'000.png', art/'001.png']

    def job(self, status='complete', model=MODEL, mode='verse', queued=(), action=None):
        logs = []
        job = SimpleNamespace(folder=self.folder, config=dict(video_model=model, artwork_mode=mode),
                              state=dict(status=status, action=action, queued_actions=list(queued)),
                              manifest=lambda: self.manifest, log=logs.append)
        job.logs = logs
        return job

    def clip(self, image):
        folder = clip_folder(self.folder, MODEL, image_digest(image))
        folder.mkdir(parents=True)
        (folder/'clip.mp4').write_bytes(b'mp4')
        (folder/'clip.json').write_text('{}', encoding='utf-8')

    def test_image_without_a_clip_is_queued_once(self):
        self.clip(self.images[0])                       # 001 was replaced: its new picture has no clip
        job = self.job()
        Job.queue_missing_clips(job)
        self.assertEqual(job.state['queued_actions'], [dict(action='animate', index=1, indices=[1])])
        Job.queue_missing_clips(job)
        self.assertEqual(len(job.state['queued_actions']), 1, 'not queued twice')

    def test_nothing_queued_before_the_video_step_ran_or_without_a_video_model(self):
        Job.queue_missing_clips(job := self.job())      # no video-clips folder yet: the pipeline animates all
        self.assertEqual(job.state['queued_actions'], [])
        self.clip(self.images[0])
        for job in (self.job(model=''), self.job(mode='cutout'), self.job(status='running'), self.job(action='animate')):
            Job.queue_missing_clips(job)
            self.assertEqual(job.state['queued_actions'], [])

    def test_every_illustration_with_a_clip_queues_nothing(self):
        for image in self.images:
            self.clip(image)
        Job.queue_missing_clips(job := self.job())
        self.assertEqual(job.state['queued_actions'], [])


if __name__ == '__main__':
    unittest.main()
