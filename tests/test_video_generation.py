"""The optional video step: clip sizes, saved clips, looping playback and the compositor's frame lookup."""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from video_generation import step
from video_generation.catalog import MODELS, clip_size, video_spec
from video_generation.clips import ClipFrames, clip_folder, clips_for, image_digest, saved_clips
from video_generation.models import frames_array


def write_clip(folder, colours, fps=24):
    """A tiny clip whose frames are flat colours, saved the way the video worker saves one."""
    folder.mkdir(parents=True)
    frames = np.stack([np.full((32, 64, 3), colour, np.uint8) for colour in colours])
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '64x32',
                    '-framerate', str(fps), '-i', 'pipe:0', '-c:v', 'libx264', '-qp', '0', '-pix_fmt', 'yuv444p',
                    str(folder/'clip.mp4')], input=frames.tobytes(), check=True)
    (folder/'clip.json').write_text(json.dumps(dict(fps=fps, frames=len(colours))), encoding='utf-8')


class CatalogTest(unittest.TestCase):
    def test_clip_size_follows_the_video_orientation(self):
        ltx = video_spec('Lightricks/LTX-2.5-Diffusers')
        self.assertEqual(clip_size(ltx, 1920, 1080), (960, 544))
        self.assertEqual(clip_size(ltx, 720, 1280), (544, 960))
        self.assertEqual(clip_size(video_spec('MiniMaxAI/MiniMax-H3'), 1280, 720), (1344, 768))
        for spec in MODELS:
            self.assertTrue(all(v % 32 == 0 for v in clip_size(spec, 1920, 1080)))

    def test_unknown_model_is_rejected(self):
        with self.assertRaises(ValueError):
            video_spec('someone/other-model')


class FramesTest(unittest.TestCase):
    def test_pipeline_output_becomes_uint8_frames(self):
        channels_first = np.ones((5, 3, 8, 16), np.float32)
        self.assertEqual(frames_array(channels_first).shape, (5, 8, 16, 3))
        self.assertEqual(frames_array(channels_first).max(), 255)
        signed = np.full((2, 8, 16, 3), -1., np.float32)
        self.assertEqual(frames_array(signed).max(), 0)
        pictures = [Image.new('RGB', (16, 8), (10, 20, 30))]*3
        self.assertEqual(frames_array(pictures)[0, 0, 0].tolist(), [10, 20, 30])


