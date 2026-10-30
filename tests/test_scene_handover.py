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
        from kinetic_director import Compositor, rules_plan
        from kinetic_lyrics import theme_for
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
        from stage_3d import close_stage
        try:
            for h in self.handovers:
                for moment in (h['glide'][0], sum(h['glide'])/2, h['glide'][1]-1e-3):
                    self.assertEqual(self.c.frame(moment).size, (320, 180))
        finally:
            close_stage()


if __name__ == '__main__':
    unittest.main()
