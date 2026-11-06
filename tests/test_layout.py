"""Smoke tests: the code, front end and data folders resolve from the project root."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from core.paths import ASSET_ROOT, UI_ROOT


class LayoutTest(unittest.TestCase):
    def test_ui_files_present(self):
        for name in ('studio.html', 'studio-tokens.css', 'studio-base.css', 'studio-header.css', 'studio-layout.css', 'studio-inspector.css',
                     'studio-workspace.css', 'studio-dialogs.css', 'studio-app.js', 'studio-gallery.js', 'studio-session.js',
                     'studio-profiles.js', 'studio-models.js', 'studio-particles.js', 'studio-timeline.js', 'studio-video.js',
                     'studio-fx-sim.js', 'studio-story.js', 'studio-shell.js', 'studio-tips.js', 'studio-home.js', 'studio-projects.js',  'studio-appearance.js', 'studio-boot.js', 'studio-project-tabs.js'):
            self.assertTrue((UI_ROOT/name).is_file(), name)

    def test_data_folders_present(self):
        for name in ('fonts', 'particles', 'scenes', 'shaders'):
            self.assertTrue((ASSET_ROOT/name).is_dir(), name)

    def test_shader_files_present(self):
        for name in ('particles.vert', 'particles.frag', 'fullscreen.vert', 'bloom.frag', 'composite.frag'):
            self.assertTrue((ASSET_ROOT/'shaders'/name).is_file(), name)

    def test_scene_catalog_loads(self):
        from direction.scene_catalog import scene_catalog
        self.assertTrue(scene_catalog())

    def test_particle_catalog_loads(self):
        from effects.particles.catalog import discover_effects
        catalog = discover_effects()
        self.assertTrue(catalog['entrance'])
        self.assertTrue(catalog['exit'])


if __name__ == '__main__':
    unittest.main()
