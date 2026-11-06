"""Image work on a job's illustrations: regenerate, verify, select, approve, rebuild."""
from core.process import module_command
import json
from pathlib import Path
import shutil
import threading
import time
from models.vision.policy import rejected, DEFAULT_THRESHOLD
from core.files import content_digest
from studio.render_settings import render_settings
from studio.lock import LOCK


class ImageOperations:
    def _job_image_operation(self, job, operation, args, files, saved_video):
        """Image work on one illustration or the whole set.

        A busy job queues regenerate and verify. Otherwise check_image_change runs, then the operation's
        method: IMAGE_OPERATIONS for the set, SLOT_OPERATIONS for one illustration, the worker for the rest."""
        if operation in ('regenerate','reprompt') and (not isinstance(args.get('prompt',''),str) or len(args.get('prompt',''))>32768):
            raise ValueError('The generation prompt must be text no longer than 32,768 characters')
        if operation in ('regenerate','reprompt') and (not isinstance(args.get('style',''),str) or len(args.get('style',''))>4000):
            raise ValueError('The art style must be text no longer than 4,000 characters')
        with LOCK, server.editable_stopped_job(job, saved_video):
            if operation in ('regenerate','reprompt') and (job.state['status'] == 'running' or job.state['action']):
                return self._image_queue_regeneration(job, operation, args)
            if operation == 'verify' and (job.state['action'] or job.state['status'] in ('running', 'queued')):
                return self._image_queue_review(job, args)  # checked as soon as the GPU is free
            if operation == 'discard':  # tidying a file nobody uses: allowed whatever runs
                return self._image_discard(job, args)
            check_image_change(job, operation, saved_video)
            if operation in ('verify','verify-all') and 'review_threshold' in args:
                save_review_settings(job, args)
            if operation in IMAGE_OPERATIONS:
                return IMAGE_OPERATIONS[operation](self, job, args, saved_video)
            index = int(args.get('index', -1))
            manifest = job.manifest()
            count = len(json.loads(manifest.read_text(encoding='utf-8'))['prompts'])
            if not 0 <= index < count:
                raise ValueError('Invalid illustration index')
            target = manifest.parent/f'{index:03d}.png'
            return SLOT_OPERATIONS.get(operation, ImageOperations._image_run_worker)(self, job, operation, args, files, index, manifest, target)

    def _image_discard(self, job, args):
        """Delete one alternative picture of an illustration: a candidate or an earlier version, never the picture
        in use or its raw painting. A candidate waiting for review stops waiting."""
        index = int(args.get('index', -1))
        manifest = job.manifest()
        count = len(json.loads(manifest.read_text(encoding='utf-8'))['prompts'])
        if not 0 <= index < count:
            raise ValueError('Invalid illustration index')
        target = manifest.parent/f'{index:03d}.png'
        path = server.checked_file(job, str(args.get('path') or ''))
        discard_variant(job.folder, path, keep=(target, target.with_suffix('.raw.png')))
        from artwork.queue import replacement_review_path, settle_replacement_review
        try:
            waiting = json.loads(replacement_review_path(job.folder).read_text(encoding='utf-8')).get('candidates', [])
        except (OSError, ValueError):
            waiting = []
        if any(c.get('index') == index and Path(str(c.get('path') or '')).resolve() == path for c in waiting):
            settle_replacement_review(job.folder, index)
        getattr(job, '_image_fingerprints', {}).pop(path, None)
        job.log(f'Illustration {index+1}: an alternative picture was deleted ({path.name}).')
        return self.respond(dict(ok=True, message='Alternative picture deleted.'))

    def _image_queue_regeneration(self, job, operation, args):
        """Queues a regeneration for the next GPU review pause while the job is busy."""
        if not args.get('image_model'):
            raise ValueError('Reload the studio page to apply the selected image model')
        index = int(args.get('index', -1))
        count = len(json.loads(job.manifest().read_text(encoding='utf-8'))['prompts'])
        if not 0 <= index < count:
            raise ValueError('Invalid illustration index')
        job.queue_generation(index,operation,str(args.get('prompt','')),str(args.get('model') or job.config.get('ai_model','auto')),args.get('image_model'),args.get('style'),args.get('steps'))
        job.log(f'Illustration {index+1} regeneration queued for the next GPU review pause.')
        job.save()
        return self.respond(dict(ok=True, queued=True))

    def _image_queue_review(self, job, args):
        """Queues a verify behind the running operation."""
        if not args.get('model'):
            raise ValueError('Choose an installed Ollama vision model')
        index = int(args.get('index', -1))
        if not 0 <= index < len(json.loads(job.manifest().read_text(encoding='utf-8'))['prompts']):
            raise ValueError('Invalid illustration index')
        threshold = args.get('review_threshold', job.config.get('review_threshold', DEFAULT_THRESHOLD))
        if type(threshold) is not int or not 0 <= threshold <= 100:
            raise ValueError('Review threshold must be an integer from 0 to 100')
        job.config.update(review_threshold=threshold, auto_repair=bool(args.get('auto_repair', job.config.get('auto_repair', True))))
        (job.folder/'config.json').write_text(json.dumps(job.config, indent=2), encoding='utf-8')
        edited = {k: ' '.join(str(args[k]).split()) if k == 'style' else str(args[k]).strip()
                  for k in ('prompt', 'style') if isinstance(args.get(k), str) and args[k].strip()}
        if 'prompt' in edited:edited['user_prompt'] = edited.pop('prompt')
        # A picture other than the selected one is named; the selected one is whichever is selected when its turn comes.
        if args.get('path'):
            chosen = server.checked_file(job, args['path'])
            if chosen.resolve() != (job.manifest().parent/f'{index:03d}.png').resolve():
                edited['candidate'] = str(chosen)
        same = lambda a: (a.get('action') == 'verify' and a.get('index') == index
                          and a.get('candidate') == edited.get('candidate'))
        # asked again for the same picture: the newest edits are the ones to check
        job.state['queued_actions'] = [a for a in job.state['queued_actions'] if not same(a)]
        job.state['queued_actions'].append(dict(action='verify', index=index, model=args['model'], **edited))
        job.log(f'Illustration {index+1} review queued after the current image operation.')
        job.save()
        return self.respond(dict(ok=True, queued=True))

    def _image_approve(self, job, args, saved_video):
        """Approves the artwork so the render continues."""
        if job.state['queued_actions']:
            raise ValueError('Wait for queued image regenerations to finish')
        if job.state['status'] != 'review':
            raise ValueError('This job is not waiting for review')
        job.state.update(status='running', message='Artwork approved; continuing render', dirty=[])
        from artwork.queue import replacement_review_path
        replacement_review_path(job.folder).unlink(missing_ok=True)
        (job.folder/'artwork-approved').touch()
        return self.respond(dict(ok=True))

    def _image_verify_all(self, job, args, saved_video):
        """Queues every illustration for review."""
        if not args.get('model'):
            raise ValueError('Choose an installed vision model first')
        job.queue_reviews(args['model'])
        job.start_next()
        job.save()
        return self.respond(dict(ok=True,queued=True))

    def _image_rerender(self, job, args, saved_video):
        """Rebuilds the finished video with new render settings."""
        if (job.state['status'] != 'complete' and not saved_video) or job.state['queued_actions']:
            raise ValueError('Wait for the current video and queued operations to finish')
        if saved_video:
            job.cancelled = False
            job.state['status'] = 'complete'
        # The same checks as a new job; anything not sent keeps the job's saved setting.
        job.config.update(render_settings(args, previous=job.config, defaults=dict(type_effect='none')))
        (job.folder/'config.json').write_text(json.dumps(job.config, indent=2), encoding='utf-8')
        command = [*module_command('studio.worker'), 'rerender', str(job.folder)]
        job.state.update(action='rerender', action_percent=0, message='Rebuilding video with selected letter effects')
        threading.Thread(target=job.run, args=(command, 'rerender'), daemon=True).start()
        return self.respond(dict(ok=True))

    def _image_rebuild(self, job, args, saved_video):
        """Queues a rebuild for each changed section."""
        from studio.video_versions import verified_changes
        changes, verified = verified_changes(job.folder, job.state['dirty'])
        if verified:job.state['dirty'] = changes
        if job.state['status'] != 'complete' and not saved_video:
            raise ValueError('Rebuild is available after the first video completes')
        if saved_video:
            job.cancelled = False
            job.state['status'] = 'complete'
        job.state['queued_actions'].extend(dict(action='patch', index=i) for i in job.state['dirty'])
        job.start_next()
        job.save()
        return self.respond(dict(ok=True, queued=True))

    def _image_skip_verify(self, job, operation, args, files, index, manifest, target):
        """Skips a pending validation of the selected picture."""
        selected = server.checked_file(job, args['path'])
        if selected != target or not target.is_file():
            raise ValueError('Only the selected illustration can skip verification')
        from filelock import FileLock
        with FileLock(str(target)+'.write.lock',timeout=30):
            fingerprint = content_digest(target)
            report_path = target.with_suffix('.review.json')
            try: previous = json.loads(report_path.read_text(encoding='utf-8'))
            except (OSError, ValueError): previous = {}
            if not previous.get('validation_pending') or previous.get('image_sha256') != fingerprint:
                raise ValueError('Only a pending validation for this image can be skipped')
            report = dict(model=previous.get('model'), manual_skip=True, validation_pending=False,
                score=None, rejected=False, verdict='skipped',
                summary='Verification skipped manually. Inspect this image before approving artwork.',
                issues=[], hand_checks=[], uncertain=True, image_sha256=fingerprint,
                image=str(target), reviewed_at=time.time(), advisory=True)
            report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        job.log(f'Illustration {index+1} verification skipped manually.')
        job.save()
        return self.respond(dict(ok=True))

    def _image_select(self, job, operation, args, files, index, manifest, target):
        """Makes a candidate, or an uploaded picture or clip, the illustration. The old one is kept as a version."""
        if operation == 'replace':
            name, content = files['replacement'][0]
            from artwork.video_art import VIDEO_SUFFIXES, import_clip
            candidate = job.folder/'candidates'/f'{index:03d}'/str(time.time_ns())
            if Path(name).suffix.lower() in VIDEO_SUFFIXES:
                candidate.mkdir(parents=True, exist_ok=True)
                upload = candidate/('upload'+Path(name).suffix.lower())
                upload.write_bytes(content)
                try:selected = import_clip(upload, candidate)
                finally:upload.unlink(missing_ok=True)
            else:
                selected = server.store_image(candidate, name, content)
        else:
            selected = server.checked_file(job, args['path'])
            report=selected.with_suffix('.review.json')
            if report.exists():
                review=json.loads(report.read_text(encoding='utf-8'))
                if review.get('image_sha256')==content_digest(selected) and rejected(review,job.config.get('review_threshold',DEFAULT_THRESHOLD)):
                    raise ValueError('This candidate is below the quality threshold; choose another image or review with a different threshold')
        if selected != target and (not target.exists() or selected.read_bytes() != target.read_bytes()):
            versions = job.folder/'versions'/f'{index:03d}'
            versions.mkdir(parents=True, exist_ok=True)
            if target.exists():
                from artwork.metadata import variant_metadata
                archived=versions/f'{time.time_ns()}.png';shutil.copy2(target,archived)
                from artwork.video_art import copy_slot_clip
                copy_slot_clip(target,archived)
                archive_job=json.loads(manifest.read_text(encoding='utf-8'))
                archived.with_suffix('.artwork.json').write_text(json.dumps(variant_metadata(target,archive_job,index)),encoding='utf-8')
            from filelock import FileLock
            with FileLock(str(target)+'.write.lock',timeout=30):
                temporary=target.with_suffix('.selected.tmp.png')
                shutil.copy2(selected,temporary)
                temporary.replace(target)
                from artwork.video_art import copy_slot_clip
                copy_slot_clip(selected,target)
                target.with_suffix('.selection.json').write_text(json.dumps(dict(selected=str(selected),time=time.time())),encoding='utf-8')
                candidate_review=selected.with_suffix('.review.json')
                try:chosen_report=json.loads(candidate_review.read_text(encoding='utf-8'))
                except (OSError,ValueError):chosen_report={}
                fingerprint=content_digest(target)
                if chosen_report.get('image_sha256')==fingerprint:
                    chosen_report['image']=str(target)
                    target.with_suffix('.review.json').write_text(json.dumps(chosen_report,indent=2),encoding='utf-8')
                else:
                    # chosen by hand: the choice stands, so the checker does not put it up for review again (Verify
                    # on its card still checks it on request)
                    chosen=dict(model=job.config.get('vision_model'),manual_skip=True,manual_selection=True,validation_pending=False,
                        score=None,rejected=False,verdict='selected',summary='Chosen by hand; not checked.',issues=[],hand_checks=[],
                        uncertain=True,image_sha256=fingerprint,image=str(target),reviewed_at=time.time(),advisory=True)
                    target.with_suffix('.review.json').write_text(json.dumps(chosen,indent=2),encoding='utf-8')
                from artwork.metadata import variant_metadata, select_metadata
                selection_job=json.loads(manifest.read_text(encoding='utf-8'))
                select_metadata(manifest,index,variant_metadata(selected,selection_job,index))
            if (job.folder/'video.mp4').exists() and index not in job.state['dirty']:
                job.state['dirty'].append(index)
        if args.get('force_use') == 'true':
            original = json.loads(args.get('force_review') or '{}')
            report_path = target.with_suffix('.review.json')
            chosen = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
            chosen.update(force_used=True, original_review=original, manual_skip=True, manual_selection=True,
                          validation_pending=False, rejected=False, score=None, verdict='selected',
                          image_sha256=content_digest(target), summary='Force used; checker skipped.')
            report_path.write_text(json.dumps(chosen, indent=2), encoding='utf-8')
        job.log(f'Illustration {index+1} selected. '+('Rebuild this section to update the video.' if (job.folder/'video.mp4').exists() else 'Selection will be used in the render.'))
        from artwork.queue import settle_replacement_review
        settle_replacement_review(job.folder, index)  # chosen by hand: nothing left to review for it
        if index in job.state.get('animating', []):
            # the running batch holds the old picture (its worker skips it, or finishes the clip it has started);
            # the new picture needs a clip of its own, queued next
            job.state['animating'] = [i for i in job.state['animating'] if i != index]
        job.queue_missing_clips()
        # the section goes into the video by itself: now, or (when its new picture still needs an AI clip) once the
        # clip is made, which queues the same rebuild (Final cut)
        clip_queued = any(q.get('action') == 'animate' and index in (q.get('indices') or [q.get('index')])
                          for q in job.state['queued_actions'])
        if index in job.state.get('dirty', []) and not clip_queued:
            job.queue_final_cut([index])
        job.save()
        job.start_next()
        return self.respond(dict(ok=True))

    def _image_regenerate(self, job, operation, args, files, index, manifest, target):
        """Queues a new picture for the illustration."""
        if not args.get('image_model'):
            raise ValueError('Reload the studio page to apply the selected image model')
        job.queue_generation(index,operation,str(args.get('prompt','')),str(args.get('model') or job.config.get('ai_model','auto')),args.get('image_model'),args.get('style'),args.get('steps'))
        job.start_next();job.save()
        return self.respond(dict(ok=True,queued=True))

    def _image_run_worker(self, job, operation, args, files, index, manifest, target):
        """Runs verify or patch for one illustration in the worker."""
        if operation not in ('verify', 'patch'):
            raise ValueError('Unknown operation')
        if operation == 'patch' and job.state['status'] != 'complete':
            raise ValueError('Section rebuild is available after the video completes')
        command = [*module_command('studio.worker'), operation, str(job.folder), '--index', str(index)]
        if operation == 'verify':
            if not args.get('model'):
                raise ValueError('Choose an installed Ollama vision model')
            selected = server.checked_file(job, args['path'])
            command += ['--model', args['model'], '--candidate', str(selected)]
            if isinstance(args.get('prompt'), str) and args['prompt'].strip():
                command += ['--prompt='+args['prompt'][:32768], '--style='+str(args.get('style', ''))[:4000]]
        job.repaired_now = set()
        job.state.update(action=operation, action_percent=0, message=f'Starting {operation}')
        threading.Thread(target=job.run, args=(command, operation), daemon=True).start()
        return self.respond(dict(ok=True))


