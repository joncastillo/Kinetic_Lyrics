"""Artwork redone after switching to FLUX.2 uses FLUX.2, fits its 512-token prompt, and is conditioned on the
style reference wherever the picture is not an isolated cutout object."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

FLUX = 'black-forest-labs/FLUX.2-klein-9B'
QWEN = 'Qwen/Qwen-Image-2512'


class SelectedModelTest(unittest.TestCase):
    def test_studio_choice_wins_over_the_jobs_model(self):
        from models.image.catalog import selected_model
        self.assertEqual(selected_model(dict(model=QWEN), dict(image_model=FLUX)), FLUX)
        self.assertEqual(selected_model(dict(model=QWEN), {}), QWEN)

    def test_candidate_is_generated_with_the_selected_model_and_its_steps(self):
        import studio.worker as studio_worker
        job = dict(model=QWEN, steps=50, seed=1, prompts=['a', 'b'], layouts=[{}, {}], groups=['x', 'y'])
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root/'config.json').write_text(json.dumps(dict(image_model=FLUX)), encoding='utf-8')
            written = {}
            def run_job(manifest, cache):
                written.update(json.loads(Path(manifest).read_text(encoding='utf-8')))
            with mock.patch('artwork.generation.run_job', run_job):
                studio_worker.generate_candidate(root, job, 1, root, '')
        self.assertEqual((written['model'], written['steps']), (FLUX, 4))
        self.assertEqual(written['prompts'], ['b'])


class BudgetTest(unittest.TestCase):
    def test_flux_budget_leaves_room_below_512_tokens(self):
        from direction.prompt_fit import budget, estimate, FLUX_TOKENS
        from direction.illustration_prompts import REFERENCE_ROLE
        words, tokens = budget(FLUX)
        self.assertEqual(tokens, FLUX_TOKENS)
        retry = ('Replace any written sign or neon lettering with unlettered geometric light tubes. All signs, screens, '
                 'walls and panels are completely blank. No alphabetic marks, captions, numerals or logos anywhere.')
        self.assertLess(estimate(REFERENCE_ROLE+'word '*words+retry)[1], 490)

    def test_qwen_length_prompt_is_over_the_flux_budget(self):
        from direction.prompt_fit import over_budget
        self.assertTrue(over_budget('word '*618, FLUX))
        self.assertFalse(over_budget('word '*618, QWEN))

    def test_reused_long_prompts_are_refitted_once(self):
        import artwork.queue as generation_queue
        job = dict(model=QWEN, prompts=['word '*618, 'short scene'], style_prompt='ink')
        images = [dict(index=0), dict(index=1)]
        with mock.patch('direction.prompt_fit.refit', return_value=['fitted']) as refit:
            generation_queue.refit_prompts(job, dict(image_model=FLUX), images)
            generation_queue.refit_prompts(job, dict(image_model=FLUX), images)
        refit.assert_called_once()
        self.assertEqual(refit.call_args.args[1], FLUX)
        self.assertEqual(images[0]['prompt'], 'fitted')
        self.assertNotIn('prompt', images[1])


class ReferenceTest(unittest.TestCase):
    def test_reference_used_for_verse_and_fullscreen_scenes_without_people(self):
        from direction.illustration_prompts import uses_reference
        landscape = 'A stone bridge over a misty river at dawn'
        self.assertTrue(uses_reference('verse', landscape))
        self.assertTrue(uses_reference('fullscreen', landscape))
        self.assertFalse(uses_reference('cutout', landscape))
        self.assertTrue(uses_reference('cutout', 'A woman dancing in the rain'))

    def test_reference_role_leads_once(self):
        from direction.illustration_prompts import REFERENCE_ROLE, with_reference_role
        prompt = with_reference_role('A river scene.')
        self.assertTrue(prompt.startswith(REFERENCE_ROLE))
        self.assertEqual(with_reference_role(prompt), prompt)

    def test_flux_reads_the_whole_fitted_prompt(self):
        from models.image.pipeline import inference_options
        options = inference_options(FLUX, ['image'])
        self.assertEqual(options['image'], ['image'])
        self.assertEqual(options['max_sequence_length'], 512)


if __name__ == '__main__':
    unittest.main()
