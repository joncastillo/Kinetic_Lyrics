"""Verify waits its turn like Regenerate, and checks the picture it was asked about."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from direction.entities import reference_role, reference_tags
from models.image.pipeline import gguf_file
from studio import server
from studio.batches import same_picture
from studio.image_operations import ImageOperations


class QueuedVerify(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.job = server.Job(self.folder, dict(name='Song'))
        self.manifest = self.folder/'video.artwork'/'illustrations.json'
        self.manifest.parent.mkdir()
        self.manifest.write_text(json.dumps(dict(prompts=['a', 'b'])), encoding='utf-8')
        self.job.manifest = lambda: self.manifest
        self.selected = self.manifest.parent/'001.png'
        self.candidate = self.folder/'candidates'/'001'/'1'/'000.png'
        self.candidate.parent.mkdir(parents=True)
        for path in (self.selected, self.candidate):
            Image.new('RGB', (4, 4)).save(path)
        self.routes = mock.Mock()

    def ask(self, path, **extra):
        ImageOperations._image_queue_review(self.routes, self.job, dict(
            index=1, model='vision', path=str(path.relative_to(self.folder)), **extra))

    def verifies(self):
        return [q for q in self.job.state['queued_actions'] if q.get('action') == 'verify']

    def test_a_queued_verify_remembers_the_candidate(self):
        self.ask(self.candidate)
        self.assertEqual(self.verifies()[0]['candidate'], str(self.candidate.resolve()))

    def test_the_selected_picture_is_not_pinned(self):
        self.ask(self.selected)
        self.assertNotIn('candidate', self.verifies()[0])

    def test_asking_again_keeps_the_newest_edits(self):
        self.ask(self.candidate, prompt='first')
        self.ask(self.candidate, prompt='second')
        self.assertEqual([q['user_prompt'] for q in self.verifies()], ['second'])

    def test_two_pictures_of_one_illustration_both_wait(self):
        self.ask(self.selected)
        self.ask(self.candidate)
        self.assertEqual(len(self.verifies()), 2)

    def test_its_turn_runs_on_that_candidate(self):
        self.ask(self.candidate)
        self.job.state.update(status='complete', action=None)
        with mock.patch('studio.job_queue.threading.Thread') as thread:
            self.job.start_next()
        command = thread.call_args.kwargs['args'][0]
        self.assertEqual(command[command.index('--candidate')+1], str(self.candidate.resolve()))


class DeletedDuringARepair(unittest.TestCase):
    def test_a_deleted_picture_ends_its_repair_without_a_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(same_picture(Path(folder)/'gone.png', 'abc'))


class ModelFile(unittest.TestCase):
    def test_a_file_in_any_snapshot_is_used_without_asking_the_hub(self):
        with tempfile.TemporaryDirectory() as cache:
            snapshots = Path(cache)/'models--owner--name'/'snapshots'
            (snapshots/'new-commit-without-it').mkdir(parents=True)
            (snapshots/'old-commit').mkdir()
            (snapshots/'old-commit'/'file.gguf').write_bytes(b'weights')
            with mock.patch('huggingface_hub.hf_hub_download') as download:
                path = gguf_file('owner/name', 'file.gguf', cache)
        self.assertEqual(Path(path).parent.name, 'old-commit')
        download.assert_not_called()

    def test_a_missing_file_is_downloaded(self):
        with tempfile.TemporaryDirectory() as cache, \
                mock.patch('huggingface_hub.hf_hub_download', return_value='downloaded.gguf') as download:
            self.assertEqual(gguf_file('owner/name', 'file.gguf', cache), 'downloaded.gguf')
        download.assert_called_once()


class ReferenceOrder(unittest.TestCase):
    """The model works on the last picture it is given, so that one must show the setting."""
    insects = dict(name='Stick Insects', kind='object')
    lab = dict(name='The Lab', kind='place')

    def test_the_illustrations_own_picture_comes_after_the_sheets(self):
        result = reference_tags('@Stick_Insects in @lab.png', ['lab.png'], 1, [self.insects])
        self.assertEqual(result, 'reference image 2 in reference image 3')

    def test_a_place_comes_last_of_all(self):
        result = reference_tags('@Stick_Insects, @lab.png, @The_Lab', ['lab.png'], 1, [self.insects, self.lab])
        self.assertEqual(result, 'reference image 2, reference image 3, reference image 4')

    def test_the_wording_numbers_them_the_same_way(self):
        result = reference_role('A lab.', [self.insects, self.lab], 1, 1, False)
        self.assertIn('Reference image 2 shows Stick Insects', result)
        self.assertIn('Reference image 3: who or what', result)
        self.assertIn('Reference image 4 is one view of The Lab', result)


class ReferenceWording(unittest.TestCase):
    def test_no_reference_is_taken_as_the_picture_to_edit(self):
        result = reference_role('A lab at night.', [], 1, 1, False)
        self.assertTrue(result.startswith('Paint a new full-frame picture'))
        self.assertIn('never keep the backdrop', result)
        self.assertTrue(result.endswith('A lab at night.'))

    def test_a_sheet_of_views_gives_looks_and_not_its_layout(self):
        self.assertIn('never copy its panels, labels', reference_role('A lab.', [], 1, 0, False))

    def test_no_references_leaves_the_prompt_alone(self):
        self.assertEqual(reference_role('A lab.', [], 0, 0, False), 'A lab.')


if __name__ == '__main__':
    unittest.main()
