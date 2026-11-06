"""A Studio job's work on its video clips: scene lyrics, storyboards, the storyline and remaking
clips. Job (studio/server.py) inherits these; they use only the job's own state and files."""

import json
from pathlib import Path
import time

pass
pass


def video_busy(job):
    alive = job.process is not None and job.process.poll() is None
    return (
        bool(job.state.get('action'))
        or job.state['status'] in ('running', 'queued')
        or (job.state['status'] == 'review' and alive)
    )


class ClipWork:
    def story_times(self, manifest):
        from direction.story import segment_times
        from core.media import media_duration
        from render.timeline import ART_TIMES, load_art_times
        from types import SimpleNamespace
        try:
            data=json.loads((self.folder/'video.timings.json').read_text(encoding='utf-8'))
            duration=media_duration(self.config['audio'])
            args=SimpleNamespace(illustration_lines=self.config.get('illustration_lines',2),lead_in=1.,art_times=load_art_times(self.folder/ART_TIMES))
            return segment_times(manifest,data,duration,args)
        except (OSError,ValueError,KeyError):
            return None

    def queue_effects_after_animation(self):
        return None

    def section_window(self, index):
        """(song time the illustration's clip starts playing, song time its section ends)."""
        from artwork.video_art import artwork_lane
        from studio.timeline_data import song_duration

        timings = json.loads((self.folder / 'video.timings.json').read_text(encoding='utf-8'))
        duration = song_duration(self.folder, self.config['audio'])
        lanes = artwork_lane(self.folder, self.config, timings, duration)
        lane = next((l for l in lanes if l['index'] == index), None)
        if lane is None:
            raise ValueError('Invalid illustration')
        return (0.0 if index == 0 else round(lane['start'], 3)), round(lane['end'], 3)

    def queue_clip_effects(self, index):
        return None




    def place_scene_lyrics(self):
        return None


    def record_scene_windows(self):
        return None



    def story_state(self):
        """Everything the storyline panel shows: per segment the image prompt (with the image model's budget), the
        lyrics and song time, and the story; plus the reference images and whether a regeneration would discard work."""
        from direction.story import load
        from direction.prompt_fit import budget
        from artwork.video_art import artwork_lane
        from studio.timeline_data import song_duration
        manifest = self.manifest()
        job = json.loads(manifest.read_text(encoding='utf-8'))
        since = self.gallery_since()
        if since and manifest.stat().st_mtime < since:
            # regenerating from before the storyline: the previous prompts and story are out of reach until the new
            # ones are written
            return dict(segments=[], budget=None, image_model=self.config.get('image_model'), video=bool(self.config.get('video_model')),
                        has_story=False, references=[], reference_use='style', main_character='', images=0,
                        busy=video_busy(self), regenerating=True)
        story = load(manifest)
        if story:
            from direction.story import retime_story
            times=self.story_times(manifest)
            if times:retime_story(story,times)
        stories = {s['index']: s for s in story['segments']} if story else {}
        from direction.scene_direction import with_style
        style_job = dict(job, reference_prompt=self.config.get('style_prompt', job.get('reference_prompt', job.get('style_prompt', ''))))
        stories = {i: with_style(s, style_job) for i, s in stories.items()}
        try:
            timings = json.loads((self.folder/'video.timings.json').read_text(encoding='utf-8'))
            lanes = {l['index']: l for l in artwork_lane(self.folder, self.config, timings,
                                                         song_duration(self.folder, self.config['audio']))}
        except (OSError, ValueError, KeyError, IndexError):
            lanes = {}
        limit = budget(job.get('model') or self.config.get('image_model'))
        groups = job.get('groups') or []
        from direction.entities import painted_prompt
        entities = [dict(id=e.get('id', ''), name=e['name'], kind=e['kind'], looks=e['looks'], segments=e['segments'],
                         cast=bool(e.get('cast')), uploaded=bool(e.get('uploaded')), base=str(e.get('base') or ''), photo=str(e.get('photo') or ''),
                         image=self.url(Path(e['image'])) if e.get('image') and Path(e['image']).is_file() else None,
                         **dict(zip(('prompt', 'prompt_exact'), painted_prompt(e, job))))
                    for e in (story or {}).get('entities') or []]
        segments = []
        for index, prompt in enumerate(job.get('prompts', [])):
            image = manifest.parent/f'{index:03d}.png'
            lane = lanes.get(index)
            story_refs = [p for p in (stories.get(index) or {}).get('references', []) if Path(p).is_file()]
            segments.append(dict(index=index, prompt=prompt, words=len(prompt.split()), lyrics=groups[index] if index < len(groups) else '',
                                 references=[dict(path=Path(p).name, url=self.url(Path(p))) for p in story_refs],
                                 entities=[e for e in entities if index in e['segments']],
                                 section=[0. if index == 0 else round(lane['start'], 2), round(lane['end'], 2)] if lane else None,
                                 image=self.url(image) if image.is_file() else None, story=stories.get(index)))
        references = [Path(p) for p in job.get('reference_paths') or [] if Path(p).is_file()]  # the ones these prompts use
        return dict(segments=segments, budget=limit[0] if limit else None, image_model=job.get('model'),
                    video=bool(self.config.get('video_model')), has_story=bool(story),
                    scene_direction=self.config.get('scene_direction', 'timed'),
                    references=[self.url(p) for p in references], reference_use=job.get('reference_use') or 'style',
                    main_character=job.get('main_character') or '', entities=entities,
                    uploads=self.uploaded_references(manifest),
                    images=sum(1 for s in segments if s['image']), busy=video_busy(self))

    def edit_entity(self, op, entry, upload=None):
        """The references editor: 'save' (edit an entry), 'add', 'remove', 'repaint' (a new sheet next time it is
        needed), 'upload' (the user's own picture instead of a painted sheet) or 'painted' (back to the painted one).
        A sheet is painted when an image that shows it is next painted (Replace or Resume). Returns a message."""
        from core.files import update_json
        from direction.entities import edited
        from direction.story import story_path
        from studio.server import store_image  # imported here: the server module imports this one
        path = story_path(self.manifest())
        if not path.is_file():
            raise ValueError('Write or save the storyline first')
        stored = store_image(path.parent/'entities'/'uploads', upload[0], upload[1]) if upload else None
        result = []
        manual_choice=[]

        def change(story):
            entities = story.setdefault('entities', [])
            count = len(story.get('segments') or [])
            found = next((e for e in entities if e.get('id') == entry.get('id')), None)
            if op != 'add' and found is None:
                raise ValueError('That reference is no longer in the storyline')
            if op in ('add', 'save'):
                fresh = edited(dict(entry, id=None if op == 'add' else found['id']), count, {e.get('id') for e in entities})
                if fresh['base'] and not any(e.get('id') == fresh['base'] and e is not found for e in entities):
                    raise ValueError('Choose a listed reference as the one it is a form of')
            if op == 'add':
                entities.append(fresh)
                result.append(f"{fresh['name']} added; its picture is painted with the next image that shows it.")
            elif op == 'save':
                if any(fresh[k] != found.get(k, '') for k in ('name', 'kind', 'looks', 'base')) and not found.get('uploaded'):
                    found.pop('image', None)  # a new description gets a new sheet
                    found.pop('prompt', None)  # and a prompt written from it
                found.update(fresh)
                result.append(f"{fresh['name']} saved.")
            elif op == 'remove':
                entities.remove(found)
                result.append(f"{found['name']} removed; images painted from now on leave it out.")
            elif op == 'repaint':
                found.pop('force_used', None)
                found.pop('force_review', None)
                found['repaint'] = int(found.get('repaint') or 0)+1
                found.pop('image', None)
                found.pop('uploaded', None)
                result.append(f"{found['name']} will be painted again with the next image that shows it.")
            elif op == 'upload':
                previous = found.get('image')
                if previous and previous != str(stored):
                    history = found.setdefault('image_history', [])
                    if previous not in history:
                        history.append(previous)
                found['uploaded'] = found['image'] = str(stored)
                found['image_origin'] = entry.get('image_origin') or 'upload'
                found['image_updated_at'] = time.time()
                found['force_used'] = bool(entry.get('force_used'))
                found['force_review'] = entry.get('force_review') if found['force_used'] else None
                manual_choice.append({k:found[k] for k in ('image','uploaded','image_updated_at','force_used','force_review','image_origin')})
                result.append(f"Your picture of {found['name']} is used from the next image that shows it.")
            elif op == 'painted':
                found.pop('force_used', None)
                found.pop('force_review', None)
                found.pop('uploaded', None)
                found.pop('image', None)
                result.append(f"{found['name']} goes back to a painted picture.")
            else:
                raise ValueError('Unknown reference change')
        update_json(path, change)
        if op in ('upload','painted','repaint','remove'):
            from direction.reference_choices import remember
            remember(self.manifest(),entry.get('id'),manual_choice[0] if manual_choice else None)
        return result[0]

    def segment_reference(self, index, upload=None, remove=None, reuse=None):
        """Add (upload = (filename, bytes)) or remove (remove = file name) a reference image of story segment `index`.
        Used for that segment's image (and described into its clip); changes need a regenerate to show."""
        from direction.story import load, save
        from studio.server import keep_upload_name, store_image  # imported here: the server module imports this one
        manifest = self.manifest()
        story = load(manifest)
        if not story or not 0 <= index < len(story['segments']):
            raise ValueError('Write or save the storyline first')
        segment = story['segments'][index]
        refs = [p for p in segment.get('references') or [] if Path(p).is_file()]
        if reuse:  # a picture uploaded for another illustration
            root = manifest.parent/'segment-references'
            source = (root/str(reuse)).resolve()
            if not source.is_relative_to(root.resolve()) or not source.is_file():
                raise ValueError('That upload is no longer there')
            upload = (source.name, source.read_bytes())
        if upload is not None:
            if len(refs) >= 3:
                raise ValueError('A segment takes at most 3 reference images')
            stored = store_image(manifest.parent/'segment-references'/f'{index:03d}', upload[0], upload[1])
            refs.append(str(keep_upload_name(stored, upload[0])))
            refs = list(dict.fromkeys(refs))   # the same picture added twice counts once
            message = f'Reference added to segment {index+1}; regenerate to use it.'
        else:
            refs = [p for p in refs if Path(p).name != remove]
            message = f'Reference removed from segment {index+1}; regenerate to apply.'
        segment['references'] = refs
        save(manifest, story)
        return message

    def uploaded_references(self, manifest):
        """Every picture uploaded for any illustration of this artwork, each once: they stay on disk when taken off an
        illustration, so they can be used again."""
        from core.files import content_digest
        root = manifest.parent/'segment-references'
        found = {}
        for path in sorted(root.glob('*/*.png')):
            found.setdefault(content_digest(path), dict(path=path.relative_to(root).as_posix(), name=path.name, url=self.url(path)))
        return list(found.values())

    def delete_upload(self, path):
        """Delete an upload and its copies from the disk. One still on an illustration stays: its file is what that
        illustration is painted from."""
        from core.files import content_digest
        from direction.story import load
        manifest = self.manifest()
        root = (manifest.parent/'segment-references').resolve()
        source = (root/str(path)).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ValueError('That upload is no longer there')
        digest = content_digest(source)
        copies = {p.resolve() for p in root.glob('*/*.png') if content_digest(p) == digest}
        used = [int(s.get('index', 0))+1 for s in (load(manifest) or {}).get('segments', [])
                if any(Path(r).resolve() in copies for r in s.get('references') or [])]
        if used:
            raise ValueError(f"Still used by illustration{'s' if len(used) > 1 else ''} {', '.join(map(str, used))}: "
                             'take it off there first')
        for copy in copies:
            copy.unlink()
        return f'{source.name} deleted.'

    def save_story(self, segments):
        """Save edited prompts and story. Clips not made yet follow the new story; made ones keep theirs until
        their images are regenerated. Called with LOCK held. Returns a message."""
        from direction.story import load, normalise, save, validate_import
        pass
        pass

        manifest = self.manifest()
        job = json.loads(manifest.read_text(encoding='utf-8'))
        validate_import(dict(segments=segments), len(job['prompts']))
        old = load(manifest) or dict(segments=[{}] * len(job['prompts']))
        story, prompts = [], list(job['prompts'])
        for index, (segment, before) in enumerate(zip(segments, old['segments'])):
            if not isinstance(segment, dict):
                raise ValueError('Invalid storyline')
            prompt = str(segment.get('prompt', prompts[index])).strip()
            if not prompt or len(prompt) > 8000:
                raise ValueError(f'Segment {index + 1} needs an image prompt (at most 8000 characters)')
            prompts[index] = prompt
            if not self.config.get('video_model') and not segment.get('beats'):
                if before:
                    story.append(before)  # a run without video: only the prompt is edited
                continue
            for key in ('characters', 'environment', 'camera'):
                if not str(segment.get(key) or '').strip():
                    raise ValueError(f'Segment {index + 1} needs its {key} described')
            summary = segment.get('scene_direction') == 'summary'
            if summary and not str(segment.get('scene') or '').strip():
                raise ValueError(f'Segment {index + 1} needs a scene summary')
            if not summary and not segment.get('beats'):
                raise ValueError(f'Segment {index + 1} needs at least one timed beat')
            seconds = (
                segment.get('seconds')
                or (before or {}).get('seconds')
                or max((float(b.get('end', 0)) for b in segment.get('beats') or []), default=5.)
            )
            entry = normalise(dict({**(before or {}), **segment}, index=index, references=(before or {}).get('references') or []), seconds)
            entry['start'] = (before or {}).get('start')
            story.append(entry)
        changed_prompts = prompts != job['prompts']
        if changed_prompts:
            job['prompts'] = prompts
            from core.files import update_json  # the image worker may be updating the same manifest

            update_json(manifest, lambda saved: saved.__setitem__('prompts', prompts))
        if len(story) == len(prompts):
            from direction.story import retime_story
            times=self.story_times(manifest)
            if times:retime_story(dict(segments=story),times)
            save(manifest, dict(segments=story, **({'entities': old['entities']} if 'entities' in old else {}),
                                **({'beats_split': True} if old.get('beats_split') else {})))
        self.log(
            'Storyline saved.'
            + (' Image prompts changed; regenerate to make new images from them.' if changed_prompts else '')
        )
        return 'Storyline saved.' + (
            ' The changed image prompts take effect when you regenerate.'
            if changed_prompts
            else ''
        )




    def redo_pending(self):
        return None

    def clips_newer_than_video(self):
        return []

    def queue_missing_clips(self, segments=None):
        return None

    def animation(self, digest):
        return None
