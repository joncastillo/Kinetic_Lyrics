"""Regenerating from Images (not resuming) redoes the recurring reference pictures with the images."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio import server


class RestartReferencesTest(unittest.TestCase):
    def test_illustrations_subnode_keeps_reference_images_and_verdicts(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);manifest=folder/'illustrations.json';manifest.write_text('{"prompts":["scene"]}')
            original=dict(segments=[],entities=[dict(id='doctor',image='doctor.png',sheet_review=dict(passed=True))])
            (folder/'story.json').write_text(json.dumps(original))
            with mock.patch('artwork.active.select_manifest',return_value=manifest),mock.patch('artwork.active.archive_images') as archive:
                server.clear_redone_work(folder,dict(start_substep='illustrations'),'images')
            self.assertEqual(json.loads((folder/'story.json').read_text()),original)
            archive.assert_called_once()

    def test_a_fresh_images_start_drops_the_painted_references_but_keeps_an_upload(self):
        folder = Path(tempfile.mkdtemp())
        art = folder/'video.artwork'/'abc'
        (art/'entities').mkdir(parents=True)
        manifest = art/'illustrations.json'
        manifest.write_text(json.dumps(dict(prompts=['a', 'b'])), encoding='utf-8')
        sheet, upload = art/'entities'/'the-criminal.png', art/'entities'/'mine.png'
        sheet.write_bytes(b'x')
        upload.write_bytes(b'y')
        (art/'story.json').write_text(json.dumps(dict(segments=[], entities=[
            dict(id='the-criminal', kind='character', image=str(sheet), sheet_review=dict(passed=False), review_repaints=1),
            dict(id='the-cat', kind='character', image=str(upload), uploaded=str(upload)),
            dict(id='elara', kind='character', cast=True)])), encoding='utf-8')
        with mock.patch('artwork.active.select_manifest', return_value=manifest), \
                mock.patch('artwork.active.archive_images'):
            server.clear_redone_work(folder, {}, 'images')
        criminal, cat, _ = json.loads((art/'story.json').read_text(encoding='utf-8'))['entities']
        self.assertNotIn('image', criminal)
        self.assertEqual(criminal['repaint'], 1, 'a new picture, under a new name')
        self.assertNotIn('sheet_review', criminal)
        self.assertNotIn('review_repaints', criminal)
        self.assertEqual(cat['image'], str(upload), "the user's own picture is kept")
        self.assertTrue(sheet.is_file(), 'nothing is deleted')

    def test_the_panel_hides_pictures_made_before_a_fresh_run(self):
        folder = Path(tempfile.mkdtemp())
        art = folder/'video.artwork'/'abc'
        art.mkdir(parents=True)
        sheet = art/'old.png'
        sheet.write_bytes(b'x')
        manifest = art/'illustrations.json'
        manifest.write_text('{}', encoding='utf-8')
        (art/'story.json').write_text(json.dumps(dict(segments=[], entities=[
            dict(id='old', name='old', kind='object', image=str(sheet), segments=[0, 1])])), encoding='utf-8')
        job = SimpleNamespace(folder=folder, config={}, manifest=lambda: manifest, url=lambda p: 'url',
                              gallery_since=lambda: time.time()+60)
        self.assertIsNone(server.Job.entity_references(job)[0]['url'])
        job.gallery_since = lambda: 0
        self.assertEqual(server.Job.entity_references(job)[0]['url'], 'url')


class SmallPicturesTest(unittest.TestCase):
    """A restart at or before the images takes the small pictures with it, kept or not; a later one leaves them."""
    def project(self):
        root = Path(tempfile.mkdtemp())
        folder = root/'job'
        (folder/'video.ornaments'/'abc').mkdir(parents=True)
        (folder/'video.ornaments'/'abc'/'000.png').write_bytes(b'picture')
        (folder/'video.blocks.json').write_text('{}', encoding='utf-8')
        (folder/'video.pictures.json').write_text('{}', encoding='utf-8')
        return root, folder

    def test_a_restart_before_the_images_purges_them(self):
        for step in ('timing', 'prompts', 'images'):
            root, folder = self.project()
            with mock.patch('artwork.active.select_manifest', return_value=folder/'none.json'), mock.patch('artwork.active.archive_images'):
                server.clear_redone_work(folder, {}, step)
            self.assertFalse((folder/'video.ornaments').exists(), step)
            self.assertFalse((folder/'video.blocks.json').exists(), step)
            self.assertFalse((folder/'video.pictures.json').exists(), step)
            kept = list((root/'.trash').glob('job.small-artwork-*/abc/000.png'))
            self.assertEqual(len(kept), 1, 'recoverable by hand')

    def test_a_restart_after_the_images_leaves_them(self):
        for step in ('review', 'render'):
            root, folder = self.project()
            server.clear_redone_work(folder, {}, step)
            self.assertTrue((folder/'video.ornaments'/'abc'/'000.png').is_file(), step)
            self.assertTrue((folder/'video.blocks.json').is_file(), step)

    def test_a_project_with_none_restarts_as_before(self):
        folder = Path(tempfile.mkdtemp())/'job'
        folder.mkdir()
        server.purge_small_pictures(folder)
        self.assertFalse((folder.parent/'.trash').exists())


if __name__ == '__main__':
    unittest.main()
