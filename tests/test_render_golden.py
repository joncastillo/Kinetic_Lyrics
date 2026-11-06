"""Rendered frames match tests/golden/render.json (see tests/render_golden.py), on the machine that saved them."""
import json
import unittest

import render_golden


class RenderGoldenTest(unittest.TestCase):
    def test_frames_match_the_golden_hashes(self):
        if not render_golden.FIXTURE.is_file():
            self.skipTest('no golden frames saved; run python tests/render_golden.py save')
        saved = json.loads(render_golden.FIXTURE.read_text(encoding='utf-8'))
        if saved['environment'] != render_golden.fingerprint():
            self.skipTest('golden frames were saved with other fonts or library versions: '
                          'run python tests/render_golden.py save on this machine')
        changed = render_golden.changes(saved['frames'], render_golden.collect())
        self.assertEqual(changed, [], 'rendered output changed; if intended, run python tests/render_golden.py save')


if __name__ == '__main__':
    unittest.main()
