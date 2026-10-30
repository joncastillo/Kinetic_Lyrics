"""The 3D stage: block grouping, justified layout, top-only effects, directed pictures and a rendered frame."""
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from render.lyric_blocks import group_lines, justify, layout_block


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
    def test_background_crossing_starts_with_valid_seam(self):
        from PIL import Image
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        data = lyrics((.2, 'silk'), (5.2, 'wind'))
        c = Compositor(data, rules_plan(data, theme_for('autumn')), 100, 60, 8.,
                       artwork_mode='verse', reading_flow='preview', text_animation='none')
        c.art = [Image.new('RGBA', (100, 60), 'red'), Image.new('RGBA', (100, 60), 'blue')]
        c.art_starts = [0., 4.]
        self.assertEqual(c.background(1, 4., veil=False).getpixel((50, 30)), (255, 0, 0))
        self.assertEqual(c.background(1, 7.7, veil=False).getpixel((50, 30)), (0, 0, 255))

    def test_wisp_partner_visits_once_in_the_second_half_on_stem_events(self):
        from types import SimpleNamespace
        from render.stage_3d import Stage3D
        stage = Stage3D.__new__(Stage3D)
        notes = [float(n) for n in range(1, 41)]
        stage._music = dict(times=notes[::2], strengths=[.9]*20, tune_times=notes, tune=[.2, .8]*20)
        stage.ribbon = [dict(keys=(notes, [], []))]
        stage.c = SimpleNamespace(duration=40.)
        windows = stage.duet_windows()
        self.assertEqual(len(windows), 1)
        self.assertTrue(all(start in notes and end in notes and start >= 20. for start, end in windows))
        start, end = windows[0]
        self.assertEqual(stage.partner_presence(start-.01), 0.)
        self.assertGreater(stage.partner_presence((start+end)/2), .9)
        self.assertEqual(stage.partner_presence(end+.01), 0.)

    def test_pseudo_3d_backdrop_uses_one_flat_composite_per_frame(self):
        from types import SimpleNamespace
        from PIL import Image
        from render.stage_3d import Stage3D
        stage = Stage3D.__new__(Stage3D)
        calls = []
        def background(index, t, veil=False):
            calls.append(t)
            return Image.new('RGB', (16, 9), 'red' if t < 5 else 'blue')
        stage.c = SimpleNamespace(background=background, art_starts=[0., 5.],
                                  art=[Image.new('RGB', (16, 9), 'red'), Image.new('RGB', (16, 9), 'blue')],
                                  art_crossing=lambda index: 2.)
        stage.world = ['first.png', 'second.png']

        class GL:
            def __init__(self):
                self.images = []
                self.quads = []

            def transient(self, image):
                self.images.append(image)
                return image

            def texture(self, key, image):
                self.images.append(image())
                return key

            def quad(self, *args):
                self.quads.append(args)

        gl = GL()
        stage.backdrop(gl, 4.99)
        stage.backdrop(gl, 5.)
        self.assertEqual(calls, [5.])
        self.assertEqual(len(gl.images), 2)
        self.assertEqual(len(gl.quads), 2)

    def test_directed_picture_joins_its_word_even_on_effect_row(self):
        from render.stage_3d import Stage3D
        word = dict(line=0, index=0, text='MOON', bare='moon', role='hero', effect=object())
        picture = dict(line=0, word=0, image='painted.png', source='generate', placement='letter', motion='pulse')
        Stage3D.choose_motion(None, [word], random.Random(1), picture)
        self.assertEqual(word['letter'], 1)
        self.assertEqual(word['ornament']['image'], 'painted.png')
        self.assertIsNone(word['effect'])

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
        from render.flow_path import build_flows, SLOWEST
        from render.realtime import thread_distance
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
        from effects.particles.catalog import discover_effects
        catalog = discover_effects()['entrance']
        self.assertEqual(catalog['autumn-maple-lettering'].placement, 'top')
        self.assertTrue(all(e.placement in ('any', 'top') for e in catalog.values()))

    def test_unknown_placement_is_rejected(self):
        from effects.particles.catalog import read_effect
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'entrance'/'bad-placement.json'
            path.parent.mkdir()
            path.write_text(json.dumps(dict(name='Bad', family='glass', placement='bottom')), encoding='utf-8')
            with self.assertRaises(ValueError):
                read_effect(path)


