"""GET routes of the studio server."""

from render.typography_settings import typography_options
from core.paths import PROJECT_ROOT, UI_ROOT
import json
import os
import mimetypes
from pathlib import Path
import re
from urllib.parse import unquote, parse_qs
from models.image.catalog import MODEL
from direction.illustration_prompts import STYLE_PROMPT
from render.text_effects import TEXT_ANIMATIONS
from effects.particles.catalog import discover_effects, catalog_choices
from direction.scene_catalog import scene_catalog
from effects.particles.scene_backdrops import backdrop_choices
from models.image.catalog import MODELS
from models.speech.catalog import ASR_MODELS, LANGUAGES, DEFAULT_ASR
from studio.lock import LOCK


class GetRoutes:
    def _get_page(self, url):
        """GET path == '/'"""
        return self.respond((UI_ROOT / 'studio.html').read_bytes(), content_type='text/html; charset=utf-8')

    def _get_default_style(self, url):
        """GET the default style reference (the old name stays an alias: saved profiles may still use it)"""
        return self.respond(
            (PROJECT_ROOT / 'assets' / 'reference_female_2.jpeg').read_bytes(), content_type='image/jpeg'
        )

    def _get_filipina_reference(self, url):
        """GET the default likeness reference (the old name stays an alias: saved profiles may still use it)"""
        return self.respond(
            (PROJECT_ROOT / 'assets' / 'reference_female_1.jpeg').read_bytes(), content_type='image/jpeg'
        )

    def _get_art(self, url):
        """GET /studio-art/<name>.(webp|mp4): the built-in pictures and looping videos."""
        path = (UI_ROOT / 'art' / url.path.removeprefix('/studio-art/')).resolve()
        if not path.is_relative_to((UI_ROOT / 'art').resolve()) or not path.is_file():
            return self.respond(dict(error='Unknown studio file'), 404)
        return self._respond_file(path)

    def _get_backdrop(self, url):
        """GET /studio-backdrop/<digest>.(webp|mp4): a backdrop the user added."""
        path = server.BACKDROPS / url.path.rsplit('/', 1)[1]
        if not path.is_file():
            return self.respond(dict(error='Unknown backdrop'), 404)
        return self._respond_file(path)

    def _get_backdrops(self, url):
        """GET /api/backdrops: every picture a theme can use."""
        return self.respond(dict(pictures=server.backdrop_list()))

    def _post_backdrops(self, route, body):
        """POST /api/backdrops (multipart, field "picture") adds a picture; /api/backdrops/remove ({url}) drops an added one."""
        if route.endswith('/remove'):
            name = server.json_body(body).get('url', '').rsplit('/', 1)[-1]
            if re.fullmatch(r'[a-f0-9]{16}\.(webp|mp4)', name):
                path = server.BACKDROPS / name
                for suffix in ('.mp4', '.webp', '.json'):
                    path.with_suffix(suffix).unlink(missing_ok=True)
            return self.respond(dict(pictures=server.backdrop_list()))
        _, files = server.parse_form(body, self.headers['Content-Type'])
        if not files.get('picture'):
            raise ValueError('Choose a picture to add')
        filename, content = files['picture'][0]
        added = server.store_backdrop(filename, content)
        return self.respond(dict(pictures=server.backdrop_list(), added=added))

    def _get_static(self, url):
        """GET any studio-*.css or studio-*.js module; they all live flat in UI_ROOT and the pattern keeps the path inside it"""
        path = UI_ROOT / url.path.lstrip('/')
        if not path.is_file():
            return self.respond(dict(error='Unknown studio file'), 404)
        return self.respond(path.read_bytes(), content_type='text/css' if path.suffix == '.css' else 'text/javascript')

    def _get_profile_audio(self, url):
        """GET path == '/api/profile-audio'"""
        from studio.profile_audio import profile_audio_path

        value = parse_qs(url.query).get('path', [''])[0]
        try:
            path = profile_audio_path(PROJECT_ROOT / 'profiles' / 'audio', value, server.AUDIO_SUFFIXES)
        except FileNotFoundError as exc:
            return self.respond(dict(error=str(exc)), 404)
        return self.respond(
            path.read_bytes(), content_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        )

    def _get_scene_preview(self, url):
        """GET path == '/api/scene-preview'"""
        from effects.particles.preview import render_scene_preview
        from effects.particles.scene_backdrops import DEFAULT_BACKDROP, backdrop_spec

        query = parse_qs(url.query)
        scene = query.get('scene', [''])[0]
        if scene not in scene_catalog():
            raise ValueError('Choose an available scene effect to preview')
        settings = typography_options(
            {key: query[key][0] for key in ('font_family', 'font_style', 'font_scale') if key in query}
        )
        from effects.particles.preview import request_prerender

        request_prerender(
            settings['font_family'], settings['font_style'], settings['font_scale']
        )  # the rest of the list, ahead of the scroll
        from direction.scene_controls import scene_settings

        overrides = scene_settings({scene: json.loads(query.get('settings', ['{}'])[0])}).get(scene, {})
        background = query.get('background', [DEFAULT_BACKDROP])[0]
        backdrop_spec(background)
        return self.respond(
            render_scene_preview(
                scene,
                settings['font_family'],
                settings['font_style'],
                settings['font_scale'],
                json.dumps(overrides, sort_keys=True),
                background,
            ),
            content_type='image/gif',
        )

    def _get_particle_preview(self, url):
        """GET path == '/api/particle-preview'"""
        from effects.particles.preview import render_preview

        query = parse_qs(url.query)
        phase = query.get('phase', ['exit'])[0]
        effect = query.get('effect', [''])[0]
        if phase == 'text':
            from effects.particles.preview import render_text_preview

            if effect not in TEXT_ANIMATIONS:
                raise ValueError('Unknown word animation')
            settings = typography_options(
                {key: query[key][0] for key in ('font_family', 'font_style', 'font_scale') if key in query}
            )
            speed = float(query.get('speed', [1.0])[0])
            if not 0.2 <= speed <= 3:
                raise ValueError('Invalid preview speed')
            from effects.particles.preview import request_prerender

            request_prerender(settings['font_family'], settings['font_style'], settings['font_scale'], 1.0, speed)
            return self.respond(
                render_text_preview(
                    effect, settings['font_family'], settings['font_style'], settings['font_scale'], speed
                ),
                content_type='image/gif',
            )
        catalog = discover_effects()
        if phase not in catalog or effect not in catalog[phase]:
            raise ValueError('Choose an available entrance or exit effect to preview')
        intensity = float(query.get('intensity', [1.0])[0])
        speed = float(query.get('speed', [1.0])[0])
        if not 0 <= intensity <= 2 or not 0.2 <= speed <= 3:
            raise ValueError('Invalid preview intensity or speed')
        settings = typography_options(
            {key: query[key][0] for key in ('font_family', 'font_style', 'font_scale') if key in query}
        )
        from effects.particles.preview import request_prerender

        request_prerender(settings['font_family'], settings['font_style'], settings['font_scale'], intensity, speed)
        return self.respond(
            render_preview(
                catalog[phase][effect],
                phase,
                intensity,
                speed,
                settings['font_family'],
                settings['font_style'],
                settings['font_scale'],
            ),
            content_type='image/gif',
        )

    def _get_job_list(self, url):
        """GET path == '/api/job-list'"""
        return self.respond(dict(jobs=server.job_list()))

    def _get_config(self, url):
        """GET path == '/api/config'"""
        from models.gpu.presets import PRESETS
        from models.ollama.catalog import PROMPT_MODELS, VISION_MODELS
        from models.vision.review import IMAGE_CHECK_RULES
        from models.vision.sheet_review import REFERENCE_CHECK_PROMPT
        from core.paths import documents_folder, saved_projects_folder

        return self.respond(
            dict(
                token=server.TOKEN,
                projects_folder=str(server.ROOT),
                projects_folder_saved=saved_projects_folder(),
                projects_folder_default=str(documents_folder() / 'Kinetic Lyrics'),
                projects_folder_fixed=bool(os.environ.get('KINETIC_LYRICS_OUTPUT')),
                image_check_prompt=IMAGE_CHECK_RULES,
                reference_check_prompt=REFERENCE_CHECK_PROMPT,
                image_instructions_supported=True,
                protected_timings_supported=True,
                auto_accept_supported=True,
                new_session_regeneration_supported=True,
                particle_materials_version=13,
                ai_typography_supported=True,
                typography_controls_supported=True,
                word_animations_supported=True,
                video_history_supported=True,
                video_history_version=2,
                live_artwork_version=2,
                replacement_priority_supported=True,
                particle_effects=catalog_choices(),
                scene_effects=list(scene_catalog().values()),
                scene_preview_backgrounds=backdrop_choices(),
                prompt_regeneration=True,
                generation_queue_version=2,
                style_prompt=STYLE_PROMPT,
                model=MODEL,
                image_models=MODELS,
                video_models=[],
                model_presets=PRESETS,
                prompt_choices=PROMPT_MODELS,
                vision_choices=VISION_MODELS,
                asr_models=ASR_MODELS,
                vocal_languages=LANGUAGES,
                default_asr=DEFAULT_ASR,
                jobs=server.job_list(),
            )
        )

    def _get_gpu(self, url):
        """GET path == '/api/gpu'"""
        from models.gpu.telemetry import gpu_usage

        return self.respond(gpu_usage(held=server.held_by_jobs()))

    def _get_downloads(self, url):
        """GET path == '/api/downloads'"""
        from models.downloads import download_status

        return self.respond(download_status())

    def _get_models_ready(self, url):
        """GET /api/models/ready?text=&image=&vision=&video=&cache=: whether each chosen model is on this computer, and
        for Ollama models whether it is loaded right now. The header pills colour themselves from this."""
        from models.readiness import readiness

        return self.respond(
            readiness({key: values[0] for key, values in parse_qs(url.query).items()}, held=set(server.held_by_jobs()))
        )

    def _get_models(self, url):
        """GET path in ('/api/models','/api/models/best')"""
        from models.ollama.catalog import model_choices
        from models.ollama.service import local_json

        return self.respond(model_choices(local_json, review=parse_qs(url.query).get('review', ['1'])[0] != '0'))

    def _get_project_status(self, url):
        """GET path.startswith('/api/projects/') and path.endswith('/status')"""
        project_id = url.path.split('/')[3]
        folder = server.project_folder(unquote(project_id))
        if not folder.is_dir():
            return self.respond(dict(exists=False), 404)
        manifests = (
            list((folder / 'video.artwork').glob('*/illustrations.json'))
            + list((folder / 'video.artwork').glob('illustrations.json'))
            + list(folder.glob('illustrations.json'))
        )
        from artwork.active import select_manifest

        try:
            manifest = select_manifest(folder)
        except ValueError:
            manifest = next((p for p in manifests if p.parent in (folder, folder / 'video.artwork')), None)
        images, reviews = [], []
        if manifest and manifest.parent.is_dir():
            images = [p.name for p in manifest.parent.glob('[0-9][0-9][0-9].png') if not p.name.endswith('.raw.png')]
            reviews = [p.name for p in manifest.parent.glob('*.review.json')]
        if not images and manifest and manifest.parent in (folder, folder / 'video.artwork'):
            images = [
                p.name
                for p in (folder / 'video.artwork').glob('*/*.png')
                if not p.name.endswith(('.raw.png', '.plate.png'))
            ]
        if not reviews and manifest and manifest.parent in (folder, folder / 'video.artwork'):
            reviews = [p.name for p in (folder / 'video.artwork').glob('*/*.review.json')]
        has_timings = (folder / 'video.timings.json').exists()
        has_prompts = bool(manifest and manifest.exists())
        has_video = (folder / 'video.mp4').exists()
        current_step = (
            5 if has_video else 4 if reviews else 3 if images else 2 if has_prompts else 1 if has_timings else 0
        )
        from direction.prompt_checkpoint import restartable

        prompt_substeps = (
            restartable(folder / 'video.artwork') if has_timings and (folder / 'video.artwork').is_dir() else []
        )
        return self.respond(
            dict(
                prompt_substeps=prompt_substeps,
                exists=True,
                id=project_id,
                has_audio=bool(server.project_audio(folder)),
                has_lyrics=(folder / 'lyrics.txt').exists(),
                has_timings=has_timings,
                has_prompts=has_prompts,
                has_images=bool(images),
                image_count=len(images),
                has_reviews=bool(reviews),
                has_video=has_video,
                current_step=current_step,
            )
        )

    def _get_story(self, url):
        """GET path.startswith('/api/jobs/') and path.endswith('/story')"""
        job = server.JOBS.get(url.path.split('/')[3])
        if job is None:
            return self.respond(dict(error='This song is no longer loaded in the studio.'), 404)
        with LOCK:
            return self.respond(job.story_state())

    def _get_timeline(self, url):
        """GET path.startswith('/api/jobs/') and path.endswith('/timeline')"""
        job = server.JOBS.get(url.path.split('/')[3])
        if job is None:
            return self.respond(
                dict(error='This song is no longer loaded in the studio. Reload the page and choose it again.'), 404
            )
        from studio.timeline_data import song_duration, timeline_stems, word_timings

        duration = song_duration(job.folder, job.config['audio'])
        # Timing failed or never finished: open on a draft the user can place by hand and save.
        draft = not (job.folder / 'video.timings.json').is_file()
        timings = word_timings(job.folder, duration)
        stems = timeline_stems(job.folder)
        from artwork.video_art import artwork_lane

        try:
            from core.files import file_digest as image_digest

            lanes = [
                dict(
                    index=lane['index'],
                    start=lane['start'],
                    end=lane['end'],
                    image=job.url(lane['image']),
                    video=job.url(lane['video']) if lane['video'] else None,
                    offset=lane['offset'],
                    framing=lane['framing'],
                    length=lane['length'],
                    animation=(job.animation(image_digest(lane['image'])) or {}).get('url'),
                )
                for lane in artwork_lane(job.folder, job.config, timings, duration)
                if lane['image'].is_file()
            ]
        except (OSError, ValueError, KeyError, IndexError):
            lanes = []

        def plan(name, key):
            # The typography plan files are optional: a song that has not been directed yet has none.
            try:
                return json.loads((job.folder / name).read_text(encoding='utf-8')).get(key) or []
            except (OSError, ValueError, AttributeError):
                return []

        blocks = [
            dict(
                lines=b.get('lines') or [],
                entrance=b.get('entrance'),
                particle=b.get('particle'),
                accent=b.get('accent_name') or b.get('accent'),
                ornament=(b.get('ornament') or {}).get('text'),
            )
            for b in plan('video.blocks.json', 'blocks')
            if isinstance(b, dict)
        ]
        design = [
            dict(mode=d.get('mode'), style=d.get('style'), camera=d.get('camera'), background=d.get('background'))
            for d in plan('video.design.json', 'scenes')
            if isinstance(d, dict)
        ]
        return self.respond(
            dict(
                timings=timings,
                lyrics=job.project_inputs()['lyrics'],
                stems=stems,
                duration=duration,
                artwork=lanes,
                blocks=blocks,
                design=design,
                scene_names=plan('video.scenes.json', 'scenes'),
                frame=dict(width=job.config.get('width', 1920), height=job.config.get('height', 1080)),
                audio=job.url(Path(job.config['audio'])),
                draft=draft,
                needs_render=job.state.get('timing_dirty', False),
            )
        )

    def _get_job(self, url):
        """GET path.startswith('/api/jobs/')"""
        job = server.JOBS[url.path.split('/')[3]]
        cursor = max(0, int(parse_qs(url.query).get('cursor', [0])[0]))
        return self.respond(job.snapshot(cursor))

    def _get_file(self, url):
        """GET path.startswith('/files/')"""
        _, _, job_id, relative = unquote(url.path).split('/', 3)
        job = server.JOBS[job_id]
        path = (job.folder / relative).resolve()
        valid = (
            path.is_relative_to(job.folder.resolve())
            and path.is_file()
            and path.suffix.lower() in {'.png', '.mp4', '.txt', '.json', *server.AUDIO_SUFFIXES}
        )
        if not valid:
            return self.respond(dict(error='File not found'), 404)
        return self._respond_file(path)

    def _respond_file(self, path):
        """Serve media with byte ranges, including backdrop and Image Maker MP4s."""
        size, start, end = path.stat().st_size, 0, path.stat().st_size - 1
        request_range = self.headers.get('Range', '')
        match = re.fullmatch(r'bytes=(\d+)-(\d*)', request_range)
        if match:
            start = int(match[1])
            end = min(end, int(match[2])) if match[2] else end
        if match and (start > end or start >= size):  # an empty file without a Range is a plain empty answer
            return self.respond(dict(error='Invalid range'), 416)
        self.send_response(206 if match else 200)
        self.send_header('Content-Type', mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if match:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        # The file is opened for each chunk, not held for the whole response: a browser that pauses reading would
        # otherwise keep it open indefinitely, and on Windows a new render could not replace it.
        position, remaining = start, end - start + 1
        while remaining:
            with path.open('rb') as source:
                source.seek(position)
                chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            self.wfile.write(chunk)
            position += len(chunk)
            remaining -= len(chunk)
        return


# Last, because studio.server imports this module.
from studio import server  # noqa: E402
