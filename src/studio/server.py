"""Local-only lyric studio. No web framework or extra UI dependencies required."""
from render.typography_settings import typography_options
from core.paths import PROJECT_ROOT, SRC_ROOT, UI_ROOT, default_model_cache, studio_output
from core.process import module_command
import argparse
import copy
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from contextlib import contextmanager
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
from urllib.parse import urlsplit
import webbrowser

from models.image.catalog import MODEL
from direction.illustration_prompts import STYLE_PROMPT
from models.image.catalog import MODELS
VIDEO_MODELS = []
VIDEO_MODES = ()
from models.vision.policy import DEFAULT_THRESHOLD
from models.speech.catalog import DEFAULT_ASR, validate_speech
from core.files import cached_digest, content_digest
from studio.job_clips import ClipWork, video_busy  # noqa: F401
from studio.render_settings import render_settings
from studio.job_process import ProcessWork
from studio.job_queue import ActionQueue
from studio.lock import LOCK
import sys
if __name__ == '__main__':
    # Run as "python -m studio.server" this module is __main__; the route mixins below import it as studio.server.
    # Register this instance under that name so they share its JOBS and ROOT instead of loading an empty second copy.
    sys.modules['studio.server'] = sys.modules[__name__]
from studio.get_routes import GetRoutes
from studio.job_routes import JobRoutes
from studio.image_operations import ImageOperations, IMAGE_OPERATIONS, SLOT_OPERATIONS  # noqa: F401
from studio.maker_routes import MakerRoutes

ROOT = studio_output(PROJECT_ROOT,'lyric-studio')
# Prompting steps. Their progress shares are in job_process.STAGES.
PROMPT_STAGES = ('subjects', 'song', 'meanings', 'story', 'scenes', 'fit')
TOKEN = secrets.token_urlsafe(32)
JOBS = {}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
AUDIO_SUFFIXES = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.webm', '.mp4', '.aiff', '.aif'}


