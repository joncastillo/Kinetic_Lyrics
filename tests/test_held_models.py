"""A model a running job holds shows as loaded when no worker reports; a live report says what really has the card."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from models.gpu.telemetry import memory_blocks, unreported_models
from models.readiness import readiness

LTX = 'Lightricks/LTX-2.5-Diffusers'


class HeldModelsTest(unittest.TestCase):

    def test_an_unreported_model_takes_the_unaccounted_memory_as_an_estimate(self):
        gpu = dict(uuid='GPU-1', total_bytes=24, free_bytes=4)
        blocks = memory_blocks([gpu], [], [], [LTX])[0]['blocks']
        self.assertEqual([(b['label'], b['bytes']) for b in blocks],
                         [('LTX-2.5-Diffusers (estimate: includes other apps)', 20), ('Free', 4)])
        self.assertEqual(memory_blocks([gpu], [], [])[0]['blocks'][0]['label'], 'Other apps / unknown')

    def test_a_live_report_beats_what_a_job_says_it_holds(self):
        """While an animating job paints its end frames, the painter has the card, not the video model."""
        held = {LTX: 'video'}
        self.assertEqual(unreported_models(held, [dict(model='Qwen/Qwen-Image-2.1')]), [])
        self.assertEqual(unreported_models(held, []), [LTX], 'no report: the job is all there is to go on')
        with mock.patch('models.readiness.loaded_models', return_value={'Qwen/Qwen-Image-2.1'}):
            state = readiness(dict(video=LTX), local_json=lambda name: {}, folders=[], held=set(held))
        self.assertEqual(state['video']['state'], 'missing', 'not loaded; these test folders hold no weights')
        with mock.patch('models.readiness.loaded_models', return_value=set()):
            state = readiness(dict(video=LTX), local_json=lambda name: {}, folders=[], held=set(held))
        self.assertEqual(state['video']['state'], 'loaded')






if __name__ == '__main__':
    unittest.main()
