"""Constructed prompts are condensed only when they overflow the selected image model's text limit."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from prompt_fit import fit_prompts

FLUX = 'black-forest-labs/FLUX.2-klein-4B'
QWEN = 'Qwen/Qwen-Image-2512'


class PromptFitTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def request(self, endpoint, payload, timeout):
        inputs = json.loads(payload['messages'][1]['content'])
        self.calls.append(inputs)
        return {'message': {'content': json.dumps({'subjects': ['Condensed scene.']*len(inputs)})}}

    def test_qwen_keeps_prompts_within_its_longer_limit(self):
        prompts = ['word '*700]
        self.assertEqual(fit_prompts(self.request, 'test', QWEN, prompts), prompts)
        self.assertEqual(self.calls, [])

    def test_flux_condenses_only_long_prompts(self):
        prompts = ['A short scene.', 'word '*500]
        self.assertEqual(fit_prompts(self.request, 'test', FLUX, prompts), ['A short scene.', 'Condensed scene.'])
        self.assertEqual(self.calls, [[{'image_prompt': prompts[1]}]])


if __name__ == '__main__':
    unittest.main()
