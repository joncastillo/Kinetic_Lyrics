"""An alternative picture can be deleted with its sidecars; the picture in use, the raw painting and anything outside
candidates/ and versions/ cannot."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio.image_operations import discard_variant


class DiscardVariantTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        art = self.root/'video.artwork'/'x'
        art.mkdir(parents=True)
        self.current, self.raw = art/'003.png', art/'003.raw.png'
        self.current.write_bytes(b'in use')
        self.raw.write_bytes(b'raw')
        self.candidate = self.root/'candidates'/'003'/'1700'/'candidate-2.png'
        self.candidate.parent.mkdir(parents=True)
        for name in ('candidate-2.png', 'candidate-2.review.json', 'candidate-2.selection.json', 'candidate-2.mp4', 'candidate-1.png'):
            (self.candidate.parent/name).write_bytes(b'x')
        self.version = self.root/'versions'/'003'/'1600.png'
        self.version.parent.mkdir(parents=True)
        self.version.write_bytes(b'old')

    def test_a_candidate_goes_with_its_sidecars_and_the_rest_stays(self):
        discard_variant(self.root, self.candidate, keep=(self.current, self.raw))
        self.assertEqual(sorted(p.name for p in self.candidate.parent.iterdir()), ['candidate-1.png'])
        discard_variant(self.root, self.candidate.parent/'candidate-1.png')
        self.assertFalse(self.candidate.parent.exists(), 'an emptied candidate folder goes too')
        self.assertTrue((self.root/'candidates'/'003').exists())

    def test_an_earlier_version_can_go(self):
        discard_variant(self.root, self.version, keep=(self.current, self.raw))
        self.assertFalse(self.version.exists())

    def test_the_picture_in_use_the_raw_painting_and_strangers_stay(self):
        for path in (self.current, self.raw):
            with self.assertRaises(ValueError):
                discard_variant(self.root, path, keep=(self.current, self.raw))
        with self.assertRaises(ValueError):
            discard_variant(self.root, self.root/'video.artwork'/'x'/'003.png')   # outside candidates and versions
        with self.assertRaises(ValueError):
            discard_variant(self.root, self.root/'candidates'/'003'/'missing.png')
        self.assertTrue(self.current.exists() and self.raw.exists())


if __name__ == '__main__':
    unittest.main()
