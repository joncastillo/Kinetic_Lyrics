"""A fresh regeneration carries inputs over without reusing the old project."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import studio
from image_models import MODEL

FLUX = 'black-forest-labs/FLUX.2-klein-9B'


class RegenerateSessionTest(unittest.TestCase):
    def test_regenerate_uses_new_project_and_all_original_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'audio.wav').write_bytes(b'audio')
            (root/'lyrics.txt').write_text('Sing this line', encoding='utf-8')
            (root/'references').mkdir()
            (root/'references'/'style.png').write_bytes(b'reference')
            (root/'references'/'character.cached.json').write_text('{"description": "cached"}', encoding='utf-8')
            source = SimpleNamespace(folder=root, config=dict(
                audio=str(root/'audio.wav'), width=1280, height=720,
                image_cache='cache', theme='Warm', style_prompt='Painted', illustration_lines=2,
                cinematic=True, auto_verify=False, auto_accept=True, auto_repair=True,
                text_pool=['fade', 'slide']))
            with patch.object(studio, 'start_job', return_value='fresh') as start:
                self.assertEqual(studio.regenerate_new_session(source), 'fresh')
            fields, files = start.call_args.args
            self.assertEqual((fields['project_id'], fields['start_step']), ('', 'beginning'))
            self.assertEqual(fields['lyrics'], 'Sing this line')
            self.assertEqual(files['audio'], [('audio.wav', b'audio')])
            self.assertEqual(files['references'], [('style.png', b'reference')])

    def test_regenerate_uses_selected_image_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'audio.wav').write_bytes(b'audio')
            (root/'lyrics.txt').write_text('Sing this line', encoding='utf-8')
            source = SimpleNamespace(folder=root, config=dict(
                audio=str(root/'audio.wav'), width=1280, height=720,
                image_cache='cache', theme='Warm', style_prompt='Painted', illustration_lines=2,
                cinematic=False, auto_verify=False, auto_accept=True, auto_repair=True,
                image_model=MODEL, steps=50))
            with patch.object(studio, 'start_job', return_value='fresh') as start:
                studio.regenerate_new_session(source, FLUX)
            fields, _ = start.call_args.args
            self.assertEqual((fields['image_model'], fields['steps']), (FLUX, '4'))


if __name__ == '__main__':
    unittest.main()