@unittest.skipUnless(shutil.which('ffmpeg'), 'needs FFmpeg')
class ClipsTest(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project)
        self.image = self.project/'000.png'
        Image.new('RGB', (64, 32), (200, 0, 0)).save(self.image)
        self.digest = image_digest(self.image)
        self.model = 'Lightricks/LTX-2.5-Diffusers'

    def test_saved_clip_is_cut_to_the_video_size_and_plays_once_then_holds(self):
        write_clip(clip_folder(self.project, self.model, self.digest), [(0, 0, 0), (120, 120, 120), (240, 240, 240)])
        clips = saved_clips(self.project, self.model, [self.digest, 'f'*64], 128, 64)
        self.assertEqual(list(clips), [self.digest], 'images without a clip stay still')
        clip = ClipFrames(clips[self.digest])
        self.assertEqual(clip.frame(0).size, (128, 64))
        # Three frames at 24 fps: 0 1 2, then the last frame holds; never played backwards.
        self.assertEqual([clip.index(n/24) for n in range(7)], [0, 1, 2, 2, 2, 2, 2])
        self.assertLess(clip.frame(0).getpixel((5, 5))[0], 20)
        self.assertGreater(clip.frame(2/24).getpixel((5, 5))[0], 220)

    def test_slots_without_a_clip_get_none(self):
        write_clip(clip_folder(self.project, self.model, self.digest), [(0, 0, 0)])
        clips = saved_clips(self.project, self.model, [self.digest], 64, 32)
        slots = clips_for(clips, [self.digest, 'other'])
        self.assertIsInstance(slots[0], ClipFrames)
        self.assertIsNone(slots[1])
        self.assertEqual(clips_for(None, [self.digest]), [])

    def test_step_skips_generation_when_every_clip_exists(self):
        write_clip(clip_folder(self.project, self.model, self.digest), [(0, 0, 0)])
        args = argparse.Namespace(video_model=self.model, artwork_mode='fullscreen', width=64, height=32,
                                  image_seed=7, image_cache=str(self.project))
        with mock.patch.object(step, 'module_command', wraps=step.module_command) as worker:
            clips = step.animate([self.image], self.project/'video.mp4', args)
        worker.assert_not_called()
        self.assertEqual(list(clips), [self.digest])

    def test_step_writes_a_job_for_missing_clips(self):
        args = argparse.Namespace(video_model=self.model, artwork_mode='verse', width=64, height=32,
                                  image_seed=7, image_cache=str(self.project))
        with mock.patch.object(step.subprocess, 'run') as run, mock.patch.object(step.shutil, 'disk_usage') as usage:
            usage.return_value.free = 10**15
            self.assertEqual(step.animate([self.image], self.project/'video.mp4', args), {})
        self.assertIn('video_generation.generation', run.call_args.args[0])
        job = json.loads((self.project/'video-clips'/'job.json').read_text(encoding='utf-8'))
        self.assertEqual(job['clips'][0]['sha256'], self.digest)
        self.assertEqual(job['clips'][0]['size'], [960, 544])

    def test_compositor_plays_the_clip_in_place_of_the_still(self):
        from render.compositor import Compositor
        from direction.typography import rules_plan
        second = self.project/'001.png'
        Image.new('RGB', (64, 32), (0, 0, 200)).save(second)
        write_clip(clip_folder(self.project, self.model, self.digest), [(0, 200, 0), (200, 200, 200)])
        clips = saved_clips(self.project, self.model, [self.digest], 320, 180)
        data = [dict(text=t, words=[dict(text=w, start=s+i*.4, end=s+i*.4+.35) for i, w in enumerate(t.split())])
                for t, s in (('over the hills', 1.), ('far away', 3.), ('down the river', 6.), ('to the sea', 8.))]
        c = Compositor(data, rules_plan(data, dict(name='calm')), 320, 180, 10., illustrations=[self.image, second],
                       illustration_lines=2, artwork_mode='fullscreen', reading_flow='preview', video_clips=clips,
                       custom_font=Path(__file__).resolve().parent.parent/'assets'/'fonts'/'Montserrat-Variable.ttf',
                       entrance_effect='none', exit_effect='none', particle_intensity=0)
        start = c.art_starts[0]
        self.assertGreater(c.art_frame(0, start).getpixel((5, 5))[1], 180, 'first clip frame, not the red still')
        self.assertGreater(c.art_frame(0, start+1/24).getpixel((5, 5))[0], 180)
        self.assertEqual(c.art_frame(1, c.art_starts[1]).getpixel((5, 5)), (0, 0, 200), 'no clip: the still')
        self.assertEqual(c.background(0, start+1., veil=False).size, (320, 180))

    def test_clip_too_short_for_its_section_is_made_again_at_full_length(self):
        write_clip(clip_folder(self.project, self.model, self.digest), [(0, 0, 0)]*3)   # 3 frames: far too short
        args = argparse.Namespace(video_model=self.model, artwork_mode='verse', width=64, height=32, image_seed=7,
                                  image_cache=str(self.project), illustration_lines=1, lead_in=1.)
        data = [dict(text='la', words=[dict(text='la', start=4., end=4.5)])]
        with mock.patch.object(step.subprocess, 'run') as run, mock.patch.object(step.shutil, 'disk_usage') as usage:
            usage.return_value.free = 10**15
            step.animate([self.image], self.project/'video.mp4', args, data=data, duration=12.)
        # Compare only the module name: a failing assert on the call itself would print its env (secrets included).
        workers = [call for call in run.call_args_list if 'video_generation.generation' in call.args[0]]
        self.assertEqual(len(workers), 1, 'the short clip is sent to the video worker again')
        job = json.loads((self.project/'video-clips'/'job.json').read_text(encoding='utf-8'))
        self.assertEqual(job['clips'][0]['frames'], 289, 'the whole 12 s on screen at 24 fps, as an 8k+1 count')

    def test_a_stopped_clip_resumes_after_its_saved_parts(self):
        from video_generation import generation
        spec = dict(video_spec(self.model), chunk_frames=33)
        calls = []
        def fake(pipe, spec, image, prompt, seed, torch, num_frames=None):
            calls.append((np.asarray(image)[0, 0, 0], prompt))
            if len(calls) == 3 and crash:
                raise MemoryError('out of memory in part 3')
            return np.full((num_frames, 32, 64, 3), 40*len(calls), np.uint8)
        folder = self.project/'clip'
        crash = True
        store = generation.PartStore(folder, 24, 'sha:7', ['first', 'second', 'third'])
        with mock.patch('video_generation.models.animate', fake), self.assertRaises(MemoryError):
            generation.animate_length(None, spec, Image.new('RGB', (64, 32)), store.prompts, 7, 81, None, sink=store)
        self.assertEqual(len(store.parts), 2, 'the two finished parts were saved before the crash')

        crash, calls[:] = False, []
        resumed = generation.PartStore(folder, 24, 'sha:7', ['NEW beats from a later run'])
        self.assertEqual((len(resumed.parts), resumed.prompts[0]), (2, 'first'), 'keeps the prompts it started with')
        with mock.patch('video_generation.models.animate', fake):
            frames, parts = generation.animate_length(None, spec, Image.new('RGB', (64, 32)), resumed.prompts, 7, 81, None,
                                                      sink=resumed)
        self.assertIsNone(frames, 'parts go to disk, not RAM')
        self.assertEqual(len(calls), 1, 'only the missing part is generated')
        self.assertEqual(calls[0][1], 'third')
        self.assertAlmostEqual(int(calls[0][0]), 80, delta=6, msg='it starts from the saved last frame of part 2')
        self.assertEqual(resumed.close(self.project/'clip.mp4'), 89)
        counted = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                                  'stream=nb_read_frames', '-of', 'csv=p=0', str(self.project/'clip.mp4')],
                                 capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(counted, '89')
        self.assertTrue((folder/'parts'/'part-002.mp4').exists(), 'parts are kept so a segment can be redone later')
        self.assertFalse(list((folder/'parts').glob('preview*')), 'temporary previews are removed')

    def test_saved_parts_of_another_painting_are_discarded(self):
        from video_generation import generation
        store = generation.PartStore(self.project/'clip', 24, 'sha-a:1', ['p'])
        store.write(np.zeros((5, 32, 64, 3), np.uint8))
        self.assertEqual(len(generation.PartStore(self.project/'clip', 24, 'sha-a:1', ['p']).parts), 1)
        self.assertEqual(generation.PartStore(self.project/'clip', 24, 'sha-b:1', ['p']).parts, [], 'replaced image')

    def test_step_ignores_cutout_artwork(self):
        args = argparse.Namespace(video_model=self.model, artwork_mode='cutout', width=64, height=32, image_seed=7)
        self.assertIsNone(step.animate([self.image], self.project/'video.mp4', args))


