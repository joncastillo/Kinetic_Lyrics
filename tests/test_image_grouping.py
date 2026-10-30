"""Automatic image grouping uses lyrics after timing and bounds model choices."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class ImageGroupingTest(unittest.TestCase):
    def test_llm_estimates_illustration_span(self):
        from image_grouping import estimate_lines

        data = [dict(text=f'Line {i}', section_label='Chorus' if i >= 6 else 'Verse') for i in range(12)]
        def request(endpoint, payload, timeout):
            self.assertEqual(json.loads(payload['messages'][1]['content'])['line_count'], 12)
            return dict(message=dict(content=json.dumps(dict(lines_per_image=3, reason='Scene changes'))))
        self.assertEqual(estimate_lines(data, 'qwen3:14b', request), 3)

    def test_invalid_model_choice_uses_bounded_fallback(self):
        from image_grouping import estimate_lines

        data = [dict(text='A lyric') for _ in range(90)]
        self.assertEqual(estimate_lines(data, 'qwen3:14b',
                                        lambda *a, **k: dict(message=dict(content='{"lines_per_image": 99}'))), 5)


if __name__ == '__main__':
    unittest.main()
