"""Small pictures are editable safe SVGs with transparent stage PNGs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class VectorClipartTest(unittest.TestCase):
    def test_validation_rejects_unsafe_or_unrenderable_shapes(self):
        from artwork.vector_clipart import validate_icon

        with self.assertRaises(ValueError):
            validate_icon(dict(shapes=[dict(kind='script', color='#FFFFFF')]*3))
        with self.assertRaises(ValueError):
            validate_icon(dict(shapes=[dict(kind='circle', color='url(https://example.com)',
                                            cx=50, cy=50, radius=20)]*3))

    def test_model_geometry_saves_svg_and_transparent_png(self):
        from artwork.vector_clipart import paint_icons
        from render.glyph_art import cutout

        shapes = [dict(kind='circle', color='#F4F4F4', cx=50, cy=50, radius=29),
                  dict(kind='ellipse', color='#FF789A', cx=42, cy=40, rx=11, ry=8),
                  dict(kind='polygon', color='#3A6090', points=[[20, 74], [50, 56], [80, 74]])]
        calls = []
        def request(endpoint, payload, timeout):
            calls.append(payload['model'])
            return dict(message=dict(content=json.dumps(dict(icons=[dict(shapes=shapes)]))))
        with tempfile.TemporaryDirectory() as folder:
            paths = paint_icons(['a bright round lantern'], ['lantern'], folder,
                                dict(mini_image_model='qwen3:14b'), request=request)
            self.assertEqual(calls, ['qwen3:14b'])
            self.assertTrue(paths[0].is_file())
            root = ET.parse(paths[0].with_suffix('.svg')).getroot()
            self.assertEqual(root.tag.rsplit('}', 1)[-1], 'svg')
            self.assertEqual(len(root), 3)
            from PIL import Image
            with Image.open(paths[0]) as image:
                self.assertEqual(image.getchannel('A').getextrema(), (0, 255))
            self.assertIsNotNone(cutout(str(paths[0])).getbbox())
            self.assertEqual(paint_icons(['a bright round lantern'], ['lantern'], folder,
                                         dict(mini_image_model='qwen3:14b'), request=request), paths)
            self.assertEqual(len(calls), 1)

    def test_familiar_tiny_subjects_use_legible_vector_silhouettes(self):
        from artwork.vector_clipart import familiar_icon, paint_icons
        from PIL import Image

        for subject in ('moth', 'flower', 'airplane', 'heart', 'star', 'leaf', 'comet'):
            self.assertGreaterEqual(len(familiar_icon(subject)), 3)
        with tempfile.TemporaryDirectory() as folder:
            path = paint_icons(['a pale moth'], ['moth'], folder, {})[0]
            self.assertTrue(path.with_suffix('.svg').is_file())
            with Image.open(path) as image:
                self.assertLess(image.getchannel('A').getbbox()[0], 45)
                self.assertGreater(image.getchannel('A').getbbox()[2], 210)


if __name__ == '__main__':
    unittest.main()
