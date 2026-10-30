import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class LyricsSanitizerTest(unittest.TestCase):
    def test_sanitize_lyrics_removes_genius_recommendations(self):
        from kinetic_lyrics import sanitize_lyrics

        raw_lyrics = """[Verse 1]
Hello, darkness, my old friend
I've come to talk with you again

[Verse 3]
And no one dared
Disturb the sound of silence
You might also like
But Daddy I Love Him
Taylor Swift
So Long, London
Taylor Swift
The Tortured Poets Department
Taylor Swift
[Verse 4]
"Fools," said I, "You do not know
Silence, like a cancer, grows123Embed"""

        cleaned = sanitize_lyrics(raw_lyrics)

        self.assertNotIn("You might also like", cleaned)
        self.assertNotIn("Taylor Swift", cleaned)
        self.assertNotIn("Daddy I Love Him", cleaned)
        self.assertNotIn("123Embed", cleaned)
        self.assertIn("Disturb the sound of silence", cleaned)
        self.assertIn('"Fools," said I, "You do not know', cleaned)
        self.assertIn("Silence, like a cancer, grows", cleaned)

    def test_sanitize_lyrics_removes_header_and_blank_line_breaks(self):
        from kinetic_lyrics import sanitize_lyrics

        raw = """14 Contributors
The Sound of Silence Lyrics
Line one
Line two

You might also like
Unrelated Ad Song
Random Artist

Line three
Line four
Embed"""

        cleaned = sanitize_lyrics(raw)
        self.assertNotIn("Contributors", cleaned)
        self.assertNotIn("Lyrics", cleaned)
        self.assertNotIn("Unrelated Ad Song", cleaned)
        self.assertNotIn("Embed", cleaned)
        self.assertIn("Line one", cleaned)
        self.assertIn("Line two", cleaned)
        self.assertIn("Line three", cleaned)
        self.assertIn("Line four", cleaned)


if __name__ == '__main__':
    unittest.main()
