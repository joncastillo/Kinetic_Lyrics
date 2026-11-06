"""The wisp leads the singing in one colour; a second wisp joins once, the only time colours change."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from PIL import Image, ImageDraw

from direction.typography import rules_plan
from render import realtime
from render.compositor import Compositor

FONT = Path('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf')
TEXTS = ['hello from the hills', 'down to the river', 'we keep walking home', 'under evening light',
         'stars above the water', 'hold me close tonight', 'dancing in the rain', 'singing to the moon',
         'never let me go', 'till the morning comes']


def song(chorus=(5, 6, 7), busy=(22, 32)):
    data = [dict(text=text, words=[dict(text=w, start=2+n*4.+i*.5, end=2.4+n*4.+i*.5) for i, w in enumerate(text.split())],
                 section_label='Chorus' if n in chorus else 'Verse') for n, text in enumerate(TEXTS)]
    rhythm = {'drums': [[busy[0]+k*.25, .8] for k in range(int((busy[1]-busy[0])*4))]}
    compositor = Compositor(data, rules_plan(data, dict(name='calm')), 640, 360, 44.,
                            custom_font=str(FONT) if FONT.is_file() else None, reading_flow='realtime', rhythm=rhythm,
                            kinetic=dict(traces=True), entrance_effect='none', exit_effect='none', particle_intensity=0)
    engine = compositor.realtime
    engine.plan()
    return data, engine


def drawn(engine, t):
    """(colour, strength) of each wisp painted at time t."""
    seen = []
    paint = engine.paint_bands
    engine.paint_bands = lambda draw, fill, points, tail, head, t, base, strength=1.: seen.append((points[-1][3], strength))
    try:
        engine.paint_thread(ImageDraw.Draw(Image.new('RGBA', (4, 4))), Image.new('RGBA', (642, 362)), t, (0, 0))
    finally:
        engine.paint_bands = paint
    return seen


class WispTest(unittest.TestCase):
    def test_head_reaches_words_and_lines_early(self):
        _, engine = song()
        arrivals = engine.thread_path()['keys'][0]
        heroes = sorted((w for line in engine.plan() for w in line['layout'].words if w.role == 'hero'), key=lambda w: w.start)
        line_of = {id(w): line for line in engine.plan() for w in line['layout'].words}
        for number, (word, arrival) in enumerate(zip(heroes, arrivals)):
            self.assertLessEqual(arrival, word.start-realtime.THREAD_LEAD+1e-6)
            if not number or line_of[id(heroes[number-1])] is not line_of[id(word)]:
                self.assertLessEqual(arrival, line_of[id(word)]['start']-realtime.THREAD_LEAD+1e-6, 'ahead of the next line')

    def test_duet_is_the_busy_chorus_and_about_a_fifth_of_the_song(self):
        data, engine = song()
        start, end = engine.duet_window()
        self.assertEqual(start, data[5]['words'][0]['start'])
        sung = data[-1]['words'][-1]['end']-data[0]['words'][0]['start']
        self.assertLess((end-start)/sung, .35)

    def test_one_colour_except_during_the_duet(self):
        data, engine = song()
        start, end = engine.duet_window()
        base, duet, partner = engine.wisp_colors()
        colours, together = set(), 0
        for k in range(20, 440):
            t = k/10
            wisps = drawn(engine, t)
            if not wisps:
                continue
            if start+realtime.DUET_EASE <= t <= end:
                together += 1
                self.assertEqual([c for c, _ in wisps], [duet, partner])
            elif t < start or t > end+realtime.DUET_EASE:
                self.assertEqual(len(wisps), 1, 'a single wisp outside the duet')
                colours.add(wisps[0][0])
        self.assertEqual(colours, {base})
        self.assertGreater(together, 0)

    def test_no_duet_on_a_short_song(self):
        data, engine = song()
        engine.c.data = data[:2]
        engine._duet = False
        self.assertIsNone(engine.duet_window())


if __name__ == '__main__':
    unittest.main()
