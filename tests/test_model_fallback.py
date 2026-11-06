"""A text model that does not fit on the GPU right now hands the call to the next smaller installed one; a short
rebuilt section still renders with several workers."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from models.ollama import gpu
from render.parallel import worker_count

GB = 2**30
TAGS = dict(models=[dict(name='qwen3.8:27b', size=16*GB), dict(name='gemma3:27b', size=15*GB),
                    dict(name='qwen3:14b', size=8*GB), dict(name='qwen3:8b', size=5*GB),
                    dict(name='qwen3-vl:8b', size=6*GB), dict(name='frozenlab/qwen3-asr:1.7b', size=2*GB)])


def request(endpoint, payload=None, timeout=5):
    return TAGS if endpoint == 'tags' else {}


class FallbackTest(unittest.TestCase):
    def test_smaller_text_models_of_the_same_family_come_first(self):
        self.assertEqual(gpu.smaller_models(request, 'qwen3.8:27b'), ['qwen3:14b', 'qwen3:8b', 'gemma3:27b'])

    def test_the_call_moves_to_the_first_smaller_model_that_fits(self):
        def ensure(req, model, options):
            if model in ('qwen3.8:27b',):
                raise gpu.GPUCapacityError(f'{model} requires an estimated 21.08 GiB free ...; short by 0.34 GiB.')
            return dict(num_gpu=999, main_gpu=0)
        query = dict(model='qwen3.8:27b', options={})
        with mock.patch.object(gpu, 'ensure_loaded', side_effect=ensure):
            self.assertEqual(gpu.load_or_smaller(request, query), dict(num_gpu=999, main_gpu=0))
        self.assertEqual(query['model'], 'qwen3:14b')

    def test_a_model_that_is_not_installed_still_fails(self):
        with mock.patch.object(gpu, 'ensure_loaded', side_effect=gpu.GPUCapacityError('Model not installed. Run: ollama pull x')):
            with self.assertRaises(gpu.GPUCapacityError):
                gpu.load_or_smaller(request, dict(model='x', options={}))


class ExactModelTest(unittest.TestCase):
    """The director's references take the chosen model or none: a smaller stand-in listed nothing."""

    def test_it_waits_for_memory_and_keeps_the_model(self):
        tries = iter([gpu.GPUCapacityError('short by 1 GiB'), dict(num_gpu=999, main_gpu=0)])

        def ensure(req, model, options):
            result = next(tries)
            if isinstance(result, Exception):
                raise result
            return result
        query = dict(model='qwen3.8:27b', options={})
        with mock.patch.object(gpu, 'ensure_loaded', side_effect=ensure), mock.patch.object(gpu.time, 'sleep'):
            self.assertEqual(gpu.wait_for_model(request, query), dict(num_gpu=999, main_gpu=0))
        self.assertEqual(query['model'], 'qwen3.8:27b')

    def test_it_gives_up_at_the_deadline(self):
        with mock.patch.object(gpu, 'ensure_loaded', side_effect=gpu.GPUCapacityError('short by 1 GiB')),                 mock.patch.object(gpu.time, 'sleep'):
            with self.assertRaises(gpu.GPUCapacityError):
                gpu.wait_for_model(request, dict(model='qwen3.8:27b', options={}), wait=0)

    def test_a_model_that_is_not_installed_does_not_wait(self):
        with mock.patch.object(gpu, 'ensure_loaded', side_effect=gpu.GPUCapacityError('Model not installed. Run: ollama pull x')) as load,                 mock.patch.object(gpu.time, 'sleep') as sleep:
            with self.assertRaises(gpu.GPUCapacityError):
                gpu.wait_for_model(request, dict(model='x', options={}))
        self.assertEqual((load.call_count, sleep.call_count), (1, 0))

    def test_the_director_asks_for_its_exact_model(self):
        from direction.entities import find_entities
        segments = [dict(index=0, moment='a'), dict(index=1, moment='b')]
        with mock.patch.object(gpu, 'gpu_chat', return_value=dict(message=dict(content='{"entities": []}'))) as chat:
            find_entities('qwen3.8:27b', segments)
        self.assertTrue(all(call.kwargs.get('exact') for call in chat.call_args_list))


class WorkersTest(unittest.TestCase):
    def test_a_short_section_gets_about_one_worker_per_second(self):
        args = SimpleNamespace(fps=30, width=1920, height=1080, reading_flow='mixed', render_workers=0)
        with mock.patch('render.parallel.hardware', return_value=(16, 64*GB)):
            self.assertEqual(worker_count(args, 30), 1, 'a one-second span renders alone')
            self.assertEqual(worker_count(args, 5*30), 5)
            self.assertGreater(worker_count(args, 60*30), 5)


if __name__ == '__main__':
    unittest.main()
