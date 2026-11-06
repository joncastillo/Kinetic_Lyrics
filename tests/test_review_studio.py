"""Regression tests for the code review fixes in Studio and the model wrappers (see CODE_REVIEW.md)."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from studio import server  # noqa: E402


class FakeRequest:
    """Just enough of a request handler for Handler.trusted."""

    def __init__(self, headers, port=8765):
        self.headers = headers
        self.server = types.SimpleNamespace(server_address=('127.0.0.1', port))


class StudioGuardTest(unittest.TestCase):
    def trusted(self, **headers):
        return server.Handler.trusted(FakeRequest(headers))

    def test_only_this_computers_pages_are_trusted(self):
        self.assertTrue(self.trusted(Host='127.0.0.1:8765'))
        self.assertTrue(self.trusted(Host='localhost:8765', Origin='http://localhost:8765'))
        self.assertFalse(self.trusted(Host='evil.example:8765'))  # DNS rebinding
        self.assertFalse(self.trusted(Host='127.0.0.1:8765', Origin='http://evil.example'))
        self.assertFalse(self.trusted())  # no Host at all
        self.assertFalse(self.trusted(Host='127.0.0.1:9999'))

    def test_project_ids_stay_inside_the_output_folder(self):
        self.assertEqual(server.project_folder('20260101-120000-abc123'), server.ROOT / '20260101-120000-abc123')
        for bad in ('..', '../x', '..\\x', 'C:/Windows', '/etc', 'a/b', '', 'x' * 81):
            with self.assertRaises(ValueError, msg=bad):
                server.project_folder(bad)

    def test_request_bodies_must_be_json_objects(self):
        self.assertEqual(server.json_body(b'{"index": 1}'), {'index': 1})
        for body in (b'[1]', b'"text"', b'null', b'nope'):
            with self.assertRaises(ValueError):
                server.json_body(body)


class RenderSettingsTest(unittest.TestCase):
    def test_new_job_and_rerender_share_one_set_of_rules(self):
        from studio.render_settings import render_settings

        fresh = render_settings({'particle_intensity': '1.5', 'text_animation': 'fade'})
        self.assertEqual(
            (fresh['particle_intensity'], fresh['text_animation'], fresh['type_effect']), (1.5, 'fade', 'mixed')
        )
        saved = dict(fresh, particle_speed=2.0)
        rerender = render_settings({'audio_mode': 'karaoke'}, previous=saved)
        self.assertEqual(
            (rerender['particle_speed'], rerender['audio_mode'], rerender['text_animation']), (2.0, 'karaoke', 'fade')
        )
        for bad in (
            {'particle_intensity': 3},
            {'particle_intensity': None},
            {'particle_speed': 'fast'},
            {'audio_mode': 'loud'},
            {'stage_pictures': 'gallery'},
            {'type_effect': 'sparkles'},
            {'entrance_effect': 'no-such-effect'},
            {'exit_pool': '["no-such-exit"]'},
        ):
            with self.assertRaises(ValueError, msg=bad):
                render_settings(bad, previous=saved)


class LocalStudio:
    """The real request handler on a local port, with one job in it."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer

        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.job = server.Job(Path(self.folder.name), dict(name='Song'))
        server.JOBS['test-song'] = self.job
        self.addCleanup(server.JOBS.pop, 'test-song', None)

    def request(self, path, body=b'{}', host=None, token=True, method='POST'):
        import http.client
        import json

        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'Host': host or f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if token:
            headers['X-Studio-Token'] = server.TOKEN
        connection.request(method, path, body=body if method == 'POST' else None, headers=headers)
        response = connection.getresponse()
        data = json.loads(response.read() or b'{}')
        connection.close()
        return response.status, data


