"""Time left for a song: the work still to do in every step, this run's and the separate AI video work after it, each
at the speed this computer was measured at.

The progress bar gives each step a fixed share, so a pace read from it cannot know that one image takes minutes, nor
see the AI video and Final cut that follow the run. Here every step is counted in its own units: images left, seconds
of clip left, seconds of song to render, sections to rebuild. Their speeds are measured as jobs finish and kept in
timing-stats.json beside the projects (a running average), so the estimate improves with every song.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# Steps of the main run, in order; images and the render are counted in their own units below.
PREPARE = ('alignment', 'song', 'meanings', 'story', 'scenes', 'fit')
IMAGES = ('model', 'references', 'reference-check', 'illustrations', 'illustration-check', 'cutouts')
TEXT = ('direction', 'pictures', 'render')
ORDER = PREPARE+IMAGES+('review',)+TEXT
ALIAS = {'subjects': 'song', 'verification': 'illustration-check', 'repair': 'illustration-check'}  # steps within a step
# Until this computer has been measured: seconds per step, per image, per second of clip or song, per section.
DEFAULTS = {'stage:alignment': 90., 'stage:song': 60., 'stage:meanings': 60., 'stage:story': 120., 'stage:scenes': 240.,
            'stage:fit': 120., 'stage:reference-check': 120., 'stage:illustration-check': 300.,
            'stage:direction': 60., 'stage:pictures': 60., 'model': 60.,
            'image': 240., 'video_per_second': 9., 'render_per_second': 1.5, 'patch': 40.,
            'load:image': 60., 'load:video': 90.}
WEIGHT = .4  # how much a new measurement moves the running average


def stats_path(folder):
    return Path(folder).parent/'timing-stats.json'


def load_stats(folder):
    try:
        stats = json.loads(stats_path(folder).read_text(encoding='utf-8'))
        return stats if isinstance(stats, dict) else {}
    except (OSError, ValueError):
        return {}


def speed(stats, key, fallback=None):
    value = stats.get(key)
    return float(value) if isinstance(value, (int, float)) and value > 0 else DEFAULTS.get(fallback or key, 60.)


def record(folder, key, value):
    """Fold one measurement into the running average for `key`; a failure to save never matters."""
    if not value or value <= 0:
        return
    try:
        from core.files import update_json
        path = stats_path(folder)
        if not path.is_file():
            path.write_text('{}', encoding='utf-8')

        def change(stats):
            old = stats.get(key)
            stats[key] = round(value if not isinstance(old, (int, float)) else old*(1-WEIGHT)+value*WEIGHT, 3)
        update_json(path, change)
    except Exception:  # noqa: BLE001 (statistics are a help, never a reason to fail a job)
        pass


def image_key(config):
    """Images are timed per base model and inference step count."""
    model = config.get('image_model') or ''
    return f"image:{model}:steps-{config.get('steps') or ''}", 'image'


def video_key(config):
    return f"video_per_second:{config.get('video_model') or ''}"


def images_left(job):
    """Images of the song with no painting yet."""
    try:
        manifest = job.manifest()
        count = len(json.loads(manifest.read_text(encoding='utf-8')).get('prompts') or [])
    except (OSError, ValueError, KeyError):
        return None
    return sum(1 for i in range(count) if not (manifest.parent/f'{i:03d}.raw.png').is_file())


def estimate(job, now=None):
    """{seconds, parts: [[label, seconds]]} of work left for this song, or None when nothing is running or queued."""
    now = now or time.time()
    state, config = job.state, job.config
    stats = load_stats(job.folder)
    summary = job.pipeline_summary() if hasattr(job, 'pipeline_summary') else {}
    sections = (summary or {}).get('sections') or {}
    seconds_of = sections.get('seconds') or []
    song = sum(seconds_of) or 0.
    video = (summary or {}).get('video')
    detail = state.get('detail') or {}
    parts = {}

    def add(label, seconds):
        if seconds and seconds > 0:
            parts[label] = parts.get(label, 0.)+seconds

    image_exact, image_general = image_key(config)
    per_image = speed(stats, image_exact, image_general) if image_exact in stats else speed(stats, image_general)
    per_clip_second = speed(stats, video_key(config), 'video_per_second') if video_key(config) in stats else \
        speed(stats, 'video_per_second')
    render_seconds = song*speed(stats, 'render_per_second')+speed(stats, 'stage:direction')+speed(stats, 'stage:pictures')
    clips_left = max(0, video['total']-video['made']) if video else 0
    clip_seconds_left = clips_left*(song/len(seconds_of)) if seconds_of else clips_left*8.

    running = state.get('status') in ('running', 'queued') and not state.get('action')
    if running:
        stage = ALIAS.get(state.get('stage'), state.get('stage'))
        position = ORDER.index(stage) if stage in ORDER else -1
        in_stage = now-float(state.get('stage_started') or now)
        for name in PREPARE:
            if ORDER.index(name) >= position:
                left = speed(stats, 'stage:'+name)-(in_stage if name == stage else 0)
                add('Timing and prompts', max(left, 15. if name == stage else 0))
        if position <= ORDER.index('illustrations'):
            remaining = images_left(job)
            add('Images', (remaining if remaining is not None else 0)*per_image
                + (speed(stats, 'model') if position < ORDER.index('references') else 0))
        if stage in TEXT:
            done = float(detail.get('fraction') or 0) if detail.get('stage') == 'render' else 0
            add('Kinetic text', render_seconds*(1-done) if stage == 'render' else render_seconds)
        elif position < ORDER.index('direction'):
            add('Kinetic text', render_seconds)
        if config.get('video_model') and video is not None:
            add('AI video', clip_seconds_left*per_clip_second)
            add('Final cut', clips_left*speed(stats, 'patch'))

    action = state.get('action')
    items = {}  # 'group:index' -> seconds of its own work, for each pill's hover

    def clip(index):
        seconds = seconds_of[index] if index < len(seconds_of) else (song/len(seconds_of) if seconds_of else 8.)
        # a cinemagraph is one 5 s part, however long the section it loops over
        return (min(seconds, 5.) if 'cinemagraph' in str(config.get('picture_kinds')) else seconds)*per_clip_second

    if action == 'animate':
        batch = list(state.get('animating') or [])
        current = detail.get('image', 0)-1 if detail.get('stage') == 'video' and isinstance(detail.get('image'), int) else None
        ahead = batch[batch.index(current):] if current in batch else batch
        if detail.get('stage') == 'video' and isinstance(detail.get('eta_seconds'), (int, float)):
            add('AI video', max(0., detail['eta_seconds']-(now-float(state.get('detail_at') or now))))
        else:
            add('AI video', sum(clip(i) for i in ahead) or clip_seconds_left*per_clip_second)
        for index in ahead:
            items[f'animation:{index}'] = clip(index)
        add('Final cut', len(ahead)*speed(stats, 'patch'))
    elif action == 'patch':
        add('Final cut', speed(stats, 'patch')*(1-float(state.get('action_percent') or 0)/100))
    elif action == 'rerender':
        add('Kinetic text', render_seconds*(1-float(state.get('action_percent') or 0)/100))
    elif action in ('regenerate', 'reprompt'):
        add('Images', max(1, len(state.get('active_images') or []))*per_image)

    # what waits after the current work, item by item, plus one model load for every job the queue will start
    from studio.job_queue import FAMILY, queue_plan
    for kind in queue_plan(state.get('queued_actions') or [], None, state.get('last_family') if not action else FAMILY.get(action)):
        family = FAMILY.get(kind)
        if family and not (kind == action):
            add('AI video' if family == 'video' else 'Images', speed(stats, 'load:'+family))
    for queued in state.get('queued_actions') or []:
        kind = queued.get('action', 'regenerate')
        if kind == 'animate':
            indices = queued.get('indices') or [queued.get('index', 0)]
            upscale = set(queued.get('upscale') or [])
            for index in indices:
                # an accepted clip is only upscaled; anything else is animated
                cost = clip(index)/per_clip_second*UPSCALE_PER_SECOND if index in upscale else clip(index)
                items[f'animation:{index}'] = cost
                add('AI video', cost)
            add('Final cut', len(indices)*speed(stats, 'patch'))
        elif kind == 'patch':
            items[f"checks:{queued.get('index')}"] = speed(stats, 'patch')
            add('Final cut', speed(stats, 'patch'))
        elif kind == 'rerender':
            add('Kinetic text', render_seconds)
        elif kind in ('regenerate', 'reprompt'):
            items[f"images:{queued.get('index')}"] = per_image
            add('Images', per_image)

    if not parts:
        return None
    return dict(seconds=round(sum(parts.values())), parts=[[label, round(seconds)] for label, seconds in parts.items()],
                items={key: round(seconds) for key, seconds in items.items()})


UPSCALE_PER_SECOND = 2.  # the upscale's seconds per second of clip on a 4090 (about 10 s for 5 s, with its encoding)


def measure_stage(job, previous, started, now=None):
    """A main-run step just ended: fold its duration in (images and the render are measured in their own units)."""
    now = now or time.time()
    took = now-float(started or now)
    if previous in PREPARE+('direction', 'pictures', 'model') and took > 2:
        record(job.folder, 'stage:'+previous if previous != 'model' else 'model', took)


def measure_image(job, gap):
    """The time between two images saved in one batch (the model already loaded)."""
    if gap and 5 < gap < 3600:
        exact, _ = image_key(job.config)
        record(job.folder, exact, gap)


def measure_action(job, action, took, indices=()):
    """A queued job finished: the AI video per second of clip made, a rebuilt section, a full re-render per second."""
    summary = job.pipeline_summary() if hasattr(job, 'pipeline_summary') else {}
    seconds_of = ((summary or {}).get('sections') or {}).get('seconds') or []
    if action == 'animate':
        made = sum(seconds_of[i] for i in indices if i < len(seconds_of))
        if made > 0 and took > 10:
            record(job.folder, video_key(job.config), took/made)
    elif action == 'patch' and took > 2:
        record(job.folder, 'patch', took)
    elif action == 'rerender' and sum(seconds_of) > 0 and took > 10:
        record(job.folder, 'render_per_second', took/sum(seconds_of))
