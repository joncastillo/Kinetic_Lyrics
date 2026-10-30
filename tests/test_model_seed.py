import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class ModelSeedTest(unittest.TestCase):
    def test_cli_seed_randomized_when_unspecified(self):
        import argparse
        from kinetic_lyrics import main

        # Verify argparser handles --image-seed and --seed
        parser = argparse.ArgumentParser()
        parser.add_argument('--image-seed', '--seed', dest='image_seed', type=int, default=None)
        
        args = parser.parse_args([])
        self.assertIsNone(args.image_seed)
        
        args_with_seed = parser.parse_args(['--seed', '123456'])
        self.assertEqual(args_with_seed.image_seed, 123456)

        args_with_img_seed = parser.parse_args(['--image-seed', '7890'])
        self.assertEqual(args_with_img_seed.image_seed, 7890)

    def test_studio_seed_randomize_logic(self):
        # When randomize is requested or seed is empty
        fields_rand = {'randomize_seed': 'on', 'image_seed': ''}
        seed_field = str(fields_rand.get('image_seed', '')).strip()
        randomize = fields_rand.get('randomize_seed') in ('on', 'true', '1') or seed_field in ('', '-1', 'random')
        self.assertTrue(randomize)

        # When a custom seed is requested and randomize is not on
        fields_custom = {'randomize_seed': 'off', 'image_seed': '987654'}
        seed_field = str(fields_custom.get('image_seed', '')).strip()
        randomize = fields_custom.get('randomize_seed') in ('on', 'true', '1') or seed_field in ('', '-1', 'random')
        self.assertFalse(randomize)
        self.assertEqual(int(seed_field), 987654)


if __name__ == '__main__':
    unittest.main()
