"""A run of the stage's small pictures leaves the illustrations' queue alone: a Replace taken from it was painted with the
small pictures' job (cutout, square, no project references) instead of the illustration's."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from artwork.generation import SMALL_PICTURES, reference_paths
from studio import worker


class QueueOwner(unittest.TestCase):
    def run_in(self, kind, waiting):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            manifest = Path(root)/kind/'abc'/'illustrations.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(dict(prompts=[])), encoding='utf-8')
            (Path(root)/'config.json').write_text('{}', encoding='utf-8')
            stack.enter_context(mock.patch('models.gpu.lifecycle.ModelSession'))
            stack.enter_context(mock.patch('artwork.generation.run_job'))
            stack.enter_context(mock.patch.object(worker, 'paint_all_references'))
            stack.enter_context(mock.patch.object(worker, 'check_references'))
            stack.enter_context(mock.patch.object(worker, 'emit', create=True))
            claim = stack.enter_context(mock.patch('artwork.queue.claim_queue', return_value=[]))
            stack.enter_context(mock.patch('artwork.queue.has_pending', side_effect=waiting))
            worker.generate_and_review(manifest, Path(root))
            return claim.call_count

    def test_small_pictures_leave_a_waiting_request_in_the_queue(self):
        self.assertEqual(self.run_in('video.ornaments', [True]), 0)

    def test_the_illustrations_own_run_still_takes_it(self):
        self.assertEqual(self.run_in('video.artwork', [False]), 1)


class NoReferences(unittest.TestCase):
    """The empty reference list of a small picture's job once counted as out of date, so every project reference went in."""
    def project(self, root):
        (Path(root)/'references').mkdir()
        (Path(root)/'references'/'hero.png').write_bytes(b'picture')

    def test_small_pictures_get_no_project_references(self):
        with tempfile.TemporaryDirectory() as root:
            self.project(root)
            for kind in SMALL_PICTURES:
                manifest = Path(root)/kind/'abc'/'illustrations.json'
                self.assertEqual(reference_paths(manifest, dict(reference_paths=[]), True), [], kind)

    def test_the_illustrations_still_follow_the_project_references(self):
        with tempfile.TemporaryDirectory() as root:
            self.project(root)
            manifest = Path(root)/'video.artwork'/'abc'/'illustrations.json'
            self.assertEqual([Path(p).name for p in reference_paths(manifest, dict(reference_paths=[]), True)], ['hero.png'])


if __name__ == '__main__':
    unittest.main()
