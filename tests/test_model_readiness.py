import tempfile
import unittest
from pathlib import Path

from models.readiness import ollama_state, readiness, weights_cached


class ModelReadinessTest(unittest.TestCase):
    def test_ollama_states(self):
        installed, running = {'qwen3:8b'}, {'qwen3:8b'}
        self.assertEqual(ollama_state('', installed, running)['state'], 'off')
        self.assertEqual(ollama_state('qwen3:8b', installed, running)['state'], 'loaded')
        self.assertEqual(ollama_state('qwen3:8b', installed, set())['state'], 'ready')
        self.assertEqual(ollama_state('llama3', installed, running)['state'], 'missing')

    def test_weights_cached_needs_a_finished_snapshot(self):
        with tempfile.TemporaryDirectory() as cache:
            root = Path(cache)/'models--Qwen--Qwen-Image-Edit-2511'
            self.assertFalse(weights_cached('Qwen/Qwen-Image-Edit-2511', folders=[cache]))
            (root/'snapshots'/'abc').mkdir(parents=True)
            self.assertTrue(weights_cached('Qwen/Qwen-Image-Edit-2511', folders=[cache]))
            (root/'blobs').mkdir(); (root/'blobs'/'x.incomplete').write_bytes(b'')
            self.assertFalse(weights_cached('Qwen/Qwen-Image-Edit-2511', folders=[cache]))

    def test_readiness_without_ollama(self):
        def no_ollama(endpoint, payload=None, timeout=5):
            raise OSError('down')
        from unittest import mock
        from models import readiness as module
        with mock.patch.object(module, 'loaded_models', return_value=set()):  # whatever this machine runs now
            result = readiness(dict(text='qwen3:8b', vision='', image='', video='Lightricks/LTX-2.5-Diffusers'), no_ollama, folders=[tempfile.gettempdir()])
        self.assertEqual(result['text']['state'], 'missing')
        self.assertEqual(result['vision']['state'], 'off')
        self.assertEqual(result['image']['state'], 'off')
        self.assertEqual(result['video']['state'], 'missing')

    def test_a_model_a_live_worker_holds_is_loaded(self):
        from unittest import mock
        from models import readiness as module
        def no_ollama(endpoint, payload=None, timeout=5):
            raise OSError('down')
        with mock.patch.object(module, 'loaded_models', return_value={'Lightricks/LTX-2.5-Diffusers'}):
            result = readiness(dict(text='', vision='', image='Qwen/Qwen-Image-Edit-2511', video='Lightricks/LTX-2.5-Diffusers'),
                               no_ollama, folders=[tempfile.gettempdir()])
        self.assertEqual(result['video']['state'], 'loaded')
        self.assertEqual(result['image']['state'], 'missing', 'not held, and not downloaded in this folder')


if __name__ == '__main__':
    unittest.main()
