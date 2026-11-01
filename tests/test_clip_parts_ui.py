"""The gallery plays the parts made so far of a clip still being made, and a clip can be started over."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio.server import Job, partial_preview
from video_generation.clips import clip_folder, image_digest
from video_generation.generation import PartStore

MODEL = 'Lightricks/LTX-2.5-Diffusers'


@unittest.skipUnless(shutil.which('ffmpeg'), 'needs FFmpeg')
class ClipPartsTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        art = self.folder/'video.artwork'/'abc'
        art.mkdir(parents=True)
        self.manifest = art/'illustrations.json'
        self.manifest.write_text(json.dumps(dict(prompts=['a'])), encoding='utf-8')
        Image.new('RGB', (8, 8), (200, 0, 0)).save(art/'000.png')
        self.clip = clip_folder(self.folder, MODEL, image_digest(art/'000.png'))

    def job(self, status='complete', stage='complete', action=None):
        return SimpleNamespace(folder=self.folder, config=dict(video_model=MODEL, artwork_mode='verse'),
                               state=dict(status=status, stage=stage, action=action, queued_actions=[], dirty=[]),
                               manifest=lambda: self.manifest, log=lambda message: None,
                               url=lambda path: '/files/'+path.relative_to(self.folder).as_posix(),
                               queue_missing_clips=lambda: Job.queue_missing_clips(job))

    def part(self, store, frames=6):
        store.write(np.full((frames, 32, 64, 3), 120, np.uint8))

    def test_parts_made_so_far_play_as_one_preview_rebuilt_per_new_part(self):
        store = PartStore(self.clip, 24, 'k', ['p'])
        self.assertIsNone(partial_preview(self.clip), 'nothing made yet')
        self.part(store); self.part(store)
        path, done = partial_preview(self.clip)
        self.assertEqual((path.name, done), ('preview-002.mp4', 2))
        frames = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                                 'stream=nb_read_frames', '-of', 'csv=p=0', str(path)], capture_output=True, text=True).stdout
        self.assertEqual(frames.strip(), '12')
        self.part(store)
        path3, done3 = partial_preview(self.clip)
        self.assertEqual((path3.name, done3), ('preview-003.mp4', 3))
        self.assertFalse(path.exists(), 'the older preview is removed')

    def test_starting_over_while_idle_clears_the_clip_and_queues_it(self):
        store = PartStore(self.clip, 24, 'k', ['p'])
        self.part(store)
        (self.clip/'clip.json').write_text('{}', encoding='utf-8')
        global job
        job = self.job()
        Job.restart_clip(job, 0)
        self.assertFalse((self.clip/'clip.json').exists())
        self.assertFalse((self.clip/'parts').exists())
        self.assertEqual(job.state['queued_actions'], [dict(action='animate', index=0, indices=[0])])

    def test_regenerating_from_a_segment_keeps_the_ones_before_and_rerolls_the_seed(self):
        from studio.server import segment_starts
        store = PartStore(self.clip, 24, 'k', ['p'])
        for frames in (24, 24, 24, 24):
            self.part(store, frames)
        (self.clip/'clip.json').write_text('{}', encoding='utf-8')
        (self.clip/'clip.mp4').write_bytes(b'mp4')
        self.assertEqual(segment_starts(self.clip), [0., 1., 2., 3.])
        global job
        job = self.job()
        Job.restart_clip(job, 0, 2)
        kept = PartStore(self.clip, 24, 'k', ['other'])
        self.assertEqual((len(kept.parts), kept.reroll, kept.prompts), (2, 1, ['p']), 'parts 1-2 kept, new seed, same prompts')
        self.assertFalse((self.clip/'part-002.mp4').exists() or (self.clip/'parts'/'part-002.mp4').exists())
        self.assertFalse((self.clip/'clip.json').exists(), 'the finished clip is undone so it is made again')
        self.assertEqual(job.state['queued_actions'], [dict(action='animate', index=0, indices=[0])])

    def test_a_clip_made_before_parts_were_kept_can_still_be_redone_from_a_segment(self):
        from studio.server import segment_starts
        from video_generation.generation import write_clip
        self.clip.mkdir(parents=True)
        frames = np.concatenate([np.full((n, 32, 64, 3), 40*(k+1), np.uint8) for k, n in enumerate((121, 120, 96))])
        write_clip(frames, 24, self.clip/'clip.mp4')
        (self.clip/'clip.json').write_text(json.dumps(dict(model=MODEL, source_sha256='s', seed=3, fps=24, frames=337,
                                                           parts=3, prompts=['a', 'b', 'c'])), encoding='utf-8')
        self.assertEqual(segment_starts(self.clip), [0., 5.04, 10.04], 'one chunk, then a chunk less one, then the rest')
        global job
        job = self.job()
        Job.restart_clip(job, 0, 1)
        kept = PartStore(self.clip, 24, 's:3', ['new'])
        self.assertEqual(([p['frames'] for p in kept.parts], kept.prompts, kept.reroll), ([121], ['a', 'b', 'c'], 1))
        self.assertAlmostEqual(int(np.asarray(kept.last_frame)[0, 0, 0]), 40, delta=4, msg='part 1 ends on its own last frame')
        self.assertFalse((self.clip/'clip.json').exists())

    def test_a_segment_redo_during_generation_is_applied_by_the_worker(self):
        store = PartStore(self.clip, 24, 'k', ['p'])
        for _ in range(3):
            self.part(store)
        global job
        job = self.job(status='running', stage='video')
        Job.restart_clip(job, 0, 1)
        self.assertEqual((self.clip/'restart').read_text(encoding='utf-8'), '1')
        self.assertTrue(store.restart_requested())
        self.assertEqual((len(store.parts), store.reroll), (1, 1))

    def test_starting_over_while_it_is_being_made_leaves_a_marker_for_the_worker(self):
        store = PartStore(self.clip, 24, 'k', ['p'])
        self.part(store)
        global job
        job = self.job(status='running', stage='video')
        Job.restart_clip(job, 0)
        self.assertTrue((self.clip/'restart').exists())
        self.assertTrue(store.restart_requested(), 'the worker sees it before its next part')
        self.assertEqual((store.parts, (self.clip/'parts').exists(), (self.clip/'restart').exists()), ([], False, False))


if __name__ == '__main__':
    unittest.main()
