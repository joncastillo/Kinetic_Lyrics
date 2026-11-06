"""Regression cases for reference selection, forced choices, and early storyboard viewing."""
import unittest

from direction.entities import reference_role, uses_entity_sheet
from direction.illustration_prompts import with_reference_role


class EditorRegressionTests(unittest.TestCase):
    def test_style_photo_does_not_displace_lead_character_sheet(self):
        lead = dict(name='Dr. Viktoria', kind='character', cast=True)
        self.assertTrue(uses_entity_sheet(lead, False, True))
        self.assertFalse(uses_entity_sheet(lead, True, True))
        self.assertTrue(uses_entity_sheet(dict(lead, uploaded='edited.png'), True, True))
        prompt = 'Always use the likeness of the reference image for the main character. Dr. Viktoria stands in her lab.'
        styled = reference_role(prompt, [lead], 0, 1, False)
        self.assertIn('Reference image 2 shows Dr. Viktoria', styled)
        self.assertNotIn('Always use the likeness', styled)
        self.assertNotIn('Always use the likeness', with_reference_role(prompt, False))
        self.assertIn('Always use the likeness', with_reference_role(prompt, True))
