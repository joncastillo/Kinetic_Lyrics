import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class DuplicateSubjectsTest(unittest.TestCase):
    def test_repair_duplicate_subjects_resolves_without_error(self):
        from direction.scenes import repair_duplicate_subjects

        # Mock payload
        payload = {
            'messages': [
                {'role': 'system', 'content': 'Generate visual scenes.'},
                {'role': 'user', 'content': '["scene 1", "scene 2", "scene 3"]'}
            ],
            'format': {'properties': {'subjects': {}}}
        }

        # Suppose model returned duplicate subjects
        subjects = [
            'A dark alley with neon signs.',
            'A dark alley with neon signs.',
            'A dark alley with neon signs.'
        ]

        # Mock local_json returning same duplicates even after revision
        def mock_local_json(action, query, timeout=None):
            return {
                'message': {
                    'content': '{"subjects": ["A dark alley with neon signs.", "A dark alley with neon signs."]}'
                }
            }

        # Before, this threw ValueError("Illustration director still repeated scenes...")
        # Now it should resolve by applying perspective variations without throwing!
        result = repair_duplicate_subjects(mock_local_json, payload, subjects, max_rounds=2)

        self.assertEqual(len(result), 3)
        # All 3 should be unique now
        self.assertEqual(len(set(result)), 3)
        self.assertTrue(any('low angle' in s.lower() or 'close-up' in s.lower() or 'perspective' in s.lower() for s in result))


if __name__ == '__main__':
    unittest.main()
