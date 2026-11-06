"""Greenscreen scenery: keying, the embedded matte, and lyrics staying behind the scenery."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import numpy as np
from PIL import Image, ImageDraw

import artwork.greenscreen as greenscreen


def scenery(skyline=380, land=(60, 80, 50), size=(1344, 768)):
    """Imperfect chroma-green sky over a hill line, with a small foliage-green tree in front."""
    image = Image.new('RGB', size, (18, 236, 28))
    draw = ImageDraw.Draw(image)
    draw.polygon([(0, skyline), (400, skyline-50), (800, skyline+20), (size[0], skyline-30),
                  (size[0], size[1]), (0, size[1])], fill=land)
    draw.ellipse((200, skyline-120, 260, skyline-40), fill=(70, 140, 60))
    return image


class GreenscreenTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def artwork(self, name, skyline, land, sky):
        raw, plate, target = (self.folder/f'{name}.raw.png', self.folder/f'{name}.plate.png', self.folder/f'{name}.png')
        scenery(skyline, land).save(raw)
        Image.new('RGB', (1344, 768), sky).save(plate)
        greenscreen.compose_files(raw, plate, target)
        return target

    def test_keys_sky_and_keeps_scenery(self):
        matte = greenscreen.key_green(scenery())
        self.assertEqual(matte.getpixel((10, 10)), 0)
        self.assertEqual(matte.getpixel((10, 700)), 255)
        self.assertEqual(matte.getpixel((230, 300)), 255, 'foliage green stays scenery')
        self.assertTrue(greenscreen.usable(scenery()))
        self.assertFalse(greenscreen.usable(Image.new('RGB', (640, 360), (60, 80, 50))))

    def test_matte_travels_inside_the_png(self):
        path = self.artwork('000', 380, (60, 80, 50), (240, 170, 120))
        rgb, matte = greenscreen.load(path)
        self.assertEqual(rgb.getpixel((10, 10)), (240, 170, 120))
        self.assertEqual(rgb.getpixel((10, 700)), (60, 80, 50))
        self.assertEqual((matte.getpixel((10, 10)), matte.getpixel((10, 700))), (0, 255))
        x, y, w, h = greenscreen.open_box(matte, 10)
        self.assertTrue(np.all(np.asarray(matte)[y:y+h, x:x+w] == 0))

    def test_fallbacks(self):
        transparent = Image.new('RGBA', (320, 180), (50, 60, 40, 255))
        ImageDraw.Draw(transparent).rectangle((0, 0, 319, 80), fill=(0, 0, 0, 0))
        transparent.save(self.folder/'upload.png')
        _, matte = greenscreen.load(self.folder/'upload.png')
        self.assertEqual((matte.getpixel((5, 5)), matte.getpixel((5, 170))), (0, 255))
        Image.new('RGB', (320, 180), (90, 120, 200)).save(self.folder/'plain.png')
        _, matte = greenscreen.load(self.folder/'plain.png')
        self.assertEqual(matte.getextrema(), (0, 0))

    def test_scenery_layer_covers_both_scenes_while_blending(self):
        from render.compositor import Compositor; from direction.typography import rules_plan
        paths = [self.artwork('000', 380, (60, 80, 50), (240, 170, 120)),
                 self.artwork('001', 460, (40, 40, 90), (120, 160, 230))]
        data = [dict(text=t, words=[dict(text=w, start=s+i*.4, end=s+i*.4+.35) for i, w in enumerate(t.split())])
                for t, s in (('over the hills', 1.), ('far away', 3.), ('down the river', 6.), ('to the sea', 8.))]
        c = Compositor(data, rules_plan(data, dict(name='calm')), 640, 360, 10., illustrations=paths,
                       illustration_lines=2, artwork_mode='matte', reading_flow='preview',
                       entrance_effect='none', exit_effect='none', particle_intensity=0)
        self.assertEqual(len(c.mattes), 2)
        for artwork, box in enumerate(c.open_boxes):
            x, y, w, h = box
            self.assertTrue(np.all(np.asarray(c.mattes[artwork])[y:y+h, x:x+w] == 0), 'reading area is open sky')
            self.assertEqual(c.composition(artwork)[1], box)
        settled = c.scenery(c.art_starts[1]+1.)
        self.assertEqual(np.asarray(settled.getchannel('A')).tolist(), np.asarray(c.mattes[1]).tolist())
        blending = np.asarray(c.scenery(c.art_starts[1]+.3).getchannel('A'))
        union = np.maximum(np.asarray(c.mattes[0]), np.asarray(c.mattes[1]))
        self.assertTrue(np.array_equal(blending, union))

    def test_layout_reserves_the_sky(self):
        from render.layout import illustration_layout
        layout = illustration_layout(0, 1280, 720, artwork_mode='matte')
        self.assertIn('#00FF00', layout['visual_prompt'])
        self.assertLess(layout['text_box'][1]+layout['text_box'][3], 720*layout['sky'])


if __name__ == '__main__':
    unittest.main()
