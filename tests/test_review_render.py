"""Regression tests for the code review fixes in rendering, effects and the artwork review gate (see CODE_REVIEW.md)."""

import json
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


def solid_sprite(width=60, height=30, alpha=255):
    sprite = Image.new('RGBA', (width, height))
    ImageDraw.Draw(sprite).rectangle((0, 4, width - 1, height - 5), fill=(240, 240, 240, alpha))
    return sprite


class RenderHelpersTest(unittest.TestCase):
    def test_motifs_match_whole_words(self):
        from render.chorus_fx import motif_for

        self.assertEqual(motif_for('start the street at the window'), 'none')
        self.assertEqual(motif_for('stars tonight'), 'star')
        self.assertEqual(motif_for('ang pag-ibig ko'), 'heart')

    def test_hyphenated_wisp_keyword_matches(self):
        from render.wisp_forms import form_for

        self.assertEqual(form_for('pag-ibig'), 'heart')

    def test_subtitles_escape_override_characters(self):
        from render.subtitles import escape, timestamp

        self.assertEqual(escape('a\\b {c}\nd'), 'a＼b ｛c｝ d')
        self.assertEqual(timestamp(3725.456), '1:02:05.46')
        self.assertEqual(timestamp(-1), '0:00:00.00')

    def test_highlight_at_the_left_edge_does_not_crash(self):
        from render.text_effects import highlight_overlay, highlight_word

        sprite = solid_sprite(40, 20)
        self.assertIs(highlight_word(sprite, (255, 0, 0, 255), 0.01), sprite)
        self.assertIsNone(highlight_overlay(sprite.size, (255, 0, 0, 255), 0.01, sprite.getchannel('A')))

    def test_liquid_ripples_blend_instead_of_cutting_holes(self):
        from render.text_effects import paint_word

        layer = Image.new('RGBA', (200, 120), (20, 40, 200, 255))
        paint_word(layer, solid_sprite(), 40, 20, 1.0, 1.0, 1.3, 0, 'liquid')
        self.assertEqual(np.asarray(layer)[..., 3].min(), 255)  # the opaque layer stays opaque everywhere


    def test_kinetic_settings_report_non_numbers_as_value_errors(self):
        from render.typography_settings import effect_intensities, effect_speeds, kinetic_options

        for call in (
            lambda: kinetic_options({'pan_speed': None}),
            lambda: kinetic_options({'beat_intensity': [1]}),
            lambda: effect_speeds({'glass-shatter': None}),
            lambda: effect_intensities({'paper-burn': 'x'}),
            lambda: effect_speeds({'glass-shatter': True}),
        ):
            with self.assertRaises(ValueError):
                call()



    def test_cinema_chunks_appear_for_the_whole_entrance(self):
        from render.cinema import ENTRY
        from direction.typography import rules_plan
        from direction.theme import theme_for
        from render.compositor import Compositor

        data = []
        for start, text in ((1.0, 'black hole sun'), (4.0, 'rain')):
            data.append(
                dict(
                    text=text,
                    words=[
                        dict(text=w, start=start + k * 0.5, end=start + k * 0.5 + 0.4)
                        for k, w in enumerate(text.split())
                    ],
                )
            )
        c = Compositor(
            data,
            rules_plan(data, theme_for('bright')),
            360,
            640,
            8.0,
            reading_flow='cinema',
            entrance_effect='none',
            exit_effect='none',
            kinetic=dict(fade=False),
        )
        chunks = c.realtime.plan()
        self.assertAlmostEqual(chunks[0]['start'], chunks[0]['words'][0]['start'] - ENTRY, places=3)
        for a, b in zip(chunks, chunks[1:]):
            self.assertLessEqual(a['end'], b['start'])  # still one chunk at a time

    def test_child_compositors_do_not_report_instructions(self):
        import contextlib
        import io
        from direction.typography import rules_plan
        from direction.theme import theme_for
        from render.compositor import Compositor

        data = [
            dict(
                text='only this line',
                words=[
                    dict(text=w, start=1 + k * 0.5, end=1.4 + k * 0.5) for k, w in enumerate('only this line'.split())
                ],
            )
        ]

        def printed(word, **options):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                Compositor(
                    data,
                    rules_plan(data, theme_for('bright')),
                    320,
                    180,
                    4.0,
                    entrance_effect='none',
                    exit_effect='none',
                    instructions=f'Make the word "{word}" red',
                    **options,
                )
            return out.getvalue()

        self.assertNotIn('Not sung', printed('elsewhereone', report_instructions=False))
        self.assertIn('Not sung', printed('elsewheretwo'))


