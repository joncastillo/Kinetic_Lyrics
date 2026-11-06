"""Beat options: what accompanies the shake, where it runs, and whether confetti flies."""
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from render.chorus_fx import ChorusFX
from render.typography_settings import kinetic_options

DATA = [dict(text='walking down the road', section_id=0, section_label='Verse', words=[dict(text='road', start=1., end=2.)]),
        dict(text='falling in love', section_id=1, section_label='Chorus', words=[dict(text='love', start=4., end=5.)]),
        dict(text='back to the road', section_id=2, section_label='Verse', words=[dict(text='road', start=7., end=8.)])]
KICKS = [[t/2, .9] for t in range(2, 20)]


def changed(effect, t):
    base = Image.new('RGB', (320, 180), '#14203A')
    return effect.paint(base, t) is not base


class BeatOptionsTest(unittest.TestCase):
    def test_chorus_scope_keeps_the_verses_plain(self):
        effect = ChorusFX(DATA, KICKS, .8, lights=True, confetti=False)
        self.assertTrue(changed(effect, 4.2))
        self.assertFalse(changed(effect, 1.5))
        self.assertIsNone(effect.beat_active(1.5))

    def test_entire_song_scope_runs_in_the_verses_too(self):
        effect = ChorusFX(DATA, KICKS, .8, lights=True, confetti=False, whole_song=True)
        self.assertTrue(changed(effect, 1.5))
        self.assertIsNotNone(effect.beat_active(7.5))
        self.assertIsNone(effect.active(7.5), 'the chorus itself is still known')

    def test_dim_or_no_effect_paints_no_lights(self):
        effect = ChorusFX(DATA, KICKS, .8, lights=False, confetti=False)
        self.assertFalse(changed(effect, 4.2))
        self.assertIsNotNone(effect.beat_active(4.2), 'the shake (and dim) still run in the chorus')

    def test_confetti_is_lyric_shaped_and_can_be_turned_off(self):
        self.assertEqual({b[4] for b in ChorusFX(DATA, KICKS, .8, confetti=True).bursts}, {'heart'})
        self.assertEqual(ChorusFX(DATA, KICKS, .8, confetti=False).bursts, [])
        song = ChorusFX(DATA, KICKS, .8, confetti=True, whole_song=True)
        self.assertTrue(any(when < 4 for when, *_ in song.bursts), 'confetti on verse kicks too')

    def test_settings_saved_before_the_beat_options_keep_their_look(self):
        old = kinetic_options(dict(chorus_fx=0., beat_dim=.5, shake_all=True))
        self.assertEqual((old['beat_effect'], old['beat_scope'], old['beat_intensity'], old['beat_confetti']), ('dim', 'song', .5, False))
        with self.assertRaises(ValueError):
            kinetic_options(dict(beat_effect='strobe'))

    def test_blur_softens_the_screen_on_the_kick_and_clears_after(self):
        import numpy as np
        base = Image.new('RGB', (320, 180), '#14203A')
        for x in range(0, 320, 8):
            base.paste((255, 255, 255), (x, 0, x+4, 180))
        effect = ChorusFX(DATA, KICKS, 0., lights=False, confetti=False, blur=1.)
        on_kick = np.asarray(effect.paint(base, 4.02).convert('RGB'), float)
        self.assertLess(on_kick.std(), np.asarray(base, float).std()*.9, 'stripes soften on the kick')
        self.assertIs(ChorusFX(DATA, KICKS, 0., lights=False, confetti=False, blur=1.).paint(base, 1.5), base, 'not outside the chorus')

    def test_confetti_intensity_sets_its_opacity_and_zero_turns_it_off(self):
        self.assertEqual(ChorusFX(DATA, KICKS, .8, confetti=True, confetti_strength=0.).bursts, [])
        faint = ChorusFX(DATA, KICKS, 0., lights=False, confetti=True, confetti_strength=.2)
        strong = ChorusFX(DATA, KICKS, 0., lights=False, confetti=True, confetti_strength=1.)
        alpha = lambda e: max(e.paint(Image.new('RGBA', (320, 180)), 4.3).getchannel('A').get_flattened_data())
        self.assertLess(alpha(faint), alpha(strong))


if __name__ == '__main__':
    unittest.main()
