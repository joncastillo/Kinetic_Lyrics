"""Recurring entities: listed from the storyline, painted once, and passed to the segments that show them."""
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.entities import NEW_PICTURE, choose_references, clean, find_entities, reference_role, segment_entities, sheet_path, sheet_prompt, shows_subject

STORY = [dict(index=i, moment='m', characters=c, environment='park', beats=[dict(action='walks')])
         for i, c in enumerate(['Mia and her dog Rex', 'Rex alone', 'Mia', 'no one'])]


class EntityTest(unittest.TestCase):
    def test_only_entities_in_two_or_more_valid_segments_are_kept_characters_first(self):
        entities = clean([dict(name='the old oak', kind='place', looks='A huge oak.', segments=[0, 3]),
                          dict(name='Mia', kind='character', looks='A girl of ten.', segments=[0, 2, 2]),
                          dict(name='Bird', kind='character', looks='A crow.', segments=[1]),
                          dict(name='Kite', kind='object', looks='Red kite.', segments=[1, 9]),
                          dict(name='Mia', kind='character', looks='Twin.', segments=[1, 3]),
                          dict(name='Fog', kind='weather', looks='Grey.', segments=[0, 1])], 4)
        self.assertEqual([(e['id'], e['segments']) for e in entities],
                         [('mia', [0, 2]), ('mia-2', [1, 3]), ('the-old-oak', [0, 3])])

    def test_the_director_lists_them_from_the_storyline(self):
        seen = []
        def request(payload):
            seen.append(payload)
            return dict(message=dict(content=json.dumps(dict(entities=[
                dict(name='Rex', kind='character', looks='A brown bulldog.', segments=[0, 1], cast=False)]))))
        entities = find_entities('model', STORY, request=request, character='a woman with red hair')
        self.assertEqual([e['name'] for e in entities], ['Rex'])
        self.assertIn('a woman with red hair', seen[0]['messages'][0]['content'])
        self.assertIn('Rex alone', seen[0]['messages'][1]['content'])

    def test_a_lasting_change_is_listed_as_a_second_form_with_its_own_segments(self):
        seen = []
        def request(payload):
            seen.append(payload)
            return dict(message=dict(content=json.dumps(dict(entities=[]))))
        find_entities('model', STORY, request=request)
        told = seen[0]['messages'][0]['content']
        self.assertIn('you must list it once per form', told)
        self.assertIn('starts with exactly what changed', told, 'looks are cut at LOOKS_WORDS')
        self.assertIn('"the vase (broken)"', told, 'objects and places have forms too')
        self.assertIn('which body part and which side', told)
        self.assertIn('even a form shown in a single segment', told)
        self.assertIn('base', seen[0]['format']['properties']['entities']['items']['required'])
        story = dict(entities=clean([dict(name='Mia', kind='character', looks='A woman.', segments=[0, 1], cast=True),
                                     dict(name='Mia (transformed)', kind='character', looks='Insect legs from her ribs.',
                                          segments=[2, 3], cast=False, from_cast=True)], 4))
        self.assertEqual([(e['id'], e['cast'], e['from_cast'], e['base']) for e in story['entities']],
                         [('mia', True, False, ''), ('mia-transformed', False, True, 'mia')])
        self.assertEqual([e['name'] for e in segment_entities(story, 1, painted=False)], ['Mia'])
        self.assertEqual([e['name'] for e in segment_entities(story, 2, painted=False)], ['Mia (transformed)'])

    def test_a_missed_form_is_asked_for_again_and_takes_the_segments_after_the_change(self):
        from direction.entities import add_forms
        asked = []
        answers = iter([dict(entities=[dict(name='The farmer', kind='character', looks='A farmer in a raincoat.', segments=[0, 1, 2],
                                            cast=False, from_cast=False, base='')]),
                        dict(forms=[dict(base='The farmer', name='The farmer (injured)', segment=1,
                                         looks='A red swollen bite welt in his left palm. A farmer in a raincoat.'),
                                    dict(base='Nobody', name='Nobody (hurt)', segment=0, looks='x'),
                                    dict(base='The farmer', name='The farmer (older)', segment=2, looks='Grey.')])])   # nothing after 2
        def request(payload):
            asked.append(payload)
            return dict(message=dict(content=json.dumps(next(answers))))
        entities = find_entities('model', STORY, request=request)
        self.assertEqual(len(asked), 2)
        self.assertIn('lasting changes of appearance that were missed', asked[1]['messages'][0]['content'])
        self.assertIn('"The farmer"', asked[1]['messages'][1]['content'], 'the list so far goes with the storyline')
        self.assertEqual([(e['id'], e['segments'], e['base']) for e in entities],
                         [('the-farmer', [0, 1], ''), ('the-farmer-injured', [2], 'the-farmer')])
        self.assertTrue(entities[1]['looks'].startswith('A red swollen bite welt in his left palm.'))
        # a form listed already for those segments is not added twice
        listed = clean([dict(name='Mia', kind='character', looks='A woman.', segments=[0, 1]),
                        dict(name='Mia (hurt)', kind='character', looks='A cut.', segments=[2, 3], base='Mia')], 4)
        again = add_forms(listed, [dict(base='Mia', name='Mia (injured)', looks='A cut.', segment=1)], 4)
        self.assertEqual([e['id'] for e in again], ['mia', 'mia-hurt'])
        self.assertEqual(add_forms(listed, [], 4), listed)

    def test_the_story_tags_who_each_uploaded_picture_shows(self):
        from direction.entities import lead_tags, link_leads, photo_index, sheet_inputs
        story = 'Dr. Viktoria Valderrama @photo2, 38, is a scientist. Arnel (@arnel.png) is a med tech. Her lab is cold.'
        self.assertEqual(lead_tags(story), {'Dr. Viktoria Valderrama': 'photo2', 'Arnel': 'arnel.png'})
        self.assertEqual(lead_tags('A sad story with no tags.'), {})
        entities = clean([dict(name='Viktoria', kind='character', looks='A woman.', segments=[0, 1]),
                          dict(name='Viktoria (mutated)', kind='character', looks='Chitin.', segments=[2, 3], base='Viktoria'),
                          dict(name='Arnel', kind='character', looks='A man.', segments=[0, 2]),
                          dict(name='Lola', kind='character', looks='An old woman.', segments=[1, 2], cast=True)], 4)
        by_id = {e['id']: e for e in link_leads(entities, story)}
        self.assertEqual((by_id['viktoria']['cast'], by_id['viktoria']['photo']), (True, 'photo2'))
        self.assertEqual(by_id['arnel']['photo'], 'arnel.png', 'two leads, each with their own picture')
        self.assertFalse(by_id['lola']['cast'], "the story's tags decide alone")
        self.assertTrue(by_id['viktoria-mutated']['from_cast'] and not by_id['viktoria-mutated']['cast'])
        self.assertNotIn('photo', by_id['viktoria-mutated'])
        untouched = [dict(id='lola', name='Lola', kind='character', cast=True)]
        self.assertTrue(link_leads(untouched, 'No tags here.')[0]['cast'], 'no tags: the director chooses as before')
        files = ['a.png', 'arnel.png', 'c.png']
        self.assertEqual([photo_index(t, files) for t in ('photo2', 'arnel.png', 'arnel', 'photo9', 'nobody')], [1, 1, 1, None, None])
        pictures, role = sheet_inputs(by_id['viktoria'], dict(entities=entities), [('a', 'person'), ('b', 'person')], False, True, lead_picture='b')
        self.assertEqual(pictures, ['b'], 'the tagged picture, not the first person, and without likeness mode')
        self.assertTrue(role.startswith('Picture 1 shows Viktoria, this character'))

    def test_the_director_reads_the_writers_story_and_fills_what_the_list_left_out(self):
        asked = []
        answers = iter([dict(entities=[dict(name='Mia', kind='character', looks='A woman in a lab coat over a t-shirt.', segments=[0, 1],
                                            cast=False, from_cast=False, base=''),
                                       dict(name='Rex', kind='character', looks='A man in a blue dress shirt and jeans.', segments=[2, 3],
                                            cast=False, from_cast=False, base='')]),
                        dict(forms=[], missing=[dict(name='the flooded lab', kind='place', looks='Dark water on the floor.', segments=[0, 2]),
                                                dict(name='Mia', kind='character', looks='A duplicate.', segments=[0, 1])],
                             outfits=[dict(name='Mia', outfit='dark trousers and flat shoes'), dict(name='Rex', outfit='shorts')])])
        def request(payload):
            asked.append(payload)
            return dict(message=dict(content=json.dumps(next(answers))))
        entities = find_entities('model', STORY, request=request, story='The lab flooded weeks ago and was never drained.')
        self.assertIn('never drained', asked[0]['messages'][1]['content'])
        self.assertIn('never drained', asked[1]['messages'][1]['content'])
        self.assertIn('is the authority', asked[0]['messages'][0]['content'])
        by_name = {e['name']: e for e in entities}
        self.assertEqual(sorted(by_name), ['Mia', 'Rex', 'the flooded lab'], 'a reference left out is added, a listed one is not doubled')
        self.assertTrue(by_name['Mia']['looks'].endswith('Full outfit: dark trousers and flat shoes.'))
        self.assertNotIn('Full outfit', by_name['Rex']['looks'], 'a complete outfit is left alone')

    def listed(self):
        from direction.entities import clean
        return clean([dict(name='Arnel', kind='character', looks='A man.', segments=[0, 1, 2]),
                      dict(name='Arnel (paralysed)', kind='character', looks='A man, paralysed.', segments=[3, 4, 5], base='Arnel')], 6)

    def form(self, name, base, at):
        return dict(base=base, name=name, looks=f'{name}, as written.', segment=at)

    def by_name(self, entities):
        return {e['name']: e for e in entities}

    def test_a_change_on_top_of_a_form_splits_that_form(self):
        from direction.entities import add_forms
        found = self.by_name(add_forms(self.listed(), [self.form('Arnel (pierced)', 'Arnel (paralysed)', 4)], 6))
        self.assertEqual(found['Arnel (paralysed)']['segments'], [3, 4])
        self.assertEqual(found['Arnel (pierced)']['segments'], [5])
        self.assertEqual(found['Arnel (pierced)']['base'], 'arnel-paralysed')

    def test_a_change_named_on_the_first_form_goes_on_the_form_then_showing(self):
        from direction.entities import add_forms
        found = self.by_name(add_forms(self.listed(), [self.form('Arnel (pierced)', 'Arnel', 4)], 6))
        self.assertEqual(found['Arnel (pierced)']['base'], 'arnel-paralysed')
        self.assertEqual(found['Arnel']['segments'], [0, 1, 2], 'its segments were not the ones split')

    def test_one_answer_can_build_a_chain(self):
        from direction.entities import add_forms
        found = self.by_name(add_forms(self.listed(), [self.form('Arnel (cut)', 'Arnel (paralysed)', 3),
                                                       self.form('Arnel (pierced)', 'Arnel (cut)', 4)], 6))
        self.assertEqual([found[n]['segments'] for n in ('Arnel (paralysed)', 'Arnel (cut)', 'Arnel (pierced)')], [[3], [4], [5]])
        self.assertEqual(found['Arnel (pierced)']['base'], 'arnel-cut')

    def test_a_change_in_the_last_segment_takes_that_segment(self):
        from direction.entities import add_forms
        found = self.by_name(add_forms(self.listed(), [self.form('Arnel (pierced)', 'Arnel (paralysed)', 5)], 6))
        self.assertEqual(found['Arnel (paralysed)']['segments'], [3, 4])
        self.assertEqual(found['Arnel (pierced)']['segments'], [5])

    def test_a_change_after_the_thing_is_last_shown_adds_nothing(self):
        from direction.entities import add_forms
        found = add_forms(self.listed(), [self.form('Arnel (pierced)', 'Arnel (paralysed)', 8)], 9)
        self.assertEqual(sorted(e['name'] for e in found), ['Arnel', 'Arnel (paralysed)'])

    def test_a_hand_painted_finish_is_not_about_people(self):
        from direction.entities import without_people
        self.assertIn('Hand-painted finish', without_people('Modern illustration, Hand-painted finish.'))
        self.assertEqual(without_people('Slender hands. Clean ink.'), 'Clean ink.')

    def test_a_standing_figure_on_a_plain_backdrop_is_cut_to_the_head(self):
        from PIL import Image, ImageDraw
        from direction.entities import lead_view
        figure = Image.new('RGB', (600, 800), 'white')
        ImageDraw.Draw(figure).rectangle((270, 40, 330, 760), fill='black')
        cut = lead_view(figure)
        self.assertLess(cut.height, 300)
        self.assertEqual(lead_view(Image.new('RGB', (600, 800), 'white')).size, (600, 800), 'nothing on it')
        portrait = Image.new('RGB', (600, 800), 'white')
        ImageDraw.Draw(portrait).rectangle((100, 100, 500, 700), fill='black')
        self.assertEqual(lead_view(portrait).size, (600, 800), 'not a standing figure')
        photo = Image.effect_noise((600, 800), 90).convert('RGB')
        self.assertEqual(lead_view(photo).size, (600, 800), 'no plain backdrop')

    def test_scenes_at_a_place_take_its_views_in_turn(self):
        from direction.entities import place_panel
        place = dict(kind='place', segments=[7, 2, 3, 5, 9])
        self.assertEqual([place_panel(place, s) for s in (2, 3, 5, 7, 9)], [0, 1, 2, 0, 1], 'never the close-up, the fourth panel')
        self.assertEqual(place_panel(place, 4), 0, 'a segment it is not listed in')

    def test_a_form_beginning_where_a_listed_one_begins_is_the_same_change(self):
        from direction.entities import add_forms
        found = self.by_name(add_forms(self.listed(), [self.form('Arnel (wounded)', 'Arnel', 2)], 6))
        self.assertNotIn('Arnel (wounded)', found)
        self.assertEqual(found['Arnel (paralysed)']['segments'], [3, 4, 5])

    def test_a_name_already_listed_is_not_added_again(self):
        from direction.entities import add_forms
        found = add_forms(self.listed(), [self.form('Arnel (paralysed)', 'Arnel', 4)], 6)
        self.assertEqual(sorted(e['name'] for e in found), ['Arnel', 'Arnel (paralysed)'])

    def test_a_form_of_a_form_of_the_lead_is_still_the_lead(self):
        from direction.entities import add_forms, clean
        entities = clean([dict(name='Mia', kind='character', looks='A woman.', segments=[0, 1], cast=True),
                          dict(name='Mia (hurt)', kind='character', looks='A woman, hurt.', segments=[2, 3], base='Mia')], 4)
        found = self.by_name(add_forms(entities, [self.form('Mia (scarred)', 'Mia (hurt)', 2)], 4))
        self.assertTrue(found['Mia (scarred)']['from_cast'])

    def test_a_form_is_tied_to_the_one_it_comes_from_and_kept_when_the_thing_spans_two_segments(self):
        from direction.entities import base_of, from_lead
        entities = clean([
            dict(name='Arnel', kind='character', looks='A farmer.', segments=[0]),
            dict(name='Arnel (injured)', kind='character', looks='His left eye is gone.', segments=[3], base='Arnel'),
            dict(name='the vase', kind='object', looks='Blue glass.', segments=[1, 2]),
            dict(name='Vase, broken', kind='object', looks='In shards.', segments=[3], base='the vase'),   # named by the base field
            dict(name='the lab (burned)', kind='place', looks='Charred walls.', segments=[4]),               # the lab itself is not listed
            dict(name='the lab (flooded)', kind='place', looks='Knee-deep water.', segments=[5]),
            dict(name='Viktoria', kind='character', looks='A woman.', segments=[2, 3], cast=True),
            dict(name='Viktoria (mutated)', kind='character', looks='Insect legs.', segments=[4])], 6)
        by_id = {e['id']: e for e in entities}
        self.assertEqual(by_id['arnel-injured']['base'], 'arnel')
        self.assertIn('arnel', by_id, 'the farmer shows once whole and once injured: two segments, so both forms are kept')
        self.assertEqual(by_id['vase-broken']['base'], 'the-vase')
        self.assertNotIn('the-lab-burned', by_id, 'a form of nothing listed, shown once')
        self.assertEqual((by_id['viktoria-mutated']['base'], by_id['viktoria-mutated']['from_cast']), ('viktoria', True),
                         'a form of the cast is the lead in another form')
        story = dict(entities=entities)
        self.assertEqual(base_of(story, by_id['arnel-injured'])['name'], 'Arnel')
        self.assertIsNone(base_of(story, by_id['arnel']))
        self.assertTrue(from_lead(by_id['viktoria-mutated'], story))
        self.assertFalse(from_lead(by_id['arnel-injured'], story))
        # the editor: a form of a listed reference, never of itself
        from direction.entities import edited
        self.assertEqual(edited(dict(name='Arnel (injured)', kind='character', looks='x', images=[4], base='arnel'), 6)['base'], 'arnel')
        with self.assertRaises(ValueError):
            edited(dict(id='arnel', name='Arnel', kind='character', looks='x', images=[1], base='arnel'), 6)

    def test_a_form_is_painted_after_and_from_the_sheet_of_the_one_it_comes_from(self):
        from PIL import Image
        from direction.entities import (BASE_ROLE, SHEET_VERSION, base_sheet, painting_order, sheet_inputs, sheet_size)
        with tempfile.TemporaryDirectory() as folder:
            sheet = Path(folder)/'arnel.png'
            Image.new('RGB', (64, 36), 'green').save(sheet)
            arnel = dict(id='arnel', name='Arnel', kind='character', looks='A farmer.', segments=[0])
            injured = dict(id='arnel-injured', name='Arnel (injured)', kind='character', looks='His left eye is gone.', segments=[3], base='arnel')
            story = dict(entities=[arnel, injured])
            # the base has no picture yet: it is pulled in and painted first
            self.assertEqual([e['id'] for e in painting_order([injured], story)], ['arnel', 'arnel-injured'])
            self.assertEqual([e['id'] for e in painting_order([injured, arnel], story)], ['arnel', 'arnel-injured'])
            self.assertIsNone(base_sheet(story, injured))
            arnel.update(image=str(sheet), sheet_version=SHEET_VERSION)
            self.assertEqual([e['id'] for e in painting_order([injured], story)], ['arnel-injured'], 'a painted base is not painted again')
            picture = base_sheet(story, injured)
            self.assertEqual(picture.size, (64, 36))
            pictures, role = sheet_inputs(injured, story, [('photo', 'person')], True, True, base_picture=picture)
            self.assertEqual(pictures, [picture], "the base's sheet, not the lead's photo")
            self.assertTrue(role.startswith('Picture 1 is the reference sheet of Arnel, who Arnel (injured) is'))
            self.assertIn('change only what the description says changed', role)
            self.assertEqual(sheet_inputs(injured, story, [], False, True, base_picture=picture)[0], [picture], 'with no project pictures too')
            self.assertEqual(sheet_inputs(injured, story, [], False, False, base_picture=picture), ([], ''), 'a model that takes no pictures')
            for kind in ('object', 'place'):
                self.assertIn(kind if kind == 'place' else 'object', sheet_inputs(dict(injured, kind=kind), story, [], False, True, base_picture=picture)[1])
            self.assertEqual(set(BASE_ROLE), {'character', 'object', 'place'})
            # the form's own prompt insists on the exact marks
            prompt = sheet_prompt(injured, 'ink')
            self.assertIn('show every lasting change exactly as the description states it', prompt)
            # seen on the injured farmer: the wound on his right hand in the front view, his left in profile, none at 3/4
            self.assertIn("Left and right are its own, not the viewer's", prompt)
            # and then: the wound on the back of his hanging hand, not the palm, and a close-up with the wound on his head
            self.assertIn('turning or raising that part towards the viewer', prompt)
            self.assertIn('The last picture on the sheet is not a portrait', prompt)
            self.assertNotIn('exactly as the description states', sheet_prompt(arnel, 'ink'))
            # the cast gets a sheet of its own, from the lead's photo
            cast = dict(id='viktoria', name='Viktoria', kind='character', looks='A woman.', segments=[0, 1], cast=True)
            pictures, role = sheet_inputs(cast, dict(entities=[cast]), [('photo', 'person')], True, True)
            self.assertEqual(pictures, ['photo'])
            self.assertTrue(role.startswith('Picture 1 shows Viktoria, this character, and sets the art style'))
            self.assertIn('exactly its linework, shading, palette and finish', role, 'the picture is the style too')
            self.assertEqual(sheet_inputs(cast, dict(entities=[cast]), [('photo', 'person')], False, True), ([], ''),
                             'in style mode the photo is not the lead')
            # sheets are 1440p 16:9, bounded by the card
            from models.image.catalog import sheet_dimensions
            self.assertEqual(sheet_size(arnel), (2560, 1440))
            self.assertEqual(sheet_dimensions(2560, 1440, 24), (2560, 1440))
            self.assertEqual(sheet_dimensions(2560, 1440, 16), (1920, 1024))
            self.assertEqual(sheet_dimensions(2560, 1440, 8), (1280, 704))

    def test_a_failed_call_or_no_model_lists_nothing(self):
        def request(payload):
            raise RuntimeError('offline')
        self.assertEqual(find_entities('model', STORY, request=request), [])
        self.assertEqual(find_entities(None, STORY), [])

    def test_the_sheet_shows_the_entity_alone_and_its_file_follows_its_looks(self):
        rex = dict(id='rex', name='Rex', kind='character', looks='A brown bulldog.', segments=[0, 1])
        sheet = sheet_prompt(rex, 'ink')
        self.assertIn('reference sheet', sheet)
        self.assertIn('taken out of any room', sheet)
        self.assertIn('each from a different camera angle', sheet)
        self.assertIn('expressions', sheet)
        self.assertTrue(sheet.startswith('Art style, the top priority for how everything is rendered: ink. '),
                        'the style leads, as in the scene prompts')
        self.assertIn('from the front, from the side', sheet_prompt(dict(rex, kind='object'), ''))
        self.assertIn('empty and unoccupied', sheet_prompt(dict(rex, kind='place'), ''))
        self.assertIn('decides only how it is drawn, never what is there', sheet_prompt(dict(rex, kind='place'), ''))
        self.assertIn('No two panels share a viewpoint', sheet_prompt(dict(rex, kind='place'), ''))
        self.assertIn('separate wide panels in a two-by-two grid', sheet_prompt(dict(rex, kind='place'), ''))
        # no person is named on a place or object sheet, not even to forbid one, and the technique loses its clauses
        # about people: Qwen Image 2.1 takes no negative prompt, so "no person" and "hair drawn as strands" drew a woman
        from direction.entities import without_people
        style = 'Clean ink outlines; very few interior lines; hair drawn as a few long smooth strands; muted palette. Faces are soft. Mucha-inspired.'
        self.assertEqual(without_people(style), 'Clean ink outlines; very few interior lines; muted palette. Mucha-inspired.')
        for kind in ('place', 'object'):
            prompt = sheet_prompt(dict(rex, kind=kind, looks='A thing.'), style)
            self.assertNotRegex(prompt.lower(), r'\b(person|hair|face|figure|silhouette|hand|human)\b', kind)
        self.assertIn('hair drawn as', sheet_prompt(rex, style), 'a character keeps the whole technique')
        first = sheet_path('a/illustrations.json', rex, 'ink', 'flux')
        self.assertEqual(first.parent, Path('a/entities'))
        self.assertNotEqual(first, sheet_path('a/illustrations.json', dict(rex, looks='A grey bulldog.'), 'ink', 'flux'))

    def test_rewording_the_sheet_template_keeps_the_picture_name(self):
        from unittest import mock
        rex = dict(id='rex', name='Rex', kind='character', looks='A brown bulldog.', segments=[0, 1])
        before = sheet_path('a/illustrations.json', rex, 'ink.', 'flux')
        with mock.patch('direction.entities.sheet_prompt', return_value='a reworded template'):
            self.assertEqual(sheet_path('a/illustrations.json', rex, 'ink', 'flux'), before)
        self.assertNotEqual(sheet_path('a/illustrations.json', dict(rex, repaint=1), 'ink', 'flux'), before)
        self.assertNotEqual(sheet_path('a/illustrations.json', rex, 'ink', 'qwen'), before)

    @mock.patch('models.gpu.edit_priority.checkpoint', new=lambda: None)
    def test_a_picture_still_linked_in_the_storyline_is_reused_not_repainted(self):
        from PIL import Image
        from artwork.generation import paint_entities
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder)/'illustrations.json'
            (Path(folder)/'story.json').write_text(json.dumps(dict(segments=[], entities=[])), encoding='utf-8')
            old = Path(folder)/'entities'/'rex.0123456789.png'
            old.parent.mkdir()
            Image.new('RGB', (8, 8), 'red').save(old)
            from direction.entities import SHEET_VERSION
            rex = dict(id='rex', name='Rex', kind='character', looks='A brown bulldog.', segments=[0, 1], image=str(old),
                       sheet_version=SHEET_VERSION)
            def never(**kwargs):
                raise AssertionError('painted again')
            model = 'Qwen/Qwen-Image-Edit-2511'
            pictures = paint_entities(never, model, manifest, dict(style_prompt='ink', steps=4, seed=1), [rex],
                                      [Image.new('RGB', (8, 8))], None, None, 24)
            self.assertIn('rex', pictures)
            self.assertTrue(sheet_path(manifest, rex, 'ink', model).is_file())
            # painted the old way (a scene or the user's photo as a guide): painted again, from a blank canvas
            calls = []
            def paint(**kwargs):
                calls.append(kwargs)
                return SimpleNamespace(images=[Image.new('RGB', (8, 8), 'white')])
            class NoText:
                def __call__(self, image):
                    return None, None
            old_way = dict(rex, id='rex2', sheet_version=None)
            paint_entities(paint, model, manifest, dict(style_prompt='ink', steps=4, seed=1, reference_use='likeness'), [old_way],
                           [(Image.new('RGB', (8, 8)), 'person')], SimpleNamespace(Generator=lambda d: SimpleNamespace(manual_seed=lambda s: None)), NoText(), 24)
            self.assertEqual(len(calls), 1, 'an old-way picture is not reused')
            self.assertIn('empty canvas', calls[0]['prompt'], "the lead's photo is not given to someone else")
            # a style picture (not a likeness photo) guides the technique of every sheet
            paint_entities(paint, model, manifest, dict(style_prompt='ink', steps=4, seed=1), [dict(rex, id='rex3', sheet_version=None)],
                           [(Image.new('RGB', (8, 8)), 'place')], SimpleNamespace(Generator=lambda d: SimpleNamespace(manual_seed=lambda s: None)), NoText(), 24)
            self.assertTrue(calls[1]['prompt'].startswith('Picture 1 shows the art style only'))

    def test_image_tags_in_a_prompt_become_the_numbers_the_model_sees(self):
        from direction.entities import own_picture_tags, reference_tags
        self.assertEqual(own_picture_tags('@image1 stands by @image2, holding @image 3.', 2, rest=1),
                         'reference image 2 stands by reference image 3, holding.')
        self.assertEqual(own_picture_tags('@image1 waits.', 0), 'waits.')
        self.assertEqual(own_picture_tags('No tags here.', 3), 'No tags here.')
        # by file name, and recurring references by name, numbered as they are sent (entities.reference_order)
        own = ['Stick_Insect.png', 'lab photo.jpg']
        shown = [dict(name='The Lab', kind='place'), dict(name='Stick Insects', kind='character')]
        self.assertEqual(reference_tags('Refer to @Stick_Insect.png and @stick_insect; @"lab photo" on the bench, @The_Lab behind, @Stick_Insects on it, @nobody.', own, rest=1, entities=shown),
                         'Refer to reference image 3 and reference image 3; reference image 4 on the bench, reference image 5 behind, reference image 2 on it.')
        self.assertEqual(reference_tags('@Stick_Insects alone.'), 'alone.')
        self.assertEqual(reference_tags('@photo1 and @photo 2 and @photo3.', own, rest=2), 'reference image 1 and reference image 2 and.')

    def test_the_lead_in_another_form_gets_the_lead_photo_and_no_one_else_does(self):
        from direction.entities import from_lead, sheet_inputs, mood_first
        story = dict(segments=[dict(characters='Dr. Aris Thorne: a woman in her 30s. The Stick Insect: brown.')]*3,
                     entities=[dict(name='Hybrid Thorne', kind='character'), dict(name='the criminal', kind='character'),
                               dict(name='the web', kind='object')])
        hybrid, criminal, web = story['entities']
        self.assertTrue(from_lead(hybrid, story))
        self.assertFalse(from_lead(criminal, story))
        photo, scene = ('photo', 'person'), ('painting', 'place')
        self.assertEqual(sheet_inputs(hybrid, story, [photo], True, True)[0], ['photo'])
        self.assertEqual(sheet_inputs(criminal, story, [photo], True, True)[0], [])
        self.assertEqual(sheet_inputs(web, story, [scene], False, True)[0], ['painting'])
        # a person photo is never a style guide, whatever the project calls it; nor is one never described
        self.assertEqual(sheet_inputs(criminal, story, [photo], False, True)[0], [])
        self.assertEqual(sheet_inputs(web, story, [('unknown', None)], False, True)[0], [])
        self.assertEqual(sheet_inputs(criminal, story, [photo, scene], False, True)[0], ['painting'])
        # a model that paints anew (Qwen Image 2.1) drew the person photo into other sheets too: never a style guide
        self.assertEqual(sheet_inputs(criminal, story, [photo], True, True, edits=False), ([], ''))
        self.assertEqual(sheet_inputs(criminal, story, [photo, scene], True, True, edits=False)[0], ['painting'])
        self.assertEqual(sheet_inputs(hybrid, story, [photo], True, True, edits=False)[0], ['photo'], 'still the lead')
        self.assertTrue(from_lead(dict(name='the queen', kind='character', from_cast=True), story), 'the director said so')
        self.assertEqual(mood_first('Soft shading. Visual mood and materials: Dark horror anime.'),
                         'Dark horror anime. Soft shading.')

    def test_segments_get_only_their_painted_entities(self):
        with tempfile.TemporaryDirectory() as folder:
            picture = Path(folder)/'rex.png'
            picture.write_bytes(b'png')
            story = dict(entities=[dict(name='Rex', segments=[0, 1], image=str(picture)),
                                   dict(name='Mia', segments=[0, 2])])
            self.assertEqual([e['name'] for e in segment_entities(story, 0)], ['Rex'])
            self.assertEqual([e['name'] for e in segment_entities(story, 0, painted=False)], ['Rex', 'Mia'])
            self.assertEqual(segment_entities(story, 3), [])
            places = dict(entities=[dict(name='the oak', kind='place', segments=[0, 1]),
                                    dict(name='Rex', kind='character', segments=[0, 1])])
            # a place is pictured too (a location sheet), and comes after the characters for the reference slots
            self.assertEqual([e['name'] for e in segment_entities(places, 0, painted=False, pictured=True)], ['the oak', 'Rex'])
            self.assertEqual(len(segment_entities(places, 0, painted=False)), 2, 'the clips still describe the place')

    def test_references_fit_three_slots_and_likeness_keeps_one_for_the_cast(self):
        entities = ['a', 'b', 'c']
        # the project's picture sets the art style, so it always keeps a slot
        self.assertEqual(choose_references(1, entities, ['style'], False), (['a'], ['style']))
        self.assertEqual(choose_references(0, entities, ['me'], True), (['a', 'b'], ['me']))
        self.assertEqual(choose_references(0, ['a'], ['s1', 's2', 's3'], False), (['a'], ['s1', 's2']))

    def test_the_prompt_says_what_each_reference_shows(self):
        prompt = ('Draw only this visual scene: a walk. REFERENCE ROLE: rendering technique ONLY. ink. '
                  'Do not copy reference people, clothes, objects or composition. FINAL SUBJECT')
        rex = dict(name='Rex', kind='character')
        oak = dict(name='the old oak', kind='place')
        result = reference_role(prompt, [rex, oak], 1, 1, False)
        self.assertTrue(result.startswith(NEW_PICTURE+' Reference image 1 sets the art style of the whole picture'))
        self.assertIn('Reference image 3: who or what this scene is about', result)
        self.assertIn('Reference image 2 shows Rex alone on a plain backdrop', result)
        self.assertIn('draw them ONCE', result)
        self.assertIn('Reference image 4 is one view of the old oak: keep its layout', result)
        self.assertNotIn('Do not copy reference people', result)
        self.assertIn('REFERENCE ROLE: as listed at the start', reference_role(prompt, [], 0, 1, False))
        self.assertEqual(reference_role('plain', [], 0, 0, False), 'plain')



    def test_a_saved_story_without_entities_gets_them_listed_once(self):
        from direction import story as stories
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder)/'illustrations.json'
            manifest.write_text('{}', encoding='utf-8')
            stories.save(manifest, dict(segments=STORY))
            calls = []
            original = stories.list_entities
            stories.list_entities = lambda model, segments, character='', story='': calls.append(model) or [dict(name='Rex')]
            try:
                args = SimpleNamespace(ai_model='m', director='ollama')
                stories.ensure_entities(manifest, args)
                stories.ensure_entities(manifest, args)
            finally:
                stories.list_entities = original
            self.assertEqual(calls, ['m'])
            self.assertEqual(stories.load(manifest)['entities'], [dict(name='Rex')])


