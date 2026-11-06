"""Image Maker: requests are checked before any GPU work, tags resolve as in a scene prompt, nothing is overwritten."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from artwork import maker
from direction.entities import scene_view
from artwork.maker import (TEMPLATES, checked, free_path, full_prompt, maker_folder, make, save_picture, side, template,
                           unknown_tags)
from models.image.catalog import MODELS
from studio import maker_routes

QWEN = 'Qwen/Qwen-Image-2.1'


class Templates(unittest.TestCase):
    def test_there_is_one_of_each_and_no_template(self):
        self.assertEqual([t['id'] for t in TEMPLATES], ['character', 'object', 'scene', 'none'])

    def test_the_sheets_use_a_white_background_and_take_a_subject(self):
        for t in TEMPLATES[:3]:
            self.assertIn('white background', t['text'])
            self.assertIn('{subject}', t['text'])

    def test_no_template_has_no_words_of_its_own(self):
        self.assertEqual(template('none')['text'], '')

    def test_an_unknown_template_is_refused(self):
        with self.assertRaises(ValueError):
            template('poster')


class Prompts(unittest.TestCase):
    def test_a_template_fills_in_its_subject(self):
        self.assertIn('sheet of a damp lab. Three', full_prompt('scene', template('scene')['text'], 'a damp lab.', []))

    def test_no_template_is_used_as_written(self):
        self.assertEqual(full_prompt('none', 'A red door.', '', []), 'A red door.')

    def test_with_no_template_a_tag_still_becomes_its_number(self):
        self.assertEqual(full_prompt('none', 'A lab like @lab.png.', '', ['lab.png']), 'A lab like reference image 1.')

    def test_a_template_says_what_the_references_are_for(self):
        result = full_prompt('object', 'Sheet of {subject}, like @lab.png.', 'a jar', ['lab.png'])
        self.assertTrue(result.startswith('Paint a new full-frame picture'))
        self.assertTrue(result.endswith('Sheet of a jar, like reference image 1.'))

    def test_unknown_tags_are_found(self):
        self.assertEqual(unknown_tags('@lab.png and @lab and @nope and @image1 and @image2', ['lab.png']), ['@nope', '@image2'])

    def test_an_email_address_is_not_a_tag(self):
        self.assertEqual(unknown_tags('Send to jo@example.com', []), ['@example.com'])


class Requests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.refs = Path(folder.name)
        Image.new('RGB', (4, 4)).save(self.refs/'lab.png')
        self.request = dict(template='none', prompt='A door.', model=QWEN, width=1344, height=768, format='png',
                            folder=str(self.refs/'out'))

    def check(self, **changes):
        return checked({**self.request, **changes}, self.refs)

    def test_a_good_request_gets_defaults(self):
        clean = self.check()
        self.assertEqual((clean['count'], clean['seed'], clean['steps']), (1, None, 40))
        self.assertEqual(clean['output'], 'image')


    def test_sides_become_multiples_of_32(self):
        self.assertEqual(side(1000, 'Width'), 992)

    def test_what_is_wrong_is_refused(self):
        for changes, words in ((dict(prompt=' '), 'prompt'), (dict(width=99), 'Width'), (dict(format='gif'), 'PNG'),
                               (dict(folder=''), 'folder'), (dict(folder='relative/path'), 'folder'), (dict(count=99), 'Pictures'),
                               (dict(steps=0), 'Steps'), (dict(template='nope'), 'template'), (dict(prompt='A @ghost.'), '@ghost'),
                               (dict(references=['gone.png']), 'gone.png'), (dict(references=['../lab.png']), 'lab.png'),
                               (dict(prompt='{subject}'), 'sheet shows')):
            with self.subTest(changes), self.assertRaisesRegex(ValueError, words):
                self.check(**changes)

    def test_references_need_a_model_that_reads_them(self):
        with mock.patch.object(maker, 'model_spec', return_value=dict(name='Plain', references=False, steps=4)), \
                self.assertRaisesRegex(ValueError, 'does not read'):
            self.check(references=['lab.png'])

    def test_too_many_references_are_refused(self):
        with mock.patch.object(maker, 'model_spec', return_value=dict(name='Small', references=True, max_references=0, steps=4)), \
                self.assertRaisesRegex(ValueError, 'at most 0'):
            self.check(references=['lab.png'])

    def test_a_tag_is_valid_only_while_its_picture_is_in_use(self):
        self.assertEqual(self.check(prompt='Like @lab.png', references=['lab.png'])['references'], ['lab.png'])
        with self.assertRaisesRegex(ValueError, '@lab.png'):
            self.check(prompt='Like @lab.png')


class FileNames(unittest.TestCase):
    def test_a_typed_name_is_kept_and_made_safe(self):
        self.assertEqual(maker.stem('Lab sheet v2'), 'Lab_sheet_v2')
        self.assertEqual(maker.stem('a/b:c'), 'a_b_c')

    def test_a_typed_extension_is_left_to_the_format_setting(self):
        self.assertEqual(maker.stem('lab.png'), 'lab')
        self.assertEqual(maker.stem('lab.JPEG'), 'lab')

    def test_an_empty_name_still_makes_a_file(self):
        self.assertEqual(maker.stem('  '), 'image')


class Files(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_nothing_is_overwritten(self):
        Image.new('RGB', (4, 4)).save(self.folder/'sheet.png')
        self.assertEqual(free_path(self.folder, 'sheet', '.png').name, 'sheet-2.png')

    def test_a_recipe_of_that_name_is_not_overwritten_either(self):
        (self.folder/'sheet.json').write_text('{}', encoding='utf-8')
        self.assertEqual(free_path(self.folder, 'sheet', '.jpg').name, 'sheet-2.jpg')

    def test_every_format_saves(self):
        for name, kind in (('a.png', 'png'), ('a.jpg', 'jpeg'), ('a.webp', 'webp')):
            save_picture(Image.new('RGBA', (8, 8)), self.folder/name, kind, 80)
            with Image.open(self.folder/name) as picture:
                self.assertEqual(picture.format, maker.FORMATS[kind][0])

    def test_it_lives_beside_the_song_projects_not_among_them(self):
        self.assertEqual(maker_folder(Path('output/lyric-studio')), Path('output/image-maker'))


class Painting(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        (self.home/'references').mkdir()
        Image.new('RGB', (2000, 1000)).save(self.home/'references'/'lab.png')
        (self.home/'history.json').write_text('[]', encoding='utf-8')
        self.calls = []

    def pipe(self, prompt, image=None, width=0, height=0, generator=None, **options):
        self.calls.append(dict(prompt=prompt, image=image, width=width, height=height))
        return mock.Mock(images=[Image.new('RGB', (width, height))])

    def run_make(self, memory=24, **changes):
        request = dict(template='none', prompt='Like @lab.png', subject='', references=['lab.png'], model=QWEN, width=1344, height=768,
                       format='png', quality=92, steps=2, seed=7, count=2, name='door', folder=str(self.home/'out'), **changes)
        torch = mock.Mock()
        self.reports = []
        return make(request, self.home, self.pipe, torch, memory, lambda *a: self.reports.append(a))

    def test_the_model_gets_the_picture_and_the_number(self):
        self.run_make()
        self.assertEqual(self.calls[0]['prompt'], 'Like reference image 1')
        self.assertEqual(len(self.calls[0]['image']), 1)
        self.assertEqual(self.calls[0]['image'][0].size, (1024, 512))

    def test_each_picture_keeps_its_recipe_and_its_own_seed(self):
        made = self.run_make()
        self.assertEqual([Path(p).name for p in made], ['door.png', 'door-2.png'])
        recipes = [json.loads(Path(p).with_suffix('.json').read_text(encoding='utf-8')) for p in made]
        self.assertEqual([r['seed'] for r in recipes], [7, 8])
        self.assertEqual(recipes[0]['prompt'], 'Like @lab.png')
        self.assertEqual(recipes[0]['sent_prompt'], 'Like reference image 1')

    def test_they_are_listed_for_the_panel(self):
        self.run_make()
        self.assertEqual(len(maker_routes.public_history(self.home)), 2)

    def test_a_shrunk_picture_says_so(self):
        self.run_make(memory=10)
        self.assertLess(self.calls[0]['width'], 1344)
        self.assertIn('short of memory', self.reports[0][1])


class DeletingPictures(Painting):
    def test_the_picture_and_its_recipe_go(self):
        made = [Path(p) for p in self.run_make()]
        first = maker_routes.public_history(self.home)[-1]
        self.assertEqual(Path(first['path']), made[0])
        maker_routes.delete_picture(self.home, first['id'])
        self.assertFalse(made[0].exists() or made[0].with_suffix('.json').exists())
        self.assertTrue(made[1].exists() and made[1].with_suffix('.json').exists())
        self.assertEqual(len(maker_routes.public_history(self.home)), 1)

    def test_only_a_picture_it_made_can_be_deleted(self):
        self.run_make()
        with self.assertRaises(ValueError):
            maker_routes.delete_picture(self.home, str(self.home/'references'/'lab.png'))
        self.assertTrue((self.home/'references'/'lab.png').exists())

    def test_one_already_gone_from_the_disk_still_leaves_the_list(self):
        made = [Path(p) for p in self.run_make()]
        made[0].unlink()
        first = json.loads((self.home/'history.json').read_text(encoding='utf-8'))[0]
        maker_routes.delete_picture(self.home, first['id'])
        self.assertEqual(len(json.loads((self.home/'history.json').read_text(encoding='utf-8'))), 1)


class KeptReferences(Painting):
    def item(self, index=0):
        return json.loads((self.home/'history.json').read_text(encoding='utf-8'))[index]

    def test_they_are_saved_beside_the_picture_in_a_hashed_folder(self):
        self.run_make()
        kept = Path(self.item()['reference_folder'])
        self.assertRegex(kept.name, r'^door_references_[0-9a-f]{8}$')
        self.assertEqual(kept.parent, self.home/'out')
        self.assertTrue((kept/'lab.png').is_file())

    def test_the_same_references_share_one_folder(self):
        self.run_make()
        self.assertEqual(self.item(0)['reference_folder'], self.item(1)['reference_folder'])

    def test_different_references_get_another_folder(self):
        self.run_make()
        Image.new('RGB', (2000, 1000), 'red').save(self.home/'references'/'lab.png')
        self.run_make()
        self.assertNotEqual(self.item(0)['reference_folder'], self.item(2)['reference_folder'])

    def test_they_come_back_after_leaving_the_library(self):
        self.run_make()
        (self.home/'references'/'lab.png').unlink()
        self.assertEqual(maker_routes.restore_references(self.home, self.item()['id']), (['lab.png'], {}, []))
        self.assertTrue((self.home/'references'/'lab.png').is_file())

    def test_a_different_picture_of_that_name_is_kept_and_this_one_is_renamed(self):
        self.run_make()
        Image.new('RGB', (40, 40), 'red').save(self.home/'references'/'lab.png')
        names, renamed, _ = maker_routes.restore_references(self.home, self.item()['id'])
        self.assertEqual((names, renamed), (['lab-2.png'], {'lab.png': 'lab-2.png'}))
        with Image.open(self.home/'references'/'lab.png') as kept:
            self.assertEqual(kept.size, (40, 40))

    def test_an_older_picture_uses_the_library_and_says_what_is_gone(self):
        history = [dict(id='old', path='x.png', references=['lab.png', 'gone.png'])]
        (self.home/'history.json').write_text(json.dumps(history), encoding='utf-8')
        self.assertEqual(maker_routes.restore_references(self.home, 'old'), (['lab.png'], {}, ['gone.png']))

    def test_the_copies_stay_until_the_last_picture_using_them_goes(self):
        self.run_make()
        kept = Path(self.item()['reference_folder'])
        maker_routes.delete_picture(self.home, self.item(0)['id'])
        self.assertTrue((kept/'lab.png').is_file())
        maker_routes.delete_picture(self.home, self.item(0)['id'])
        self.assertFalse(kept.exists())

    def test_a_file_someone_added_there_is_left_alone(self):
        self.run_make()
        kept = Path(self.item()['reference_folder'])
        (kept/'notes.txt').write_text('mine', encoding='utf-8')
        for _ in range(2):
            maker_routes.delete_picture(self.home, self.item(0)['id'])
        self.assertTrue((kept/'notes.txt').is_file())


class SavedPrompts(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)

    def test_a_prompt_is_kept_and_replaced_by_name(self):
        maker_routes.save_prompt(self.home, dict(name='Lab', prompt='one'))
        maker_routes.save_prompt(self.home, dict(name='Lab', prompt='two'))
        self.assertEqual([p['prompt'] for p in maker_routes.saved_prompts(self.home)], ['two'])

    def test_it_can_be_deleted(self):
        maker_routes.save_prompt(self.home, dict(name='Lab', prompt='one'))
        self.assertEqual(maker_routes.delete_prompt(self.home, 'Lab'), [])

    def test_it_needs_a_name(self):
        with self.assertRaises(ValueError):
            maker_routes.save_prompt(self.home, dict(name=' ', prompt='one'))


class ReplacedReferences(unittest.TestCase):
    def picture(self):
        # four panels on white, like a painted location sheet
        sheet = Image.new('RGB', (200, 100), 'white')
        for box in ((10, 10, 90, 45), (110, 10, 190, 45), (10, 55, 90, 90), (110, 55, 190, 90)):
            sheet.paste((30, 30, 30), box)
        return sheet

    def test_a_painted_place_gives_one_panel(self):
        self.assertLess(scene_view(self.picture(), dict(kind='place')).width, 100)

    def test_an_uploaded_place_stays_whole(self):
        self.assertEqual(scene_view(self.picture(), dict(kind='place', uploaded='mine.png')).size, (200, 100))

    def test_an_uploaded_object_is_still_cut_to_one_view(self):
        self.assertLess(scene_view(self.picture(), dict(kind='object', uploaded='mine.png')).width, 200)


class ModelList(unittest.TestCase):
    def test_every_image_model_is_offered(self):
        with tempfile.TemporaryDirectory() as cache:
            offered = maker_routes.model_list(cache)
        self.assertEqual([m['id'] for m in offered], [m['id'] for m in MODELS])
        self.assertFalse(any(m['on_disk'] for m in offered))


class CinemagraphMaker(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.image = self.home/'lake.png'
        Image.new('RGB', (256, 256), 'blue').save(self.image)
        self.recipe = dict(template='none', prompt='A lake.', subject='', references=[], model=QWEN, width=256, height=256,
                           format='png', quality=92, steps=2, seed=0, count=1, name='lake', folder=str(self.home), path=str(self.image))
        self.image.with_suffix('.json').write_text(json.dumps(self.recipe), encoding='utf-8')
        (self.home/'history.json').write_text(json.dumps([dict(self.recipe, id='lake')]), encoding='utf-8')





class EditQueue(unittest.TestCase):
    def test_used_reference_reports_selection_queue_history_and_project_copy(self):
        from studio import server
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);(home/'references').mkdir()
            Image.new('RGBA',(32,32),'red').save(home/'references'/'Doctor.png')
            project=home/'song';project.mkdir();Image.new('RGB',(32,32),'red').save(project/'doctor.png')
            manifest=project/'illustrations.json';manifest.write_text('{}',encoding='utf-8')
            (project/'story.json').write_text(json.dumps(dict(segments=[],entities=[dict(name='Doctor',image=str(project/'doctor.png'))])),encoding='utf-8')
            output=home/'edit.png';output.write_bytes(b'output')
            maker_routes.write_json_atomic(home/'history.json',[dict(name='Earlier edit',path=str(output),references=['Doctor.png'])])
            maker_routes.write_json_atomic(home/'queue.json',[dict(name='Next edit',references=['Doctor.png'])])
            job=SimpleNamespace(manifest=lambda:manifest,folder=project,config=dict(name='My song'))
            with mock.patch.dict(server.JOBS,{'usage-song':job},clear=True):
                uses=maker_routes.reference_usage(home,'Doctor.png',['Doctor.png'])
            self.assertIn('Selected for this edit',uses)
            self.assertIn('Queued edit: Doctor',uses)
            self.assertIn('Edit history: Earlier edit',uses)
            self.assertIn('My song: recurring reference Doctor',uses)

    def test_reference_delete_is_blocked_when_selected(self):
        from studio import server
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);(home/'references').mkdir();picture=home/'references'/'Doctor.png';Image.new('RGB',(32,32)).save(picture)
            handler=SimpleNamespace(_maker_home=lambda:home,respond=lambda value,status=200:(value,status))
            with mock.patch.dict(server.JOBS,{},clear=True):
                answer,status=maker_routes.MakerRoutes._post_maker(handler,'/api/image-maker/reference-delete',json.dumps(dict(name='Doctor.png',selected_references=['Doctor.png'])).encode())
            self.assertEqual(status,409)
            self.assertTrue(picture.exists())
            self.assertIn('Selected for this edit',answer['uses'])

    def test_large_reference_is_scaled_to_supported_edit_size(self):
        request=dict(width=4096,height=2304,edit_target=dict(job='song',id='doctor'))
        result=maker_routes.edit_dimensions(request)
        self.assertEqual((result['width'],result['height']),(2048,1152))
        self.assertEqual(maker_routes.edit_dimensions(dict(width=4096,height=2304))['width'],4096)

    def test_finished_edit_applies_reference_once(self):
        from studio import server
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home/'edited.png'
            Image.new('RGB', (32,32)).save(source)
            request = dict(request_id='edit-1', edit_target=dict(job='song',id='doctor'))
            maker_routes.write_json_atomic(home/'history.json', [dict(request_id='edit-1',path=str(source))])
            job = mock.Mock()
            job.folder = home/'project'
            job.folder.mkdir()
            with mock.patch.dict(server.JOBS, {'song':job}), mock.patch.object(server, 'store_image', return_value=source), \
                    mock.patch.object(server, 'keep_upload_name', return_value=source):
                status=maker_routes.apply_completed_reference(home,request,dict(state='done',files=[str(source)]))
                maker_routes.apply_completed_reference(home,request,status)
            job.edit_entity.assert_called_once()
            self.assertEqual(job.edit_entity.call_args.args[:2], ('upload',dict(id='doctor',image_origin='generated_edit')))
            self.assertTrue(status['reference_applied'])
            self.assertTrue(maker_routes.read_json(home/'history.json',[])[0]['reference_applied'])

    def test_completed_and_duplicate_requests_leave_queue(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(maker_routes,'running',None):
            home=Path(directory)
            done=dict(request_id='done',edit_target=dict(job='song',id='doctor'))
            waiting=dict(request_id='next',edit_target=dict(job='song',id='nurse'))
            maker_routes.write_json_atomic(home/'request.json',done)
            maker_routes.write_json_atomic(home/'queue.json',[done,waiting,dict(waiting,request_id='duplicate')])
            self.assertEqual(maker_routes.clean_queue(home,dict(state='done')),[waiting])

    def test_edit_progress_reaches_project_log_and_status(self):
        from studio import server
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            (home/'run.log').write_text('50%|#####     | 20/40 [00:23<00:22, 1.12s/it]',encoding='utf-8')
            job=mock.Mock(state={})
            with mock.patch.dict(server.JOBS,{'progress-song':job}):
                status=maker_routes.forward_progress(home,dict(edit_target=dict(job='progress-song',id='doctor',label='Doctor')),dict(state='painting'))
            self.assertEqual((status['step'],status['steps']),(20,40))
            self.assertIn('20/40',job.state['image_edit_status'])
            job.log.assert_called_once()

    def test_revising_waiting_edit_preserves_its_position_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);(home/'references').mkdir();(home/'references'/'face.png').write_bytes(b'original')
            old=dict(request_id='old',template='none',prompt='Old prompt',references=['face.png'],model=QWEN,width=512,height=512,folder=str(home),name='Doctor',edit_target=dict(job='song',id='doctor'))
            other=dict(request_id='other',name='Nurse',edit_target=dict(job='song',id='nurse'))
            maker_routes.write_json_atomic(home/'request.json',dict(request_id='active',edit_target=dict(job='song',id='patient')))
            maker_routes.write_json_atomic(home/'queue.json',[old,other])
            with mock.patch.object(maker_routes,'run_status'),mock.patch.object(maker_routes,'running',object()), \
                    mock.patch.object(maker_routes,'queue_watcher',None),mock.patch.object(maker_routes.threading,'Thread'), \
                    mock.patch.object(maker_routes,'stop_current') as stop:
                maker_routes.revise(home,dict(old,prompt='Revised prompt'),home)
            queued=maker_routes.read_json(home/'queue.json',[])
            self.assertEqual([r['name'] for r in queued],['Doctor','Nurse'])
            self.assertEqual(queued[0]['prompt'],'Revised prompt')
            self.assertEqual((Path(queued[0]['input_reference_folder'])/'face.png').read_bytes(),b'original')
            stop.assert_not_called()

    def test_legacy_request_keeps_its_label_prompt_and_sources(self):
        request = dict(name='Dr_Viktoria_edit', prompt='Change this picture', references=['Dr_Viktoria.png'])
        public = maker_routes.public_request(request)
        self.assertEqual(public['label'], 'Dr_Viktoria')
        self.assertEqual(public['prompt'], request['prompt'])
        self.assertEqual(public['references'], request['references'])
        self.assertTrue(maker_routes.is_edit(request))

    def test_restart_requeues_interrupted_request_without_losing_pending_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            maker_routes.write_json_atomic(home/'request.json', dict(request_id='first', prompt='First edit'))
            maker_routes.write_json_atomic(home/'queue.json', [dict(request_id='second', prompt='Second edit')])
            maker_routes.write_json_atomic(home/'status.json', dict(state='waiting'))
            with mock.patch.object(maker_routes, 'running', None), mock.patch.object(maker_routes, 'recovered_home', None), \
                    mock.patch('psutil.process_iter', return_value=[]):
                maker_routes.recover(home)
                maker_routes.recover(home)
            self.assertEqual([q['request_id'] for q in maker_routes.read_json(home/'queue.json', [])], ['first','second'])

    def test_restart_reattaches_surviving_worker_without_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            maker_routes.write_json_atomic(home/'request.json', dict(request_id='first'))
            maker_routes.write_json_atomic(home/'queue.json', [dict(request_id='first'), dict(request_id='second')])
            maker_routes.write_json_atomic(home/'status.json', dict(state='painting'))
            worker = mock.Mock(info=dict(cmdline=['python', '-m', 'artwork.maker', str(home/'request.json')]), pid=123)
            worker.is_running.return_value = True
            with mock.patch.object(maker_routes, 'running', None), mock.patch.object(maker_routes, 'recovered_home', None), \
                    mock.patch('psutil.process_iter', return_value=[worker]):
                maker_routes.recover(home)
                self.assertEqual(maker_routes.running.pid, 123)
                self.assertIsNone(maker_routes.running.poll())
            self.assertEqual([q['request_id'] for q in maker_routes.read_json(home/'queue.json', [])], ['second'])

    def test_distinct_edits_queue_with_frozen_inputs_and_reference_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home/'references').mkdir()
            (home/'references'/'face.png').write_bytes(b'original face')
            request = dict(template='none', prompt='Change @face.png', references=['face.png'], model=QWEN,
                           width=512, height=512, folder=str(home), name='second', edit_target=dict(job='song', id='second'))
            maker_routes.write_json_atomic(home/'request.json', dict(edit_target=dict(job='song', id='first')))
            maker_routes.write_json_atomic(home/'queue.json', [dict(name='ordinary', references=[])])
            with mock.patch.object(maker_routes, 'run_status', return_value=dict(state='waiting')), \
                    mock.patch.object(maker_routes, 'running', object()), \
                    mock.patch.object(maker_routes, 'queue_watcher', None), \
                    mock.patch.object(maker_routes.threading, 'Thread') as thread:
                maker_routes.start(home, request, home)
                queued = maker_routes.read_json(home/'queue.json', [])
                self.assertEqual([q['name'] for q in queued], ['second', 'ordinary'])
                (home/'references'/'face.png').write_bytes(b'changed library')
                self.assertEqual((Path(queued[0]['input_reference_folder'])/'face.png').read_bytes(), b'original face')
                with self.assertRaisesRegex(ValueError, 'already has an edit'):
                    maker_routes.start(home, request, home)
                self.assertEqual(len(maker_routes.read_json(home/'queue.json', [])), 2)
                thread.return_value.start.assert_called_once()

    def test_queue_advances_without_browser_polling(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            maker_routes.write_json_atomic(home/'queue.json', [dict(name='next')])
            with mock.patch.object(maker_routes, 'run_status'), mock.patch.object(maker_routes, 'running', None), \
                    mock.patch.object(maker_routes, 'launch') as launch, mock.patch.object(maker_routes.time, 'sleep'):
                maker_routes.watch_queue(home)
            launch.assert_called_once_with(home, dict(name='next'))
            self.assertEqual(maker_routes.read_json(home/'queue.json', []), [])


if __name__ == '__main__':
    unittest.main()
