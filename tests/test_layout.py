"""Smoke tests: the src/ui/data split resolves from the project root."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from project_paths import PROJECT_ROOT, UI_ROOT


class LayoutTest(unittest.TestCase):
    def test_ui_files_present(self):
        for name in ('studio.html', 'studio.css', 'studio-models.js', 'studio-particles.js', 'studio-profiles.js', 'studio-timeline.js', 'studio-timeline.css'):
            self.assertTrue((UI_ROOT/name).is_file(), name)

    def test_data_folders_present(self):
        for name in ('assets', 'particles', 'shaders'):
            self.assertTrue((PROJECT_ROOT/name).is_dir(), name)

    def test_particle_catalog_loads(self):
        from particle_catalog import discover_effects
        catalog = discover_effects()
        self.assertTrue(catalog['entrance'])
        self.assertTrue(catalog['exit'])


if __name__ == '__main__':
    unittest.main()
