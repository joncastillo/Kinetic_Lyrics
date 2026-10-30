"""All repair rounds' prompts are written in one prompting session."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.prompt_repair import revise_repair_prompts


class Worker:
    def emit(self, *args, **kwargs):
        pass


class PromptRepairTest(unittest.TestCase):
    def test_each_rejected_image_gets_one_prompt_per_round(self):
        requests = []

        def chat(endpoint, payload, timeout=900):
            inputs = json.loads(payload['messages'][1]['content'])
            requests.append(inputs)
            return {'message': {'content': json.dumps({'subjects': [
                f"{entry.get('lyrics', 'fit')} variant {entry.get('variant', '')}".strip() for entry in inputs]})}}

        job = dict(model='Qwen/Qwen-Image-2512', groups=['first line', 'second line'], prompts=['old one', 'old two'],
                   layouts=[{}, {}], song_gist='A song about isolation.')
        items = [dict(index=0, review=dict(score=20)), dict(index=1, review=dict(score=30))]
        with patch('models.ollama.gpu.gpu_chat', chat), patch('models.ollama.gpu.unload_model'), \
                patch('models.ollama.catalog.resolve_prompt_model', return_value='test'), \
                patch('direction.prompt_fit.fit_prompts', side_effect=lambda request, model, image_model, prompts, style='': prompts):
            planned = revise_repair_prompts(Worker(), job, {}, items, variants=2)
        self.assertEqual([plan['prompts'][0] for plan in planned[0]], ['first line variant 1', 'first line variant 2'])
        self.assertEqual([plan['prompts'][1] for plan in planned[1]], ['second line variant 1', 'second line variant 2'])
        self.assertEqual(sum(len(batch) for batch in requests), 4)


if __name__ == '__main__':
    unittest.main()
