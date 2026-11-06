"""The Project panel's settings are saved into the open project as they are edited, and come back on reopening."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio.job_routes import JobRoutes  # noqa: E402


class ProjectSettingsTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.job = SimpleNamespace(folder=self.folder, config=dict(name='Song', type_effect='none', story_prompt='old'))
        self.replies = []
        self.handler = SimpleNamespace(respond=lambda payload, *a: self.replies.append(payload))

    def save(self, args):
        return JobRoutes._job_settings(self.handler, self.job, 'settings', args, {})

    def test_settings_and_story_are_written_into_the_project(self):
        self.save(dict(text_animation='fade', story_prompt='  A detective and her bulldog  ', stage_pictures='off',
                       image_instructions='soft light'))
        saved = json.loads((self.folder/'config.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['text_animation'], 'fade')
        self.assertEqual(saved['story_prompt'], 'A detective and her bulldog')
        self.assertEqual(saved['stage_pictures'], 'off')
        self.assertEqual(saved['image_instructions'], 'soft light')
        self.assertEqual(saved['name'], 'Song')          # what was not sent is kept
        self.assertEqual(self.replies, [dict(ok=True)])

    def test_an_invalid_setting_saves_nothing(self):
        with self.assertRaises(ValueError):
            self.save(dict(text_animation='spin-forever'))
        self.assertFalse((self.folder/'config.json').exists())
        self.assertEqual(self.job.config['story_prompt'], 'old')



if __name__ == '__main__':
    unittest.main()


class RegenerationHidesOldWorkTest(unittest.TestCase):
    def since(self, status, stage):
        from studio.server import Job
        job = SimpleNamespace(config=dict(gallery_since=123.), state=dict(status=status, stage=stage))
        return Job.gallery_since(job)

    def test_old_images_stay_hidden_when_the_regeneration_fails_or_is_cancelled(self):
        self.assertEqual(self.since('running', 'scenes'), 123.)
        self.assertEqual(self.since('failed', 'alignment'), 123.)
        self.assertEqual(self.since('cancelled', 'illustrations'), 123.)

    def test_a_run_that_reached_review_shows_its_artwork(self):
        self.assertEqual(self.since('review', 'review'), 0)
        self.assertEqual(self.since('complete', 'complete'), 0)


class ProjectReferencesTest(unittest.TestCase):
    def test_references_are_added_once_and_listed(self):
        import io
        from PIL import Image
        from studio.job_routes import JobRoutes
        folder = Path(tempfile.mkdtemp())
        picture = io.BytesIO(); Image.new('RGB', (8, 8), (200, 40, 40)).save(picture, 'PNG')
        listed = [p.name for p in (folder/'references').glob('*.png')] if (folder/'references').is_dir() else []
        replies = []
        job = SimpleNamespace(folder=folder, project_inputs=lambda: dict(references=sorted(p.name for p in (folder/'references').glob('*.png'))))
        handler = SimpleNamespace(respond=lambda payload, *a: replies.append(payload))
        files = dict(reference=[('dog.png', picture.getvalue()), ('dog again.png', picture.getvalue())])
        JobRoutes._job_reference_add(handler, job, 'reference-add', {}, files)
        self.assertEqual(listed, [])
        self.assertEqual(len(replies[0]['references']), 1)   # the same picture twice is kept once
        with self.assertRaises(ValueError):
            JobRoutes._job_reference_add(handler, job, 'reference-add', {}, {})
