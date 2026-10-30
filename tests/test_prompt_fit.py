"""Every constructed prompt is rewritten to the selected image model's text budget."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.prompt_fit import FLUX_WORDS, fit_prompts

FLUX = 'black-forest-labs/FLUX.2-klein-4B'
QWEN = 'Qwen/Qwen-Image-2512'


class PromptFitTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def request(self, endpoint, payload, timeout):
        inputs = json.loads(payload['messages'][1]['content'])
        self.calls.append(inputs)
        return {'message': {'content': json.dumps({'subjects': ['Fitted scene.']*len(inputs)})}}

    def test_every_prompt_is_rewritten_with_its_size_and_budget(self):
        prompts = ['A short scene.', 'word '*500]
        self.assertEqual(fit_prompts(self.request, 'test', QWEN, prompts), ['Fitted scene.']*2)
        self.assertEqual([entry['estimated_words'] for entry in self.calls[0]], [3, 500])
        self.assertEqual(self.calls[0][0]['target_words'], 700)

    def test_art_style_leads_every_prompt_word_for_word(self):
        style = 'Delicate ink linework and soft painterly shading inspired by Alphonse Mucha.'
        fitted = fit_prompts(self.request, 'test', FLUX, ['word '*400], style)
        self.assertTrue(fitted[0].startswith('Art style, the top priority for how everything is rendered: '+style))
        self.assertTrue(fitted[0].endswith('Fitted scene.'))
        self.assertLess(self.calls[0][0]['target_words'], FLUX_WORDS)

    def test_overlong_rewrite_is_condensed_again(self):
        replies = iter(['word '*600, 'Shorter scene.'])
        def request(endpoint, payload, timeout):
            self.calls.append(json.loads(payload['messages'][1]['content']))
            return {'message': {'content': json.dumps({'subjects': [next(replies)]})}}
        self.assertEqual(fit_prompts(request, 'test', FLUX, ['A scene.']), ['Shorter scene.'])
        self.assertEqual(len(self.calls), 2)


if __name__ == '__main__':
    unittest.main()