class Job(ClipWork, ProcessWork, ActionQueue):
    def __init__(self, folder, config):
        self.folder, self.config = folder, config
        self.process = self.action_process = None
        self.cancelled = False
        self.command = None  # the main pipeline command, so a stopped run can be resumed from saved work
        self.runs = 0  # run() calls still in progress, including their post-exit bookkeeping
        self.generation = 0  # bumped on every stop, so a pending automatic resume is dropped
        self.generation_batch = None  # the image requests the running worker owns, retried if it crashes
        self.retry_at = 0
        self.repaired_now = set()  # images a running Verify replaced; their video sections are rebuilt afterwards
        self._image_fingerprints = {}
        self.state = self.initial_state(folder, config)

    @staticmethod
    def initial_state(folder, config):
        return dict(id=folder.name, name=config['name'], status='queued', stage='queued',
            percent=0, message='Waiting to start', started=time.time(), history=[], logs=[], action=None,
            action_percent=0, dirty=[], queued_actions=[])

    def log(self, message, level=None):
        if not message.strip():
            return
        if level is None and (message.startswith('| ') or message.startswith('[LLM ')):
            level = 'error' if message.startswith('[LLM ERROR ') else 'info'
        level = level or ('error' if re.search(r'error|failed|traceback', message, re.I) else
                          'warning' if re.search(r'warn|retry|lettering detected', message, re.I) else 'info')
        with LOCK:
            self.state['logs'].append(dict(time=time.time(), level=level, text=message[:6000]))


    def save(self):
        """Write state.json whole (never half-written if the studio stops mid-write), under LOCK so no other
        thread changes the state while it is serialised."""
        from core.files import write_text_atomic
        with LOCK:
            text = json.dumps(self.state)
        write_text_atomic(self.folder/'state.json', text)

    def planned_queue(self):
        """The kinds of work in the order they will run (studio.job_queue.queue_plan), for the header's queue."""
        from studio.job_queue import queue_plan
        return queue_plan(self.state.get('queued_actions') or [], self.state.get('action'), self.state.get('last_family'))

    def eta(self):
        """Time left for everything still to do for this song (see studio.eta); None when nothing runs."""
        try:
            from studio.eta import estimate
            return estimate(self)
        except Exception:  # noqa: BLE001 (an estimate never breaks the page)
            return None

    def entity_references(self):
        """The storyline's recurring characters, objects and places, each with its painted reference picture (None until
        painted; the cast uses the user's own photos), for the Artwork tab."""
        try:
            from direction.story import load
            story = load(self.manifest())
        except (OSError, ValueError, KeyError):
            return []
        def picture(entity):
            # the cast's sheet is painted from the user's photo; until then it has no picture of its own (the photos
            # show above it in the tab)
            image = Path(str(entity.get('image') or ''))
            if not entity.get('image') or not image.is_file():
                return None
            since = self.gallery_since()  # a new run redoes the artwork: its earlier pictures are not shown
            if since and self.config.get('start_substep')!='illustrations' and not entity.get('uploaded') and image.stat().st_mtime < since:
                return None
            return self.url(image)
        from direction.entities import current_sheet

        def rejected(entity):
            """The checker's verdict on the picture shown (or, with none shown, on the one just taken down)."""
            if entity.get('uploaded'):
                return False
            review = entity.get('sheet_review') or {}
            if not review or review.get('passed', True):
                return False
            image = Path(str(entity.get('image') or ''))
            if image.is_file():
                from models.vision.sheet_review import fingerprint
                return review.get('sha') == fingerprint(image)
            return True
        from direction.entities import earlier_sheets
        def passed(entity):
            from models.vision.sheet_review import fingerprint
            review=entity.get('sheet_review') or {}
            path=Path(str(entity.get('image') or ''))
            return bool(not entity.get('uploaded') and review.get('passed') is True and path.is_file() and review.get('sha')==fingerprint(path))
        manifest = self.manifest()
        def history(entity):
            paths = earlier_sheets(manifest, entity)
            if entity.get('image') and Path(entity['image']).is_file():
                paths.insert(0, Path(entity['image']))
            records = []
            for path in paths:
                try:
                    review = json.loads(path.with_suffix('.sheet-review.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    from models.vision.sheet_review import fingerprint
                    latest = entity.get('sheet_review') or {}
                    review = latest if latest.get('sha') == fingerprint(path) else None
                try:
                    prompt_used = json.loads(path.with_suffix('.prompt.json').read_text(encoding='utf-8')).get('prompt', '')
                except (OSError, ValueError):
                    prompt_used = entity.get('painted_prompt', '') if str(path) == entity.get('image') and not entity.get('uploaded') else ''
                records.append(dict(url=self.url(path), review=review, prompt=prompt_used, path=str(path)))
            return records
        return [dict(id=e.get('id', ''), name=e.get('name', ''), kind=e.get('kind', ''), cast=bool(e.get('cast')),
                     base=str(e.get('base') or ''), segments=[i+1 for i in e.get('segments') or []], url=picture(e),
                     stale=bool(picture(e)) and not current_sheet(e),
                     updated_at=e.get('image_updated_at'),
                     force_used=bool(e.get('force_used')), force_review=e.get('force_review'),
                     check_passed=passed(e),check_summary=(e.get('sheet_review') or {}).get('summary',''),
                     rejected=rejected(e), issues=[str(i) for i in (e.get('sheet_review') or {}).get('issues') or []][:4],
                     # earlier pictures still on disk, to look at (never put back in use)
                     earlier=[self.url(p) for p in earlier_sheets(manifest, e)], history=history(e))
                for e in (story or {}).get('entities') or []]

    def tag_entity(self, index, entity_id, on):
        """Show (on) or stop showing a recurring reference in image `index`: its segments in the storyline, which the
        image worker (new images, Replace, Resume) and the clips follow. Returns a message."""
        from core.files import update_json
        from direction.story import story_path
        path = story_path(self.manifest())
        if not path.is_file():
            raise ValueError('This project has no storyline yet')
        found = []

        def change(story):
            for entity in story.get('entities') or []:
                if entity.get('id') == entity_id:
                    segments = set(entity.get('segments') or [])
                    segments.add(index) if on else segments.discard(index)
                    entity['segments'] = sorted(segments)
                    found.append(entity.get('name', entity_id))
        update_json(path, change)
        if not found:
            raise ValueError('That reference is not in the storyline')
        return (f'{found[0]} added to image {index+1}; Replace or Resume to use it.' if on else
                f'{found[0]} removed from image {index+1}.')

    def project_inputs(self):
        """What the Project tab shows for an open song: its name, lyrics, prompts and the reference images it was made with."""
        try:
            lyrics = (self.folder/'lyrics.txt').read_text(encoding='utf-8')
        except OSError:
            lyrics = ''
        references = self.folder/'references'
        urls, seen = [], set()
        for p in (sorted(references.iterdir()) if references.is_dir() else []):
            if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            try:
                digest = cached_digest(p)  # older projects hold one copy per restart; show each picture once
            except OSError:
                continue
            if digest in seen:
                continue
            seen.add(digest); urls.append(self.url(p))
        return dict(name=self.config.get('name', ''), lyrics=lyrics, theme=self.config.get('theme', ''),
                    protect_word_alignment=bool(self.config.get('protect_word_alignment')),
                    has_word_timings=(self.folder/'video.timings.json').is_file(),
                    lines=self.config.get('line_pattern') or ('auto' if self.config.get('illustration_lines_mode') == 'auto'
                          else str(self.config.get('illustration_lines', 'auto'))),
                    style_prompt=self.config.get('style_prompt', ''), language=self.config.get('language', 'auto'), references=urls)

    def snapshot(self, cursor=0):
        with LOCK:  # copy only the log entries this poll has not seen: the whole log grows for the job's lifetime
            logs = self.state['logs']
            result = copy.deepcopy({key: value for key, value in self.state.items() if key != 'logs'})
            if result.get('image_edit_status'):
                result['message'] = result['image_edit_status']
            result['logs'] = [dict(entry) for entry in logs[cursor:]]
            total = len(logs)
        if (result['status'] == 'cancelled' and result['stage'] == 'complete'
                and (self.folder/'video.mp4').is_file()):
            result['status'] = 'complete'
            result['message'] = 'Video ready; saved work can be edited'
        from studio.video_versions import verified_changes, video_versions
        result['dirty'], result['dirty_verified'] = verified_changes(self.folder, result.get('dirty', []))
        result['video_versions'] = video_versions(self.folder, self.url)
        from artwork.queue import replacement_review_path
        try:
            waiting=json.loads(replacement_review_path(self.folder).read_text(encoding='utf-8'))
            result['replacement_review']=[c['index'] for c in waiting.get('candidates',[])] if waiting.get('manifest')==str(self.manifest()) else []
        except (OSError,ValueError):result['replacement_review']=[]
        result.update(cursor=total, images=self.images(), entity_references=self.entity_references(), redo_pending=self.redo_pending(), eta=self.eta(), queue_plan=self.planned_queue(), gallery_cleared=bool(self.gallery_since()), ornaments=self.ornaments(),
                      rejected_images=self.rejected_selections(),
                      elapsed=round(self.state.get('finished', time.time())-self.state['started']),
                      render_settings=dict(**typography_options(self.config),**self.project_inputs(),story_prompt=self.config.get('story_prompt',''),stage_pictures=self.config.get('stage_pictures','ai-painted'),text_animation=self.config.get('text_animation','directed'), audio_mode=self.config.get('audio_mode','original'), auto_accept=self.config.get('auto_accept',False), auto_verify=self.config.get('auto_verify',False), image_instructions=self.config.get('image_instructions',''), cast_reference=self.config.get('reference_use')=='likeness', type_effect=self.config.get('type_effect','none'), entrance_effect=self.config.get('entrance_effect','legacy'), exit_effect=self.config.get('exit_effect','legacy'), entrance_pool=self.config.get('entrance_pool'), exit_pool=self.config.get('exit_pool'), particle_speed=self.config.get('particle_speed',1.), particle_intensity=self.config.get('particle_intensity',1.), image_seed=self.config.get('image_seed'), randomize_seed=self.config.get('randomize_seed', True), image_model=self.config.get('image_model', MODEL), scene_direction=self.config.get('scene_direction', 'timed'), video_upscale=self.config.get('video_upscale', 'off'), picture_kinds=picture_choice(self.config.get('picture_kinds') or ('cinemagraph' if self.config.get('video_cinemagraph') == 'on' else ''), bool(self.config.get('video_model'))), end_frame_model=self.config.get('end_frame_model', 'auto'), end_frame_review=bool(self.config.get('end_frame_review')), depth_model=self.config.get('depth_model', 'depth-anything'), review_references=self.config.get('review_references', True), repaint_references=self.config.get('repaint_references', True), image_check_prompt=self.config.get('image_check_prompt', ''), reference_check_prompt=self.config.get('reference_check_prompt', '')))
        # The text model this song runs with; only an 'auto' choice is named from what the saved prompts recorded
        # (the previous artwork's model must not show while a new run uses another one).
        prompt_model=self.config.get('ai_model','auto')
        if prompt_model=='auto':
            try:
                manifest=json.loads(self.manifest().read_text(encoding='utf-8'))
                prompt_model=manifest.get('prompt_model') or manifest.get('prompt_audit',{}).get('model') or prompt_model
            except (OSError,ValueError,KeyError):pass
        result['production_models']=dict(
            audio=self.config.get('audio_name') or Path(self.config.get('audio','')).name or self.config.get('name',''),
            profile=self.config.get('profile_name',''),
            asr=self.config.get('asr_model',''), alignment=self.config.get('alignment_model','auto'),
            prompt=prompt_model, image=self.config.get('image_model',''),
            vision=self.config.get('vision_model','') if self.config.get('auto_verify') else '',
            encoder=self.config.get('encoder',''), artwork_mode=self.config.get('artwork_mode','cutout'),
            stage_pictures=self.config.get('stage_pictures','ai-painted'), video=self.config.get('video_model',''),
            video_generation=bool(self.config.get('video_generation')))
        result['pipeline_summary'] = self.pipeline_summary()
        from pipeline.versions import Versions
        result['pipeline_history'] = Versions(self.folder).summary()
        if (self.folder/'video.mp4').exists():
            result['video'] = self.url(self.folder/'video.mp4')
        if (self.folder/'poster.png').exists():
            result['poster'] = self.url(self.folder/'poster.png')
        return result

    def pipeline_summary(self):
        """What the header shows for the two steps that are not stages of the run itself: the estimated length of
        each section (once the prompts have grouped the lyrics) and how many AI video clips exist. Cached until the
        prompts, timings, illustrations or clips change: the header polls every second."""
        model = self.config.get('video_model') or ''
        try:
            manifest = self.manifest()
            job = json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError, ValueError, KeyError):
            return dict(sections=None, video=dict(model=model, made=0, total=0) if model else None, references=None, scene=None)
        count = len(job.get('prompts', []))
        images = [manifest.parent/f'{i:03d}.png' for i in range(count)]
        clips = self.folder/'video-clips'
        timings = self.folder/'video.timings.json'
        from direction.story import story_path
        story_file = story_path(manifest)
        signature = (str(manifest), manifest.stat().st_mtime_ns, timings.stat().st_mtime_ns if timings.is_file() else 0,
                     story_file.stat().st_mtime_ns if story_file.is_file() else 0, self.gallery_since(),
                     tuple(p.stat().st_mtime_ns if p.is_file() else 0 for p in images), model,
                     sum(1 for _ in clips.glob('*/clip.json')) if clips.is_dir() else 0,
                     sum(1 for _ in clips.glob('*/scene-suggestion.json')) if clips.is_dir() else 0,
                     tuple(p.stat().st_mtime_ns for p in manifest.parent.glob('[0-9][0-9][0-9].review.json')))
        cached = getattr(self, '_pipeline_summary', None)
        if cached and cached[0] == signature:
            return cached[1]
        sections = None
        try:
            from artwork.video_art import artwork_lane
            from studio.timeline_data import song_duration
            lanes = artwork_lane(self.folder, self.config, json.loads(timings.read_text(encoding='utf-8')),
                                 song_duration(self.folder, self.config.get('audio')))
            lengths = [max(0., l['end']-(0. if i == 0 else l['start'])) for i, l in enumerate(lanes)]
            if lengths:
                sections = dict(count=len(lengths), shortest=round(min(lengths), 1), longest=round(max(lengths), 1),
                                seconds=[round(x, 1) for x in lengths])
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            pass
        video = scene = None
        pass
        story = references = None
        try:
            if self.gallery_since() and manifest.stat().st_mtime < self.gallery_since():
                raise ValueError('regenerating: the previous storyline is out of reach')
            from direction.story import load as load_story
            written = load_story(manifest)
            if written and written.get('segments'):
                story = dict(segments=len(written['segments']), edited=bool(written.get('edited')))
                if 'entities' in written:  # recurring entities and how many have their reference picture
                    from direction.entities import PICTURED  # what gets a reference picture
                    listed = [e for e in written['entities'] or [] if e.get('kind') in PICTURED]
                    reviews = [e.get('sheet_review') or {} for e in listed]
                    references = dict(listed=len(listed), painted=sum(
                        1 for e in listed if e.get('image') and Path(e['image']).is_file()),
                        checked=sum(1 for r in reviews if r), failed=sum(1 for r in reviews if r and not r.get('passed', True)))
        except (OSError, ValueError, KeyError):
            pass
        checked = None   # the illustrations' check: how many have a verdict, how many of those are rejected
        try:
            reviewed = sum(1 for p in images if p.with_suffix('.review.json').is_file())
            checked = dict(reviewed=reviewed, rejected=len(self.rejected_selections())) if reviewed else dict(reviewed=0, rejected=0)
        except (OSError, ValueError, KeyError):
            pass
        summary = dict(sections=sections, video=video, story=story, references=references, scene=scene, images=checked)
        self._pipeline_summary = (signature, summary)
        return summary

    def url(self, path):
        from urllib.parse import quote
        path = Path(path)
        try:
            inside = path.relative_to(self.folder)
        except ValueError:  # a relative or differently written path to the same file
            inside = path.resolve().relative_to(self.folder.resolve())
        return '/files/'+self.folder.name+'/'+quote(inside.as_posix())+'?v='+str(path.stat().st_mtime_ns)

    def manifest(self):
        from artwork.active import select_manifest
        return select_manifest(self.folder,self.config,self.state)

    def ornaments(self):
        """Small painted and library pictures used by the stage, with cached transparent previews. While the stage's
        pictures are still being painted, those finished so far show too (see fresh_ornaments): the blocks file that
        places them is written only when the whole set is done."""
        try:
            blocks = json.loads((self.folder/'video.blocks.json').read_text(encoding='utf-8'))['blocks']
        except (OSError, ValueError, KeyError, TypeError):
            blocks = []
        result = []
        for block in blocks:
            ornament = (block or {}).get('ornament') or {}
            image = ornament.get('image')
            kind = ornament.get('library')
            if not image and not kind:
                continue
            try:
                if image:
                    path = Path(image)
                    path = (path if path.is_absolute() else self.folder/path).resolve()
                    if not path.is_file() or not path.is_relative_to(self.folder.resolve()):
                        continue
                    shown = path.with_suffix('.cutout.png')
                    cutout_source = SRC_ROOT/'render'/'glyph_art.py'
                    if not shown.exists() or shown.stat().st_mtime_ns < max(path.stat().st_mtime_ns, cutout_source.stat().st_mtime_ns):
                        from render.glyph_art import cutout
                        cutout(str(path)).save(shown)
                else:
                    from direction.ornaments import library_preview
                    shown = library_preview(kind, self.folder)
                    if shown is None:
                        continue
            except (OSError, ValueError, KeyError):
                continue
            from direction.ornaments import picture_key, released_pictures
            key = picture_key(ornament)
            result.append(dict(word=ornament.get('text', ''), subject=ornament.get('subject') or kind or '',
                               source='painted' if image else 'library', line=ornament.get('line'),
                               url=self.url(shown), key=key, keep=key not in released_pictures(self.folder)))
        return result+self.fresh_ornaments({Path(str(((b or {}).get('ornament') or {}).get('image') or '')).resolve() for b in blocks})

    def fresh_ornaments(self, placed):
        """The stage's pictures painted so far in the newest typography job that the blocks file does not place yet,
        each shown the moment its file is complete, with its subject; `placed` are the paths already listed."""
        jobs = sorted((self.folder/'video.ornaments').glob('*/illustrations.json'), key=lambda p: p.stat().st_mtime)
        if not jobs:
            return []
        manifest = jobs[-1]
        try:
            job = json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return []
        subjects = job.get('visual_descriptions') or job.get('prompts') or []
        result = []
        for i in range(len(job.get('prompts') or [])):
            path = (manifest.parent/f'{i:03d}.png').resolve()
            if not path.is_file() or path in placed:
                continue
            try:
                shown = path.with_suffix('.cutout.png')
                if not shown.exists() or shown.stat().st_mtime_ns < path.stat().st_mtime_ns:
                    from render.glyph_art import cutout
                    cutout(str(path)).save(shown)
            except (OSError, ValueError):
                continue
            result.append(dict(word='', subject=str(subjects[i] if i < len(subjects) else ''), source='painted', line=None,
                               url=self.url(shown), key=f'fresh:{manifest.parent.name}:{i}', keep=True, fresh=True))
        return result

    def gallery_since(self):
        """After a regeneration from before the images, the gallery shows only images made since: the previous
        ones stay out of reach even if that run fails or is cancelled. A run that found its artwork already made
        shows it again once it reaches review. 0 when nothing is hidden."""
        since = self.config.get('gallery_since', 0)
        reached_review = self.state.get('stage') in ('review', 'video', 'direction', 'pictures', 'render', 'complete')
        return 0 if not since or reached_review else since

    def images(self):
        try:
            manifest = self.manifest()
            job = json.loads(manifest.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return []
        result = []
        since = self.gallery_since()
        # An older manifest stays hidden until this run paints into it: a run whose prompts are unchanged reuses the
        # same manifest (its folder is a content hash), so its new pictures must still appear as they are made.
        if since and manifest.stat().st_mtime < since and not any(
                p.stat().st_mtime >= since for p in manifest.parent.glob('[0-9][0-9][0-9]*.png')):
            return []
        try:  # what the current video was rendered from, so a changed image can be put back
            rendered = json.loads((self.folder/'video.render.json').read_text(encoding='utf-8')).get('artwork_revisions') or {}
        except (OSError, ValueError, AttributeError):
            rendered = {}
        for i, prompt in enumerate(job['prompts']):
            recorded = str(rendered.get(str(i)) or '').split('@')[0]
            current, raw = manifest.parent/f'{i:03d}.png', manifest.parent/f'{i:03d}.raw.png'
            variants = [p for p in (current, raw) if p.exists()]
            variants += sorted((self.folder/'candidates'/f'{i:03d}').glob('*/*.png'))
            variants += sorted((self.folder/'versions'/f'{i:03d}').glob('*.png'))
            variants = [p for p in variants if not since or p.stat().st_mtime >= since]
            entries = []
            seen = set()
            for path in variants:
                if '.tmp.' in path.name or '.rejected-' in path.name or path.name.endswith('.plate.png') or (path.name == '000.raw.png' and path.parent != manifest.parent):
                    continue
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                cached = self._image_fingerprints.get(path)
                if cached is None or cached[:2] != signature:
                    cached = (*signature, content_digest(path))
                    self._image_fingerprints[path] = cached
                fingerprint = cached[2]
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                review = None
                if path.with_suffix('.review.json').exists():
                    try:
                        review = json.loads(path.with_suffix('.review.json').read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        pass
                from artwork.metadata import variant_metadata
                metadata=variant_metadata(path,job,i)
                from artwork.video_art import sidecar
                clip=sidecar(path)
                clip_info=self.animation(fingerprint) if not clip else None
                animation=clip_info['url'] if clip_info else None
                entries.append(dict(prompt=metadata.get('prompt',prompt),subject=metadata.get('subject',''),style=metadata.get('style',''),video=self.url(clip) if clip else None,animation=animation,animation_parts=clip_info['parts'] if clip_info else None,animation_total=clip_info['total'] if clip_info else None,animation_segments=clip_info.get('segments') if clip_info else None,animation_scene=clip_info.get('scene') if clip_info else None,animation_upscaled=clip_info.get('upscaled') if clip_info else None,path=path.relative_to(self.folder).as_posix(), url=self.url(path),
                    current=path == current, raw=path == raw, rendered=bool(recorded) and fingerprint == recorded, fresh=path.is_relative_to(self.folder/'candidates') and stat.st_mtime>=self.state['started'], review=review))
            queued=next((q for q in self.state.get('queued_actions',[]) if q.get('index')==i and q.get('action','regenerate') in ('regenerate','reprompt')),None)
            pending=('Prompt queued' if queued.get('action')=='reprompt' else 'Image queued') if queued else ''
            reference_work = list(self.state.get('queued_actions', [])) + list(self.state.get('reference_batch') or [])
            if not pending and any(q.get('action') == 'reference' and i in q.get('images', []) for q in reference_work):
                pending = 'Waiting for regenerated references'
            animate=next((q for q in self.state.get('queued_actions',[]) if q.get('action')=='animate' and i in (q.get('indices') or [])),None)
            if not pending and animate:
                first=(animate.get('segments') or {}).get(str(i))
                pending='Upscale queued' if i in (animate.get('upscale') or []) else 'Animation queued'+(f' from segment {first+1}' if first else '')
            if not pending and i in self.state.get('animating',[]):
                pending='Animating'
            if i in self.state.get('active_images',[]) :
                pending='Preparing prompt' if self.state.get('action_stage') in PROMPT_STAGES else 'Generating replacement'
            # why it is painted again, when a reason was recorded ('reference': a reference it shows was repainted); the
            # request is in the queue until the worker claims it into the running batch
            requests=list(self.state.get('queued_actions',[]))+list((getattr(self,'generation_batch',None) or {}).get('items') or [])
            reason=next((r.get('reason') for r in requests if r.get('index')==i and r.get('reason')),None)
            result.append(dict(index=i, pending=pending, reason=reason, subject=job.get('visual_descriptions', job['prompts'])[i],
                lyrics=job['groups'][i], prompt=prompt, style=job.get('style_prompt',self.config.get('style_prompt','')), variants=entries))
        return result


def held_by_jobs():
    """{model id: kind} that running jobs hold on the GPU, from their own state: the video model while a job animates,
    the image model while one paints. Workers also report themselves (models.gpu.telemetry); this covers one that
    started before it did, or between its reports."""
    held = {}
    for job in list(JOBS.values()):
        action, state = job.state.get('action'), job.state
        if action == 'animate' or (state.get('status') == 'running' and state.get('stage') == 'video'):
            if job.config.get('video_model'):
                held[job.config['video_model']] = 'video'
        if action in ('regenerate', 'reprompt', 'verify', 'repair') or (
                state.get('status') == 'running' and state.get('stage') in ('model', 'references', 'illustrations')):
            if job.config.get('image_model'):
                held[job.config['image_model']] = 'image'
        if state.get('status') == 'running' and state.get('stage') == 'alignment' and job.config.get('asr_model'):
            held[job.config['asr_model']] = 'transcription'
    return held


def checked_file(job, value):
    path = (job.folder/value).resolve()
    if not path.is_relative_to(job.folder.resolve()) or not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('Select an image belonging to this job')
    return path


STOP_GRACE = 25  # seconds a cancelled run has to leave by itself


def request_stop(process):
    """Ask a run to leave at its next step (see core.stopping)."""
    try:
        process.stop_file.write_text('stop', encoding='utf-8')
    except (AttributeError, OSError):  # a run from before stop files: finish_stop forces it
        pass


def force_stop(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    else:
        os.killpg(process.pid, signal.SIGTERM)


def finish_stop(processes, grace=None):
    """Wait for the asked runs to leave, forcing what has not left by the end of `grace`. A step takes up to 8 seconds
    (LTX-2.5); loading a model cannot be interrupted, and is safe to force."""
    deadline = time.monotonic()+(STOP_GRACE if grace is None else grace)
    for process in processes:
        try:
            process.wait(timeout=max(.1, deadline-time.monotonic()) if getattr(process, 'stop_file', None) else 0)
        except subprocess.TimeoutExpired:
            print(f'Run {process.pid} did not stop in time; forcing it.', flush=True)
            force_stop(process)


def stop_job(job, keep_queue=False, background=False):
    """Stop the job's running work. With `keep_queue` (the Cancel button, closing the studio) the queued work stays,
    waiting for Run queue, and an interrupted animation batch's unfinished clips are put back in it; otherwise (a new
    run, a restart from the storyline) the queue goes too. The running work is asked to stop (finish_stop); with
    `background` this returns without waiting for it."""
    with LOCK:
        if job.state['status'] == 'complete' and not job.state.get('action'):
            return
        job.cancelled = True
        job.generation += 1
        from artwork.queue import queue_path
        if not keep_queue:
            queue_path(job.folder).unlink(missing_ok=True)
        stopping = [process for process in (job.action_process, job.process) if process and process.poll() is None]
        for process in stopping:
            request_stop(process)
        if keep_queue:
            if job.state.get('action') == 'reference':
                queued_ids = {q.get('entity') for q in job.state.get('queued_actions', []) if q.get('action') == 'reference'}
                job.state['queued_actions'].extend(q for q in job.state.get('reference_batch', []) if q.get('entity') not in queued_ids)
            batch = job.state.get('action') == 'animate'
            job.state.update(status='cancelled', action=None, animating=[], animating_segments={}, redo_pending={},
                             message='Cancelled; the queue is kept (Run queue starts it again)', finished=time.time())
            if batch:
                job.queue_missing_clips()  # the batch's clips not finished yet wait in the queue
        else:
            job.state.update(status='cancelled', action=None, queued_actions=[], message='Cancelled; saved files retained', finished=time.time())
        job.save()
    if background:
        threading.Thread(target=finish_stop, args=(stopping,), daemon=True).start()
    else:
        finish_stop(stopping)


def stop_video_work(job):
    """Stop the video being made so edited timings can be saved. Returns what restart_video_work starts again."""
    from artwork.queue import queue_path
    with LOCK:
        action = job.state.get('action')
        if action and action not in ('rerender', 'patch'):
            raise ValueError('Wait for the current image operation to finish before saving timings')
        kind = 'rerender' if action else 'run'
        if kind == 'run' and not job.command:
            raise ValueError('This run started before the studio restarted. Cancel it, then save the timings.')
        status, queued = job.state['status'], list(job.state['queued_actions'])
        pending = queue_path(job.folder).read_text(encoding='utf-8') if queue_path(job.folder).exists() else None
    stop_job(job)
    try:
        deadline = time.time()+60
        while True:
            with LOCK:
                if not job.runs:break
            if time.time() > deadline:
                raise ValueError('The current video operation did not stop. Try saving again.')
            time.sleep(.2)
    finally:
        with LOCK:  # queued image requests are not part of the video; keep them, even if the stop timed out
            job.state['queued_actions'] = queued
            if pending is not None:queue_path(job.folder).write_text(pending, encoding='utf-8')
    return kind, status


def restart_video_work(job, kind, status):
    with LOCK:
        job.cancelled = False
        if kind == 'rerender':
            command = [*module_command('studio.worker'), 'rerender', str(job.folder)]
            job.state.update(status='complete' if status == 'cancelled' else status, action='rerender', action_percent=0,
                             message='Rebuilding the video with the edited word timings')
            args = (command, 'rerender')
        else:
            command = job.resume_command(job.command)
            job.state.update(status='running', action=None, auto_resumes=0, timing_dirty=False,
                             message='Restarting video generation with the edited word timings')
            args = (command,)
        job.log('Word timings edited in the timeline; the running video was stopped and restarted with them.', 'warning')
        job.save()
    threading.Thread(target=job.run, args=args, daemon=True).start()


def parse_form(body, content_type):
    message = BytesParser(policy=default).parsebytes(
        b'Content-Type: '+content_type.encode()+b'\r\nMIME-Version: 1.0\r\n\r\n'+body)
    if not message.is_multipart():
        raise ValueError('Expected multipart form data')
    fields, files = {}, {}
    for part in message.iter_parts():
        name = part.get_param('name', header='content-disposition')
        if not name:
            continue
        data = part.get_payload(decode=True) or b''
        if part.get_filename():
            files.setdefault(name, []).append((part.get_filename(), data))
        else:
            fields[name] = data.decode('utf-8')
    return fields, files


def store_image(folder, filename, content):
    from PIL import Image
    import io
    if Path(filename).suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('Reference and replacement images must be PNG, JPEG or WebP')
    with Image.open(io.BytesIO(content)) as image:
        image.verify()
    folder.mkdir(parents=True, exist_ok=True)
    # Content-addressed: the same picture uploaded again (every restart re-sends the form's references) is kept once.
    import hashlib
    path = folder/(hashlib.sha1(content).hexdigest()[:16]+'.png')
    if path.is_file():
        return path
    with Image.open(io.BytesIO(content)) as image:
        image.convert('RGBA').save(path)
    return path


def keep_upload_name(path, filename):
    """Rename a stored image to the name it was uploaded under, so its @tag is a name the user knows. Only letters,
    digits, _ and - stay, as a tag holds no others. A different picture with that name makes this one name-2."""
    stem = re.sub(r'[^\w-]+', '_', Path(filename).stem).strip('_')[:60] or path.stem
    number = 1
    while True:
        target = path.with_name(f"{stem}{f'-{number}' if number > 1 else ''}{path.suffix}")
        if target == path:
            return path
        if not target.exists():
            return path.rename(target)
        if target.read_bytes() == path.read_bytes():
            path.unlink()
            return target
        number += 1


BACKDROPS = ROOT/'backdrops'


def backdrop_list():
    """The pictures a theme can show behind the glass: the front end's built-in art, then the ones the user added."""
    pictures = []
    for path in sorted((UI_ROOT/'art').glob('*.webp')):
        if path.with_suffix('.mp4').is_file():  # a built-in video's poster is offered with the video
            continue
        # file names start with the theme they were drawn for: day-meadow, night-osaka-lanterns
        theme, _, rest = path.stem.partition('-')
        fits = {'day': 'light', 'night': 'dark'}.get(theme)
        pictures.append(dict(url='/studio-art/'+path.name, name=(rest if fits else path.stem).replace('-', ' ').capitalize(),
                             builtin=True, theme=fits))
    pass
    if BACKDROPS.is_dir():
        pictures += [dict(url='/studio-backdrop/'+path.name, name='Added picture', builtin=False)
                     for path in sorted(BACKDROPS.glob('*.webp'), key=lambda path: path.stat().st_mtime)
                     if not path.with_suffix('.mp4').is_file()]
        pass
    return pictures


def store_backdrop(filename, content):
    """Keep an added backdrop as a webp no longer than 2000 px on its long side, content-addressed so the same
    picture added twice is kept once. Returns the URL the page loads it from."""
    from PIL import Image
    import hashlib
    import io
    pass
    if Path(filename).suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('Backdrops must be PNG, JPEG or WebP')
    with Image.open(io.BytesIO(content)) as image:
        image.verify()
    BACKDROPS.mkdir(parents=True, exist_ok=True)
    path = BACKDROPS/(hashlib.sha1(content).hexdigest()[:16]+'.webp')
    if not path.is_file():
        with Image.open(io.BytesIO(content)) as image:
            image = image.convert('RGB')
            scale = 2000/max(image.size)
            if scale < 1:
                image = image.resize((round(image.width*scale), round(image.height*scale)), Image.LANCZOS)
            image.save(path, 'WEBP', quality=82, method=4)
    return '/studio-backdrop/'+path.name


def forget_audio_analysis(folder):
    """Remove everything measured from a project's previous audio track."""
    for name in ('video.timings.json', 'video.melody.json', 'video.rhythm.json', 'video.instruments.json', 'vocals.wav',
                 'video.graph.sqlite', 'video.graph.sqlite-wal', 'video.graph.sqlite-shm'):
        (folder/name).unlink(missing_ok=True)
    shutil.rmtree(folder/'stems', ignore_errors=True)


# Names a project writes itself, or Windows keeps for devices: a song called one of these is set apart.
TAKEN_AUDIO_NAMES = re.compile(r'(?:video|vocals|instrumental|poster|con|prn|aux|nul|com\d|lpt\d)', re.I)


def audio_file_name(filename):
    """The name a song is kept under in its project: its own, without folders or what Windows refuses."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(filename).replace('\\', '/').rsplit('/', 1)[-1]).strip(' ')
    stem, suffix = os.path.splitext(name)
    if not stem or stem.startswith('.') and not suffix:  # '.mp3' has a suffix only
        stem, suffix = 'audio', suffix or name
    stem = stem.rstrip(' .')[:120] or 'audio'
    return ('song-' if TAKEN_AUDIO_NAMES.fullmatch(stem) else '')+stem+suffix


def project_audio(folder):
    """The song of a project: the file its config names, and any kept as audio.* by older versions."""
    found = [path for path in folder.glob('audio.*') if path.suffix.lower() in AUDIO_SUFFIXES]
    try:
        named = folder/Path(str(json.loads((folder/'config.json').read_text(encoding='utf-8')).get('audio') or '').replace('\\', '/')).name
    except (OSError, ValueError, AttributeError):
        return found
    return found+[named] if named not in found and named.is_file() and named.suffix.lower() in AUDIO_SUFFIXES else found


def run_audio(files, project_id, is_restart):
    """The run's audio as (file name, bytes): the upload, or the saved track on a restart."""
    if not files.get('audio'):
        if is_restart:
            existing_audio = sorted(project_audio(ROOT / project_id), key=lambda p: p.stat().st_mtime_ns)
            if existing_audio:
                return existing_audio[-1].name, existing_audio[-1].read_bytes()
        raise ValueError('Choose an audio file')
    return files['audio'][0]


def save_audio(folder, filename, audio_bytes):
    """Saves the audio under its own name. The same track stays as it is, under the name it has; a different one replaces
    the old one and its analysis. Returns (path, replaced)."""
    audio = folder/audio_file_name(filename)
    previous_audio = project_audio(folder)
    same = next((path for path in previous_audio if path.read_bytes() == audio_bytes), None)
    if same:
        return same, False
    audio_replaced = bool(previous_audio)
    if audio_replaced:
        for path in previous_audio:
            path.unlink()
        forget_audio_analysis(folder)
    if audio_replaced or not audio.exists():
        audio.write_bytes(audio_bytes)
    return audio, audio_replaced


UPSCALE_CHOICES = ('off', 'review', 'auto')


def upscale_choice(value):
    return 'off'


def end_frame_choice(value):
    return 'off'


def cinemagraph_choice(value):
    return 'off'


def picture_choice(value, video=False):
    return 'static'


def mood_choice(fields):
    """The visual style and mood from a form: none unless the user writes one, also on a restart of the job."""
    return str(fields.get('style') or '').strip()


def run_seed(fields, folder, is_restart, start_step):
    """Returns (seed, randomised). A restart that keeps saved prompts keeps the saved seed unless given one."""
    seed_val = fields.get('image_seed', fields.get('seed', ''))
    seed_field = str(seed_val).strip() if seed_val is not None else ''
    randomize = fields.get('randomize_seed') in ('on', 'true', '1') or seed_field in ('', '-1', 'random')
    if randomize:
        image_seed = secrets.randbelow(2**31)
    else:
        try:
            image_seed = int(seed_field)
        except ValueError:
            image_seed = secrets.randbelow(2**31)
    if is_restart and start_step in ('images','review','render') and (not seed_field or fields.get('resume') == '1'):
        try:image_seed=json.loads((folder/'config.json').read_text(encoding='utf-8')).get('image_seed',image_seed)
        except (OSError,ValueError):pass
    return image_seed, randomize


def check_run_config(config):
    """Checks settings that must agree: artwork, video model, review and encoder."""
    if config['artwork_mode'] not in ('cutout','fullscreen','verse','matte'):
        raise ValueError('Invalid artwork mode')
    if config['video_model'] and config['video_model'] not in [m['id'] for m in VIDEO_MODELS]:
        raise ValueError('Choose a supported video model')
    if config['video_model'] and config['artwork_mode'] not in VIDEO_MODES:
        raise ValueError('Video generation needs full-screen or verse-inspired artwork')
    if not 0 <= config['review_threshold'] <= 100:
        raise ValueError('Review threshold must be between 0 and 100 percent')
    if config['auto_verify'] and not config['vision_model']:
        raise ValueError('Select a vision model, or turn off anatomy review for this job')
    if config['encoder'] not in ('h264_nvenc', 'libx264'):
        raise ValueError('Invalid encoder')


def purge_small_pictures(folder):
    """The stage's small pictures go with a restart at or before the images, kept or not: they were chosen for what is
    being redone. Their folder goes too, as a picture is reused from it whenever its prompt comes out the same; it is
    moved to the output folder's .trash, where it can be recovered by hand."""
    from direction.ornaments import KEEP_FILE
    for name in ('video.blocks.json', KEEP_FILE):
        (folder/name).unlink(missing_ok=True)
    painted = folder/'video.ornaments'
    if painted.is_dir():
        trash = folder.parent/'.trash'
        trash.mkdir(exist_ok=True)
        shutil.move(str(painted), str(trash/f'{folder.name}.small-artwork-{time.time_ns()}'))


def clear_redone_work(folder, config, start_step):
    """Invalidate both displayed artwork and the inputs generation would otherwise reuse."""
    reset_references = start_step in ('timing', 'prompts', 'images') and not (
        start_step == 'images' and config.get('start_substep') == 'illustrations')
    token, edited_images = '', set()
    if reset_references:
        from artwork.maker import maker_folder
        from artwork.reference_lifecycle import advance, edited_signatures, retire_library
        home = maker_folder(folder.parent)
        edited_images = edited_signatures(folder, home)
        token = advance(folder)
        retire_library(folder, home)
    if start_step in ('timing', 'prompts', 'images'):
        purge_small_pictures(folder)
    if start_step == 'timing':
        for f in [folder/'video.timings.json', folder/'video.theme.json', folder/'video.art-times.json']:
            if f.exists(): f.unlink()
    elif start_step == 'prompts':
        for f in [folder/'video.theme.json']:
            if f.exists(): f.unlink()
    if start_step in ('timing', 'prompts'):
        # A matching prompt can select any older content-addressed run. Clear every
        # reusable image cache, including entity sheets, while retaining checkpoints.
        from artwork.active import archive_folder
        for artwork in (folder/'video.artwork').iterdir() if (folder/'video.artwork').is_dir() else []:
            if artwork.is_dir() and not artwork.is_symlink():
                archive_folder(artwork, references=True, story=True)
    elif start_step == 'images':
        from artwork.active import archive_images, select_manifest
        try:  # the reference pictures are redone with the images: painted again, not reused (an upload is kept)
            from core.files import update_json
            from direction.story import story_path
            path = story_path(select_manifest(folder, dict(config, start_step='review')))  # as archive_images finds it

            def repaint(story):
                if config.get('start_substep')=='illustrations':
                    return
                for entity in story.get('entities') or []:
                    from artwork.reference_lifecycle import is_generated_edit
                    if entity.get('uploaded') and not is_generated_edit(entity, edited_images):
                        continue
                    entity['reference_generation'] = token
                    if entity.pop('image', None):
                        entity['repaint'] = int(entity.get('repaint') or 0)+1
                    for key in ('sheet_review', 'review_repaints', 'uploaded', 'image_history', 'image_origin',
                                'painted_prompt', 'force_used', 'force_review', 'image_updated_at'):
                        entity.pop(key, None)
            if path.is_file():
                update_json(path, repaint)
                if reset_references:
                    from direction.reference_choices import path as choices_path
                    from core.files import cached_digest, write_json_atomic
                    saved = json.loads(path.read_text(encoding='utf-8'))
                    choices = {e['id']: dict(**{k: e[k] for k in ('image', 'uploaded', 'image_updated_at', 'force_used', 'force_review', 'image_origin') if k in e},
                                sha=cached_digest(Path(e['image'])), reference_generation=token)
                               for e in saved.get('entities', []) if e.get('uploaded') and e.get('image') and Path(e['image']).is_file()}
                    write_json_atomic(choices_path(path.with_name('illustrations.json')), choices)
        except (OSError, ValueError):
            pass
        archive_images(folder, config)


def register_run(folder, config):
    """The job for this run: a new one, or the project's job reset."""
    if folder.name in JOBS:
        job = JOBS[folder.name]
        job.config = config
        job.cancelled = False
        # A new run starts from a clean state: nothing from the previous run (its start time, history, review
        # flags, stage) may leak into this one's elapsed time, progress or resume decisions.
        job.state = dict(Job.initial_state(folder, config), status='running')
        from artwork.queue import queue_path
        pending_path=queue_path(folder)
        job.state['queued_actions'] = json.loads(pending_path.read_text(encoding='utf-8')) if pending_path.exists() else []
    else:
        job = Job(folder, config)
        JOBS[folder.name] = job
    return job


def start_job(fields, files):
    """Starts a pipeline run for a new song, or restarts a saved project from a later step."""
    with LOCK:
        if any(j.state['status'] in ('queued', 'running', 'review') or j.state['action'] for j in JOBS.values()):
            raise ValueError('Finish or cancel the active job before starting another GPU job')
        project_id = fields.get('project_id', '').strip()
        if project_id:
            project_folder(project_id)  # refuses anything but a project folder inside ROOT
            if project_id in JOBS and JOBS[project_id].runs:
                # Its stopped process is still being wound down; starting now could read that exit as a crash.
                raise ValueError('The previous run of this song is still stopping; start again in a moment')
        start_step = fields.get('start_step', 'beginning').strip()
        if project_id:
            from studio.pipeline_history import preserve_existing
            preserve_existing(ROOT/project_id)
        ai_model = fields.get('ai_model', 'auto').strip()
        is_restart = bool(start_step != 'beginning' and project_id and (ROOT / project_id).is_dir())
        if ai_model not in ('','auto') or fields.get('auto_verify')=='on':
            from models.ollama.catalog import validate_selected_models
            ai_model=validate_selected_models(ai_model,fields.get('vision_model',''),fields.get('auto_verify')=='on')

        filename, audio_bytes = run_audio(files, project_id, is_restart)
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_SUFFIXES or not audio_bytes:
            raise ValueError('Unsupported or empty audio file')
        from pipeline.timing import imported_timings, sanitize_lyrics, validate, normalized_newlines
        lyrics = sanitize_lyrics(fields.get('lyrics', '')).strip()
        new_timings = bool(fields.get('lyric_timings'))
        imported = imported_timings(fields['lyric_timings']) if new_timings else None
        if fields.get('protect_word_alignment') == 'on' and imported is None:
            timing_path = ROOT/project_id/'video.timings.json' if project_id else None
            if timing_path is None or not timing_path.is_file():
                raise ValueError('Import a timeline before protecting word alignment. ASR will not run.')
            imported = imported_timings(timing_path.read_text(encoding='utf-8-sig'))
        if imported is not None:
            timed_lyrics = '\n'.join(line['text'] for line in imported)
            submitted = [s.strip() for s in fields.get('lyrics', '').splitlines()
                         if s.strip() and not re.fullmatch(r'\s*\[.*\]\s*', s)]
            if submitted != timed_lyrics.splitlines():
                raise ValueError('Lyrics differ from the imported timeframe. Import it again or load plain lyrics.')
            lyrics = normalized_newlines(fields.get('lyrics', '')).strip()  # keep section labels and paragraph boundaries
        if is_restart and start_step in ('prompts', 'images', 'review', 'render'):
            try:
                previous_lyrics = sanitize_lyrics((ROOT / project_id / 'lyrics.txt').read_text(encoding='utf-8')).strip()
            except OSError:
                previous_lyrics = None
            if previous_lyrics is not None and lyrics != previous_lyrics:
                start_step = 'timing'
        width, height = {'720p': (1280, 720), '1080p': (1920, 1080), 'portrait': (720, 1280)}[fields.get('resolution', '720p')]
        asr_model=fields.get('asr_model',DEFAULT_ASR)
        alignment_model=fields.get('alignment_model','auto')
        if imported is None:
            validate_speech(asr_model,fields.get('language','auto'),alignment_model,has_lyrics=bool(lyrics))
        image_model = fields.get('image_model', MODEL)
        spec = next((m for m in MODELS if m['id'] == image_model), None)
        if spec is None:
            raise ValueError('Choose a supported image model')
        steps, lines = int(fields.get('steps') or spec['steps']), str(fields.get('lines', 'auto')).strip().lower()
        from direction.song_structure import parse_line_pattern
        pattern = parse_line_pattern(lines)  # a manual split such as 2-3-2-4, cycled over the song
        lines_ok = pattern is not None or lines == 'auto' or (lines.isdecimal() and 1 <= int(lines) <= 50)
        if not 1 <= steps <= 150 or not lines_ok:
            raise ValueError('Steps must be 1–150; lines per image must be Auto, 1–50, or a split such as 2-3-2-4')
        if pattern:
            lines = max(1, round(sum(pattern)/len(pattern)))  # the fixed count stands in where only a number fits
        elif lines != 'auto':
            lines = int(lines)
        if is_restart:
            folder = ROOT / project_id
        else:
            folder = ROOT/(time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
            folder.mkdir(parents=True, exist_ok=True)
        audio, audio_replaced = save_audio(folder, filename, audio_bytes)
        if imported is not None:
            from core.media import media_duration
            validate(imported, [line['text'] for line in imported], media_duration(audio))
            if is_restart and new_timings:
                start_step = 'timing'  # downstream plans must use the newly imported timeframe
        if audio_replaced and start_step in ('prompts', 'images', 'review', 'render'):
            # Saved timings belong to the old track; artwork for unchanged lyrics is still reused.
            start_step = 'timing'
        from core.files import write_text_atomic
        write_text_atomic(folder/'lyrics.txt', normalized_newlines(lyrics))
        refs = [store_image(folder/'references', name, content) for name, content in files.get('references', [])]
        if not refs and is_restart and (folder/'references').is_dir():
            # A restart sends no files: the pictures already kept with the project (added and removed in its
            # References panel) are the ones to use, or the prompts are planned as if there were none.
            refs = sorted(p for p in (folder/'references').iterdir()
                          if p.is_file() and p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'))
        image_seed, randomize = run_seed(fields, folder, is_restart, start_step)
        if is_restart and not files.get('audio'):
            try:filename=json.loads((folder/'config.json').read_text(encoding='utf-8')).get('audio_name',filename)
            except (OSError,ValueError):pass
        from direction.image_instruction_cleanup import clean_legacy_imported_meaning
        config = dict(name=str(fields.get('name', '')).strip()[:80] or Path(filename).stem, audio=str(audio), audio_name=filename,
            profile_name=str(fields.get('profile_name','')).strip()[:80], width=width, height=height, fps=30,
            protect_word_alignment=imported is not None,
            image_cache=str(Path(fields.get('cache', '').strip() or str(default_model_cache())).expanduser().resolve()),
            style_prompt=fields.get('reference_prompt', '').strip() or STYLE_PROMPT,
            image_instructions=clean_legacy_imported_meaning(fields.get('image_instructions', ''))[:2000],
            story_prompt=str(fields.get('story_prompt', '')).strip()[:50000],
            reference_use='likeness' if fields.get('cast_reference') == 'on' else 'style',
            theme=mood_choice(fields),
            artwork_mode=fields.get('artwork_mode','cutout'), image_seed=image_seed, randomize_seed=randomize,
            scene_direction='summary' if fields.get('scene_direction') == 'summary' else 'timed', video_upscale=upscale_choice(fields.get('video_upscale')), end_frame_model=end_frame_choice(fields.get('end_frame_model')), end_frame_review=fields.get('end_frame_review')=='on',
            picture_kinds=picture_choice(fields.get('picture_kinds') or ('cinemagraph' if fields.get('video_cinemagraph') == 'on' else ''), fields.get('video_generation') == 'on'),
            cinematic=fields.get('cinematic') == 'on', encoder=fields.get('encoder', 'h264_nvenc'),
            illustration_lines=lines, line_pattern='-'.join(map(str, pattern)) if pattern else '', steps=steps, image_model=image_model, asr_model=asr_model, alignment_model=alignment_model,
            language=fields.get('language','').strip(),
            ai_model=ai_model, start_step=start_step, project_id=folder.name, run_started=time.time(),
            start_substep=fields.get('start_substep', '') if (start_step == 'prompts' and fields.get('start_substep') in PROMPT_STAGES[1:]) or (start_step=='images' and fields.get('start_substep') in ('references','illustrations')) else '',
            vision_model=fields.get('vision_model','').strip(),auto_verify=fields.get('auto_verify')=='on',review_references=fields.get('review_references','on')=='on',repaint_references=fields.get('repaint_references','on')=='on',image_check_prompt=str(fields.get('image_check_prompt','')).strip()[:12000],reference_check_prompt=str(fields.get('reference_check_prompt','')).strip()[:6000],
            auto_accept=fields.get('auto_accept')=='on', auto_repair=fields.get('auto_repair','on')=='on',review_threshold=int(fields.get('review_threshold',DEFAULT_THRESHOLD)),
            video_model='')
        config.update(render_settings(fields))  # effects, particles, word animation, audio, stage pictures, typography
        check_run_config(config)
        # Resume (the run stopped inside or before this step): keep everything it finished and make only what is
        # missing. Otherwise the step is redone from scratch.
        resume = is_restart and not new_timings and fields.get('resume') == '1'
        if resume:
            try:
                previous_config = json.loads((folder/'config.json').read_text(encoding='utf-8'))
                if previous_config.get('gallery_since'):
                    config['gallery_since'] = previous_config['gallery_since']
            except (OSError, ValueError):
                pass
        if start_step in ('beginning', 'timing', 'prompts', 'images') and not resume:
            # This run makes new artwork, so the gallery starts empty instead of showing the previous images.
            config['gallery_since'] = time.time()
        (folder/'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')

        if is_restart and not resume:
            clear_redone_work(folder, config, start_step)
        if imported is not None:
            from core.files import write_json_atomic
            write_json_atomic(folder/'video.timings.json', imported)
        from studio.timeline_preview import reuse_stems
        reuse_stems(audio, folder)
        command = pipeline_command(config, folder, audio, lyrics, refs, width=width, height=height, steps=steps, lines=lines,
                                   ai_model=ai_model, is_restart=is_restart, start_step=start_step)
        job = register_run(folder, config)
        if imported is not None:
            job.log('Imported lyric timeframe: skipping ASR and word alignment; using the saved word timestamps.')
        if audio_replaced:
            job.log('New audio track: lyric timing, vocal and instrument analysis are redone for it.')
        job.save()
        threading.Thread(target=job.run, args=(command,), daemon=True).start()
        return job


def pipeline_command(config, folder, audio, lyrics, refs, *, width, height, steps, lines, ai_model, is_restart, start_step):
    """The pipeline.cli command line for a job's run. A restart from a later step reuses the saved timings, plan and
    illustration times, and re-saves lyrics.txt with the timed line breaks when the lyrics were edited."""
    command = [*module_command('pipeline.cli'), str(audio)]
    if lyrics:
        command.append(str(folder/'lyrics.txt'))
    story_arg = config.get('story_prompt', '')
    if len(story_arg) > 4000:
        story_file = folder / 'story.txt'
        story_file.write_text(story_arg, encoding='utf-8')
        story_arg = str(story_file)
    command += [
        # Free text goes as --flag=value, so text starting with '-' is never read as another option.
        '--theme='+config['theme'], '--style-prompt='+config['style_prompt'],
        '--image-instructions='+config['image_instructions'], '--story='+story_arg,
        '--image-cache', config['image_cache'],
        '--reference-use', config['reference_use'], '--vision-model', config['vision_model'],
        '--artwork-mode', config['artwork_mode'], '--image-seed', str(config['image_seed']),
        '--image-model', config['image_model'], '--image-steps', str(steps), '--illustration-lines', str(lines), *(['--line-pattern', config['line_pattern']] if config.get('line_pattern') else []),
        '--width', str(width), '--height', str(height), '--encoder', config['encoder'], '--preserve-art-slots',
        '--asr-model',config['asr_model'], '--alignment-model',config['alignment_model'],
        '--type-effect',config['type_effect'], '--particle-intensity', str(config['particle_intensity']), '--particle-speed', str(config.get('particle_speed', 1.)),
        '-o', str(folder/'video.mp4')]
    command += ['--text-animation', config['text_animation'], '--audio-mode', config['audio_mode'], '--text-pool',json.dumps(config['text_pool']),
                '--font-family',config['font_family'],'--font-style',config['font_style'],'--font-scale',str(config['font_scale']),'--lettering-styles',json.dumps(config['lettering_styles']),'--reading-flow',config['reading_flow'],'--kinetic',json.dumps(config['kinetic']),'--effect-speeds',json.dumps(config['effect_speeds']),
                '--effect-intensities',json.dumps(config['effect_intensities']),
                '--stage-pictures',config.get('stage_pictures','ai-painted')]
    if config.get('instructions'):
        command += ['--instructions='+config['instructions']]
    if not config['auto_accept']:
        command.append('--review-artwork')
    if config['video_model']:
        # Video generation is its own job (the queued "animate" action), separate from typography and the render,
        # so either can be repeated without the other.
        command += ['--video-model', config['video_model'], '--no-video-step', '--scene-direction', config.get('scene_direction', 'timed')]
    command += ['--entrance-effect', config['entrance_effect'], '--exit-effect', config['exit_effect']]
    for phase in ('entrance', 'exit'):
        if config[phase + '_pool'] is not None:
            command += ['--' + phase + '-pool', json.dumps(config[phase + '_pool'])]
    if config['language'] and config['language']!='auto':
        command += ['--language',config['language']]
    if ai_model and ai_model != 'auto':
        command += ['--ai-model', ai_model]
    if is_restart:
        command.append('--overwrite')
        design_path = folder/'video.design.json'
        if start_step == 'render' and design_path.exists():
            try:
                scenes = json.loads(design_path.read_text(encoding='utf-8')).get('scenes')
                lines = json.loads((folder/'video.timings.json').read_text(encoding='utf-8'))
                if isinstance(scenes, list) and len(scenes) == len(lines):
                    command += ['--plan', str(design_path)]
            except (OSError, ValueError, AttributeError):
                pass
        if start_step in ('prompts', 'images', 'review', 'render'):
            timings_path = folder/'video.timings.json'
            if timings_path.exists():
                command += ['--timings', str(timings_path)]
                if lyrics:
                    from render.timeline import rewrite_lyrics
                    timed = [line['text'] for line in json.loads(timings_path.read_text(encoding='utf-8'))]
                    submitted = [s for s in (l.strip() for l in lyrics.splitlines()) if s and not re.fullmatch(r'\[.*\]', s)]
                    if len(submitted) == len(timed):
                        from core.files import write_text_atomic
                        write_text_atomic(folder/'lyrics.txt', rewrite_lyrics(lyrics, timed))
        if start_step in ('review', 'render') and (folder/'video.art-times.json').exists():
            command += ['--art-times', str(folder/'video.art-times.json')]
    if config.get('protect_word_alignment'):
        if '--timings' not in command:
            command += ['--timings', str(folder/'video.timings.json')]
        command.append('--protect-word-alignment')
    command += ['--style-reference', *map(str, refs)] if refs else ['--no-default-style-references']
    if config['cinematic']:
        command.append('--cinematic')
    return command


def regenerate_from_story(job):
    """Stop the job's current work and restart it at Images with the saved prompts and story: every image, and so
    every clip, is made again (the old ones are archived, not deleted)."""
    try:
        stop_job(job)
        deadline = time.time()+60
        while True:
            with LOCK:
                if not job.runs:
                    break
            if time.time() > deadline:
                raise ValueError('The current work did not stop')
            time.sleep(.2)
        regenerate_new_session(job, restart_step='images')
    except Exception as exc:
        with LOCK:
            job.log(f'Could not restart image generation from the storyline: {exc}', 'error')
            job.save()


def regenerate_new_session(source, image_model=None, restart_step=None):
    """Run the whole pipeline with the source job's inputs in a fresh project folder, or (restart_step) restart the
    same project at that step."""
    config = source.config
    fields = {key: json.dumps(value) if isinstance(value, (list, dict)) else str(value)
              for key, value in config.items() if value is not None}
    fields.update(project_id='', start_step='beginning',
                  resolution={(1280, 720): '720p', (1920, 1080): '1080p', (720, 1280): 'portrait'}[
                      (config['width'], config['height'])],
                  cache=config['image_cache'], style=config['theme'], reference_prompt=config['style_prompt'], scene_direction=config.get('scene_direction', 'timed'),
                  lines=config.get('line_pattern') or ('auto' if config.get('illustration_lines_mode') == 'auto' else str(config['illustration_lines'])),
                  cinematic='on' if config['cinematic'] else 'off',
                  auto_verify='on' if config['auto_verify'] else 'off',
                  auto_accept='on' if config['auto_accept'] else 'off',
                  auto_repair='on' if config['auto_repair'] else 'off',
                  # The form keeps a video model only with this checkbox on; without it the new run lost its video step.
                  video_generation='on' if config.get('video_model') else 'off',
                  randomize_seed='on' if config.get('randomize_seed') else 'off')
    if image_model is not None:
        from models.image.catalog import model_spec
        if image_model not in {spec['id'] for spec in MODELS}:
            raise ValueError('Choose a supported image model')
        fields['image_model']=image_model
        fields['steps']=str(model_spec(image_model)['steps'])
    audio = Path(config['audio'])
    references = source.folder/'references'
    files = dict(audio=[(config.get('audio_name') or audio.name, audio.read_bytes())],
                 references=[(path.name, path.read_bytes()) for path in sorted(references.iterdir())
                             if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
                 if references.is_dir() else [])
    fields['lyrics'] = (source.folder/'lyrics.txt').read_text(encoding='utf-8')
    if config.get('protect_word_alignment'):
        fields['protect_word_alignment'] = 'on'
        fields['lyric_timings'] = (source.folder/'video.timings.json').read_text(encoding='utf-8')
    if restart_step:
        fields.update(project_id=source.folder.name, start_step=restart_step)
    return start_job(fields, files)


class Handler(GetRoutes, JobRoutes, ImageOperations, MakerRoutes, BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def log_message(self, *args):
        pass

    def trusted(self):
        """Only this computer's own pages may talk to the studio. A web page whose name was pointed at 127.0.0.1
        (DNS rebinding) sends its own Host, and a cross-site form post sends its own Origin; both are refused."""
        port = self.server.server_address[1]
        allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host', '') not in allowed:
            return False
        origin = self.headers.get('Origin')
        return origin is None or origin in {'http://'+host for host in allowed}

    def respond(self, data, status=200, content_type='application/json'):
        payload = json.dumps(data).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if not self.trusted():
            return self.respond(dict(error='Open the studio at http://127.0.0.1:%d' % self.server.server_address[1]), 403)
        try:
            url = urlsplit(self.path)
            for matches, route in GET_ROUTES:  # in order: the job routes before the /api/jobs/<id> catch-all
                if matches(url.path):
                    return route(self, url)
            self.respond(dict(error='Not found'), 404)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True
        except (KeyError, ValueError, OSError) as exc:
            self.respond(dict(error=str(exc)), 400)
        except Exception as exc:
            self.respond(dict(error=str(exc)), 503)

    def _post_projects_folder(self, route, body):
        """Choose where new projects go (Settings); used from the next start, as the studio reads its projects then."""
        from core.paths import save_projects_folder, studio_output
        save_projects_folder(json_body(body).get('path'))
        folder = studio_output(PROJECT_ROOT, 'lyric-studio')
        return self.respond(dict(ok=True, folder=str(folder), restart=folder != ROOT))

    def do_POST(self):
        if not self.trusted():
            return self.respond(dict(error='Open the studio at http://127.0.0.1:%d' % self.server.server_address[1]), 403)
        try:
            if self.headers.get('X-Studio-Token') != TOKEN:
                return self.respond(dict(error='Reload the studio page'), 403)
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 256*1024*1024:
                raise ValueError('Upload must be between 1 byte and 256 MiB')
            body = self.rfile.read(length)
            route = urlsplit(self.path).path
            if route in POST_ROUTES:
                return POST_ROUTES[route](self, route, body)
            if not re.fullmatch(r'/api/jobs/[^/]+/[^/]+', route):
                return self.respond(dict(error='Unknown API route'), 404)
            _, _, _, job_id, operation = route.split('/')
            job = JOBS[job_id]
            # A stopped job (cancelled or failed at any step) that still has a finished video from an earlier render
            # can be edited and rebuilt like a completed one.
            saved_video = (job.state['status'] in ('cancelled', 'failed') and not job.state.get('action')
                           and (job.folder/'video.mp4').is_file())
            if operation in JOB_ROUTES_RAW:
                return JOB_ROUTES_RAW[operation](self, job, body)
            if self.headers.get('Content-Type', '').startswith('multipart/'):
                args, files = parse_form(body, self.headers['Content-Type'])
            else:
                args, files = json_body(body), {}
            if operation in JOB_ROUTES:
                return JOB_ROUTES[operation](self, job, operation, args, files)
            return self._job_image_operation(job, operation, args, files, saved_video)
        except (ValueError, KeyError, OSError, IndexError) as exc:
            self.respond(dict(error=str(exc)), 400)
        except ImportError as exc:
            # Answer instead of dropping the connection, which the browser only reports as "Failed to fetch".
            package = {'yt_dlp': 'yt-dlp', 'bs4': 'beautifulsoup4'}.get(exc.name, exc.name)
            self.respond(dict(error=f'The studio Python environment is missing the "{package}" package. '
                                    f'Install it with: python -m pip install -r requirements.txt, then restart the studio.'), 500)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True
        except Exception as exc:  # noqa: BLE001 - any other failure still gets an answer, with the cause logged
            import traceback
            traceback.print_exc()
            self.respond(dict(error=f'{type(exc).__name__}: {exc}'), 500)

    def _post_downloads(self, route, body):
        """Start or cancel model downloads."""
        from models.downloads import request_downloads, cancel_downloads
        args=json_body(body)
        return self.respond(cancel_downloads(args.get('ids',[])) if route.endswith('/cancel') else request_downloads(args.get('models',[])))

    def _post_profile_audio(self, route, body):
        """Store a profile's audio file."""
        from studio.profile_audio import store_profile_audio
        fields,files=parse_form(body,self.headers['Content-Type'])
        if len(files.get('audio',[]))!=1:
            raise ValueError('Choose one audio file')
        name,content=files['audio'][0]
        path=store_profile_audio(PROJECT_ROOT/'profiles'/'audio',name,content,AUDIO_SUFFIXES)
        return self.respond(dict(path=str(path)),201)

    def _post_import_youtube(self, route, body):
        """Import a song and its lyrics from YouTube."""
        from studio.youtube_import import import_youtube
        args=json_body(body)
        return self.respond(import_youtube(args.get('url',''), PROJECT_ROOT/'profiles'/'audio'),201)

    def _post_timeline_stems(self, route, body):
        from studio.profile_audio import profile_audio_path
        from studio.timeline_preview import request_stems
        args = json_body(body)
        if args.get('audio_path'):
            audio = profile_audio_path(PROJECT_ROOT/'profiles'/'audio', args['audio_path'], AUDIO_SUFFIXES)
        elif args.get('project_id') in JOBS:
            audio = Path(JOBS[args['project_id']].config['audio'])
        else:
            raise ValueError('Choose the song audio before loading stem waveforms')
        def busy():
            with LOCK:
                return any(j.state['status'] in ('queued', 'running', 'review') or j.state.get('action') for j in JOBS.values())
        source = JOBS.get(args.get('project_id'))
        return self.respond(request_stems(audio, busy, retry=args.get('retry') is True,
                                         source_folder=source.folder if source else None))

    def _post_start_job(self, route, body):
        """Start a new job, or restart an existing song from a step."""
        fields, files = parse_form(body, self.headers['Content-Type'])
        return self.respond(dict(id=start_job(fields, files).folder.name), 201)


# GET routes, tried in order (prefix and suffix tests overlap, so order matters).
GET_ROUTES = [
    (lambda path: path == '/', Handler._get_page),
    (lambda path: path.startswith('/api/image-maker'), Handler._get_maker),
    (lambda path: path in ('/assets/reference_female_2.jpeg', '/assets/reference_default.jpeg', '/assets/default-style-reference.jpg'), Handler._get_default_style),
    (lambda path: path in ('/assets/reference_female_1.jpeg', '/assets/filipina-reference.png'), Handler._get_filipina_reference),
    (lambda path: re.fullmatch(r'/studio-art/(?:scene-assets/)?[a-z0-9-]+\.(?:webp|mp4|png|scene\.json)', path) is not None, Handler._get_art),
    (lambda path: re.fullmatch(r'/studio-backdrop/[a-f0-9]{16}\.(webp|mp4)', path) is not None, Handler._get_backdrop),
    (lambda path: path == '/api/backdrops', Handler._get_backdrops),
    (lambda path: re.fullmatch(r'/studio(?:-[a-z0-9-]+)?\.(?:css|js)', path) is not None, Handler._get_static),
    (lambda path: path == '/api/profile-audio', Handler._get_profile_audio),
    (lambda path: path == '/api/scene-preview', Handler._get_scene_preview),
    (lambda path: path == '/api/particle-preview', Handler._get_particle_preview),
    (lambda path: path == '/api/job-list', Handler._get_job_list),
    (lambda path: path == '/api/config', Handler._get_config),
    (lambda path: path == '/api/gpu', Handler._get_gpu),
    (lambda path: path == '/api/downloads', Handler._get_downloads),
    (lambda path: path == '/api/models/ready', Handler._get_models_ready),
    (lambda path: path in ('/api/models','/api/models/best'), Handler._get_models),
    (lambda path: path.startswith('/api/projects/') and path.endswith('/status'), Handler._get_project_status),
    (lambda path: path.startswith('/api/jobs/') and path.endswith('/story'), Handler._get_story),
    (lambda path: path.startswith('/api/jobs/') and path.endswith('/timeline'), Handler._get_timeline),
    (lambda path: path.startswith('/api/jobs/'), Handler._get_job),
    (lambda path: path.startswith('/files/'), Handler._get_file),
]


# POST routes: the whole path, then a job operation (/api/jobs/<id>/<operation>). Operations in
# JOB_ROUTES_RAW read the body themselves; the others get it parsed; anything else is an image operation.
POST_ROUTES = {'/api/timeline-stems': Handler._post_timeline_stems, '/api/projects-folder': Handler._post_projects_folder, '/api/backdrops': Handler._post_backdrops, '/api/backdrops/remove': Handler._post_backdrops, '/api/downloads': Handler._post_downloads, '/api/downloads/cancel': Handler._post_downloads, '/api/profile-audio': Handler._post_profile_audio, '/api/import-youtube': Handler._post_import_youtube, '/api/jobs': Handler._post_start_job}
POST_ROUTES.update({'/api/image-maker/'+action: Handler._post_maker for action in
                    ('reference', 'project-references', 'reference-delete', 'reference-usage', 'picture-references', 'picture-delete', 'prompt', 'prompt-delete', 'generate', 'revise', 'stop', 'choose-folder')})
JOB_ROUTES_RAW = {'regenerate-new': Handler._job_regenerate_new, 'cancel': Handler._job_cancel, 'rename': Handler._job_rename, 'delete': Handler._job_delete}
JOB_ROUTES = {'pipeline-version': Handler._job_pipeline_version, 'settings': Handler._job_settings, 'reference-add': Handler._job_reference_add, 'reference-remove': Handler._job_reference_remove, 'story-reference': Handler._job_story_reference, 'story-entity': Handler._job_story_entity, 'story-entities': Handler._job_story_entities, 'queue-remove': Handler._job_queue_remove, 'clear-log': Handler._job_clear_log, 'queue-run': Handler._job_queue_run, 'story-reference-remove': Handler._job_story_reference, 'story-upload-delete': Handler._job_story_upload_delete, 'story-write': Handler._job_story_write, 'story': Handler._job_story, 'reference-repaint': Handler._job_reference_repaint, 'reference-input-upload': Handler._job_reference_input_upload, 'reference-version': Handler._job_reference_version, 'reference-prompt': Handler._job_reference_prompt, 'keep-picture': Handler._job_keep_picture, 'timings': Handler._job_timings, }


@contextmanager
def editable_stopped_job(job, saved_video):
    """A stopped job that kept a finished video is edited like a completed one. If the request then fails before
    any work starts, the job is left stopped as it was. Called with LOCK held."""
    if not saved_video:
        yield
        return
    before = job.cancelled, job.state['status']
    job.cancelled, job.state['status'] = False, 'complete'
    try:
        yield
    except BaseException:
        if not job.state.get('action') and job.state['status'] == 'complete':
            job.cancelled, job.state['status'] = before
        raise


def json_body(body):
    """A request's JSON body, which must be an object."""
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError('The request body must be a JSON object')
    return value


PROJECT_ID = re.compile(r'[\w-]{1,80}')


def project_folder(project_id):
    """The folder of an existing project. Only a plain folder name directly inside ROOT is accepted, so a form or
    an imported profile can never point the studio at another folder (`..`, an absolute path, a drive)."""
    if not PROJECT_ID.fullmatch(project_id):
        raise ValueError('Invalid project')
    folder = ROOT/project_id
    if folder.resolve().parent != ROOT.resolve():
        raise ValueError('Invalid project')
    return folder


def job_list():
    """Every song, newest first, with its run status so a fresh window can open the one that is running."""
    def entry(j):
        video = j.folder/'video.mp4'; poster = j.folder/'poster.png'
        return dict(id=j.folder.name, name=j.config['name'], status=j.state.get('status', ''),
                    started=j.state.get('started'), finished=j.state.get('finished'),
                    has_images=(j.folder/'active-artwork.json').is_file() or (j.folder/'video.artwork').is_dir(),
                    video=j.url(video) if video.is_file() else None, poster=j.url(poster) if poster.is_file() else None)
    return [entry(j) for j in reversed(list(JOBS.values()))]


def restore():
    ROOT.mkdir(parents=True, exist_ok=True)
    for folder in sorted(ROOT.iterdir()):
        if (folder/'config.json').exists():
            try:
                from pipeline.versions import Versions
                if (folder/'pipeline'/'restore.json').is_file():
                    Versions(folder).summary()  # recover before reading the working config
                job = Job(folder, json.loads((folder/'config.json').read_text(encoding='utf-8')))
                try:  # a damaged state file loses the run's history, not the song
                    if (folder/'state.json').exists():
                        job.state.update(json.loads((folder/'state.json').read_text(encoding='utf-8')))
                except (OSError, ValueError, TypeError):
                    job.state.update(status='failed', message='Saved run state was unreadable')
                if job.state['status'] not in ('complete', 'failed', 'cancelled'):
                    job.state.update(status='cancelled', message='Server restarted; previous job interrupted', finished=time.time())
                job.state['action'] = None
                # The queue saved with the project waits again (Run queue starts it); image requests still in their
                # own file join it once. What a stopped job was doing (its clips being animated) is over.
                saved = [q for q in job.state.get('queued_actions') or [] if isinstance(q, dict)]
                job.state.update(queued_actions=saved, active_images=[], animating=[], animating_segments={},
                                 effecting=[], redo_pending={})
                from artwork.queue import queue_path
                pending_path=queue_path(folder)
                if pending_path.exists():
                    known = {q.get('request_id') for q in saved if q.get('request_id')}
                    job.state['queued_actions'] += [q for q in json.loads(pending_path.read_text(encoding='utf-8'))
                                                    if isinstance(q, dict) and q.get('request_id') not in known]
                JOBS[folder.name] = job
            except (OSError, ValueError):
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--no-prerender', action='store_true', help='do not draw the effect samples ahead of time')
    args = parser.parse_args()
    restore()
    if not args.no_prerender:  # the effect lists open at once; drawn one sample at a time, never while a job runs
        from effects.particles.preview import start_prerender
        start_prerender(busy=lambda: any(job.state['status'] in ('queued', 'running') or job.state.get('action')
                                         for job in list(JOBS.values())))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{args.port}'
    print(f'Kinetic Lyrics: {url}\nOutputs: {ROOT}\nPress Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for job in JOBS.values():
            if job.state['status'] in ('queued', 'running', 'review') or job.state['action']:
                stop_job(job, keep_queue=True)
        server.server_close()


if __name__ == '__main__':
    main()
