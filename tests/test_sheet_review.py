"""Check reference pictures: a sheet that fails the vision check is painted again once, never in a loop."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.entities import SHEET_VERSION
from models.vision import sheet_review


class SheetReviewTest(unittest.TestCase):
    def test_place_occupants_are_not_treated_as_character_identity_errors(self):
        reply = dict(other_subjects=[], matches_description=True, matches_style=True, issues=[], summary='Expected patients')
        with mock.patch.object(sheet_review, 'sheet_picture', return_value='image'), \
                mock.patch.object(sheet_review, 'ask_vision', return_value=reply) as ask:
            result = sheet_review.review_sheet('ward.png', dict(name='Hospital ward', kind='place', looks='Patients in beds and sleeping relatives'), 'painterly', 'vl', prompt='Legacy rule: all places must be empty.')
        instruction = ask.call_args.args[0]['messages'][0]['content']
        self.assertIn('overriding generic empty-sheet', instruction)
        self.assertIn('Different occupants may have different sex', instruction)
        self.assertTrue(result['passed'])

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.manifest = self.folder/'illustrations.json'
        self.manifest.write_text('{}', encoding='utf-8')
        sheet = self.folder/'entities'/'the-criminal.png'
        sheet.parent.mkdir()
        sheet.write_bytes(b'sheet')
        self.story = self.folder/'story.json'
        self.story.write_text(json.dumps(dict(segments=[], entities=[
            dict(id='the-criminal', name='the criminal', kind='character', looks='A man in a dirty jacket.',
                 segments=[0, 2], image=str(sheet), sheet_version=SHEET_VERSION),
            dict(id='elara', name='Elara', kind='character', looks='A woman.', segments=[0, 1], cast=True)])),
            encoding='utf-8')

    def entity(self):
        return json.loads(self.story.read_text(encoding='utf-8'))['entities'][0]

    def test_a_failed_sheet_is_painted_again_once(self):
        failed = dict(passed=False, other_subjects=['a woman in a white dress'], issues=[], matches_style=True,
                      matches_description=True, summary='')
        with mock.patch.object(sheet_review, 'review_sheet', return_value=failed) as check:
            self.assertEqual(sheet_review.review_references(self.manifest, 'vl', 'anime', log=lambda m: None), ['the-criminal'])
            self.assertEqual(check.call_count, 1, 'the cast has no sheet yet, so nothing of it is checked')
        entity = self.entity()
        self.assertNotIn('image', entity, 'its picture is dropped, to be painted again')
        self.assertEqual(entity['review_repaints'], 1)
        self.assertFalse(entity['sheet_review']['passed'])
        # painted again and failing again: kept, no second retry
        new = self.folder/'entities'/'the-criminal.2.png'
        new.write_bytes(b'again')
        story = json.loads(self.story.read_text(encoding='utf-8'))
        story['entities'][0].update(image=str(new), sheet_version=SHEET_VERSION)
        self.story.write_text(json.dumps(story), encoding='utf-8')
        with mock.patch.object(sheet_review, 'review_sheet', return_value=failed):
            self.assertEqual(sheet_review.review_references(self.manifest, 'vl', 'anime', log=lambda m: None), [])
        self.assertEqual(self.entity()['image'], str(new))
        saved_reviews = list((self.folder/'entities').glob('*.sheet-review.json'))
        self.assertEqual(len(saved_reviews), 2)
        for record in saved_reviews:
            result = json.loads(record.read_text(encoding='utf-8'))
            self.assertFalse(result['passed'])
            self.assertEqual(result['summary'], failed['summary'])

    def test_a_sheet_that_passes_has_its_body_parts_compared_by_the_text_model(self):
        passed = dict(passed=True, other_subjects=[], issues=[], matches_style=True, matches_description=True, summary='')
        with mock.patch.object(sheet_review, 'review_sheet', return_value=passed), \
                mock.patch.object(sheet_review, 'look_at_sheet', return_value='huge pincers') as look, \
                mock.patch.object(sheet_review, 'wrong_parts', return_value=['drawn as pincers, should be a beak']) as compare:
            retry = sheet_review.review_references(self.manifest, 'vl', 'anime', log=lambda m: None, text_model='big')
        self.assertEqual(retry, ['the-criminal'])
        look.assert_called_once()
        self.assertEqual(compare.call_args.args[1:], ('huge pincers', 'big'))
        self.assertEqual(self.entity()['sheet_review']['issues'], ['drawn as pincers, should be a beak'])

    def test_a_failed_comparison_leaves_the_vision_verdict_standing(self):
        passed = dict(passed=True, other_subjects=[], issues=[], matches_style=True, matches_description=True, summary='')
        logged = []
        with mock.patch.object(sheet_review, 'review_sheet', return_value=passed), \
                mock.patch.object(sheet_review, 'look_at_sheet', return_value='a man'), \
                mock.patch.object(sheet_review, 'wrong_parts', side_effect=ValueError('no room')):
            retry = sheet_review.review_references(self.manifest, 'vl', 'anime', log=logged.append, text_model='big')
        self.assertEqual(retry, [])
        self.assertTrue(any('could not be compared' in line for line in logged))

    def test_a_sheet_already_failed_is_not_looked_at_again(self):
        failed = dict(passed=False, other_subjects=['a cat'], issues=[], matches_style=True, matches_description=True, summary='')
        with mock.patch.object(sheet_review, 'review_sheet', return_value=failed), \
                mock.patch.object(sheet_review, 'look_at_sheet') as look:
            sheet_review.review_references(self.manifest, 'vl', 'anime', log=lambda m: None, text_model='big')
        look.assert_not_called()

    def test_a_place_has_no_body_parts_to_compare(self):
        passed = dict(passed=True, other_subjects=[], issues=[], matches_style=True, matches_description=True, summary='')
        story = json.loads(self.story.read_text(encoding='utf-8'))
        story['entities'][0]['kind'] = 'place'
        self.story.write_text(json.dumps(story), encoding='utf-8')
        with mock.patch.object(sheet_review, 'review_sheet', return_value=passed), \
                mock.patch.object(sheet_review, 'look_at_sheet') as look:
            sheet_review.review_references(self.manifest, 'vl', 'anime', log=lambda m: None, text_model='big')
        look.assert_not_called()

    def test_the_comparison_never_falls_to_a_smaller_model(self):
        reply = dict(message=dict(content='{"wrong_parts": []}'))
        with mock.patch('models.ollama.gpu.gpu_chat', return_value=reply) as chat:
            self.assertEqual(sheet_review.wrong_parts(dict(name='A bug', looks='A beak.'), 'pincers', 'big'), [])
        self.assertTrue(chat.call_args.kwargs['exact'])

    def test_a_picture_is_checked_once_in_its_current_form(self):
        passed = dict(passed=True, other_subjects=[], issues=[], matches_style=True, matches_description=True, summary='')
        with mock.patch.object(sheet_review, 'review_sheet', return_value=passed) as check:
            sheet_review.review_references(self.manifest, 'vl', 'anime', log=lambda m: None)
            sheet_review.review_references(self.manifest, 'vl', 'anime', log=lambda m: None)
        self.assertEqual(check.call_count, 1)


class WorkerTest(unittest.TestCase):
    def test_the_worker_carries_the_image_check_the_batches_call(self):
        import inspect
        from studio import worker
        self.assertTrue(callable(worker.vision_review), 'studio.batches reviews images through worker.vision_review')
        self.assertIn('rules', inspect.signature(worker.vision_review).parameters)


class RequestCheckTest(unittest.TestCase):
    """The checker's model (qwen3-vl) reasons before its JSON and can loop: an answer that is empty because the
    budget went on reasoning, or is cut short, is asked for again, warmer, and only then given up."""

    def payload(self):
        return dict(model='qwen3-vl:8b', options=dict(temperature=.1, num_ctx=8192),
                    messages=[dict(role='user', content='Check this picture.', images=['x'])])

    def test_an_empty_answer_is_asked_again_warmer(self):
        replies = iter([dict(message=dict(content='', thinking='hmm'), done_reason='length'),
                        dict(message=dict(content='{"summary": "fine", "other_subjects": []}'), done_reason='stop')])
        queries = []
        result = sheet_review.request_check(lambda q: queries.append(q) or next(replies), self.payload())
        self.assertEqual(result['summary'], 'fine')
        self.assertEqual([q['options']['num_predict'] for q in queries], [4096, 4096])
        self.assertEqual([q['options']['temperature'] for q in queries], [.1, .5])
        self.assertIn('Answer at once', queries[1]['messages'][0]['content'])
        self.assertNotIn('Answer at once', queries[0]['messages'][0]['content'])

    def test_a_fenced_answer_is_read(self):
        reply = dict(message=dict(content='```json\n{"summary": "ok", "other_subjects": ["a cat"]}\n```'))
        self.assertEqual(sheet_review.request_check(lambda q: reply, self.payload())['other_subjects'], ['a cat'])

    def test_three_unreadable_answers_raise(self):
        reply = dict(message=dict(content='not json at all'), done_reason='stop')
        queries = []
        with self.assertRaises(ValueError) as caught:
            sheet_review.request_check(lambda q: queries.append(q) or reply, self.payload())
        self.assertIn('not JSON', str(caught.exception))
        self.assertEqual(len(queries), 3)


if __name__ == '__main__':
    unittest.main()
