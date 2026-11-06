import inspect
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

from models.image.catalog import model_spec
from models.image.pipeline import LEAN_TEXT_PIPELINES, VAE_TILES, inference_options, quantized_folder


class QwenImage21MemoryTest(unittest.TestCase):
    def test_no_more_than_four_reference_pictures_reach_the_model(self):
        self.assertEqual(model_spec('Qwen/Qwen-Image-2.1')['max_references'], 4)
        self.assertEqual(inference_options('Qwen/Qwen-Image-2.1', list('abcdef'))['image'], list('abcd'))

    def test_the_vae_paints_in_tiles_too_large_to_leave_streaks(self):
        from diffusers.models.autoencoders.autoencoder_kl_qwenimage21 import AutoencoderKLQwenImage21
        tiles = VAE_TILES[model_spec('Qwen/Qwen-Image-2.1')['pipeline']]
        self.assertEqual((tiles['tile_sample_min_width'], tiles['tile_sample_stride_width']), (512, 384))
        self.assertLessEqual(set(tiles), set(inspect.signature(AutoencoderKLQwenImage21.enable_tiling).parameters))

    def test_text_encoder_is_dropped_while_painting(self):
        self.assertIn(model_spec('Qwen/Qwen-Image-2.1')['pipeline'], LEAN_TEXT_PIPELINES)

    def test_saved_weights_have_a_home_when_the_transformer_was_never_downloaded(self):
        # The GGUF transformer stands in for the repository's own, so the snapshot is incomplete on purpose.
        with tempfile.TemporaryDirectory() as cache:
            repo = Path(cache)/'models--Example--Image-Model'
            (repo/'refs').mkdir(parents=True)
            (repo/'refs'/'main').write_text('abc123', encoding='utf-8')
            (repo/'snapshots'/'abc123'/'text_encoder').mkdir(parents=True)
            self.assertEqual(quantized_folder('Example/Image-Model', cache),
                             Path(cache)/'quantized-nf4'/'Example--Image-Model'/'abc123')

    def test_loading_waits_until_the_model_fits(self):
        from types import SimpleNamespace
        import models.image.pipeline as pipeline
        gib = 2**30
        readings = iter([4*gib, 4*gib, 9*gib, 20*gib])
        torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None))
        original = pipeline.gpu_memory.dedicated_memory
        pipeline.gpu_memory.dedicated_memory = lambda torch: (next(readings), 24*gib)
        naps = []
        try:
            free = pipeline.wait_for_gpu_memory(dict(id='m', name='Model'), 16*gib, torch, sleep=naps.append)
        finally:
            pipeline.gpu_memory.dedicated_memory = original
        self.assertEqual(free, 20*gib)
        self.assertEqual(len(naps), 3, 'paused until the card had room')

    def test_a_model_that_fits_starts_at_once(self):
        from types import SimpleNamespace
        import models.image.pipeline as pipeline
        torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None))
        original = pipeline.gpu_memory.dedicated_memory
        pipeline.gpu_memory.dedicated_memory = lambda torch: (20*2**30, 24*2**30)
        try:
            pipeline.wait_for_gpu_memory(dict(id='m'), 16*2**30, torch, sleep=lambda s: self.fail('should not wait'))
        finally:
            pipeline.gpu_memory.dedicated_memory = original

    def test_no_snapshot_means_no_saved_weights(self):
        with tempfile.TemporaryDirectory() as cache:
            self.assertIsNone(quantized_folder('Example/Missing-Model', cache))


if __name__ == '__main__':
    unittest.main()
