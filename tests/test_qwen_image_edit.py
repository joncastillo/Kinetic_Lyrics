"""Qwen-Image-Edit-2509: Qwen quality guided by reference images, loaded like Qwen Image."""
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.prompt_fit import budget
from models.image.catalog import model_spec
from models.image.pipeline import QWEN_PIPELINES, inference_options

EDIT = 'Qwen/Qwen-Image-Edit-2509'


class QwenImageEditTest(unittest.TestCase):
    def test_catalog_entry_takes_references_and_uses_4_bit_loading(self):
        spec = model_spec(EDIT)
        self.assertTrue(spec['references'])
        self.assertEqual(spec['quantize'], ['transformer', 'text_encoder'])
        self.assertIn(spec['pipeline'], QWEN_PIPELINES, 'protected 8-bit modulation layers like Qwen Image')
        self.assertEqual(budget(EDIT), (600, 1024))

    def test_references_are_passed_at_most_three_with_qwen_options(self):
        refs = [Image.new('RGB', (8, 8))]*5
        options = inference_options(EDIT, refs)
        self.assertEqual(len(options['image']), 3, 'its trained maximum')
        self.assertEqual(options['true_cfg_scale'], 4.)
        self.assertEqual(options['negative_prompt'], inference_options('Qwen/Qwen-Image-2512', [])['negative_prompt'])

    def test_no_reference_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'needs a reference image'):
            inference_options(EDIT, [])


if __name__ == '__main__':
    unittest.main()