class PhotoTest(unittest.TestCase):
    WOMAN = dict(kind='person', who='a young woman')
    DOG = dict(kind='animal', who='an adult Chocolate Merle English Bulldog')

    def test_a_scene_gets_only_the_photos_of_who_it_shows(self):
        self.assertTrue(shows_subject(self.WOMAN, 'The detective kneels by the stream.'))
        self.assertFalse(shows_subject(self.WOMAN, 'A koala sleeps in a hollow tree.'))
        self.assertTrue(shows_subject(self.DOG, 'Her dog sniffs the leaves.'))
        self.assertTrue(shows_subject(self.DOG, 'The bulldogs rest.'))
        self.assertFalse(shows_subject(self.DOG, 'A woman walks alone at dawn.'))
        self.assertFalse(shows_subject(self.WOMAN, 'Theatre lights hover over the hedge.'), 'whole words only')

    def test_an_undescribed_photo_is_still_passed_on(self):
        self.assertTrue(shows_subject(None, 'A koala sleeps.'))

    def test_photos_are_named_in_the_prompt(self):
        result = reference_role('scene', [], 0, 2, True, ['a young woman', 'an adult bulldog'])
        self.assertIn('Reference image 1 shows a young woman and sets the art style', result)
        self.assertIn('Reference image 2 shows an adult bulldog', result)

    def test_a_photo_of_someone_not_in_the_scene_still_sets_the_style(self):
        result = reference_role('A koala sleeps.', [], 0, 1, True, [None])
        self.assertIn('Reference image 1 sets the art style', result)
        self.assertIn('Do not draw its people', result)


