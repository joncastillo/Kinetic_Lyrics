"""The 3D stage: block grouping, justified layout, top-only effects, directed pictures and a rendered frame."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from lyric_blocks import group_lines, justify, layout_block


def lyrics(*lines):
    """Made-up timings: each (start, text) line sung word by word."""
    data = []
    for start, text in lines:
        words, t = [], start
        for word in text.split():
            words.append(dict(text=word, start=round(t, 3), end=round(t+.3, 3)))
            t += .36
        data.append(dict(text=text, words=words))
    return data


class BlockTest(unittest.TestCase):
    def test_pause_and_breaks_start_new_blocks(self):
        data = lyrics((0, 'one two three'), (1.2, 'four five'), (6, 'six seven'), (7, 'eight nine'))
        self.assertEqual(group_lines(data), [[0, 1], [2, 3]])
        self.assertEqual(group_lines(data, breaks={1}), [[0], [1], [2, 3]])

    def test_rows_are_justified_to_one_width(self):
        sizes = [(300, 100), (520, 100), (180, 80), (410, 100), (260, 100), (600, 120)]
        layout = layout_block(sizes, .4, 4., [3, 3])
        for start, end in layout['rows']:
            last = layout['words'][end-1]
            self.assertAlmostEqual(last['x']+sizes[end-1][0]*last['scale'], 4., places=6)

    def test_line_breaks_are_preferred(self):
        sizes = [(400, 100)]*9
        layout = layout_block(sizes, .3, 4., [3, 3, 3])
        self.assertEqual(layout['rows'], [(0, 3), (3, 6), (6, 9)])

    def test_height_matches_rows(self):
        rows, height = justify([(100, 50), (100, 50)], [(0, 1), (1, 2)], 2.)
        self.assertAlmostEqual(height, 1.+1.2)



class FlowTest(unittest.TestCase):
    def test_band_turns_gently_and_never_brakes(self):
        import math
        import numpy as np
        from flow_path import build_flows, SLOWEST
        from realtime_typography import thread_distance
        times = [0., 1., 1.4, 5., 6., 20., 21.5]
        points = [(0, 0), (300, 40), (320, 60), (360, 300), (700, 260), (900, 100), (1300, 200)]
        lines = [0, 1, 2, 3, 4, 9, 10]
        runs = build_flows(times, points, ['a']*7, amplitude=200., lines=lines)
        self.assertEqual(len(runs), 2)
        for run in runs:
            pts = [np.array(p) for piece in run['pieces'] for p in piece['points']]
            pts = [p for p, q in zip(pts, pts[1:]+[None]) if q is None or np.linalg.norm(q-p) > 1e-9]
            turns = [math.degrees(math.acos(max(-1., min(1., float(np.dot(b-a, c-b)/(np.linalg.norm(b-a)*np.linalg.norm(c-b)))))))
                     for a, b, c in zip(pts, pts[1:], pts[2:])]
            self.assertLess(max(turns), 15.)
            keys = run['keys']
            moments = np.arange(keys[0][0], keys[0][-1]-.5, 1/30)
            speed = np.diff([thread_distance(keys, t) for t in moments])*30
            self.assertGreater(speed.min(), speed.max()*SLOWEST*.7)


class PlacementTest(unittest.TestCase):
    def test_growing_effects_are_top_only(self):
        from particle_catalog import discover_effects
        catalog = discover_effects()['entrance']
        self.assertEqual(catalog['autumn-maple-lettering'].placement, 'top')
        self.assertTrue(all(e.placement in ('any', 'top') for e in catalog.values()))

    def test_unknown_placement_is_rejected(self):
        from particle_catalog import read_effect
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'entrance'/'bad-placement.json'
            path.parent.mkdir()
            path.write_text(json.dumps(dict(name='Bad', family='glass', placement='bottom')), encoding='utf-8')
            with self.assertRaises(ValueError):
                read_effect(path)


class DirectorTest(unittest.TestCase):
    def test_answers_are_checked(self):
        from ornament_director import checked
        words = {'0:1': dict(text='RAIN', line=0, index=1), '0:2': dict(text='MOON', line=0, index=2)}
        self.assertIsNone(checked(dict(word='9:9'), words, ['moon']))
        rain = checked(dict(word='0:1', picture='falling raindrop', source='library', library='none', placement='letter',
                            motion='bob'), words, ['moon'])
        self.assertEqual((rain['source'], rain['placement']), ('generate', 'beside'))
        moon = checked(dict(word='0:2', picture='library', source='library', library='moon', placement='letter',
                            motion='spin'), words, ['moon'])
        self.assertEqual((moon['subject'], moon['library'], moon['placement']), ('', 'moon', 'letter'))


class StageTest(unittest.TestCase):
    def test_renders_a_frame_with_top_row_effect(self):
        try:
            import moderngl
            moderngl.create_standalone_context(require=330).release()
        except Exception as exc:
            self.skipTest(f'No OpenGL 3.3 context: {exc}')
        from kinetic_director import Compositor, rules_plan
        from kinetic_lyrics import theme_for
        from stage_3d import close_stage
        data = lyrics((.2, 'maple leaves turning gold'), (1.8, 'under the silver moon'), (6, 'we were running home'))
        c = Compositor(data, rules_plan(data, theme_for('autumn')), 320, 180, 9., entrance_effect='autumn-maple-lettering',
                       reading_flow='stage', text_animation='none')
        try:
            blocks = c.realtime.plan()
            self.assertEqual([b['lines'] for b in blocks], [[0, 1], [2]])
            for block in blocks:
                self.assertTrue(all((w['effect'] is not None) == (w['row'] == 0) for w in block['words']))
                self.assertEqual(sum(w['color'] == (239, 76, 84) for w in block['words']), 1)
            moon = next(w for w in blocks[0]['words'] if w['bare'] == 'moon')
            self.assertEqual((moon['ornament']['kind'], moon['letter']), ('moon', 1))
            frame = c.frame(3.)
            self.assertEqual(frame.size, (320, 180))
            self.assertGreater(max(frame.convert('L').getextrema()), 120)
            again = c.frame(3.)
            self.assertLessEqual(max(abs(a-b) for a, b in zip(again.tobytes(), frame.tobytes())), 2)
        finally:
            close_stage()



class SceneTest(unittest.TestCase):
    def test_scene_catalog_owns_particles(self):
        from scene_catalog import scene_catalog
        catalog = scene_catalog()
        self.assertEqual(catalog['tree-canopy']['particles'], ['autumn-maple-lettering', 'old-oak-lettering'])
        self.assertEqual({catalog[s]['camera'] for s in ('panning-canvas', 'framed-lines', 'plain-blocks')}, {'pan', 'still', 'blocks'})

    def test_sections_split_and_repeat(self):
        from scene_mix import rule_scenes, segments
        from scene_catalog import scene_catalog
        data = lyrics(*((i*2., f'line {i} goes here') for i in range(12)))
        for i, line in enumerate(data):
            line.update(section_id=0 if i < 10 else 1, section_label='Verse' if i < 10 else 'Chorus')
        parts = segments(data)
        self.assertEqual(parts[-1], (10, 12))
        self.assertTrue(all(3 <= end-start <= 8 for start, end in parts[:-1]))
        chorus = lyrics((0, 'same words'), (2, 'other words'), (4, 'same words'))
        for i, line in enumerate(chorus):
            line.update(section_id=i, section_label='Chorus' if i != 1 else 'Verse')
        scenes = rule_scenes(chorus, segments(chorus), ['panning-canvas', 'tree-canopy'], scene_catalog())
        self.assertEqual(scenes[0], scenes[2])

    def test_mixed_flow_renders_each_scene(self):
        try:
            import moderngl
            moderngl.create_standalone_context(require=330).release()
        except Exception as exc:
            self.skipTest(f'No OpenGL 3.3 context: {exc}')
        from kinetic_director import Compositor, rules_plan
        from kinetic_lyrics import theme_for
        from stage_3d import close_stage
        data = lyrics((.2, 'maple leaves turning gold'), (1.8, 'every word you never told'),
                      (5, 'under the silver moon'), (6.6, 'i hold your love so tight'))
        for i, line in enumerate(data):
            line.update(section_id=i//2, section_label='Verse' if i < 2 else 'Chorus')
        flows = [dict(start=0, end=2, scene='panning-canvas'), dict(start=2, end=4, scene='tree-canopy')]
        plan = dict(rules_plan(data, theme_for('autumn')), scene_flows=flows)
        c = Compositor(data, plan, 320, 180, 10., reading_flow='mixed', text_animation='none')
        try:
            mix = c.realtime
            self.assertEqual(set(mix.engines), {'pan', 'blocks'})
            self.assertEqual([b['lines'] for b in mix.stage.plan()], [[2, 3]])
            top = [w for w in mix.stage.plan()[0]['words'] if w['row'] == 0]
            self.assertTrue(all(w['effect'].id in ('autumn-maple-lettering', 'old-oak-lettering') for w in top if not w['ornament']))
            for moment in (1., mix.switches[0], 8.):
                self.assertEqual(c.frame(moment).size, (320, 180))
        finally:
            close_stage()

    def test_contrast_layout(self):
        try:
            import moderngl
            moderngl.create_standalone_context(require=330).release()
        except Exception as exc:
            self.skipTest(f'No OpenGL 3.3 context: {exc}')
        import numpy as np
        from kinetic_director import Compositor, rules_plan
        from kinetic_lyrics import theme_for
        from stage_3d import BLOCK_WIDTH, close_stage
        data = lyrics((.2, 'maple leaves are turning gold'), (2.4, 'every word you never told'))
        for line in data:
            line.update(section_id=0, section_label='Verse')
        plan = dict(rules_plan(data, theme_for('autumn')), scene_flows=[dict(start=0, end=2, scene='sweet-contrast')])
        c = Compositor(data, plan, 320, 180, 6., reading_flow='mixed', text_animation='none')
        try:
            block = c.realtime.stage.plan()[0]
            words = block['words']
            vertical = [w for w in words if w.get('vertical')]
            self.assertEqual([w['text'] for w in vertical], ['TOLD'])
            self.assertFalse(np.allclose(vertical[0]['frame'], np.identity(4)))
            self.assertAlmostEqual(vertical[0]['width'], block['height'], delta=block['height']*.02+1e-6)
            self.assertEqual(sum(1 for w in words if w.get('sweet')), 1)
            self.assertEqual({w['font'] for w in words} >= {'thin', 'heavy', 'sweet'}, True)
            rows = [w for w in words if not w.get('vertical')]
            self.assertTrue(all(-BLOCK_WIDTH/2-1e-6 <= w['x'] and w['x']+w['width'] <= BLOCK_WIDTH/2+1e-6 for w in rows))
            self.assertNotEqual(block['roll'], 0.)
            self.assertEqual(c.frame(5.).size, (320, 180))
        finally:
            close_stage()


if __name__ == '__main__':
    unittest.main()
