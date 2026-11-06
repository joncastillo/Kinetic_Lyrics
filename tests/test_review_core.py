"""Regression tests for the code review fixes in core, pipeline, audio and direction (see CODE_REVIEW.md)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


def line(text, start, step=0.5, length=0.4):
    return dict(
        text=text,
        words=[
            dict(text=w, start=round(start + k * step, 3), end=round(start + k * step + length, 3))
            for k, w in enumerate(text.split())
        ],
    )


class CoreHelpersTest(unittest.TestCase):
    def test_words_keep_accents_and_inner_apostrophes(self):
        from core.text import words

        self.assertEqual(words("Corazón, don't — ¡ámame!"), ['corazón', "don't", 'ámame'])

    def test_json_object_rejects_other_shapes(self):
        from core.text import json_object

        self.assertEqual(json_object('{"a": 1}'), {'a': 1})
        for text in ('[1, 2]', '"text"', '3', 'not json'):
            with self.assertRaises(ValueError):
                json_object(text)

    def test_atomic_write_replaces_whole_file_and_leaves_no_temporary(self):
        from core.files import write_json_atomic

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'state.json'
            target.write_text('old', encoding='utf-8')
            write_json_atomic(target, dict(a='ü'))
            self.assertEqual(json.loads(target.read_text(encoding='utf-8')), dict(a='ü'))
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['state.json'])
            self.assertNotIn(b'\r\n', target.read_bytes())

    def test_concurrent_json_updates_are_never_lost(self):
        import threading
        from core.files import update_json, write_json_atomic

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'illustrations.json'
            write_json_atomic(target, dict(count=0, prompts=['a']))

            def bump():
                for _ in range(50):
                    update_json(target, lambda job: job.update(count=job['count'] + 1))

            workers = [threading.Thread(target=bump) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            saved = json.loads(target.read_text(encoding='utf-8'))
        self.assertEqual(saved, dict(count=100, prompts=['a']))

    def test_flat_pixels_matches_pixel_values(self):
        from PIL import Image
        from core.imaging import flat_pixels

        image = Image.new('RGB', (2, 1), (10, 20, 30))
        self.assertEqual(list(flat_pixels(image)), [(10, 20, 30)] * 2)


class ProgressLayeringTest(unittest.TestCase):
    def test_core_imports_nothing_above_it(self):
        import ast

        for path in (Path(__file__).resolve().parent.parent / 'src' / 'core').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or '']
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                for name in names:
                    self.assertNotIn(
                        name.split('.')[0],
                        ('artwork', 'models', 'render', 'direction', 'studio', 'pipeline', 'effects', 'audio'),
                        f'{path.name} imports {name}',
                    )

    def test_artwork_events_reach_the_gallery_and_failures_stay_quiet(self):
        import artwork  # noqa: F401  (registers its listener)
        from core import progress

        with mock.patch('artwork.gallery.publish_gallery') as publish:
            progress.emit('cutouts', 1, artifact='C:/song/video.artwork/run/003.png')
            publish.side_effect = AttributeError('odd manifest')
            progress.emit('fit', 1, manifest='C:/song/video.artwork/run/illustrations.json')  # must not raise
        self.assertEqual([Path(c.args[0]).name for c in publish.call_args_list], ['illustrations.json'] * 2)


class PipelineOptionsTest(unittest.TestCase):
    def test_each_node_gets_its_own_options_and_realignment_survives_a_resume(self):
        import argparse
        import types
        from pipeline.graph import options

        base = argparse.Namespace(timings=Path('video.timings.json'), plan=Path('video.design.json'), image_seed=1)
        runtime = types.SimpleNamespace(context=types.SimpleNamespace(args=base))
        first = options(dict(image_seed=7), runtime)
        first.illustration_lines = 99  # a node changing its copy
        self.assertEqual(first.image_seed, 7)
        self.assertFalse(hasattr(base, 'illustration_lines'))  # never leaks into the shared options
        self.assertEqual(base.image_seed, 1)
        resumed = options(dict(realigned=True), runtime)  # what a resumed run rebuilds from the checkpoint
        self.assertIsNone(resumed.timings)
        self.assertIsNone(resumed.plan)
        self.assertEqual(base.timings, Path('video.timings.json'))


class TimingRepairTest(unittest.TestCase):
    def test_lines_sharing_the_last_phrase_follow_one_another(self):
        from core.timing_repair import spread_collapsed

        squeezed = lambda text, at: dict(text=text, words=[dict(text=w, start=at, end=at + 0.01) for w in text.split()])
        data = [
            line('one two three four', 0.0),
            squeezed('a b c d', 3.0),
            squeezed('e f g h', 3.0),
            squeezed('i j k l', 3.0),
            line('five six seven eight', 12.0),
        ]
        self.assertEqual(spread_collapsed(data, [(4.0, 10.0)]), [1, 2, 3])
        starts = [data[i]['words'][0]['start'] for i in (1, 2, 3)]
        ends = [data[i]['words'][-1]['end'] for i in (1, 2, 3)]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(len(set(starts)), 3)
        for end, next_start in zip(ends, starts[1:]):
            self.assertLessEqual(end, next_start + 1e-6)  # one line after another, never stacked

    def test_transcript_timing_without_any_match_raises_value_error(self):
        from core.timing_repair import transcript_timing

        with self.assertRaises(ValueError):
            transcript_timing(['hello world'], [dict(word='xyz', start=0, end=1)], min_coverage=0)


class LyricsSanitiserTest(unittest.TestCase):
    def test_real_lyrics_that_look_like_page_furniture_are_kept(self):
        from pipeline.timing import sanitize_lyrics

        text = 'Singing these lyrics\nI see the way you live\nand it hurts\nso bad\n\nchorus line'
        self.assertEqual(sanitize_lyrics(text), text)

    def test_genius_banners_are_still_removed(self):
        from pipeline.timing import sanitize_lyrics

        raw = '3 ContributorsSong Lyrics\nfirst\nSee Coldplay LiveGet tickets as low as $44\nAd text\n\nsecond'
        self.assertEqual(sanitize_lyrics(raw), 'first\nsecond')

    def test_lyrics_file_is_not_rewritten_for_line_endings_only(self):
        from pipeline.timing import lyrics_lines

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lyrics.txt'
            path.write_bytes(b'one  line\r\ntwo\r\n')
            self.assertEqual(lyrics_lines(path), ['one line', 'two'])
            self.assertEqual(path.read_bytes(), b'one  line\r\ntwo\r\n')
            self.assertFalse((Path(folder) / 'lyrics.original.txt').exists())

    def test_cleaned_lyrics_keep_the_original_beside_them(self):
        from pipeline.timing import lyrics_lines

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lyrics.txt'
            path.write_text('first\nYou might also like\nAd\n\nsecond\n', encoding='utf-8')
            self.assertEqual(lyrics_lines(path), ['first', 'second'])
            self.assertIn('You might also like', (Path(folder) / 'lyrics.original.txt').read_text(encoding='utf-8'))


class InstrumentCacheTest(unittest.TestCase):
    def test_a_replaced_song_does_not_reuse_the_old_instruments(self):
        from audio import instruments

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'stems').mkdir()
            (folder / 'stems' / 'other.wav').write_bytes(b'x')
            song = folder / 'audio.mp3'
            song.write_bytes(b'first song')
            with mock.patch.object(
                instruments, 'analyse', return_value=[dict(name='Piano', confidence=0.9)]
            ) as analyse:
                instruments.ensure_instruments(song, folder, 10.0, cache=folder)
                instruments.ensure_instruments(song, folder, 10.0, cache=folder)
                self.assertEqual(analyse.call_count, 1)  # cached for the same song
                song.write_bytes(b'another song')
                instruments.ensure_instruments(song, folder, 10.0, cache=folder)
                self.assertEqual(analyse.call_count, 2)


class DirectionTest(unittest.TestCase):
    def test_every_word_animation_has_a_description(self):
        from direction.animation import MOTION_DESCRIPTIONS
        from render.typography_settings import WORD_ANIMATIONS

        self.assertEqual(set(WORD_ANIMATIONS), set(MOTION_DESCRIPTIONS))

    def test_translation_notes_ignore_prose(self):
        from direction.verse import translation_notes

        self.assertEqual(translation_notes('Keep it simple, which means no people.'), {})
        self.assertEqual(translation_notes('This means nothing to me'), {})
        self.assertEqual(translation_notes('ambon means drizzle'), {'ambon': 'drizzle'})
        self.assertEqual(translation_notes('Note: "ulan" means rain'), {'ulan': 'rain'})

    def test_unquoted_filler_is_not_a_target_word(self):
        from direction.instructions import parse_instructions

        directive, problem = parse_instructions('Give the words a neon glow', {})[0]
        self.assertIsNone(directive)
        self.assertIn('quotes', problem)
        directive, _ = parse_instructions('Make word neong red', {})[0]
        self.assertEqual(directive['words'], {'neong'})

    def test_theme_words_match_whole_words(self):
        from direction.theme import theme_for

        for prompt, name in (
            ('a slow funeral march', 'minimal'),
            ('crusade', 'minimal'),
            ('enjoy the ride', 'minimal'),
            ('sad song', 'solemn'),
            ('heartbroken', 'solemn'),
            ('fun summer', 'playful'),
            ('bright, uplifting', 'playful'),
            ('dance floor', 'electric'),
            ('dreamy love', 'romantic'),
        ):
            self.assertEqual(theme_for(prompt)['name'], name, prompt)

    def test_pre_and_post_chorus_are_not_the_chorus(self):
        from direction.song_structure import section_role

        self.assertEqual(
            [section_role(x) for x in ('Chorus 2', 'Pre-Chorus', 'Post-Chorus', 'Verse 1', 'Song')],
            ['chorus', 'unknown', 'unknown', 'verse', 'unknown'],
        )


    def test_imported_beats_need_times_and_an_action(self):
        from direction.story import validate_import

        good = dict(segments=[dict(beats=[dict(start='1', end=2, action='Waves roll')])])
        self.assertEqual(validate_import(good, 1)['segments'][0]['beats'][0]['start'], 1.0)
        for beat in (dict(end=2, action='x'), dict(start='1" onfocus="x', end=2, action='x'), dict(start=0, end=1)):
            with self.assertRaises(ValueError):
                validate_import(dict(segments=[dict(beats=[beat])]), 1)

    def test_a_changed_prompting_step_drops_the_steps_built_on_it(self):
        from direction.prompt_checkpoint import Checkpoint

        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Checkpoint(folder, ['a'], {})
            for step in ('song', 'meanings', 'scenes', 'fit'):
                checkpoint.save(step, [step])
            checkpoint.save('meanings', ['meanings'])  # unchanged: later steps stay
            self.assertEqual(checkpoint.get('fit'), ['fit'])
            checkpoint.save('meanings', ['new meanings'])
            self.assertIsNone(checkpoint.get('scenes'))
            self.assertIsNone(checkpoint.get('fit'))
            self.assertEqual(checkpoint.get('song'), ['song'])

    def test_duplicate_repair_keeps_the_word_budget_and_survives_a_failed_rewrite(self):
        from direction import scenes

        payload = dict(
            model='m',
            format=dict(type='object', properties=dict(subjects=dict(type='array'))),
            messages=[dict(role='system', content='s'), dict(role='user', content=json.dumps(['a', 'b']))],
        )
        seen = []

        def failing(*args, **kwargs):
            seen.append(kwargs.get('max_words'))
            raise ValueError('no JSON')

        with mock.patch.object(scenes, 'request_subjects', failing):
            result = scenes.repair_duplicate_subjects(None, payload, ['same scene', 'same scene'], max_words=180)
        self.assertEqual(seen, [180])
        self.assertNotEqual(result[0], result[1])  # perspective variation instead of a crash

    def test_scene_requests_keep_non_latin_lyrics_readable(self):
        from direction.scenes import request_subjects

        payload = dict(
            model='m',
            format=dict(type='object', properties=dict(subjects=dict(type='array'))),
            messages=[dict(role='system', content='s'), dict(role='user', content=json.dumps(['ありがとう']))],
        )
        sent = []

        def chat(endpoint, query, timeout):
            sent.append(query['messages'][1]['content'])
            return dict(message=dict(content=json.dumps(dict(subjects=['a scene']))))

        request_subjects(chat, payload)
        self.assertIn('ありがとう', sent[0])

    def test_embedding_uses_the_right_endpoints_and_falls_back_to_keywords(self):
        from direction.effects import Retriever, ollama_embedder

        calls = []

        def local_json(endpoint, payload=None, timeout=5):
            calls.append(endpoint)
            if endpoint == 'tags':
                return dict(models=[dict(name='nomic-embed-text')])
            raise OSError('embedding model failed to load')

        embed = ollama_embedder(local_json)
        self.assertIsNotNone(embed)
        retriever = Retriever(dict(a='glass shatter sparkle', b='soft petals'), embed)
        self.assertEqual(calls, ['tags', 'embed'])
        scores = retriever.scores('glass')
        self.assertGreater(scores['a'], scores['b'])  # BM25 after the embedding failure

    def test_non_object_model_reply_falls_back_in_scene_mix(self):
        from direction.scene_catalog import scene_catalog
        from render.scene_mix import direct_scenes, rule_scenes

        catalog = scene_catalog()
        allowed = list(catalog)[:2]
        data = [line('first line here', 0.0), line('second line here', 4.0)]
        parts = [(0, 1), (1, 2)]
        reply = lambda payload: dict(message=dict(content='["not", "an", "object"]'))  # noqa: E731
        self.assertEqual(
            direct_scenes(data, parts, allowed, catalog, 'm', reply), rule_scenes(data, parts, allowed, catalog)
        )


if __name__ == '__main__':
    unittest.main()