class SingleViewTest(unittest.TestCase):
    def test_a_scene_gets_one_view_cut_from_the_sheet(self):
        from PIL import Image, ImageDraw
        from direction.entities import single_view
        sheet = Image.new('RGB', (800, 400), (40, 40, 48))
        draw = ImageDraw.Draw(sheet)
        for k in range(4):  # a row of four full-body views, a row of close-ups under it
            draw.rectangle((40+k*190, 30, 140+k*190, 260), fill=(200, 180, 150))
            draw.ellipse((60+k*190, 300, 120+k*190, 370), fill=(200, 180, 150))
        view = single_view(sheet, 'character')
        self.assertLess(view.width, 200, 'one figure, not the row')
        self.assertGreater(view.height, 220, 'the full-body figure, not a close-up')
        panels = Image.new('RGB', (800, 400), (0, 0, 0))
        draw = ImageDraw.Draw(panels)
        for x in (10, 410):
            for y in (10, 210):
                draw.rectangle((x, y, x+380, y+180), fill=(30, 90, 160))
        panel = single_view(panels, 'place')
        self.assertLess(panel.width, 420)
        self.assertLess(panel.height, 220)
        plain = Image.new('RGB', (300, 200), (40, 40, 48))
        self.assertIs(single_view(plain, 'object'), plain, 'nothing to cut: the picture as it is')

    def test_a_place_is_cut_to_its_first_panel_in_a_row_or_a_grid(self):
        from PIL import Image, ImageDraw
        from direction.entities import single_view
        row = Image.new('RGB', (1000, 400), 'white')
        for left in (10, 260, 510, 760):
            ImageDraw.Draw(row).rectangle((left, 20, left+230, 380), fill='black')
        self.assertEqual(single_view(row, 'place').size, (231, 361), 'a row of four tall panels: the first whole')
        grid = Image.new('RGB', (1000, 600), 'white')
        for left, top in ((10, 10), (510, 10), (10, 310), (510, 310)):
            ImageDraw.Draw(grid).rectangle((left, top, left+480, top+280), fill='black')
        self.assertEqual(single_view(grid, 'place').size, (481, 281), 'two by two: the top-left')

    def test_a_sheet_is_painted_in_the_art_style_before_the_mood(self):
        from direction.entities import sheet_style
        style = sheet_style(dict(style='Soft painterly shading inspired by Alphonse Mucha.',
                                 style_prompt='Linework. Visual mood and materials: Dark horror anime.'))
        # the project's own style prompt leads a sheet, as it leads every scene prompt; the app's built-in style
        # ("ink contours inspired by Mucha") led the sheets of a project whose style was photographic realism
        self.assertEqual(style, 'Dark horror anime. Linework.')
        self.assertEqual(sheet_style(dict(style='Soft painterly shading inspired by Alphonse Mucha.', style_prompt='')),
                         'Soft painterly shading inspired by Alphonse Mucha', 'the built-in style only without one')
        self.assertEqual(sheet_style(dict(style='Mucha.', style_prompt=' Visual mood and materials: Dark.')), 'Mucha. Dark.')
        # a place or an object is painted without the mood: "bloody and gory" put a bleeding woman into the lab's panels
        from direction.entities import sheet_check_style, without_mood
        job = dict(style='Mucha.', style_prompt='Ink lines. Visual mood and materials: Dark, body-horror short. Bloody and gory.')
        self.assertEqual(sheet_style(job, mood=False), 'Ink lines.')
        self.assertNotIn('gory', sheet_prompt(dict(name='The lab', kind='place', looks='Tanks.'), job['style_prompt']))
        self.assertNotIn('gory', sheet_prompt(dict(name='The vase', kind='object', looks='Blue.'), sheet_style(job, mood=False)))
        self.assertIn('gory', sheet_prompt(dict(name='Mia', kind='character', looks='A woman.'), job['style_prompt']))
        self.assertEqual(without_mood('Ink lines.'), 'Ink lines.')
        # the checker is told the mood is the film's, not the sheet's: it failed clean character sheets for lacking gore
        self.assertEqual(sheet_check_style(job['style_prompt']),
                         'Ink lines. (the mood of the film, which this sheet need not show: Dark, body-horror short. Bloody and gory)')
        from direction.entities import CAST_ROLE
        self.assertIn('nothing the photo shows them wearing', CAST_ROLE)
        # the project's cut-out rules ("isolated subjects on plain white, no scenery, shadows or glow") painted every
        # sheet flat on white: only the art-style sentences lead a sheet
        from direction.illustration_prompts import STYLE
        led = sheet_style(dict(style=STYLE, style_prompt=''))
        self.assertTrue(led.startswith('Confident clean delicate ink contours'))
        self.assertNotIn('plain white', led)
        self.assertNotIn('surrealism', led)


if __name__ == '__main__':
    unittest.main()