class DirectorTest(unittest.TestCase):
    def test_ai_exit_choice_is_applied(self):
        from direction.effects import ensure_line_effects
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        data = lyrics((.2, 'quiet rain'), (2., 'distant light'))
        plan = rules_plan(data, theme_for('autumn'))
        c = Compositor(data, plan, 320, 180, 4., reading_flow='preview', text_animation='none', exit_effect='ai')
        pool = ['dust-disintegrate', 'petals-scatter']
        def request(payload):
            return {'message': {'content': json.dumps({line['line']: line['candidates'][0]['id']
                                                        for line in json.loads(payload['messages'][1]['content'])['lines']})}}
        with tempfile.TemporaryDirectory() as folder:
            directed = ensure_line_effects(data, plan, c, {'exit_pool': pool, 'ai_model': 'test'}, folder,
                                           request=request, phase='exit')
        self.assertEqual(len(directed['line_exits']), 2)
        rebuilt = Compositor(data, directed, 320, 180, 4., reading_flow='preview', text_animation='none', exit_effect='ai')
        self.assertEqual([pair[1] for pair in rebuilt.effect_pairs], directed['line_exits'])

    def test_answers_are_checked(self):
        from direction.ornaments import checked
        words = {'0:1': dict(text='RAIN', line=0, index=1), '0:2': dict(text='MOON', line=0, index=2)}
        self.assertIsNone(checked(dict(word='9:9'), words, ['moon']))
        rain = checked(dict(word='0:1', picture='falling raindrop', source='library', library='none', placement='letter',
                            motion='bob'), words, ['moon'])
        self.assertEqual((rain['source'], rain['placement']), ('generate', 'beside'))
        self.assertIsNone(checked(dict(word='0:2', picture='library', source='library', library='moon',
                                       placement='letter', motion='spin'), words, ['moon']))
        moon = checked(dict(word='0:2', picture='crescent moon', source='library', library='moon', placement='letter',
                            motion='spin'), words, ['moon'])
        self.assertEqual((moon['subject'], moon['library'], moon['placement']), ('crescent moon', 'moon', 'letter'))

    def test_pictures_are_translated_and_never_hang_on_function_words(self):
        from direction.ornaments import checked, content_word
        words = {'15:3': dict(text='ambon', bare='ambon', line=15, index=3), '16:3': dict(text='balon', bare='balon', line=16, index=3)}
        lyrics = {'salita', "ko'y", 'tulad', 'ng', 'ambon', 'na', 'umalingawngaw', 'sa', 'balon'}
        answer = dict(word='15:3', picture='ambon', source='generate', library='none', placement='beside', motion='bob')
        drizzle = checked(answer, words, [], {'ambon': 'drizzle'}, lyrics)
        self.assertEqual(drizzle['subject'], 'drizzle')  # the user's word meaning, not the untranslated word
        untranslated = dict(answer, word='16:3', picture='the balon')
        self.assertIsNone(checked(untranslated, words, [], {}, lyrics))  # an untranslated subject is never painted
        well = checked(dict(untranslated, picture='old stone well'), words, [], {}, lyrics)
        self.assertEqual(well['subject'], 'old stone well')
        self.assertEqual([w for w in ('sa', "ko'y", 'ng', 'at', 'narito', 'mata', 'balon', 'liwanag') if content_word(w)],
                         ['mata', 'balon', 'liwanag'])


