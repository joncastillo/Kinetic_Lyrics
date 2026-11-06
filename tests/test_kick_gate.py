"""Quiet bleed in the drum stem before the drums come in must not become a beat that shakes the screen."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from audio.rhythm import SAMPLE_RATE, onsets


def kicks(seconds, start, gain, every=.5):
    samples = np.zeros(int(seconds*SAMPLE_RATE))
    t = np.arange(int(.12*SAMPLE_RATE))/SAMPLE_RATE
    thump = np.sin(2*np.pi*60*t)*np.exp(-t*30)
    for at in np.arange(start, seconds-.2, every):
        i = int(at*SAMPLE_RATE)
        samples[i:i+len(thump)] += gain*thump
    return samples


class KickGateTest(unittest.TestCase):
    def test_quiet_bleed_before_the_drums_is_not_a_kick(self):
        quiet = kicks(8, 0, .03)          # about 26 dB below the real kicks
        loud = kicks(8, 0, .6)
        path = Path(tempfile.mkdtemp())/'drums.wav'
        sf.write(path, np.concatenate([quiet, loud]), SAMPLE_RATE)
        found = [t for t, _ in onsets(path, kick_only=True)]
        self.assertTrue(found, 'the real kicks are found')
        self.assertGreaterEqual(min(found), 7.9, 'nothing from the quiet stretch')


if __name__ == '__main__':
    unittest.main()
