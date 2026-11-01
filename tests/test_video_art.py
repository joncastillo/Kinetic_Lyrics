"""An uploaded video clip replaces one artwork slot: it plays from its slot's start (from the start frame chosen in
the timeline) and the next background takes over on cue."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is needed for video clips')
class VideoArtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from artwork.video_art import import_clip
        cls.folder = Path(tempfile.mkdtemp())
        source = cls.folder/'upload.mov'
        # A moving test pattern: every frame differs from the one before.
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=4',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
        cls.still = import_clip(source, cls.folder/'candidate')

    def test_import_makes_a_clip_and_its_first_frame(self):
        from artwork.video_art import clip_duration, sidecar
        clip = sidecar(self.still)
        self.assertIsNotNone(clip)
        self.assertAlmostEqual(clip_duration(clip), 4., delta=.1)
        with Image.open(self.still) as image:
            self.assertEqual(image.size, (320, 180))

    def compositor(self, offset=None, framing=None):
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        from artwork.video_art import copy_slot_clip, offset_path
        art = Path(tempfile.mkdtemp())
        shutil.copy2(self.still, art/'000.png')
        copy_slot_clip(self.still, art/'000.png')
        settings = {k: v for k, v in (('offset', offset), ('framing', framing)) if v is not None}
        if settings:
            offset_path(art/'000.png').write_text(json.dumps(settings), encoding='utf-8')
        Image.new('RGBA', (320, 180), '#335577').save(art/'001.png')
        words = lambda start, text: [dict(text=text, start=start, end=start+.8)]
        data = [dict(text='one', words=words(1.5, 'one')), dict(text='two', words=words(6.5, 'two'))]
        return Compositor(data, rules_plan(data, theme_for('bright')), 320, 180, 9., artwork_mode='verse',
                          illustrations=[art/'000.png', art/'001.png'], illustration_lines=1,
                          reading_flow='preview', text_animation='none')

    def test_clip_plays_in_its_slot_and_the_next_background_takes_over(self):
        c = self.compositor()
        self.assertEqual(set(c.videos), {0})
        top = lambda t: np.asarray(c.background(0, t, veil=False))[:40].astype(float)
        c.advance_videos(.5); early = top(.5)
        c.advance_videos(1.5); later = top(1.5)
        self.assertGreater(np.abs(later-early).mean(), 1.)  # the clip moves
        c.advance_videos(8.)
        self.assertEqual(c.background(1, 8., veil=False).getpixel((10, 10)), (51, 85, 119))  # next background

    def test_start_frame_chosen_in_the_timeline_shifts_the_clip(self):
        plain, shifted = self.compositor(), self.compositor(offset=1.)
        start = plain.art_starts[0]
        plain.advance_videos(start+1.); shifted.advance_videos(start)
        self.assertTrue(np.array_equal(np.asarray(plain.art[0]), np.asarray(shifted.art[0])))

    def test_framing_fills_by_default_and_leaves_centred_white_when_smaller(self):
        from artwork.video_art import FRAMING, frame_picture
        picture = Image.new('RGBA', (160, 90), (200, 20, 20, 255))
        filled = frame_picture(picture, FRAMING, (320, 180))
        self.assertEqual(filled.getpixel((2, 2)), (200, 20, 20, 255))
        small = frame_picture(picture, dict(FRAMING, zoom=.5), (320, 180))
        self.assertEqual(small.getpixel((2, 2)), (255, 255, 255, 255))  # white around it
        self.assertEqual(small.getpixel((160, 90)), (200, 20, 20, 255))  # centred
        picture_area = small.getchannel('G').point(lambda v: 255 if v < 250 else 0).getbbox()
        self.assertEqual(picture_area, (80, 45, 240, 135))  # exactly half size, centred
        moved = frame_picture(picture, dict(FRAMING, zoom=.5, x=.25), (320, 180))
        self.assertEqual(moved.getpixel((100, 90)), (255, 255, 255, 255))
        self.assertEqual(moved.getpixel((230, 90)), (200, 20, 20, 255))

    def test_crop_trims_the_clip_edges_before_fitting(self):
        from artwork.video_art import FRAMING, frame_picture
        picture = Image.new('RGBA', (200, 100), (0, 0, 255, 255))
        picture.paste((0, 255, 0, 255), (0, 0, 40, 100))  # a green strip on the left edge
        self.assertEqual(frame_picture(picture, FRAMING, (200, 100)).getpixel((5, 50))[:3], (0, 255, 0))
        cropped = frame_picture(picture, dict(FRAMING, left=.2), (200, 100))
        self.assertEqual(cropped.getpixel((5, 50))[:3], (0, 0, 255))

    def test_out_of_range_framing_is_refused(self):
        from artwork.video_art import checked_framing
        with self.assertRaises(ValueError):
            checked_framing(dict(zoom=40))
        with self.assertRaises(ValueError):
            checked_framing(dict(left=.9))

    def test_renderer_uses_the_saved_framing(self):
        c = self.compositor(framing=dict(zoom=.5))
        c.advance_videos(c.art_starts[0]+.5)
        self.assertEqual(c.art[0].getpixel((3, 3))[:3], (255, 255, 255))
        self.assertNotEqual(c.art[0].getpixel((160, 90))[:3], (255, 255, 255))

    def test_selecting_a_still_removes_the_slot_clip(self):
        from artwork.video_art import copy_slot_clip, sidecar
        art = Path(tempfile.mkdtemp())
        shutil.copy2(self.still, art/'000.png'); copy_slot_clip(self.still, art/'000.png')
        plain = art/'plain.png'; Image.new('RGBA', (32, 18), 'red').save(plain)
        copy_slot_clip(plain, art/'000.png')
        self.assertIsNone(sidecar(art/'000.png'))


if __name__ == '__main__':
    unittest.main()
