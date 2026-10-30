"""A particle entrance completes at its vocal cue instead of starting then."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class RealtimeTimingTest(unittest.TestCase):
    def test_hero_particle_is_readable_at_word_start(self):
        from kinetic_director import Compositor, rules_plan
        from kinetic_lyrics import theme_for

        data = [dict(text='THUNDER', words=[dict(text='THUNDER', start=1., end=1.6)])]
        c = Compositor(data, rules_plan(data, theme_for('bright')), 640, 360, 3.,
                       reading_flow='realtime', entrance_effect='glass-assemble', exit_effect='none',
                       kinetic=dict(fade=False, traces=False, geometry=0.))
        engine = c.realtime
        engine.plan()
        amounts = []
        with patch.object(engine, 'paint_particle_word', side_effect=lambda *args: amounts.append(args[4])):
            engine.paint_line(Image.new('RGBA', (642, 362)), 0, .7, 1., (0, 0))
            engine.paint_line(Image.new('RGBA', (642, 362)), 0, 1., 1., (0, 0))
        self.assertEqual(len(amounts), 2)
        self.assertGreater(amounts[0], 0.)
        self.assertEqual(amounts[1], 0.)


if __name__ == '__main__':
    unittest.main()
