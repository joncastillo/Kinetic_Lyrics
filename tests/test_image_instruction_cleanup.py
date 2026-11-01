import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from image_instruction_cleanup import clean_legacy_imported_meaning


class ImageInstructionCleanupTest(unittest.TestCase):
    def test_old_imported_song_summaries_are_not_used_as_image_directions(self):
        self.assertEqual(clean_legacy_imported_meaning(
            'Song meaning (a non-literal reading of the full lyrics): The narrator is young.'), '')
        self.assertEqual(clean_legacy_imported_meaning(
            'The narrator is young. The central message is heartbreak.'), '')

    def test_user_image_directions_are_preserved(self):
        self.assertEqual(clean_legacy_imported_meaning(
            'Do not depict the narrator; paint the empty room.'),
            'Do not depict the narrator; paint the empty room.')


if __name__ == '__main__':
    unittest.main()
