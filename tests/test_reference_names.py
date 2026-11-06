"""An uploaded reference keeps its file name, so its @tag is one the user knows and still finds the picture."""
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from direction.entities import painted_prompt, reference_tags, sheet_prompt, sheet_style
from direction.story import load, save
from studio import server
from studio.server import keep_upload_name, store_image


def picture(colour):
    data = io.BytesIO()
    Image.new('RGB', (4, 4), colour).save(data, 'PNG')
    return data.getvalue()


class UploadNames(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def upload(self, name, colour='red'):
        return keep_upload_name(store_image(self.folder, name, picture(colour)), name)

    def test_keeps_the_name_it_was_uploaded_under(self):
        self.assertEqual(self.upload('Stick_Insect.png').name, 'Stick_Insect.png')

    def test_a_jpeg_is_saved_as_png_under_its_own_name(self):
        self.assertEqual(self.upload('Stick Insect.jpg').name, 'Stick_Insect.png')

    def test_leaves_only_what_a_tag_can_hold(self):
        self.assertEqual(self.upload('Stick Insect (1) v2.final.png').name, 'Stick_Insect_1_v2_final.png')

    def test_a_name_of_only_symbols_falls_back_to_the_hash(self):
        self.assertRegex(self.upload('(!).png').name, r'^[0-9a-f]{16}\.png$')

    def test_a_different_picture_with_the_same_name_is_numbered(self):
        self.assertEqual(self.upload('a.png', 'red').name, 'a.png')
        self.assertEqual(self.upload('a.png', 'blue').name, 'a-2.png')
        self.assertEqual(self.upload('a.png', 'green').name, 'a-3.png')

    def test_the_same_picture_again_is_kept_once(self):
        self.upload('a.png')
        self.assertEqual(self.upload('a.png').name, 'a.png')
        self.assertEqual([p.name for p in self.folder.iterdir()], ['a.png'])


class UploadsAreKept(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.job = server.Job(root, dict(name='Song'))
        manifest = root/'video.artwork'/'illustrations.json'
        manifest.parent.mkdir()
        self.manifest = manifest
        self.job.manifest = lambda: manifest
        save(manifest, dict(segments=[dict(index=0, references=[]), dict(index=1, references=[])]))

    def names(self, index):
        return [Path(p).name for p in load(self.manifest)['segments'][index]['references']]

    def test_an_upload_can_be_used_for_another_illustration(self):
        self.job.segment_reference(0, ('lab.png', picture('red')))
        [upload] = self.job.uploaded_references(self.manifest)
        self.job.segment_reference(1, reuse=upload['path'])
        self.assertEqual(self.names(1), ['lab.png'])

    def test_it_stays_available_after_being_taken_off(self):
        self.job.segment_reference(0, ('lab.png', picture('red')))
        self.job.segment_reference(0, None, 'lab.png')
        self.assertEqual(self.names(0), [])
        self.assertEqual([u['name'] for u in self.job.uploaded_references(self.manifest)], ['lab.png'])

    def test_the_same_picture_on_two_illustrations_is_listed_once(self):
        self.job.segment_reference(0, ('lab.png', picture('red')))
        self.job.segment_reference(1, ('lab.png', picture('red')))
        self.assertEqual(len(self.job.uploaded_references(self.manifest)), 1)

    def test_an_unused_upload_can_be_deleted_with_its_copies(self):
        self.job.segment_reference(0, ('lab.png', picture('red')))
        self.job.segment_reference(1, ('lab.png', picture('red')))
        self.job.segment_reference(0, None, 'lab.png')
        self.job.segment_reference(1, None, 'lab.png')
        [upload] = self.job.uploaded_references(self.manifest)
        self.job.delete_upload(upload['path'])
        self.assertEqual(self.job.uploaded_references(self.manifest), [])

    def test_an_upload_in_use_is_kept_and_says_where(self):
        self.job.segment_reference(1, ('lab.png', picture('red')))
        [upload] = self.job.uploaded_references(self.manifest)
        with self.assertRaisesRegex(ValueError, 'illustration 2'):
            self.job.delete_upload(upload['path'])
        self.assertEqual(self.names(1), ['lab.png'])

    def test_a_copy_in_use_elsewhere_also_keeps_it(self):
        self.job.segment_reference(0, ('lab.png', picture('red')))
        self.job.segment_reference(1, ('lab.png', picture('red')))
        self.job.segment_reference(0, None, 'lab.png')
        with self.assertRaisesRegex(ValueError, 'illustration 2'):
            self.job.delete_upload('000/lab.png')

    def test_only_uploads_can_be_deleted(self):
        with self.assertRaises(ValueError):
            self.job.delete_upload('../illustrations.json')

    def test_only_uploads_can_be_reused(self):
        with self.assertRaises(ValueError):
            self.job.segment_reference(1, reuse='../illustrations.json')


class PromptOfAPicture(unittest.TestCase):
    sheet = dict(name='The Lab', kind='place', looks='A cramped lab.')
    job = dict(style='Mucha', style_prompt='Soft ink.')

    def test_the_recorded_prompt_is_the_exact_one(self):
        self.assertEqual(painted_prompt(dict(self.sheet, painted_prompt='Paint it.'), self.job), ('Paint it.', True))

    def test_an_older_sheet_is_rebuilt_with_the_painters_style_and_says_so(self):
        prompt, exact = painted_prompt(self.sheet, self.job)
        self.assertEqual(prompt, sheet_prompt(self.sheet, sheet_style(self.job)))
        self.assertIn('Soft ink', prompt, "the project's style prompt leads, not the app's built-in style")
        self.assertNotIn('Mucha', prompt)
        self.assertFalse(exact)

    def test_a_photo_or_an_upload_was_never_painted(self):
        self.assertTrue(painted_prompt(dict(self.sheet, cast=True), self.job)[0], 'the cast is painted too, from the photo')
        self.assertEqual(painted_prompt(dict(self.sheet, uploaded='my.png'), self.job), ('', False))


class TagsForUploadNames(unittest.TestCase):
    def test_a_long_file_name_finds_its_picture(self):
        name = 'Stick_Insect_1_v2_final.png'
        self.assertEqual(reference_tags(f'Paint @{name} on the wall.', [name]), 'Paint reference image 1 on the wall.')

    def test_a_file_called_image_n_is_read_as_a_file_name(self):
        names = ['moth.png', 'image1.png']
        self.assertEqual(reference_tags('Use @image1.png here.', names), 'Use reference image 2 here.')

    def test_a_file_called_photo_n_with_many_digits_stays_whole(self):
        self.assertEqual(reference_tags('Use @photo12.png here.', ['photo12.png']), 'Use reference image 1 here.')

    def test_image_n_at_the_end_of_a_sentence_still_counts(self):
        self.assertEqual(reference_tags('Use @image1. Then stop.', ['moth.png']), 'Use reference image 1. Then stop.')


if __name__ == '__main__':
    unittest.main()
