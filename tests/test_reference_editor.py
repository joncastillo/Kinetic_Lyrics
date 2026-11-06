"""The references editor: recurring characters, objects and places edited, added, removed, repainted and uploaded."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.entities import sheet_path
from studio.job_clips import ClipWork


def png():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buffer, 'PNG')
    return buffer.getvalue()


class ReferenceEditorTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.manifest = self.folder/'illustrations.json'
        self.manifest.write_text('{}', encoding='utf-8')
        self.story = self.folder/'story.json'
        koala = dict(id='the-koala', name='the koala', kind='character', looks='A grey koala.', segments=[1, 2],
                     image=str(self.folder/'old.png'))
        self.story.write_text(json.dumps(dict(segments=[{} for _ in range(5)], entities=[koala])), encoding='utf-8')
        self.job = SimpleNamespace(manifest=lambda: self.manifest)

    def edit(self, op, entry, upload=None):
        return ClipWork.edit_entity(self.job, op, entry, upload)

    def entities(self):
        return json.loads(self.story.read_text(encoding='utf-8'))['entities']

    def test_add_checks_the_entry_and_numbers_images_from_one(self):
        self.edit('add', dict(name='the orchid', kind='object', looks='A pink orchid.', images=[1, 5]))
        orchid = self.entities()[1]
        self.assertEqual((orchid['id'], orchid['segments'], orchid['cast']), ('the-orchid', [0, 4], False))
        for bad, why in ((dict(name='', kind='object', looks='x', images=[1]), 'name'),
                         (dict(name='a', kind='weather', looks='x', images=[1]), 'kind'),
                         (dict(name='a', kind='object', looks='', images=[1]), 'looks'),
                         (dict(name='a', kind='object', looks='x', images=[6]), 'image out of range')):
            with self.assertRaises(ValueError, msg=why):
                self.edit('add', bad)
        self.assertEqual(len(self.entities()), 2, 'a rejected entry is not saved')

    def test_a_new_description_drops_the_old_picture(self):
        self.edit('save', dict(id='the-koala', name='the koala', kind='character', looks='A sleepy grey koala.', images=[2]))
        koala = self.entities()[0]
        self.assertEqual((koala['looks'], koala['segments']), ('A sleepy grey koala.', [1]))
        self.assertNotIn('image', koala)

    def test_repaint_gives_the_sheet_a_new_name(self):
        before = sheet_path(self.manifest, self.entities()[0], 'ink', 'model')
        self.edit('repaint', dict(id='the-koala'))
        koala = self.entities()[0]
        self.assertEqual(koala['repaint'], 1)
        self.assertNotIn('image', koala)
        self.assertNotEqual(sheet_path(self.manifest, koala, 'ink', 'model'), before)

    def test_an_uploaded_picture_is_used_until_a_painted_one_is_asked_for(self):
        self.edit('upload', dict(id='the-koala'), ('mine.png', png()))
        koala = self.entities()[0]
        self.assertTrue(Path(koala['uploaded']).is_file())
        self.assertEqual(koala['image'], koala['uploaded'])
        self.edit('save', dict(id='the-koala', name='the koala', kind='character', looks='Changed.', images=[2]))
        self.assertEqual(self.entities()[0]['image'], koala['uploaded'], 'editing the text keeps the uploaded picture')
        self.edit('painted', dict(id='the-koala'))
        self.assertNotIn('uploaded', self.entities()[0])

    def test_remove(self):
        self.edit('remove', dict(id='the-koala'))
        self.assertEqual(self.entities(), [])
        with self.assertRaises(ValueError):
            self.edit('remove', dict(id='the-koala'))

    def test_forced_reference_retains_checker_reason_until_replaced(self):
        reason=dict(passed=False,summary='Wrong outfit',issues=['Blue instead of red'])
        self.edit('upload',dict(id='the-koala',force_used=True,force_review=reason),('forced.png',png()))
        entity=self.entities()[0]
        self.assertTrue(entity['force_used'])
        self.assertEqual(entity['force_review'],reason)
        self.assertEqual(entity['uploaded'],entity['image'])
        self.edit('repaint',dict(id='the-koala'))
        self.assertNotIn('force_used',self.entities()[0])

    def test_stale_story_save_cannot_undo_force_acceptance(self):
        from direction.story import load,save
        before=json.loads(self.story.read_text(encoding='utf-8'))
        reason=dict(passed=False,summary='Checker disliked the scene',issues=['Old issue'])
        self.edit('upload',dict(id='the-koala',force_used=True,force_review=reason),('forced.png',png()))
        chosen=self.entities()[0]['image']
        save(self.manifest,before)
        recovered=load(self.manifest)['entities'][0]
        self.assertEqual(recovered['image'],chosen)
        self.assertTrue(recovered['force_used'])
        self.assertEqual(recovered['force_review'],reason)
        self.edit('painted',dict(id='the-koala'))
        self.assertNotIn('uploaded',load(self.manifest)['entities'][0])


if __name__ == '__main__':
    unittest.main()