class StudioHttpTest(LocalStudio, unittest.TestCase):
    """Guards, token, the route tables and the image-operation fallback."""

    def test_guards(self):
        self.assertEqual(self.request('/api/jobs/test-song/cancel', host='evil.example')[0], 403)
        self.assertEqual(self.request('/api/jobs/test-song/cancel', token=False)[0], 403)
        self.assertEqual(self.request('/api/config', host='evil.example', method='GET')[0], 403)

    def test_routes(self):
        status, data = self.request('/api/jobs/no-such-song/cancel')
        self.assertEqual(status, 400)  # unknown job
        status, data = self.request('/api/jobs/test-song/keep-picture', b'[1, 2]')
        self.assertEqual((status, data['error']), (400, 'The request body must be a JSON object'))
        status, data = self.request('/api/jobs/test-song/keep-picture', b'{"key": 5}')
        self.assertEqual((status, data['error']), (400, 'Invalid picture'))  # reached its route method
        self.job.state['status'] = 'queued'
        status, data = self.request('/api/jobs/test-song/no-such-operation')
        self.assertEqual(status, 400)  # the image-operation fallback rejects it
        status, data = self.request('/api/jobs/test-song/cancel')
        self.assertEqual((status, data), (200, dict(ok=True)))
        self.assertEqual(self.job.state['status'], 'cancelled')

    def test_clear_log_empties_the_log_and_the_progress_history(self):
        self.job.log('one line')
        self.job.state['history'] = [[1.0, 5], [2.0, 10]]
        status, data = self.request('/api/jobs/test-song/clear-log')
        self.assertEqual((status, data['ok']), (200, True))
        self.assertEqual((self.job.state['logs'], self.job.state['history']), ([], []))
        self.job.log('after')
        self.assertEqual([l['text'] for l in self.job.snapshot(cursor=0)['logs']], ['after'], 'the log goes on from here')

    def test_get_routes(self):
        status, songs = self.request('/api/job-list', method='GET')
        self.assertEqual(status, 200)
        self.assertIn(Path(self.folder.name).name, [s['id'] for s in songs['jobs']])  # listed by folder name
        status, snapshot = self.request('/api/jobs/test-song', method='GET')
        self.assertEqual((status, snapshot['id']), (200, Path(self.folder.name).name))
        self.assertEqual(self.request('/files/test-song/../../secret.json', method='GET')[0], 404)
        self.assertEqual(self.request('/no/such/page', method='GET')[0], 404)

    def test_files_stream_whole_and_with_ranges(self):
        import http.client

        content = bytes(range(256)) * 9000  # a little over two 1 MiB chunks
        (Path(self.folder.name) / 'video.mp4').write_bytes(content)
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        connection.request('GET', '/files/test-song/video.mp4', headers={'Host': f'127.0.0.1:{self.port}'})
        self.assertEqual(connection.getresponse().read(), content)
        connection.request(
            'GET',
            '/files/test-song/video.mp4',
            headers={'Host': f'127.0.0.1:{self.port}', 'Range': 'bytes=1048570-1048590'},
        )
        response = connection.getresponse()
        self.assertEqual((response.status, response.read()), (206, content[1048570:1048591]))
        connection.close()

    def test_every_route_points_at_a_handler_method(self):
        for table in (server.POST_ROUTES, server.JOB_ROUTES_RAW, server.JOB_ROUTES, server.IMAGE_OPERATIONS, server.SLOT_OPERATIONS):
            for name, method in table.items():
                self.assertIs(getattr(server.Handler, method.__name__), method, name)
        for matches, method in server.GET_ROUTES:
            self.assertIs(getattr(server.Handler, method.__name__), method)


