"""A prompt is shortened only when the selected image model cannot read all of it."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.prompt_fit import FLUX_WORDS, fit_prompts, trim

FLUX = 'black-forest-labs/FLUX.2-klein-4B'
QWEN = 'Qwen/Qwen-Image-Edit-2511'


class PromptFitTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def request(self, endpoint, payload, timeout):
        inputs = json.loads(payload['messages'][1]['content'])
        self.calls.append(inputs)
        return {'message': {'content': json.dumps({'subjects': ['Fitted scene.']*len(inputs)})}}

    def test_trimming_never_leaves_a_list_number_without_its_item(self):
        text = ('Scene here. THE CAST: 1. a young woman: brown hair; wearing white. 2. an adult bulldog: merle coat. '
                'Made in 2020. Extra words go on.')
        self.assertEqual(trim(text, 16), 'Scene here. THE CAST: 1. a young woman: brown hair; wearing white.')
        self.assertTrue(trim(text, 22).endswith('Made in 2020.'), 'a year is not a list number')

    def test_a_prompt_that_fits_is_left_as_written_and_never_stretched(self):
        prompts = ['A short scene.', 'word '*473]
        self.assertEqual(fit_prompts(self.request, 'test', QWEN, prompts), prompts)
        self.assertEqual(self.calls, [], 'the text model is not asked at all')

    def test_only_a_prompt_over_the_limit_is_condensed(self):
        prompts = ['A short scene.', 'word '*1300]
        self.assertEqual(fit_prompts(self.request, 'test', QWEN, prompts), ['A short scene.', 'Fitted scene.'])
        self.assertEqual([entry['estimated_words'] for call in self.calls for entry in call], [1300])
        self.assertEqual(self.calls[0][0]['target_words'], 1000)

    def test_the_art_style_leads_a_prompt_that_fits_and_is_not_added_twice(self):
        style = 'Soft ink.'
        once = fit_prompts(self.request, 'test', QWEN, ['A scene.'], style)
        self.assertEqual(once, ['Art style, the top priority for how everything is rendered: Soft ink. A scene.'])
        self.assertEqual(fit_prompts(self.request, 'test', QWEN, once, style), once, 'a prompt fitted before')

    def test_a_prompt_that_cannot_be_condensed_is_trimmed_and_the_run_goes_on(self):
        def request(endpoint, payload, timeout):
            self.calls.append(1)
            return {'message': {'content': '{"subjects":["cut off'}, 'done_reason': 'length'}
        fitted = fit_prompts(request, 'test', QWEN, ['A short scene.', 'word '*1300])
        self.assertEqual(fitted[0], 'A short scene.')
        self.assertLessEqual(len(fitted[1].split()), 1000)
        self.assertTrue(self.calls)

    def test_the_text_model_is_never_told_to_add_detail(self):
        fit_prompts(self.request, 'test', QWEN, ['word '*1300])
        seen = []
        def request(endpoint, payload, timeout):
            seen.append(payload['messages'][0]['content'])
            return self.request(endpoint, payload, timeout)
        fit_prompts(request, 'test', QWEN, ['word '*1300])
        self.assertNotIn('extra words', seen[0])
        self.assertIn('at most 1000 words', seen[0])

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
        self.assertEqual(fit_prompts(request, 'test', FLUX, ['word '*400]), ['Shorter scene.'])
        self.assertEqual(len(self.calls), 2)


if __name__ == '__main__':
    unittest.main()
