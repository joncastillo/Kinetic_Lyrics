"""Scene joins affect only the seam, never the whole painting."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from world_canvas import WorldCanvas


class WorldCanvasTest(unittest.TestCase):
    def test_neighboring_paintings_mix_only_near_the_seam(self):
        class PathAcross:
            def at(self, t):
                return t*100, 0

        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for name, color in [('left', '#e02020'), ('right', '#2050e0')]:
                path = Path(folder)/f'{name}.png'
                Image.new('RGB', (100, 60), color).save(path)
                paths.append(str(path))
            world = WorldCanvas(paths, [(0, 1), (1, 2)], 100, 60, PathAcross(), bleed=.8)
            view = np.asarray(world.view(50, -30, 100, 60).convert('RGB'))
            mixed = (view[..., 0] > 50) & (view[..., 2] > 50)
            self.assertLess(mixed.mean(), .2)
            self.assertGreater((view[..., 0] > 180).mean(), .15)
            self.assertGreater((view[..., 2] > 180).mean(), .15)


if __name__ == '__main__':
    unittest.main()
