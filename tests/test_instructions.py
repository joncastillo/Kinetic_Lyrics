"""Special instructions typed for the renderer: parsed into per-word effects and colours."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from effects.particles.catalog import discover_effects
from direction.instructions import parse_instructions, typography_colors, word_directives


def song(*lines):
    data, t = [], 0.
    for line in lines:
        words = []
        for text in line.split():
            words.append(dict(text=text, start=t, end=t+.4))
            t += .5
        data.append(dict(text=line, words=words))
    return data


class InstructionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entrances = discover_effects()['entrance']

    def test_neon_effect_on_a_quoted_word(self):
        (directive, problem), = parse_instructions('Apply a neon effect to the word "neong"', self.entrances)
        self.assertIsNone(problem)
        self.assertEqual(directive, dict(words={'neong'}, effect='neon-tube-ignite', color=None))

    def test_colours_by_name_and_hex(self):
        named, hexed = parse_instructions('Make "liwanag" gold\nmake "gabi" #3366FF', self.entrances)
        self.assertEqual(named[0]['color'], (255, 201, 60))
        self.assertIsNone(named[0]['effect'])
        self.assertEqual(hexed[0]['color'], (51, 102, 255))

    def test_song_wide_lettering_colours(self):
        self.assertEqual(typography_colors('Make all lyrics gold'), ((255, 201, 60), None))
        self.assertEqual(typography_colors('Accent colour #FF5DA2'), (None, (255, 93, 162)))
        self.assertEqual(typography_colors('Text in white\nmake "love" red'), ((255, 255, 255), None))
        directives, problems = word_directives(song('all my love'), 'Make all lyrics gold', self.entrances)
        self.assertEqual((directives, problems), ({}, []))

    def test_unclear_lines_are_reported_not_fatal(self):
        results = parse_instructions('something vague\nsparkle "x" with zzzz', self.entrances)
        self.assertTrue(all(directive is None and problem for directive, problem in results))

    def test_words_match_wherever_sung_ignoring_case_and_punctuation(self):
        data = song('Hello neong, world', 'NEONG again')
        directives, problems = word_directives(data, 'neon on "neong"\nfrost on "missing"', self.entrances)
        self.assertEqual(set(directives), {(0, 1), (1, 0)})
        self.assertEqual(problems, ['Not sung in this song: "missing"'])

    def test_compositor_overrides_only_the_named_word(self):
        from render.compositor import Compositor
        data = song('one neong two', 'three four')
        plan = dict(scenes=[dict(mode='push', style='swiss', palette='midnight', font='condensed', align='center',
                                 background='glow', camera='hold', emphasis=0, energy=.5) for _ in data])
        c = Compositor(data, plan, 320, 180, 4., entrance_effect='none', exit_effect='none',
                       instructions='Apply a neon effect to the word "neong"')
        self.assertEqual(c.word_effect_pairs[0][1][0], 'neon-tube-ignite')
        self.assertEqual(c.word_effect_pairs[0][0][0], 'none')
        self.assertEqual(c.effect_pairs[0][0], 'none')  # the line keeps its own effect

    def test_compositor_applies_song_wide_lettering_colours(self):
        from render.compositor import Compositor
        data = song('one two', 'three four')
        plan = dict(scenes=[dict(mode='push', style='swiss', palette='midnight', font='condensed', align='center',
                                 background='glow', camera='hold', emphasis=0, energy=.5) for _ in data])
        c = Compositor(data, plan, 320, 180, 4., entrance_effect='none', exit_effect='none',
                       instructions='Make all lyrics gold\nAccent colour #FF5DA2')
        self.assertEqual(c.scene_palette(plan['scenes'][0]), ('#101725', '#223348', '#FFC93C', '#FF5DA2'))
        pixels = c.frame(1.).convert('RGB').getdata()
        self.assertTrue(any(r > 220 and 170 < g < 230 and b < 110 for r, g, b in pixels))  # gold lettering drawn


if __name__ == '__main__':
    unittest.main()