class EngineContractTest(unittest.TestCase):
    def test_every_reading_flow_builds_an_engine_that_meets_the_contract(self):
        from direction.typography import rules_plan
        from direction.theme import theme_for
        from render.compositor import Compositor
        from render.engine import LyricEngine, WispEngine

        data = [
            dict(
                text='one two three',
                words=[
                    dict(text=w, start=1 + k * 0.5, end=1.4 + k * 0.5) for k, w in enumerate('one two three'.split())
                ],
            )
        ]
        wisps = {'realtime', 'stage'}
        for flow in ('realtime', 'stage', 'cinema', 'mixed'):
            with self.subTest(flow=flow):
                c = Compositor(
                    data,
                    rules_plan(data, theme_for('bright')),
                    320,
                    180,
                    4.0,
                    reading_flow=flow,
                    entrance_effect='none',
                    exit_effect='none',
                )
                self.assertIsInstance(c.realtime, LyricEngine)
                if flow in wisps:
                    self.assertIsInstance(c.realtime, WispEngine)
        preview = Compositor(data, rules_plan(data, theme_for('bright')), 320, 180, 4.0, reading_flow='preview')
        self.assertIsNone(preview.realtime)
        self.assertIsInstance(preview.preview, LyricEngine)  # the preview flow is drawn by its own engine


class EffectsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from effects.particles.catalog import discover_effects

        cls.curated = discover_effects()

    def test_every_legacy_preset_resolves_in_the_curated_catalogue(self):
        from effects.particles.catalog import LEGACY, resolve_effect

        for name, (entrance, exit_effect) in LEGACY.items():
            self.assertTrue(entrance == 'none' or entrance in self.curated['entrance'], name)
            self.assertIn(exit_effect, self.curated['exit'], name)
            self.assertEqual(resolve_effect(None, 'exit', self.curated, legacy=name), exit_effect)

    def test_outlined_lettering_keeps_its_outline_into_the_exit(self):
        from core.fonts import truetype
        from render.text_effects import paint_word

        font = truetype('ArchivoBlack-Regular.ttf', 60)
        sprite = Image.new('RGBA', (260, 100))
        ImageDraw.Draw(sprite).text((10, 10), 'Bloom', font=font, fill=(240, 200, 120, 255))

        def outline(fade):
            layer = Image.new('RGBA', (800, 500), (255, 255, 255, 255))
            paint_word(
                layer,
                sprite,
                260,
                200,
                1.0,
                fade,
                5.0,
                3,
                'none',
                intensity=1.0,
                entrance_effect='bamboo-lettering',
                exit_effect='glass-shatter',
                effect_catalog=self.curated,
                cache={},
            )
            return int((np.asarray(layer.convert('RGB')).max(-1) < 40).sum())

        held, first_exit_frame = outline(1.0), outline(0.999)
        self.assertGreater(held, 0)
        self.assertGreater(first_exit_frame, held * 0.9)  # no single-frame pop

    def test_choices_and_pools_are_validated(self):
        from effects.particles.catalog import parse_pool, validate_choice

        self.assertEqual(validate_choice('mixed', 'entrance', self.curated), 'mixed')
        with self.assertRaises(ValueError):
            validate_choice('no-such-effect', 'entrance', self.curated)
        with self.assertRaises(ValueError):
            validate_choice(3, 'entrance', self.curated)
        some = sorted(self.curated['exit'])[:2]
        self.assertEqual(parse_pool(json.dumps(some), 'exit', self.curated), some)
        self.assertIsNone(parse_pool(None, 'exit', self.curated))

    def test_base_color_is_checked_when_a_recipe_loads(self):
        import tempfile
        from effects.particles.catalog import EFFECT_ROOT, read_effect

        source = json.loads((EFFECT_ROOT / 'entrance' / 'glass-assemble.json').read_text(encoding='utf-8-sig'))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'entrance' / 'test-effect.json'
            path.parent.mkdir()
            for color in ('#FFF', 12, 'red'):
                path.write_text(json.dumps(dict(source, base_color=color)), encoding='utf-8')
                with self.assertRaises(ValueError):
                    read_effect(path)
            path.write_text(json.dumps(dict(source, base_color='#A0B0C0')), encoding='utf-8')
            self.assertEqual(read_effect(path).base_color, '#A0B0C0')

    def test_every_recipe_survives_a_faint_glyph(self):
        from effects.particles.catalog import EFFECT_ROOT, discover_effects
        from effects.particles.motion import paint_transition

        everything = discover_effects(root=EFFECT_ROOT)  # the whole folder, not only the curated catalogue
        faint = solid_sprite(28, 18, alpha=100)
        for phase in ('entrance', 'exit'):
            for effect in everything[phase].values():
                with self.subTest(effect=effect.id, phase=phase):
                    layer = Image.new('RGBA', (120, 100))
                    paint_transition(layer, faint, 40, 40, phase, 0.5, effect, 3, 1.0, 0.6, {}, paced=False)