class StageTest(unittest.TestCase):
    def test_textured_accent_avoids_purple_in_artwork(self):
        import colorsys
        from types import SimpleNamespace
        from PIL import Image, ImageDraw
        from render.stage_3d import Stage3D

        art = Image.new('RGB', (100, 100), (116, 78, 151))
        ImageDraw.Draw(art).rectangle((0, 0, 24, 99), fill=(168, 116, 63))
        stage = Stage3D.__new__(Stage3D)
        stage.c = SimpleNamespace(artwork_mode='verse', art=[art], art_starts=[0.])
        stage.art_tones = {}
        color = stage.artwork_accent(1., (255, 185, 170))
        hue = colorsys.rgb_to_hsv(*(component/255 for component in color))[0]
        self.assertLess(hue, .2)

    def test_renders_a_frame_with_top_row_effect(self):
        try:
            import moderngl
            moderngl.create_standalone_context(require=330).release()
        except Exception as exc:
            self.skipTest(f'No OpenGL 3.3 context: {exc}')
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        from render.stage_3d import close_stage
        data = lyrics((.2, 'maple leaves turning gold'), (1.8, 'under the silver moon'), (6, 'we were running home'))
        c = Compositor(data, rules_plan(data, theme_for('autumn')), 320, 180, 9., entrance_effect='autumn-maple-lettering',
                       reading_flow='stage', text_animation='none')
        try:
            blocks = c.realtime.plan()
            self.assertEqual([b['lines'] for b in blocks], [[0, 1], [2]])
            for block in blocks:
                self.assertTrue(all((w['effect'] is not None) == (w['row'] == 0) for w in block['words']))
                self.assertEqual(sum(w['color'] == block['palette'][3] for w in block['words']), 1)
            from render.stage_3d import MOVE
            transition = blocks[1]['move']
            before = c.realtime.camera(transition-1e-5)
            at = c.realtime.camera(transition)
            after = c.realtime.camera(transition+MOVE)
            middle = c.realtime.camera(transition+MOVE/2)
            import numpy as np
            self.assertLess(np.linalg.norm(before[0]-at[0]), .01)
            before_distance = np.linalg.norm(before[0]-before[1])
            middle_distance = np.linalg.norm(middle[0]-middle[1])
            after_distance = np.linalg.norm(after[0]-after[1])
            self.assertGreaterEqual(middle_distance, min(before_distance, after_distance)-.05)
            self.assertLessEqual(middle_distance, max(before_distance, after_distance)+.05)
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
        from direction.scene_catalog import scene_catalog
        catalog = scene_catalog()
        self.assertIn('autumn-maple-lettering', catalog['tree-canopy']['particles'])
        self.assertIn('bamboo-lettering', catalog['tree-canopy']['particles'])
        self.assertTrue({'autumn-maple-lettering', 'old-oak-lettering', 'bamboo-lettering', 'succulent-garden-lettering',
                         'meadow-grass-lettering'} <= set(catalog['tree-canopy']['particles']))
        self.assertGreater(len(catalog['crystal-and-coral']['particles']), 4)  # scenes offer a wide choice to filter
        self.assertIn('mucha-silk-lettering', catalog['lace-and-paper']['particles'])
        self.assertIn('catholic-cross-lettering', catalog['crystal-and-coral']['particles'])
        self.assertNotIn('framed-lines', catalog)
        self.assertEqual(catalog['full-screen-type']['camera'], 'pan')
        self.assertEqual({catalog[s]['camera'] for s in ('panning-canvas', 'plain-blocks')}, {'pan', 'blocks'})

    def test_scene_particles_honour_the_ticked_entrances(self):
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        data = lyrics((.2, 'lace and silk'), (5., 'paper cranes'))
        plan = dict(rules_plan(data, theme_for('autumn')), scene_flows=[dict(start=0, end=2, scene='lace-and-paper')])
        pool = ['pearl-lace-lettering', 'glass-prism']
        c = Compositor(data, plan, 320, 180, 9., reading_flow='mixed', text_animation='none', entrance_pool=pool)
        self.assertEqual(set(c.realtime.stage.owned_effects(0)), set(pool))
        unticked = Compositor(data, plan, 320, 180, 9., reading_flow='mixed', text_animation='none', entrance_pool=[])
        self.assertEqual(unticked.realtime.stage.owned_effects(0), [])

    def test_tree_canopy_restricts_entrances_to_trees(self):
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        data = lyrics((.2, 'maple leaves'), (5., 'old branches'))
        plan = dict(rules_plan(data, theme_for('autumn')), scene_flows=[dict(start=0, end=2, scene='tree-canopy')])
        pool = ['glass-prism', 'old-oak-lettering', 'bamboo-lettering']
        c = Compositor(data, plan, 320, 180, 9., reading_flow='mixed', text_animation='none', entrance_pool=pool)
        self.assertEqual(set(c.realtime.stage.owned_effects(0)), {'old-oak-lettering', 'bamboo-lettering'})

    def test_scene_effects_render_an_animated_sample(self):
        from io import BytesIO
        from PIL import Image
        from effects.particles.preview import SCENE_SIZE, _render_scene
        sample = Image.open(BytesIO(_render_scene('black-hole-sun')))
        self.assertEqual(sample.size, SCENE_SIZE)
        self.assertGreater(getattr(sample, 'n_frames', 1), 20)

    def test_full_screen_scene_enlarges_words(self):
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        data = lyrics((.2, 'vast sky'), (5., 'vast sky'))
        plan = dict(rules_plan(data, theme_for('autumn')), scene_flows=[
            dict(start=0, end=1, scene='full-screen-type'),
            dict(start=1, end=2, scene='panning-canvas')])
        c = Compositor(data, plan, 320, 180, 9., reading_flow='mixed', text_animation='none')
        lines = c.realtime.engines['pan'].plan()
        self.assertGreater(lines[0]['layout'].words[0].size, lines[1]['layout'].words[0].size*1.5)

    def test_sections_split_and_repeat(self):
        from render.scene_mix import rule_scenes, segments
        from direction.scene_catalog import scene_catalog
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
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        from direction.scene_catalog import scene_catalog
        from render.stage_3d import close_stage
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
            self.assertTrue(all(w['effect'].id in scene_catalog()['tree-canopy']['particles'] for w in top if not w['ornament']))
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
        from render.compositor import Compositor
        from direction.typography import rules_plan
        from direction.theme import theme_for
        from render.stage_3d import BLOCK_WIDTH, close_stage
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
