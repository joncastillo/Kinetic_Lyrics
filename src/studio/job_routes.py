"""Routes that act on one job: story, scene lyrics, storyboard, clips, timings."""
import json
import shutil
import threading
from studio.job_clips import video_busy
from studio.lock import LOCK


# Actions on the AI video track, which never read the word timings (see _job_timings).
VIDEO_TRACK = ('animate', 'clip-effects', 'scene-scan')


class JobRoutes:
    def _job_pipeline_version(self, job, operation, args, files):
        """Select a node output or a saved whole-pipeline selection while workers are stopped."""
        from pipeline.versions import Versions
        from studio.pipeline_history import preserve_existing, working_files
        from artwork.reference_lifecycle import advance
        import time

        with LOCK:
            if (job.runs or job.state['status'] in ('queued', 'running', 'review') or job.state.get('action')
                    or job.state.get('queued_actions') or job.state.get('image_edit_status')):
                raise ValueError('Stop running work and clear queued actions before switching pipeline versions')
            preserve_existing(job.folder)
            history = Versions(job.folder)
            if args.get('initialize') is True:
                return self.respond(dict(ok=True, history=history.summary()))
            if 'sequence' in args:
                if type(args['sequence']) is not int:
                    raise ValueError('Choose a pipeline version')
                result = history.select(sequence=args['sequence'], extra_managed=working_files(job.folder))
            else:
                if type(args.get('version')) is not int or not isinstance(args.get('node'), str):
                    raise ValueError('Choose a node version')
                result = history.select(node=args['node'], version=args['version'], extra_managed=working_files(job.folder))
            # A checkpoint resumes mutable graph state, not the selected immutable outputs.
            # Retain it as history, and make the next run start from the selected files.
            for suffix in ('.sqlite', '.sqlite-wal', '.sqlite-shm'):
                checkpoint = job.folder/('video.graph'+suffix)
                if checkpoint.exists():
                    archive = job.folder/'pipeline'/'checkpoints'
                    archive.mkdir(exist_ok=True)
                    checkpoint.rename(archive/f'{time.time_ns()}{suffix}')
            advance(job.folder)
            job.command = None
            job.config = json.loads((job.folder/'config.json').read_text(encoding='utf-8'))
            job._pipeline_summary = None
            job.state.pop('active_manifest', None)
            complete = (job.folder/'video.mp4').is_file()
            job.state.update(status='complete' if complete else 'cancelled', stage='complete' if complete else 'saved',
                             percent=100 if complete else 0, dirty=[], timing_dirty=False,
                             message=f"Pipeline v{result['active']} selected")
            job.save()
        return self.respond(dict(ok=True, history=result))

    def _job_regenerate_new(self, job, body):
        """Copy the song into a new session that regenerates every image."""
        args=server.json_body(body)
        if not isinstance(args,dict) or not args.get('image_model'):
            raise ValueError('Reload the studio page to apply the selected image model')
        return self.respond(dict(id=server.regenerate_new_session(job,args.get('image_model')).folder.name), 201)

    def _job_cancel(self, job, body):
        """Stop the running work; the queue stays (see server.stop_job)."""
        with LOCK:
            job.state.pop('reference_resume_command', None)
        server.stop_job(job, keep_queue=True, background=True)
        return self.respond(dict(ok=True))

    def _job_rename(self, job, body):
        """Give the project a new name; its folder keeps the id."""
        name = str(server.json_body(body).get('name', '')).strip()[:80]
        if not name:
            raise ValueError('Give the project a name')
        with LOCK:
            job.config['name'] = name
            (job.folder/'config.json').write_text(json.dumps(job.config, indent=2), encoding='utf-8')
        return self.respond(dict(ok=True, name=name))

    def _job_delete(self, job, body):
        """Move the project into the output folder's .trash: the studio forgets it, the files stay recoverable by hand."""
        with LOCK:
            if job.state['status'] in ('queued', 'running') or job.state.get('action'):
                raise ValueError('Stop the job before deleting the project')
            server.JOBS.pop(job.folder.name, None)
        trash = server.ROOT/'.trash'
        trash.mkdir(exist_ok=True)
        target = trash/job.folder.name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(job.folder), str(target))
        return self.respond(dict(ok=True, trash=str(target)))


    def _job_story_reference(self, job, operation, args, files):
        """Add (a multipart upload, or JSON naming an earlier upload) or remove (JSON with its path) one of a story
        segment's reference images."""
        index = int(args.get('index', -1))
        upload = (files.get('reference') or [None])[0] if operation == 'story-reference' else None
        with LOCK:
            reuse = args.get('reuse') if operation == 'story-reference' else None
            message = job.segment_reference(index, upload, args.get('path') if upload is None and not reuse else None, reuse)
            job.save()
        return self.respond(dict(ok=True, message=message))

    def _job_story_upload_delete(self, job, operation, args, files):
        """Delete an earlier upload: JSON with its path from the storyline's `uploads`."""
        with LOCK:
            message = job.delete_upload(args.get('path'))
        return self.respond(dict(ok=True, message=message))

    def _job_clear_log(self, job, operation, args, files):
        """Empty the production log and the progress history the header chart is drawn from. The run goes on; new
        lines and progress points start from here."""
        with LOCK:
            job.state['logs'] = []
            job.state['history'] = []
            job.save()
        return self.respond(dict(ok=True, message='Log cleared.'))

    def _job_queue_remove(self, job, operation, args, files):
        """Take one item out of the queue: JSON {group, index} for an illustration's pill (images, animation, checks),
        or {group: 'song', action} for a song-wide task, or {group: 'references', entity} for one sheet. A clip waiting later in the running animation batch is
        skipped by the worker."""
        group, index = str(args.get('group') or ''), args.get('index')
        kinds = {'images': ('regenerate', 'reprompt'), 'animation': ('animate', 'clip-effects'),
                 'render': ('patch',), 'checks': ('verify', 'repair', 'patch')}.get(group)
        with LOCK:
            queued = job.state['queued_actions']
            if group == 'song':
                action = str(args.get('action') or '')
                job.state['queued_actions'] = [q for q in queued if q.get('action') != action]
                message = 'Removed from the queue.'
            elif group == 'references':  # one reference sheet's repaint
                entity = str(args.get('entity') or '')
                job.state['queued_actions'] = [q for q in queued if not (q.get('action') == 'reference' and q.get('entity') == entity)]
                message = 'Removed from the queue.'
            elif kinds is not None and isinstance(index, int):
                removed, kept = [], []
                for q in queued:
                    kind = q.get('action', 'regenerate')
                    if kind not in kinds:
                        kept.append(q)
                    elif q.get('indices'):
                        rest = [i for i in q['indices'] if i != index]
                        if len(rest) < len(q['indices']):
                            removed.append(q)
                        if rest:
                            kept.append(dict(q, indices=rest, index=rest[0]))
                    elif q.get('index') == index:
                        removed.append(q)
                    else:
                        kept.append(q)
                job.state['queued_actions'] = kept
                ids = [q.get('request_id') for q in removed if q.get('request_id')]
                if ids:
                    from artwork.queue import update_queue
                    update_queue(job.folder, remove=ids)
                if group == 'animation' and index in job.state.get('animating', []):
                    (job.clip_folder_for(index)/'skip').write_text('1', encoding='utf-8')  # the running worker skips it
                    job.state['animating'] = [i for i in job.state['animating'] if i != index]
                message = f'Illustration {index+1} removed from the queue.'
            else:
                raise ValueError('Choose an item in the queue')
            job.save()
        return self.respond(dict(ok=True, message=message))

    def _job_queue_run(self, job, operation, args, files):
        """Start the queue kept after a cancel."""
        with LOCK:
            if job.state.get('action') or job.state['status'] in ('running', 'queued'):
                raise ValueError('Work is already running')
            has_video = (job.folder/'video.mp4').exists()
            reference_work = any(q.get('action') == 'reference' for q in job.state.get('queued_actions', []))
            if not has_video and not reference_work:
                raise ValueError('The queue runs once the song has a video: resume the run first')
            job.cancelled = False
            job.state['status'] = 'complete' if has_video else 'review'
            job.save()
        job.start_next()
        return self.respond(dict(ok=True, message='Running the queue.'))

    def _job_story_entities(self, job, operation, args, files):
        """The references editor: JSON {op, entry} for save, add, remove, repaint and painted; a multipart upload
        (`picture` file, `id`) for upload."""
        upload = (files.get('picture') or [None])[0]
        if upload and args.get('regenerate_dependents') == 'true':
            from studio.reference_regeneration import details
            info = details(job, str(args.get('id') or ''))
            return self._job_reference_repaint(job, 'reference-repaint', dict(id=info['id'], revision=info['revision'],
                looks=info['looks'], prompt=info['prompt']), {}, selection=upload)
        op, entry = ('upload', dict(id=args.get('id'))) if upload else (str(args.get('op') or ''), args.get('entry') or {})
        if upload and args.get('force_use') == 'true':
            review = json.loads(args.get('force_review') or '{}')
            if not isinstance(review, dict):
                raise ValueError('Invalid checker result')
            entry.update(force_used=True, force_review=review)
        if not isinstance(entry, dict):
            raise ValueError('Invalid reference')
        with LOCK:
            message = job.edit_entity(op, entry, upload)
        return self.respond(dict(ok=True, message=message))

    def _job_story_entity(self, job, operation, args, files):
        """Tag (on=true) or untag one recurring reference for one image: JSON {index, id, on}."""
        index, entity_id = int(args.get('index', -1)), str(args.get('id') or '')
        if index < 0 or not entity_id:
            raise ValueError('Choose an image and a reference')
        with LOCK:
            message = job.tag_entity(index, entity_id, bool(args.get('on')))
        return self.respond(dict(ok=True, message=message, entity_references=job.entity_references()))

    def _job_reference_prompt(self, job, operation, args, files):
        from studio.reference_regeneration import details
        with LOCK:
            return self.respond(details(job, str(args.get('id') or '')))

    def _job_reference_input_upload(self, job, operation, args, files):
        uploads = files.get('reference') or []
        if not uploads or len(uploads) > 4:
            raise ValueError('Choose one to four reference pictures.')
        added = []
        for name, content in uploads:
            path = server.keep_upload_name(server.store_image(job.folder/'reference-inputs', name, content), name)
            added.append(dict(kind='upload', id=path.name, label=path.stem, role='detail', url=job.url(path)))
        return self.respond(dict(ok=True, added=added))

    def _job_reference_version(self, job, operation, args, files):
        from studio.reference_versions import discard_plan, mark_discarded
        from studio.reference_regeneration import details
        with LOCK:
            plan = discard_plan(job, args)
            replacement = plan['replacement']
            if replacement is None:
                mark_discarded(job, plan['id'], plan['paths'])
                return self.respond(dict(ok=True, message='Version discarded; the selected reference is unchanged.'))
            selected = (replacement.name, replacement.read_bytes())
            info = details(job, plan['id'])
        return self._job_reference_repaint(job, 'reference-repaint', dict(id=info['id'], revision=info['revision'],
            looks=info['looks'], prompt=info['prompt']), {}, selection=selected, discard_paths=plan['paths'])

    def _job_reference_repaint(self, job, operation, args, files, selection=None, discard_paths=()):
        from studio.reference_regeneration import prepare, commit
        if selection:
            import io
            from PIL import Image
            with Image.open(io.BytesIO(selection[1])) as image:
                image.verify()
        with LOCK:
            plan = prepare(job, args)  # reject bad inputs before stopping work or changing files
            active = set(job.state.get('active_images') or job.state.get('animating') or [])
            stop = job.state.get('status') in ('running', 'queued') or bool(
                job.state.get('action') and (job.state['action'] == 'reference' or active.intersection(plan['indices'])))
            resume = job.state.get('reference_resume_command')
            if job.state.get('status') == 'running' and not job.state.get('action') and getattr(job, 'command', None):
                resume = job.resume_command(job.command)
            interrupted = list(job.state.get('reference_batch') or []) if job.state.get('action') == 'reference' else []
        if stop:
            server.stop_job(job, keep_queue=True)
            import time
            deadline = time.monotonic()+5
            while getattr(job, 'runs', 0) and time.monotonic() < deadline:
                time.sleep(.02)
            if getattr(job, 'runs', 0):
                raise ValueError('The previous worker is still stopping. Retry regeneration in a moment.')
        with LOCK:
            plan = prepare(job, args)
            revision, archive = commit(job, plan)
            if selection:
                job.edit_entity('upload', dict(id=plan['entity_id']), selection)
            if discard_paths:
                from studio.reference_versions import mark_discarded
                from pathlib import Path
                retired = list(discard_paths)
                for original in discard_paths:
                    path = Path(original)
                    if path.is_relative_to(job.folder):
                        moved = archive/path.relative_to(job.folder)
                        if moved.is_file(): retired.append(str(moved.resolve()))
                mark_discarded(job, plan['entity_id'], retired)
            for index in plan['indices']:
                job.leave_animation(index)
            from artwork.queue import queue_path, update_queue
            path = queue_path(job.folder)
            if path.exists():
                pending = json.loads(path.read_text(encoding='utf-8'))
                update_queue(job.folder, remove=[item.get('request_id') for item in pending if item.get('index') in plan['indices']])
            job.state['queued_actions'] = [item for item in job.state['queued_actions']
                if not (item.get('action') == 'reference' and item.get('entity') in plan['affected'])
                and not (item.get('action') in ('regenerate','reprompt','verify','repair','animate','clip-effects','patch')
                         and item.get('index') in plan['indices'])]
            for item in interrupted:
                if item.get('entity') not in plan['affected'] and not any(
                        queued.get('action') == 'reference' and queued.get('entity') == item.get('entity')
                        for queued in job.state['queued_actions']):
                    job.state['queued_actions'].append(item)
            names = {e['id']: e['name'] for e in plan['story'].get('entities', [])}
            for entity_id in sorted(plan['affected'], key=lambda key: key != plan['entity_id']):
                job.state['queued_actions'].append(dict(action='reference', index=0, entity=entity_id,
                    name=names[entity_id], revision=revision,
                    images=plan['indices'] if entity_id == plan['entity_id'] else []))
            if stop or job.state['status'] not in ('running','review','complete'):
                job.cancelled = False
                job.state.update(status='complete' if (job.folder/'video.mp4').is_file() else 'review', action=None)
            if resume:
                job.state['reference_resume_command'] = resume
            job.log(f"Saved {plan['name']}'s description, prompt and inputs; regenerating {len(plan['affected'])} reference(s) and {len(plan['indices'])} dependent image(s).")
            job.save()
        job.start_next()
        message = (f"{'Previous reference restored' if discard_paths else 'Reference selected'}. Regenerating {len(plan['indices'])} dependent image(s)." if selection else
                   f"Saved. Regenerating {plan['name']}, its derived references and {len(plan['indices'])} dependent image(s).")
        return self.respond(dict(ok=True, message=message,
            entity_references=job.entity_references(), archive=str(archive)))

    def _job_reference_add(self, job, operation, args, files):
        """Add reference images to the project (a multipart upload of `reference` files); the next generation,
        replacement or verification uses them."""
        uploads = files.get('reference') or []
        if not uploads:
            raise ValueError('Choose a picture to add')
        for name, content in uploads[:6]:
            server.store_image(job.folder/'references', name, content)
        return self.respond(dict(ok=True, references=job.project_inputs()['references']))

    def _job_reference_remove(self, job, operation, args, files):
        """Drop one of the reference images kept with the project (JSON {url}), and every copy of the same picture;
        the next generation runs without it."""
        name = str(args.get('url', '')).split('?')[0].rsplit('/', 1)[-1]
        folder = job.folder/'references'
        path = folder/name
        if not name or '/' in name or '\\' in name or not path.is_file():
            raise ValueError('That reference image is not part of this project')
        digest = server.cached_digest(path)
        for copy in list(folder.iterdir()):
            try:
                if copy.is_file() and server.cached_digest(copy) == digest:
                    copy.unlink()
            except OSError:
                pass
        return self.respond(dict(ok=True, references=job.project_inputs()['references']))

    def _job_story_write(self, job, operation, args, files):
        """Queue the director to write (or rewrite) the storyline."""
        with LOCK:
            if not any(a.get('action') == 'story' for a in job.state['queued_actions']):
                job.state['queued_actions'].append(dict(action='story', index=0))
            job.log('Storyline queued to be written by the director model.')
            job.save()
        job.start_next()
        return self.respond(dict(ok=True, message='The storyline is queued; it appears here when written.'))

    def _job_story(self, job, operation, args, files):
        """Save the storyline panel, optionally making every image (and clip) again."""
        with LOCK:
            message = job.save_story(args.get('segments'))
            job.save()
        if args.get('regenerate'):
            threading.Thread(target=server.regenerate_from_story, args=(job,), daemon=True).start()
            message = 'Storyline saved. Stopping the current work and generating every image again.'
        return self.respond(dict(ok=True, message=message))







    def _job_settings(self, job, operation, args, files):
        """Save the Project panel's settings into this project as they are edited, without running anything: the
        effects, typography and stage pictures (checked as a rerender checks them), the story, the image direction and
        the style. Reopening the project restores them; the next generation or rerender starts from them."""
        from studio.render_settings import render_settings
        from core.files import write_text_atomic
        from direction.image_instruction_cleanup import clean_legacy_imported_meaning
        settings = render_settings(args, previous=job.config, defaults=dict(type_effect=job.config.get('type_effect', 'none')))
        text = {}
        for key, limit in (('story_prompt', 50000), ('image_instructions', 2000), ('theme', 2000), ('style_prompt', 4000)):
            if key in args:
                value = str(args[key] or '').strip()[:limit]
                text[key] = clean_legacy_imported_meaning(value) if key == 'image_instructions' else value
        if 'review_references' in args:  # read by the image step when it checks the reference pictures
            text['review_references'] = bool(args['review_references'])
        if 'repaint_references' in args:
            text['repaint_references'] = bool(args['repaint_references'])
        for key, limit in (('image_check_prompt', 12000), ('reference_check_prompt', 6000)):
            if key in args:  # '' means the built-in prompt
                text[key] = str(args[key] or '').strip()[:limit]
        if 'video_upscale' in args:  # read by the video step at the start of every animation job
            from studio.server import upscale_choice
            text['video_upscale'] = upscale_choice(args['video_upscale'])
        if 'end_frame_model' in args:  # read by the video step at the start of every animation job
            from studio.server import end_frame_choice
            text['end_frame_model'] = end_frame_choice(args['end_frame_model'])
        if 'end_frame_review' in args:
            text['end_frame_review'] = bool(args['end_frame_review'])
        if 'scene_direction' in args:
            from direction.scene_direction import scene_direction
            text['scene_direction'] = scene_direction(args['scene_direction'])
        if 'video_cinemagraph' in args:  # read by the video step at the start of every animation job
            from studio.server import cinemagraph_choice
            text['video_cinemagraph'] = cinemagraph_choice(args['video_cinemagraph'])
        if 'picture_kinds' in args:  # read by the video step at the start of every animation job
            from studio.server import picture_choice
            text['picture_kinds'] = picture_choice(args['picture_kinds'], bool(job.config.get('video_model')))
        if 'image_model' in args:
            from models.image.catalog import model_spec
            model = str(args['image_model'])
            model_spec(model)
            text['image_model'] = model
        with LOCK:
            job.config.update(settings, **text)
            write_text_atomic(job.folder/'config.json', json.dumps(job.config, indent=2))
        return self.respond(dict(ok=True))

    def _job_keep_picture(self, job, operation, args, files):
        """Keep or drop a 3D stage picture for the next render."""
        if not isinstance(args.get('key'), str) or len(args['key']) > 40:
            raise ValueError('Invalid picture')
        from direction.ornaments import set_picture_kept
        set_picture_kept(job.folder, args['key'], bool(args.get('keep', True)))
        return self.respond(dict(ok=True))


    def _job_timings(self, job, operation, args, files):
        """Save word timings edited in the timeline."""
        from pipeline.timing import validate
        from studio.timeline_data import song_duration, word_timings
        current_path = job.folder/'video.timings.json'
        updated = args.get('timings')
        if not isinstance(updated, list):
            raise ValueError('Supply lyric word timings')
        duration = song_duration(job.folder, job.config['audio'])
        draft = not current_path.is_file()
        if draft and (job.state['status'] == 'running' or job.state.get('action')):
            raise ValueError('Step 1: Timing is still running for this song; wait for it to finish or stop it first.')
        current = word_timings(job.folder, duration)
        validate(updated, [line['text'] for line in current], duration)
        lyrics = args.get('lyrics')
        if lyrics is not None:
            if not isinstance(lyrics, str):
                raise ValueError('Supply annotated lyrics as text')
            from pipeline.timing import normalized_newlines
            lyrics = normalized_newlines(lyrics)
            import re
            lines = [line.strip() for line in lyrics.splitlines() if line.strip()
                     and not re.fullmatch(r'\s*\[.*\]\s*', line)]
            if lines != [line['text'] for line in updated]:
                raise ValueError('Annotated lyrics must match the saved timing lines')
        if [[word['text'] for word in line['words']] for line in updated] != [[word['text'] for word in line['words']] for line in current]:
            raise ValueError('The timeline editor can change timing, not lyric text')
        # The AI video track (clips, their effects, the lyric-spot scan) does not read word timings: it keeps running,
        # and the kinetic text is re-rendered with the new timings after it. A run or render still being made would
        # finish with the old timings: stop it, save, and start it again.
        video_track = job.state.get('action') in VIDEO_TRACK and job.state['status'] == 'complete'
        restart = server.stop_video_work(job) if video_busy(job) and not video_track else None
        backup = job.folder/'video.timings.before-editor.json'
        if not backup.exists() and not draft:
            shutil.copy2(current_path, backup)
        temporary = job.folder/'video.timings.editing.json'
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(current_path)
        if lyrics is not None:
            from core.files import write_text_atomic
            write_text_atomic(job.folder/'lyrics.txt', lyrics)
        if draft:
            job.log('Word timings placed by hand in the timeline; restart from Step 2: Prompts to continue with them.')
            job.save()
            return self.respond(dict(ok=True, draft=True))
        job.state['timing_dirty'] = True
        if restart:
            server.restart_video_work(job, *restart)
            return self.respond(dict(ok=True, restarted=restart[0]))
        if video_track:
            with LOCK:
                if not any(a.get('action') == 'rerender' for a in job.state['queued_actions']):
                    job.state['queued_actions'].append(dict(action='rerender', index=0, reason='timings'))
                job.log('Word timings saved; the AI video carries on, and the kinetic text is re-rendered with them '
                        'once it finishes.')
                job.save()
            return self.respond(dict(ok=True, queued='rerender'))
        with LOCK:  # the kinetic text is re-rendered with the new timings by itself, as queued work
            if job.state['status'] == 'complete' and not any(a.get('action') == 'rerender' for a in job.state['queued_actions']):
                job.state['queued_actions'].append(dict(action='rerender', index=0, reason='timings'))
                job.log('Word timings edited in the timeline; the video is re-rendered with them (queued).')
            else:
                job.log('Word timings edited in the timeline; rebuild the video to apply them.')
            job.save()
        job.start_next()
        return self.respond(dict(ok=True, queued='rerender'))


# Last, because studio.server imports this module.
from studio import server  # noqa: E402
