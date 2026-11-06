"""Text models offered to choose: one pulled from Hugging Face is an option, never the automatic pick."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from models.gpu.devices import GIB
from models.ollama.catalog import PROMPT_MODELS, normalize

HAUHAU = 'hf.co/HauhauCS/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-MTP-GGUF:IQ4_XS'


class PromptCatalogTest(unittest.TestCase):
    def test_the_hugging_face_model_is_offered_under_its_pull_name(self):
        entry = next(m for m in PROMPT_MODELS if m['id'] == HAUHAU)
        self.assertEqual(normalize(entry['id']), HAUHAU, 'the quant tag is the Ollama tag; nothing is appended')
        self.assertFalse(entry['recommend'])

    def test_best_never_picks_it_even_when_it_fits(self):
        from models.gpu import presets
        gpu = dict(index=0, name='test', uuid='u', total_bytes=24*GIB, free_bytes=24*GIB)
        with mock.patch.object(presets, 'detect_gpus', return_value=[gpu]):
            catalog = presets.gpu_catalog(installed=[], running=[], review=True)
        self.assertIsNotNone(catalog['recommendation'])
        self.assertEqual(catalog['recommendation']['ai_model'], 'qwen3:14b')
        self.assertIn(HAUHAU, [m['id'] for m in catalog['prompt_choices']], 'still offered in the list')


if __name__ == '__main__':
    unittest.main()
