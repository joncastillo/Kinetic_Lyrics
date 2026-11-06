"""Small pictures ask for a transparent background; a chroma-key screen is still cut out without a coloured fringe."""
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.ornaments import icon_prompt
from models.matting.cutout import without_screen_colour
from models.matting.staging import staging_alpha


def staged(subject, screen, size=96, radius=30):
    """A disc of `subject` colour on a `screen`, with an antialiased edge like a painted one."""
    y, x = np.mgrid[0:size, 0:size]
    cover = np.clip(radius+.5-np.hypot(x-size/2, y-size/2), 0, 1)[..., None]
    rgb = np.asarray(subject, float)*cover+np.asarray(screen, float)*(1-cover)
    return Image.fromarray(rgb.round().astype(np.uint8)), cover[..., 0]


def cut(image):
    alpha, reference = staging_alpha(image)
    rgba = image.convert('RGBA')
    rgba.putalpha(Image.fromarray((alpha*255).round().astype(np.uint8)))
    return np.asarray(without_screen_colour(rgba, reference), float), reference


class PromptTest(unittest.TestCase):
    def test_small_pictures_ask_for_a_transparent_background(self):
        for subject in ('a small, warm street lamp', 'a green frog'):
            prompt = icon_prompt(subject, 'orange')
            self.assertIn('Make the background transparent.', prompt, subject)
            for screen in ('chroma-key', '#00FF00', '#FF00FF', 'light grey'):
                self.assertNotIn(screen, prompt, subject)


class CutoutTest(unittest.TestCase):
    def test_the_green_screen_leaves_no_green_fringe(self):
        image, cover = staged((200, 40, 30), (0, 255, 0))
        pixels, reference = cut(image)
        self.assertGreater(reference[1]-max(reference[0], reference[2]), 200, 'the screen is found from the border')
        visible = pixels[..., 3] > 20
        edge = visible & (cover < .999)
        self.assertTrue(edge.any())
        green_excess = pixels[..., 1]-np.maximum(pixels[..., 0], pixels[..., 2])
        self.assertLessEqual(green_excess[visible].max(), 0, 'no visible pixel keeps the screen green')
        self.assertTrue(np.allclose(pixels[cover >= .999][:, :3], (200, 40, 30), atol=1), 'the subject is untouched')
        self.assertEqual(pixels[cover == 0][:, 3].max(), 0, 'the screen is transparent')

    def test_a_magenta_screen_behind_a_green_subject_keeps_the_green(self):
        image, cover = staged((40, 170, 50), (255, 0, 255))
        pixels, _ = cut(image)
        inside = cover >= .999
        self.assertTrue(np.allclose(pixels[inside][:, :3], (40, 170, 50), atol=1), 'the green subject stays green')
        visible = (pixels[..., 3] > 20) & ~inside
        magenta_excess = np.minimum(pixels[..., 0], pixels[..., 2])-pixels[..., 1]
        self.assertLessEqual(magenta_excess[visible].max(), 0, 'no magenta fringe')

    def test_a_grey_backdrop_still_cuts_out(self):
        image, cover = staged((30, 60, 160), (205, 205, 205))
        pixels, _ = cut(image)
        self.assertEqual(pixels[cover == 0][:, 3].max(), 0)
        self.assertTrue(np.allclose(pixels[cover >= .999][:, :3], (30, 60, 160), atol=1))


if __name__ == '__main__':
    unittest.main()
