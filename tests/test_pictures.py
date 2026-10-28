"""Typography pictures: kept by default, repainted only when released, and painted without stray faces."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import ornament_director
from ornament_director import icon_prompt, picture_key, released_pictures, repaint_released, set_picture_kept


def block(folder, line, word, image=True):
    path = Path(folder)/f'{line}-{word}.png'
    if image:
        path.write_bytes(b'png')
    return dict(lines=[line], ornament=dict(line=line, word=word, source='generate', image=str(path) if image else None))


class PictureTest(unittest.TestCase):
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
        self.assertTrue(lamp.startswith('A single small warm street lamp'))
        self.assertIn('expressive faces', icon_prompt('a dancing woman', '', style))


if __name__ == '__main__':
    unittest.main()