class ReviewGateTest(unittest.TestCase):
    def review(self, **changes):
        base = dict(summary='Clean painting', score=80, uncertain=False, issues=[], hand_checks=[], figure_checks=[])
        return dict(base, **changes)

    def test_negated_defects_are_not_counted(self):
        from models.vision.policy import female_facial_hair, reported_defect

        self.assertTrue(reported_defect('The left hand has an extra finger'))
        self.assertFalse(reported_defect('no extra fingers are visible'))
        self.assertFalse(reported_defect('possibly an extra finger, unclear'))
        self.assertFalse(reported_defect('an extra hand hidden behind the chair'))
        self.assertTrue(female_facial_hair('The woman has a visible moustache'))
        self.assertFalse(female_facial_hair('The woman has no beard'))

    def test_rejection_follows_score_and_anatomy(self):
        from models.vision.policy import anatomy_only, rejected

        self.assertFalse(rejected(self.review()))
        self.assertTrue(rejected(self.review(score=20)))
        self.assertTrue(rejected(self.review(validation_pending=True)))
        six = self.review(hand_checks=[dict(hand='left', assessment='six fingers', uncertain=False, visible_fingers=6)])
        self.assertTrue(rejected(six))
        self.assertTrue(anatomy_only(six))
        bad_scene = dict(six, issues=[dict(issue='muddy colours', severity='high', location='sky')])
        self.assertFalse(anatomy_only(bad_scene))

    def test_parse_review_accepts_fenced_json_and_rejects_bad_evidence(self):
        from models.vision.response import parse_review

        reply = lambda content, **extra: dict(message=dict(content=content), **extra)  # noqa: E731
        good = self.review()
        self.assertEqual(parse_review(reply('```json\n' + json.dumps(good) + '\n```'))['score'], 80)
        for broken in (
            dict(good, score=101),
            dict(good, score='80'),
            dict(good, uncertain='no'),
            dict(good, issues=[dict(issue='x', severity='huge', location='y')]),
            dict(good, hand_checks=[dict(hand='l', assessment='a', uncertain=False)]),
        ):
            with self.assertRaises(ValueError):
                parse_review(reply(json.dumps(broken)))
        with self.assertRaisesRegex(ValueError, 'token limit'):
            parse_review(dict(message=dict(content=''), done_reason='length'))

    def test_retry_keeps_the_schema_and_gives_up_after_two_attempts(self):
        from models.vision.response import ReviewUnavailable, request_review

        sent = []

        def request(query):
            sent.append(query['messages'][0]['content'])
            return dict(message=dict(content='not json'))

        payload = dict(model='vl', format=dict(type='object'), messages=[dict(role='user', content='Review this.')])
        with self.assertRaises(ReviewUnavailable):
            request_review(request, payload)
        self.assertEqual(len(sent), 2)
        self.assertIn('JSON schema', sent[1])
        self.assertIn('immediately', sent[1])


if __name__ == '__main__':
    unittest.main()