class LengthTest(unittest.TestCase):
    def test_each_painting_covers_its_time_on_screen_including_the_crossfade(self):
        spec = video_spec('Lightricks/LTX-2.5-Diffusers')
        # Two lines, one painting each: the first from 0 s (through the intro) until the second has crossfaded in.
        data = [dict(text=t, words=[dict(text=t, start=s, end=s+.5)]) for t, s in (('one', 30.), ('two', 40.))]
        args = argparse.Namespace(illustration_lines=1, lead_in=1., art_times=None)
        seconds = step.on_screen_seconds(['000.png', '001.png'], data, 60., args)
        # Starts 29 s and 39 s (1 s lead-in); the second's crossing is min(20, 0.9 x (39-29)) = 9 s, plus the 1 s
        # margin. The last painting runs to the end of the song.
        self.assertEqual(seconds, [49., 21.])
        self.assertEqual(step.frames_for(49., spec), 1177)
        self.assertEqual(step.frames_for(None, spec), spec['frames'], 'unknown timing: the standard clip')
        self.assertEqual((step.frames_for(.1, spec)-1) % 8, 0)

    def test_long_section_is_made_as_parts_continuing_from_the_last_frame(self):
        from video_generation import generation
        spec = dict(video_spec('Lightricks/LTX-2.5-Diffusers'), chunk_frames=33)
        starts, lengths = [], []
        def fake(pipe, spec, image, prompt, seed, torch, num_frames=None):
            starts.append(np.asarray(image)[0, 0, 0]); lengths.append(num_frames)
            base = len(lengths)*10
            return np.stack([np.full((4, 4, 3), base+i, np.uint8) for i in range(num_frames)])
        with mock.patch('video_generation.models.animate', fake):
            frames, parts = generation.animate_length(None, spec, Image.new('RGB', (4, 4), (7, 7, 7)), 'p', 1, 81, None)
        self.assertGreaterEqual(len(frames), 81)
        self.assertEqual(parts, 3)
        self.assertTrue(all((n-1) % 8 == 0 and n <= 33 for n in lengths), lengths)
        self.assertEqual(starts[0], 7, 'the first part starts from the painting')
        self.assertEqual(starts[1], 10+32, 'each later part starts from the previous part\'s last frame')
        self.assertEqual(int(frames[33, 0, 0, 0]), 21, 'the repeated first frame of a later part is dropped')


if __name__ == '__main__':
    unittest.main()
