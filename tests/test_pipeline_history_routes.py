import json
import unittest

from pipeline.versions import Versions
from test_review_studio import LocalStudio


class PipelineHistoryRoutesTest(LocalStudio, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.job.state['status'] = 'cancelled'
        (self.job.folder / 'config.json').write_text('{"name":"Song"}', encoding='utf-8')
        self.timings = self.job.folder / 'video.timings.json'
        self.timings.write_text('[]', encoding='utf-8')

    def select(self, value):
        return self.request('/api/jobs/test-song/pipeline-version', json.dumps(value).encode())

    def test_initialize_and_select_are_routed_and_restore_saved_outputs(self):
        status, data = self.select(dict(initialize=True))
        self.assertEqual(status, 200, data)
        first = data['history']['active']
        self.timings.write_text('[{"text":"changed"}]', encoding='utf-8')
        Versions(self.job.folder).capture('timing', [self.timings])
        status, data = self.select(dict(sequence=first))
        self.assertEqual(status, 200, data)
        self.assertEqual(self.timings.read_text(), '[]')
        self.assertEqual(self.job.state['status'], 'cancelled')
        self.assertIn('selected', self.job.state['message'])

    def test_active_and_stopping_workers_cannot_switch_versions(self):
        for status, runs, queued in [
            ('running', 0, []),
            ('review', 0, []),
            ('cancelled', 1, []),
            ('cancelled', 0, [{'action': 'patch'}]),
        ]:
            with self.subTest(status=status, runs=runs, queued=queued):
                self.job.state.update(status=status, queued_actions=queued)
                self.job.runs = runs
                code, data = self.select(dict(initialize=True))
                self.assertEqual(code, 400, data)
                self.assertFalse((self.job.folder / 'pipeline.json').exists())

    def test_invalid_versions_and_missing_csrf_token_are_rejected(self):
        for value in (dict(node='../escape', version=1), dict(node='timing', version=True), dict(sequence='1')):
            code, _ = self.select(value)
            self.assertEqual(code, 400)
        self.assertEqual(self.request('/api/jobs/test-song/pipeline-version', token=False)[0], 403)
