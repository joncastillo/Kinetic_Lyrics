"""The validator counts duplicated characters and wrong animal anatomy as defects, and not their negations."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from models.vision.policy import reported_defect  # noqa: E402


class AnimalDefectTest(unittest.TestCase):
    def test_reported(self):
        for text in ('The bulldog has a raccoon-like ringed tail on the right', 'a fox tail on the dog',
                     'Duplicated dog: two identical bulldogs on the left', 'the dog has two heads',
                     'Age mismatch: a puppy instead of the adult bulldog', 'the woman is drawn as a girl of about ten'):
            self.assertTrue(reported_defect(text), text)

    def test_not_reported(self):
        for text in ('no duplicated character, the dog has a stub tail', 'the dog may have an extra tail',
                     'the cat sits on the wall with its tail curled', 'no age mismatch: the bulldog is an adult'):
            self.assertFalse(reported_defect(text), text)


if __name__ == '__main__':
    unittest.main()
