"""Typography pictures: kept by default, repainted only when released, and painted without stray faces."""
import sys
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import ornament_director
from glyph_art import cutout
from ornament_director import icon_prompt, picture_key, released_pictures, repaint_released, set_picture_kept


def block(folder, line, word, image=True):
    path = Path(folder)/f'{line}-{word}.png'
    if image:
        path.write_bytes(b'png')
    return dict(lines=[line], ornament=dict(line=line, word=word, source='generate', image=str(path) if image else None))


class PictureTest(unittest.TestCase):
    def test_library_picture_appears_in_workspace_snapshot(self):
        from studio import Job
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'video.blocks.json').write_text(json.dumps({'blocks': [
                {'ornament': {'line': 0, 'word': 1, 'text': 'AMBON', 'subject': 'fine drizzle',
                              'source': 'library', 'library': 'drop', 'image': None}}
            ]}), encoding='utf-8')
            pictures = Job(root, {'name': 'test'}).ornaments()
            self.assertEqual([(item['word'], item['source']) for item in pictures], [('AMBON', 'library')])
            self.assertTrue((root/'video.picture-previews'/'drop.png').is_file())

    def test_cutout_removes_white_sticker_border(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'portrait.png'
            image = Image.new('RGBA', (128, 128), (224, 224, 224, 255))
            draw = ImageDraw.Draw(image)
            draw.ellipse((18, 18, 110, 110), fill='#aaaaaa')  # model-made shadow separates the outline from the matte
            draw.ellipse((24, 24, 104, 104), fill='white')
            draw.ellipse((34, 34, 94, 94), fill='#c86a32')
            image.save(path)
            pixels = np.asarray(cutout(str(path)))
            white = (pixels[..., :3].min(axis=-1) > 195) & (pixels[..., 3] > 128)
            self.assertLess(white.mean(), .01)
            self.assertGreater(pixels[pixels.shape[0]//2, pixels.shape[1]//2, 3], 200)

    def test_only_released_or_missing_pictures_are_repainted(self):
        with tempfile.TemporaryDirectory() as folder:
            kept, released, missing = block(folder, 1, 0), block(folder, 2, 1), block(folder, 3, 0, image=False)
            Path(released['ornament']['image']).with_suffix('.cutout.png').write_bytes(b'cut')
            set_picture_kept(folder, picture_key(released['ornament']), False)
            painted = []

            def fake_paint(directions, folder_, options):
                for entry in directions:
                    if not entry['ornament']['image']:
                        painted.append(picture_key(entry['ornament']))
                        entry['ornament']['image'] = str(Path(folder_)/f'new-{len(painted)}.png')
                return directions
            original = ornament_director.paint
            ornament_director.paint = fake_paint
            try:
                old_released = released['ornament']['image']
                result = repaint_released([kept, released, missing], folder, {})
            finally:
                ornament_director.paint = original
            self.assertEqual(sorted(painted), ['2:1', '3:0'])
            self.assertEqual(result[0]['ornament']['image'], kept['ornament']['image'])
            self.assertFalse(Path(old_released).exists())
            self.assertFalse(Path(old_released).with_suffix('.cutout.png').exists())
            self.assertEqual(released_pictures(folder), set())  # repainted pictures are kept again

    def test_object_pictures_never_inherit_faces(self):
        style = 'Delicate linework, expressive faces, flowing hair, inspired by Alphonse Mucha.'
        lamp = icon_prompt('a small, warm street lamp', 'orange', style)
        self.assertNotIn('expressive faces', lamp)
        self.assertIn('no people, faces', lamp)
        self.assertTrue(lamp.startswith('Create one small painted picture of warm street lamp'))
        self.assertGreaterEqual(len(lamp.split()), 250)
        self.assertIn('expressive faces', icon_prompt('a dancing woman', '', style))


class InstrumentOverlayTest(unittest.TestCase):
    def test_overlay_keeps_the_frame_rgb_for_the_encoder(self):
        from instrument_stage import InstrumentStage
        stage = InstrumentStage.__new__(InstrumentStage)
        stage.width, stage.height, stage.size = 64, 36, 9
        picture = Image.new('RGBA', (9, 9), (200, 120, 40, 255))
        stage.items = [dict(picture=picture, spans=[(0., 10.)], motion='keys', hits=[], hit_times=[], level=[],
                            pitch=None, anchor=(.5, .5), flip=False)]
        frame = stage.paint(Image.new('RGB', (64, 36)), 5.)
        self.assertEqual((frame.mode, frame.size), ('RGB', (64, 36)))
        self.assertNotEqual(frame.getpixel((32, 18)), (0, 0, 0))


if __name__ == '__main__':
    unittest.main()
