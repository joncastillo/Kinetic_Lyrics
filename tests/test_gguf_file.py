"""The GGUF transformer loads from the disk first: a renamed Hub repository must not stop a file already here."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from models import downloads
from models.image.pipeline import gguf_file


class GgufFileTest(unittest.TestCase):
    def test_a_file_on_disk_is_used_without_asking_the_hub(self):
        with tempfile.TemporaryDirectory() as cache:
            snapshots = Path(cache)/'models--owner--name'/'snapshots'
            (snapshots/'old-commit').mkdir(parents=True)
            (snapshots/'new-commit').mkdir()   # the commit `main` moved to, without the file
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

    def test_the_studio_download_check_does_not_ask_the_hub_for_a_file_on_disk(self):
        spec = dict(gguf=('owner/name', 'file.gguf'), disk_gb=1)
        with tempfile.TemporaryDirectory() as cache:
            snapshot = Path(cache)/'models--owner--name'/'snapshots'/'old-commit'
            snapshot.mkdir(parents=True)
            (snapshot/'file.gguf').write_bytes(b'weights')
            task = dict(id='t', model='owner/model', cache=cache, _cancel=threading.Event())
            with mock.patch('models.image.catalog.model_spec', return_value=spec), \
                    mock.patch('huggingface_hub.snapshot_download', return_value='snapshot'), \
                    mock.patch('huggingface_hub.hf_hub_download') as download:
                downloads._pull_image(task)
        download.assert_not_called()
        self.assertEqual(task['status'], 'complete')


if __name__ == '__main__':
    unittest.main()
