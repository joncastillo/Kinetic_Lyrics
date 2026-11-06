"""A reference's earlier pictures stay on disk to look at; the one in use is not among them."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.entities import earlier_sheets


class EarlierSheetsTest(unittest.TestCase):
    def test_newest_first_without_the_one_in_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp)/'illustrations.json'
            folder = Path(tmp)/'entities'
            folder.mkdir()
            old, older, current, other = (folder/f'the-lab.{d}.png' for d in ('aaaa', 'bbbb', 'cccc', 'dddd'))
            for n, path in enumerate((older, old, current)):
                path.write_bytes(b'x')
                t = time.time()-100+n*10
                __import__('os').utime(path, (t, t))
            (folder/'the-lab.eeee.tmp.png').write_bytes(b'half written')
            (folder/'the-hallway.ffff.png').write_bytes(b'another reference')
            entity = dict(id='the-lab', image=str(current))
            self.assertEqual(earlier_sheets(manifest, entity), [old, older])
            self.assertEqual(earlier_sheets(manifest, dict(id='the-lab')), [current, old, older], 'nothing in use: all of them')
            self.assertEqual(earlier_sheets(manifest, dict(id='', image=str(other))), [])


if __name__ == '__main__':
    unittest.main()