class ImageOperationGuardTest(LocalStudio, unittest.TestCase):
    """Image operation guards in the order they run. Each request fails at exactly one."""

    def setUp(self):
        import json

        super().setUp()
        manifest = Path(self.folder.name) / 'illustrations' / 'job.json'
        manifest.parent.mkdir()
        manifest.write_text(json.dumps(dict(prompts=['a', 'b'])), encoding='utf-8')
        for name, value in (('manifest', lambda job: manifest), ('rejected_selections', lambda job: [])):
            patcher = mock.patch.object(server.Job, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.job.state.update(status='review', action=None, queued_actions=[], dirty=[])

    @property
    def image_model(self):
        return server.MODELS[0]['id']

    def error(self, operation, **args):
        import json

        status, data = self.request(f'/api/jobs/test-song/{operation}', json.dumps(args).encode())
        self.assertEqual(status, 400, data)
        return data['error']

    def test_text_limits(self):
        self.assertIn('32,768', self.error('regenerate', prompt='x' * 40000))
        self.assertIn('4,000', self.error('reprompt', style='x' * 5000))

    def test_busy_job_queues_regeneration_and_review(self):
        import json

        self.job.state.update(status='running', action='verify')
        self.assertIn('Reload the studio page', self.error('regenerate', index=0))
        self.assertEqual(self.error('regenerate', index=2, image_model='m'), 'Invalid illustration index')
        with mock.patch('artwork.queue.update_queue'), mock.patch.object(server.Job, 'save'):
            status, data = self.request(
                '/api/jobs/test-song/regenerate', json.dumps(dict(index=1, image_model=self.image_model, prompt='p')).encode()
            )
        self.assertEqual((status, data), (200, dict(ok=True, queued=True)))
        self.assertEqual(self.job.state['queued_actions'][-1]['index'], 1)
        self.job.state.update(status='review')
        self.assertIn('vision model', self.error('verify', index=0))
        self.assertEqual(self.error('verify', index=5, model='v'), 'Invalid illustration index')
        self.assertIn('Review threshold', self.error('verify', index=0, model='v', review_threshold=101))
        with mock.patch.object(server.Job, 'save'):
            status, data = self.request('/api/jobs/test-song/verify', b'{"index": 0, "model": "v"}')
        self.assertEqual((status, data), (200, dict(ok=True, queued=True)))
        self.assertEqual(self.job.state['queued_actions'][-1], dict(action='verify', index=0, model='v'))

    def test_order_of_the_guards(self):
        self.job.state['action'] = 'patch'
        self.assertEqual(self.error('approve'), 'Wait for the current image operation to finish')
        self.job.state.update(action=None, status='queued')
        self.assertIn('artwork review', self.error('approve'))
        self.job.state['status'] = 'review'
        other = server.Job(Path(self.folder.name), dict(name='Other'))
        other.state['status'] = 'running'
        server.JOBS['other-song'] = other
        try:
            self.assertIn('Another job is active', self.error('approve'))
        finally:
            server.JOBS.pop('other-song')
        with mock.patch.object(server.Job, 'rejected_selections', lambda job: [0, 2]):
            self.assertIn('Illustrations 1, 3 are below', self.error('approve'))
        self.job.state['queued_actions'] = [dict(action='patch', index=0)]
        self.assertIn('queued image regenerations', self.error('approve'))
        self.job.state.update(queued_actions=[], status='complete')
        self.assertEqual(self.error('approve'), 'This job is not waiting for review')
        self.assertIn('Review threshold', self.error('verify-all', review_threshold='high'))
        self.assertIn('Automatic repair', self.error('verify-all', review_threshold=50, auto_repair='yes'))
        self.assertIn('vision model', self.error('verify-all'))
        self.job.state['queued_actions'] = [dict(action='patch', index=0)]
        self.assertIn('Wait for the current video', self.error('rerender'))
        self.job.state.update(queued_actions=[], status='review')
        self.assertIn('after the first video completes', self.error('rebuild'))
        self.assertEqual(self.error('select', index=2), 'Invalid illustration index')
        self.assertEqual(self.error('no-such-operation', index=0), 'Unknown operation')
        self.assertIn('after the video completes', self.error('patch', index=0))
        self.job.state['status'] = 'complete'
        self.assertIn('vision model', self.error('verify', index=0))

    def test_approve_continues_the_render(self):
        status, data = self.request('/api/jobs/test-song/approve')
        self.assertEqual((status, data), (200, dict(ok=True)))
        self.assertEqual(self.job.state['status'], 'running')
        self.assertTrue((Path(self.folder.name) / 'artwork-approved').exists())

    def test_worker_operations_start_the_worker(self):
        import queue

        started = queue.Queue()
        self.job.state['status'] = 'complete'
        with mock.patch.object(server.Job, 'run', lambda job, command, action=None: started.put((command, action))):
            status, data = self.request('/api/jobs/test-song/patch', b'{"index": 1}')
            command, operation = started.get(timeout=10)
        self.assertEqual((status, data), (200, dict(ok=True)))
        self.assertEqual((operation, command[-4:]), ('patch', ['patch', self.folder.name, '--index', '1']))
        self.assertEqual(self.job.state['action'], 'patch')


class StartJobTest(unittest.TestCase):
    """start_job: a new run, its checks, and restarts that keep or redo saved work."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, self.root, True)
        self.started = []
        for target, name, value in (
            (server, 'ROOT', self.root),
            (server, 'JOBS', {}),
            (server.Job, 'run', lambda job, command, action=None: self.started.append(command)),
            (server.threading, 'Thread', lambda target, args, daemon: types.SimpleNamespace(start=lambda: target(*args))),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def start(self, files=None, **fields):
        fields = dict(dict(lyrics='la la' + chr(10) + 'la', randomize_seed='off', image_seed='7'), **fields)
        return server.start_job(fields, {'audio': [('Song.mp3', b'tune')]} if files is None else files)

    def config(self, job):
        import json

        return json.loads((job.folder / 'config.json').read_text(encoding='utf-8'))

    def test_resuming_protected_existing_timings_keeps_images_and_line_breaks(self):
        first = self.start()
        first.state['status'] = 'complete'
        timings = [dict(text='la la', words=[]), dict(text='la', words=[])]
        (first.folder/'video.timings.json').write_text(__import__('json').dumps(timings), encoding='utf-8')
        with mock.patch('pipeline.timing.imported_timings', return_value=timings), \
                mock.patch('pipeline.timing.validate'), mock.patch('core.media.media_duration', return_value=30), \
                mock.patch.object(server, 'clear_redone_work') as clear:
            job = self.start(files={}, project_id=first.folder.name, start_step='images', resume='1',
                             protect_word_alignment='on', lyrics='la la\r\nla')
        clear.assert_not_called()
        self.assertEqual(job.config['start_step'], 'images')
        self.assertEqual(job.config['image_seed'], 7)
        self.assertIn('gallery_since', job.config)
        self.assertNotIn(b'\r\r\n', (job.folder/'lyrics.txt').read_bytes())

    def test_a_new_run(self):
        job = self.start()
        config = self.config(job)
        self.assertEqual(job.folder.parent, self.root)
        self.assertIs(server.JOBS[job.folder.name], job)
        self.assertEqual((job.folder / 'Song.mp3').read_bytes(), b'tune')
        self.assertEqual((job.folder / 'lyrics.txt').read_text(encoding='utf-8'), 'la la' + chr(10) + 'la')
        self.assertEqual(
            {k: config[k] for k in ('name', 'audio_name', 'width', 'height', 'image_seed', 'randomize_seed', 'start_step',
                                    'illustration_lines', 'artwork_mode', 'project_id', 'encoder')},
            dict(name='Song', audio_name='Song.mp3', width=1280, height=720, image_seed=7, randomize_seed=False,
                 start_step='beginning', illustration_lines='auto', artwork_mode='cutout', project_id=job.folder.name,
                 encoder='h264_nvenc'),
        )
        self.assertIn('gallery_since', config)
        self.assertEqual(job.state['status'], 'queued')  # running once its process starts
        self.assertIn(str(job.folder / 'Song.mp3'), self.started[0])

    def test_checks(self):
        cases = [
            (dict(files={}), 'Choose an audio file'),
            (dict(files={'audio': [('song.txt', b'x')]}), 'Unsupported or empty audio file'),
            (dict(steps='0'), 'Steps must be'),
            (dict(lines='99'), 'Steps must be'),
            (dict(image_model='no-such-model'), 'Choose a supported image model'),
            (dict(artwork_mode='odd'), 'Invalid artwork mode'),
            (dict(encoder='odd'), 'Invalid encoder'),
            (dict(review_threshold='101'), 'Review threshold'),
        ]
        for fields, message in cases:
            with self.subTest(message=message, fields=fields), self.assertRaises(ValueError) as caught:
                self.start(**fields)
            self.assertIn(message, str(caught.exception))
        job = self.start()
        with self.assertRaises(ValueError) as caught:
            self.start()
        self.assertIn('Finish or cancel the active job', str(caught.exception))
        job.state['status'] = 'complete'
        job.runs = 1
        with self.assertRaises(ValueError) as caught:
            self.start(project_id=job.folder.name, start_step='images', files={})
        self.assertIn('still stopping', str(caught.exception))

    def restarted(self, **fields):
        first = self.start()
        first.state['status'] = 'complete'
        (first.folder / 'video.timings.json').write_text('[]', encoding='utf-8')
        with mock.patch('artwork.active.archive_images') as archive:
            job = self.start(project_id=first.folder.name, image_seed='', **dict(dict(start_step='images', files={}), **fields))
        self.assertIs(job, first)
        self.assertEqual(job.state['status'], 'running')  # a restart starts from a clean state
        job.state['status'] = 'complete'
        return job, archive

    def test_a_restart_reuses_saved_work(self):
        job, archive = self.restarted()
        config = self.config(job)
        self.assertEqual((config['start_step'], config['image_seed'], config['audio_name']), ('images', 7, 'Song.mp3'))
        archive.assert_called_once()
        self.assertTrue((job.folder / 'video.timings.json').exists())
        self.assertEqual(len(self.started), 2)

    def test_edited_lyrics_or_new_audio_redo_the_timing(self):
        job, archive = self.restarted(lyrics='new words')
        self.assertEqual(self.config(job)['start_step'], 'timing')
        self.assertFalse((job.folder / 'video.timings.json').exists())
        archive.assert_not_called()
        job, archive = self.restarted(files={'audio': [('Other.wav', b'other tune')]})
        self.assertEqual(self.config(job)['start_step'], 'timing')
        self.assertEqual([p.name for p in server.project_audio(job.folder)], ['Other.wav'])
        self.assertIn('New audio track', job.state['logs'][-1]['text'])


class PipelineCommandTest(unittest.TestCase):
    def config(self, **changes):
        from studio.render_settings import render_settings

        config = dict(
            theme='-moody night',
            style_prompt='ink',
            image_instructions='',
            image_cache='C:/cache',
            reference_use='style',
            vision_model='',
            artwork_mode='fullscreen',
            image_seed=7,
            image_model='m',
            encoder='libx264',
            asr_model='a',
            alignment_model='auto',
            instructions='',
            auto_accept=True,
            video_model='',
            language='',
            cinematic=False,
        )
        config.update(render_settings({}))
        config.update(changes)
        return config

    def build(self, folder, config, **options):
        values = dict(
            width=1280, height=720, steps=20, lines='2', ai_model='auto', is_restart=False, start_step='beginning'
        )
        values.update(options)
        return server.pipeline_command(config, folder, folder / 'audio.mp3', 'one' + chr(10) + 'two', [], **values)

    def test_new_run(self):
        with tempfile.TemporaryDirectory() as folder:
            command = self.build(Path(folder), self.config())
        self.assertIn('--theme=-moody night', command)  # free text stays one value
        self.assertIn('--no-default-style-references', command)
        self.assertNotIn('--overwrite', command)

    def test_long_story_prompt_writes_file_for_command(self):
        long_tale = "Long story segment " * 300  # > 5000 characters
        with tempfile.TemporaryDirectory() as folder:
            folder_path = Path(folder)
            command = self.build(folder_path, self.config(story_prompt=long_tale))
            story_flag = [arg for arg in command if arg.startswith('--story=')][0]
            story_file_arg = story_flag.split('=', 1)[1]
            self.assertEqual(story_file_arg, str(folder_path / 'story.txt'))
            self.assertEqual((folder_path / 'story.txt').read_text(encoding='utf-8'), long_tale)

    def test_restart_reuses_saved_work_and_keeps_edited_lyrics_in_timed_lines(self):
        import json

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'video.timings.json').write_text(
                json.dumps([dict(text='one'), dict(text='two')]), encoding='utf-8'
            )
            (folder / 'video.design.json').write_text(json.dumps(dict(scenes=[{}, {}])), encoding='utf-8')
            command = self.build(folder, self.config(), is_restart=True, start_step='render')
            self.assertEqual(command[command.index('--timings') + 1], str(folder / 'video.timings.json'))
            self.assertEqual(command[command.index('--plan') + 1], str(folder / 'video.design.json'))
            self.assertIn('--overwrite', command)
            self.assertTrue((folder / 'lyrics.txt').is_file())


class ReplaceFileTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'only Windows refuses to replace an open file')
    def test_replace_waits_for_a_reader_to_let_go(self):
        import threading
        from core.files import replace_file

        with tempfile.TemporaryDirectory() as folder:
            target, new = Path(folder) / 'video.mp4', Path(folder) / 'video.new.mp4'
            target.write_bytes(b'old')
            new.write_bytes(b'new')
            reader = open(target, 'rb')  # like Studio streaming the old video
            threading.Timer(0.4, reader.close).start()
            replace_file(new, target, delay=0.1)
            self.assertEqual(target.read_bytes(), b'new')


class StudioJobTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.job = server.Job(Path(self.folder.name), dict(name='Song'))

    def test_each_queued_section_rebuild_runs_on_its_own(self):
        started = []
        self.job.state.update(
            status='complete', queued_actions=[dict(action='patch', index=2), dict(action='patch', index=5)]
        )
        with mock.patch.object(
            server.threading,
            'Thread',
            lambda target, args, daemon: types.SimpleNamespace(start=lambda: started.append(args)),
        ):
            self.job.start_next()
        command = started[0][0]
        self.assertEqual(command[command.index('--index') + 1], '2')
        self.assertNotIn('--batch', command)
        self.assertEqual(self.job.state['queued_actions'], [dict(action='patch', index=5)])  # not dropped

    def test_free_text_is_passed_as_one_value(self):
        started = []
        self.job.state.update(
            status='complete', queued_actions=[dict(action='regenerate', index=0, prompt='-moody night')]
        )
        with (
            mock.patch.object(
                server.threading,
                'Thread',
                lambda target, args, daemon: types.SimpleNamespace(start=lambda: started.append(args)),
            ),
            mock.patch('artwork.queue.update_queue'),
        ):
            self.job.start_next()
        self.assertIn('--prompt=-moody night', started[0][0])

    def test_saved_state_is_written_whole(self):
        self.job.state['message'] = 'ünïcode'
        self.job.save()
        files = sorted(p.name for p in Path(self.folder.name).iterdir())
        self.assertEqual(files, ['state.json'])
        import json

        self.assertEqual(
            json.loads((Path(self.folder.name) / 'state.json').read_text(encoding='utf-8'))['message'], 'ünïcode'
        )

    def test_a_failed_edit_leaves_a_stopped_job_stopped(self):
        self.job.state['status'], self.job.cancelled = 'cancelled', True
        with self.assertRaises(ValueError):
            with server.editable_stopped_job(self.job, True):
                self.assertEqual(self.job.state['status'], 'complete')
                raise ValueError('bad index')
        self.assertEqual((self.job.state['status'], self.job.cancelled), ('cancelled', True))
        with server.editable_stopped_job(self.job, True):
            pass
        self.assertEqual(self.job.state['status'], 'complete')

    def test_a_restarted_song_starts_from_a_clean_state(self):
        fresh = server.Job.initial_state(Path(self.folder.name), dict(name='Song'))
        self.assertEqual(fresh['history'], [])
        self.assertNotIn('auto_review_queued', fresh)


class ModelWrapperTest(unittest.TestCase):
    def test_gpu_chat_honours_the_callers_keep_alive(self):
        from models.ollama import gpu

        sent = []

        def local_json(endpoint, payload=None, timeout=5):
            if endpoint == 'ps':
                return dict(models=[dict(name='vl', size=10, size_vram=10)])
            sent.append(payload)
            return dict(message=dict(content='{}'))

        with (
            mock.patch('models.ollama.service.local_json', local_json),
            mock.patch.object(gpu, 'ensure_loaded', return_value={}),
            mock.patch('models.gpu.lifecycle.current_session', return_value=object()),
            mock.patch('models.ollama.trace.log_request'),
            mock.patch('models.ollama.trace.log_response'),
        ):
            gpu.gpu_chat('chat', dict(model='vl', messages=[dict(role='user', content='hi')], keep_alive='30m'))
            gpu.gpu_chat('chat', dict(model='vl', messages=[dict(role='user', content='hi')]))
        self.assertEqual([p['keep_alive'] for p in sent], ['30m', -1])

    def test_image_generation_does_not_start_ollama(self):
        from models.gpu import lifecycle

        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(empty_cache=lambda: None, memory_reserved=lambda: 0)
        )
        session = lifecycle.ModelSession()
        with (
            mock.patch.dict(sys.modules, torch=fake_torch),
            mock.patch.object(lifecycle.gpu_memory, 'dedicated_memory', return_value=(0, 24 * 2**30)),
            mock.patch('models.ollama.service.ready', return_value=False),
            mock.patch('models.ollama.service.local_json', side_effect=AssertionError('Ollama was contacted')),
        ):
            session.before_generation('black-forest-labs/FLUX.2-klein-4B')
        self.assertEqual(session.phase, ('generation', 'black-forest-labs/FLUX.2-klein-4B'))

    def test_model_cleanup_reports_instead_of_raising(self):
        import contextlib
        import io
        from models.ollama import gpu

        out = io.StringIO()
        with (
            mock.patch.object(gpu, 'unload_model', side_effect=OSError('connection refused')),
            contextlib.redirect_stdout(out),
        ):
            gpu.release_model('qwen3:8b', 'effect model')  # must not raise from a finally block
        self.assertIn('effect model cleanup (qwen3:8b): connection refused', out.getvalue())

    def test_ocr_scores_given_as_text_are_compared_as_numbers(self):
        from PIL import Image
        from models.ocr.lettering import detected_lettering

        ocr = lambda array: ([(None, 'HELLO WORLD', '0.95'), (None, 'faint', '0.2')], None)  # noqa: E731
        readings = detected_lettering(ocr, Image.new('RGB', (8, 8)))
        self.assertEqual([r['text'] for r in readings], ['HELLO WORLD'])


if __name__ == '__main__':
    unittest.main()
