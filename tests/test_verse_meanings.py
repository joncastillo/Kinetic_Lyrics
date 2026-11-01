"""User supplied Tagalog glosses must reach and constrain the lyric meaning pass."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.verse import lyric_meanings, notes_for_group, translation_notes, uses_definition
from direction.verse import image_prompt


class VerseMeaningTest(unittest.TestCase):
    def test_explicit_gloss_matches_lyric_group(self):
        notes = translation_notes('Interpret lyrics in Tagalog.\n"ambon" means drizzle.')
        self.assertEqual(notes_for_group("Salita ko'y tulad ng ambon", notes), {'ambon': 'drizzle'})
        self.assertEqual(translation_notes('"ambon" means drizzle, not a seashell.'), {'ambon': 'drizzle'})
        self.assertEqual(notes_for_group('Yumuko at nagdasal', notes), {})

    def test_gloss_is_honored_in_any_word_form(self):
        self.assertTrue(uses_definition('drizzle rain', 'A light drizzle falls on the town.'))
        self.assertTrue(uses_definition('drizzle rain', 'Drizzling rain echoes in the well.'))
        self.assertFalse(uses_definition('drizzle rain', 'A seashell on a beach.'))

    def test_wrong_initial_meaning_is_retried_with_binding_gloss(self):
        calls = []

        def request(endpoint, payload, timeout):
            inputs = json.loads(payload['messages'][1]['content'])
            calls.append(inputs)
            meaning = ('The words are like a seashell by the sea.' if len(calls) == 1 else
                       'The speaker compares their words to drizzle falling softly and echoing in a well.')
            return {'message': {'content': json.dumps({'subjects': [meaning]})}}

        result = lyric_meanings(request, 'test', ["Salita ko'y tulad ng ambon / Na umalingawngaw sa balon"],
                                image_instructions='Interpret lyrics in Tagalog.\n"ambon" means drizzle.')
        self.assertIn('drizzle', result[0])
        self.assertEqual(calls[0][0]['binding_translation_notes'], {'ambon': 'drizzle'})
        self.assertIn('seashell', calls[1][0]['previous_incorrect_meaning'])

    def test_persistent_misreading_fails_before_image_generation(self):
        def request(endpoint, payload, timeout):
            return {'message': {'content': json.dumps({'subjects': ['A seashell on a beach.']})}}

        with self.assertRaisesRegex(ValueError, 'ambon'):
            lyric_meanings(request, 'test', ['ambon'], image_instructions='ambon means drizzle')


if __name__ == '__main__':
    unittest.main()
