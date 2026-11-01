"""A change of scene glides across one stitched strip and hands the wisp over: it leaves from where the old
scene's wisp stops, arrives where the new scene's wisp sets off, never jumps on the way, and only one wisp
is drawn at a time."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cinema import lyrics

FPS = 30


class HandoverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        lines = [(1.+k*3.2, 'the quiet river carries every word home') for k in range(9)]
        data = lyrics(*lines)
        for i, line in enumerate(data):
            line.update(section_id=i//3, section_label=('Verse', 'Chorus', 'Verse')[i//3])
        flows = [dict(start=0, end=3, scene='panning-canvas'), dict(start=3, end=6, scene='tree-canopy'),
                 dict(start=6, end=9, scene='panning-canvas')]
        plan = dict(rules_plan(data, theme_for('autumn')), scene_flows=flows)
        cls.c = Compositor(data, plan, 320, 180, 32., reading_flow='mixed', text_animation='none')
        cls.mix = cls.c.realtime
        cls.mix.plan()
        cls.handovers = [h for h in cls.mix.handovers() if h is not None]

    def test_every_change_of_scene_carries_the_wisp(self):
        self.assertEqual(len(self.handovers), 2)
        for handover in self.handovers:
            self.assertIsNotNone(handover['leaving'])
            self.assertIsNotNone(handover['arriving'])

    def test_wisp_leaves_and_arrives_exactly_where_the_scenes_have_it(self):
        for h in self.handovers:
            before, after = self.mix.engine(h['number']), self.mix.engine(h['number']+1)
            start, end = h['held']
            stop = before.wisp_runs()[h['leaving']][1]
            go = after.wisp_runs()[h['arriving']][0]
            leaving = before.wisp_screen(h['leaving'], min(start, stop), start)
            arriving = after.wisp_screen(h['arriving'], max(end-1e-6, go), end-1e-6)
            self.assertLess(math.dist(self.mix.carried(h, start, start), leaving), 1.)
            self.assertLess(math.dist(self.mix.carried(h, end-1e-6, end-1e-6), arriving), 1.)

    def test_carried_wisp_glides_without_jumping(self):
        for h in self.handovers:
            start, end = h['held']
            track = [self.mix.carried(h, start+k/FPS, start+k/FPS) for k in range(int((end-start)*FPS))]
            steps = [math.dist(a, b) for a, b in zip(track, track[1:])]
            self.assertLess(max(steps), self.c.width*.06)
            jerks = [abs(b-a) for a, b in zip(steps, steps[1:])]
            self.assertLess(max(jerks), self.c.width*.02)

    def test_scenes_hide_their_own_wisp_while_it_is_carried(self):
        stage = self.mix.stage
        for h in self.handovers:
            middle = sum(h['held'])/2
            self.assertEqual(stage.ribbon_heads(middle, stage.camera(middle)[0]), [])
            self.assertIn(h['held'], self.mix.engines['pan'].veils)

    def test_glide_frames_render(self):
        try:
            import moderngl
            moderngl.create_standalone_context(require=330).release()
        except Exception as exc:
            self.skipTest(f'No OpenGL 3.3 context: {exc}')
        from render.stage_3d import close_stage
        try:
            for h in self.handovers:
                for moment in (h['glide'][0], sum(h['glide'])/2, h['glide'][1]-1e-3):
                    self.assertEqual(self.c.frame(moment).size, (320, 180))
        finally:
            close_stage()


if __name__ == '__main__':
    unittest.main()


class SharedPaintingTest(unittest.TestCase):
    """With full-screen or verse artwork every scene paints the same picture, so a change of scene or of painting
    must never move the picture: no slide into itself, no snap of Black hole sun's push-in."""

    @classmethod
    def setUpClass(cls):
        from PIL import Image, ImageDraw
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        lines = [(1.+k*3.2, 'the quiet river carries every word home') for k in range(6)]
        data = lyrics(*lines)
        for i, line in enumerate(data):
            line.update(section_id=i//3, section_label=('Verse', 'Chorus')[i//3])
        flows = [dict(start=0, end=3, scene='panning-canvas'), dict(start=3, end=6, scene='black-hole-sun')]
        plan = dict(rules_plan(data, theme_for('autumn')), scene_flows=flows)
        cls.c = Compositor(data, plan, 320, 180, 21., reading_flow='mixed', text_animation='none',
                           artwork_mode='verse')
        art = []
        for colour in ('#336699', '#996633'):
            image = Image.new('RGBA', (320, 180), colour)
            draw = ImageDraw.Draw(image)
            for x in range(0, 320, 10):
                draw.line((x, 0, x, 180), fill='white', width=2)
            art.append(image)
        cls.c.art, cls.c.art_starts = art, [0., 14.]
        cls.mix = cls.c.realtime
        cls.mix.plan()

    def stripes(self, t):
        """Where the painting's white stripes sit: the column profile of the frame, so lyrics and the wisp drawn
        over a few rows barely change it while any slide or zoom of the painting moves every stripe."""
        import numpy as np
        frame = np.asarray(self.c.frame(t).convert('L')).astype(float)
        profile = np.median(frame, axis=0)
        return profile-profile.mean()

    def offset(self, a, b):
        """The shift, in pixels, that best lines up stripe profile b with a (stripes repeat every 10 px)."""
        import numpy as np
        return min(range(-4, 5), key=lambda d: np.abs(np.roll(b, d)[20:-20]-a[20:-20]).mean())

    def test_change_of_scene_does_not_slide_the_painting(self):
        handover = next(h for h in self.mix.handovers() if h is not None)
        start, end = handover['glide']
        first = self.stripes(start)
        for k in range(1, 7):
            self.assertEqual(self.offset(first, self.stripes(start+k*(end-start)/6)), 0)

    def test_black_hole_sun_push_does_not_snap_when_the_painting_changes(self):
        # 14 s starts the second painting inside the Black hole sun section; the first is still mostly on screen.
        import numpy as np
        before, after = self.stripes(14.-1/30), self.stripes(14.+1/30)
        right = slice(200, 300)
        self.assertLess(np.abs(after[right]-before[right]).mean(), 4.)
