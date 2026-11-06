import unittest

from direction.song_structure import parse_line_pattern, pattern_groups, valid_line_groups


class LinePatternTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_line_pattern('2-3-2-4'), [2, 3, 2, 4])
        self.assertIsNone(parse_line_pattern('3'))
        self.assertIsNone(parse_line_pattern('auto'))
        self.assertIsNone(parse_line_pattern('2-0'))
        self.assertIsNone(parse_line_pattern('2--3'))

    def test_groups_cycle_and_keep_the_remainder(self):
        groups = pattern_groups(14, [2, 3, 2, 4])
        self.assertEqual([len(g) for g in groups], [2, 3, 2, 4, 2, 1])
        self.assertTrue(valid_line_groups(groups, 14))
        self.assertEqual(pattern_groups(0, [2, 3]), [])


if __name__ == '__main__':
    unittest.main()
