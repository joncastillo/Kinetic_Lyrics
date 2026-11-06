"""Images queued behind a reference repaint wait for it: a running job must not paint them again with the old picture."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from artwork.queue import queue_path
from studio import server


class HeldRegenerationsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.job = server.Job(Path(self.folder.name), dict(name='Song'))
        self.job.state['queued_actions'].append(dict(action='reference', index=0, entity='the-lab', name='The Lab'))

    def file(self):
        path = queue_path(self.folder.name)
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

    def test_they_reach_the_queue_file_only_once_the_reference_is_painted(self):
        self.job.queue_generation(3, 'regenerate', '', 'auto', reason='reference', after='the-lab')
        self.job.queue_generation(5, 'regenerate', '', 'auto')   # an ordinary request goes at once
        self.assertEqual([i['index'] for i in self.file()], [5], 'the held one is not in the file a running job claims')
        self.assertEqual([q.get('after') for q in self.job.state['queued_actions']], [None, 'the-lab', None])
        self.job.release_held()
        self.assertEqual([i['index'] for i in self.file()], [5], 'still held: the repaint is queued')
        self.job.state['queued_actions'] = [q for q in self.job.state['queued_actions'] if q.get('action') != 'reference']
        self.job.release_held()
        self.assertEqual(sorted(i['index'] for i in self.file()), [3, 5])
        self.assertNotIn('after', self.job.state['queued_actions'][0])


if __name__ == '__main__':
    unittest.main()
