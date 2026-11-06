"""A picture can be swapped while the AI video track runs; other image work still waits."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio import image_operations


def job(action):
    return SimpleNamespace(state=dict(action=action, status='complete', stage='render'))


class SwapDuringVideoTest(unittest.TestCase):
    def test_use_image_works_while_clips_are_made(self):
        with mock.patch.object(image_operations.server, 'JOBS', {}):
            for action in ('animate', 'clip-effects', 'scene-scan'):
                image_operations.check_image_change(job(action), 'select', False)
                image_operations.check_image_change(job(action), 'replace', False)

    def test_other_image_work_still_waits_for_the_video(self):
        with mock.patch.object(image_operations.server, 'JOBS', {}):
            with self.assertRaises(ValueError):
                image_operations.check_image_change(job('animate'), 'regenerate', False)
            with self.assertRaises(ValueError):
                image_operations.check_image_change(job('rerender'), 'select', False)


if __name__ == '__main__':
    unittest.main()