def discard_variant(folder, path, keep=()):
    """Delete an alternative picture and the files that go with it (its review, selection, clip and plate), inside the
    job's candidates/ or versions/ only. The pictures in `keep` (the illustration in use, its raw painting) stay."""
    folder, path = Path(folder).resolve(), Path(path).resolve()
    if any(path == Path(k).resolve() for k in keep):
        raise ValueError('The picture in use cannot be deleted; choose another picture first')
    if not (path.is_relative_to(folder/'candidates') or path.is_relative_to(folder/'versions')):
        raise ValueError('Only alternative pictures (candidates and earlier versions) can be deleted')
    if not path.is_file():
        raise ValueError('That picture is already gone')
    for extra in list(path.parent.glob(path.stem+'.*')):
        extra.unlink(missing_ok=True)
    parent = path.parent   # a candidate's own folder, emptied, goes too
    if parent.is_relative_to(folder/'candidates') and parent != folder/'candidates' and not any(parent.iterdir()):
        parent.rmdir()


def check_image_change(job, operation, saved_video):
    """Checks every image change shares, in order: nothing else running, a stage where pictures can change,
    and no selected picture below the review threshold before a render. Call with LOCK held."""
    # The AI video track (clips, their effects, the lyric-spot scan) never changes the pictures: a picture can be
    # swapped while it runs, and the new one's clip is queued (the worker skips a picture swapped under it). Image
    # work (verify, regenerate, repair, a reference repaint) checks the picture it was given against the slot before
    # it writes, so a picture chosen under it is kept and that slot's work is skipped.
    if job.state['action'] and not (operation in ('select','replace') and job.state['action'] in ('verify','regenerate','reprompt','repair','reference','animate','clip-effects','scene-scan')):
        raise ValueError('Wait for the current image operation to finish')
    # changed while the run goes on, so the change is in use straight away: any stage of a running job
    live_selection = operation in ('select', 'replace') and job.state['status'] in ('running', 'queued')
    # stopped at the review pause (the studio was restarted, or Cancel pressed while it waited): the pictures are
    # finished, so choosing one, uploading one or accepting one works as in review
    saved_review = (operation in ('skip-verify', 'select', 'replace') and job.state['status'] == 'cancelled'
                    and job.state['stage'] == 'review')
    if job.state['status'] not in ('review', 'complete') and not saved_video and not live_selection and not saved_review:
        if job.state['status'] in ('running', 'queued'):
            raise ValueError('This waits for artwork review or the finished video. Choosing, uploading, regenerating and '
                             'verifying images work while the run goes on.')
        raise ValueError('This run stopped before its images were finished. Resume it (or start from Images) to change them.')
    if any(other is not job and (other.state['status'] in ('queued', 'running', 'review') or other.state['action']) for other in server.JOBS.values()):
        raise ValueError('Another job is active; finish or cancel it first')
    if operation in ('approve','rebuild','rerender','patch'):
        failures=job.rejected_selections()
        if failures:
            numbers=', '.join(str(i+1) for i in failures)
            raise ValueError(f'Illustrations {numbers} are below the review threshold. Regenerate or replace them, or change the threshold and review again.')


def save_review_settings(job, args):
    """Saves the review threshold and auto repair setting sent with a review."""
    threshold=args['review_threshold']
    if type(threshold) is not int or not 0 <= threshold <= 100:
        raise ValueError('Review threshold must be an integer from 0 to 100')
    if type(args.get('auto_repair')) is not bool:
        raise ValueError('Automatic repair must be true or false')
    job.config.update(review_threshold=threshold,auto_repair=args['auto_repair'])
    (job.folder/'config.json').write_text(json.dumps(job.config,indent=2),encoding='utf-8')


IMAGE_OPERATIONS = {'approve': ImageOperations._image_approve, 'verify-all': ImageOperations._image_verify_all,
                    'rerender': ImageOperations._image_rerender, 'rebuild': ImageOperations._image_rebuild}


SLOT_OPERATIONS = {'skip-verify': ImageOperations._image_skip_verify, 'select': ImageOperations._image_select, 'replace': ImageOperations._image_select,
                   'regenerate': ImageOperations._image_regenerate, 'reprompt': ImageOperations._image_regenerate}


# Last, because studio.server imports this module.
from studio import server  # noqa: E402
