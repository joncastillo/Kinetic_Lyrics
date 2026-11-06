"""Project artifact contracts for the versioned pipeline working copy."""

import json
from pathlib import Path

from pipeline.versions import DEPENDENCIES, Versions, ancestors


SETTINGS = {
    'timing': ('audio', 'audio_name', 'language', 'asr_model', 'alignment_model', 'protect_word_alignment'),
    'prompts': ('ai_model', 'theme', 'style_prompt', 'illustration_lines', 'illustration_lines_mode', 'line_pattern'),
    'story': ('story_prompt', 'scene_direction', 'reference_use'),
    'image-prompts': ('image_model', 'artwork_mode', 'image_instructions', 'image_seed'),
    'images': (
        'image_model',
        'steps',
        'image_seed',
        'vision_model',
        'reference_prompt',
        'image_check_prompt',
        'reference_check_prompt',
        'review_threshold',
    ),
    'review': (),
    'video': (
        'video_model',
        'video_generation',
        'video_upscale',
        'picture_kinds',
        'end_frame_model',
        'end_frame_review',
    ),
    'scene-scan': ('depth_model',),
    'render': (
        'kinetic',
        'width',
        'height',
        'fps',
        'encoder',
        'reading_flow',
        'cinematic',
        'instructions',
        'font_family',
        'font_style',
        'font_scale',
        'text_pool',
        'effect_speeds',
        'effect_intensities',
        'lettering_styles',
        'type_effect',
        'particle_intensity',
        'particle_speed',
        'text_animation',
        'audio_mode',
        'entrance_effect',
        'exit_effect',
        'entrance_pool',
        'exit_pool',
        'stage_pictures',
    ),
    'final': (),
}


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


def files(folder, node, artwork=None):
    folder = Path(folder)
    names = {
        'timing': (
            'video.timings.json',
            'video.theme.json',
            'video.lyrics.txt',
            'video.rhythm.json',
            'video.melody.json',
            'video.instruments.json',
            'vocals.wav',
        ),
        'prompts': (),
        'story': (),
        'image-prompts': ('active-artwork.json',),
        'images': ('active-artwork.json', 'video.art-times.json', 'reference-edits.json',
                   'reference-generation.json', 'reference-image-revisions.json', 'reference-discarded.json'),
        'review': ('artwork-approved',),
        'video': (),
        'scene-scan': ('scene-lyrics.json',),
        'render': ('video.design.json', 'video.ass', 'video.blocks.json', 'video.pictures.json'),
        'final': ('video.mp4', 'video.render.json', 'poster.png'),
    }[node]
    result = [folder / name for name in names if (folder / name).is_file()]
    if node == 'timing':
        audio = read(folder / 'config.json').get('audio')
        if audio and Path(audio).is_file() and Path(audio).resolve().is_relative_to(folder.resolve()):
            result.append(Path(audio))
        if (folder / 'lyrics.txt').is_file():
            result.append(folder / 'lyrics.txt')
    if node == 'prompts':
        result += [p for p in (folder / 'references').rglob('*') if p.is_file()]
    if node == 'images':
        result += [p for p in (folder / 'reference-inputs').rglob('*') if p.is_file()]
    if node in ('prompts', 'story', 'image-prompts', 'images'):
        base = Path(artwork) if artwork else None
        if base is None:
            active = read(folder / 'active-artwork.json').get('manifest')
            if active:
                base = (folder / active).parent
        if base is None:
            candidates = list((folder / 'video.artwork').glob('*/illustrations.json'))
            base = (
                max(candidates, key=lambda p: p.stat().st_mtime_ns).parent if candidates else folder / 'video.artwork'
            )
        if not base.resolve().is_relative_to((folder / 'video.artwork').resolve()):
            raise ValueError('Artwork version leaves the project')
        for path in base.rglob('*'):
            if not path.is_file() or any(
                part.startswith(('.', 'archive', 'retired')) for part in path.relative_to(base).parts
            ):
                continue
            if (
                node == 'images'
                or node == 'image-prompts'
                and path.name in ('prompting.json', 'illustrations.json', 'story.json')
                or node == 'story'
                and path.name == 'story.json'
            ):
                result.append(path)
    if node in ('video', 'scene-scan'):
        for path in (folder / 'video-clips').rglob('*'):
            if path.is_file() and not any(
                part.startswith(('.', 'frames-')) for part in path.relative_to(folder / 'video-clips').parts
            ):
                if node == 'video' or path.suffix == '.json':
                    result.append(path)
    if node == 'render':
        result += [p for p in (folder / 'video.ornaments').rglob('*') if p.is_file()]
    return [p for p in result if not p.name.endswith(('.lock', '.tmp', '.part'))]


def capture(folder, node, force=False, artwork=None, attempt=None):
    folder = Path(folder).resolve()
    if not (folder / 'config.json').is_file():
        return None  # standalone CLI runs do not use Studio's project file contracts
    config = read(folder / 'config.json')
    start = config.get('start_step', 'beginning')
    start = 'timing' if start == 'beginning' else start
    if start == 'prompts':
        start = {'story': 'story', 'scenes': 'image-prompts', 'fit': 'image-prompts'}.get(
            config.get('start_substep'), start
        )
    force = force or bool(config.get('run_started') and (node == start or start in ancestors(node)))
    contents = {}
    if node in ('prompts', 'story'):
        allowed = ('song', 'meanings') if node == 'prompts' else ('song', 'meanings', 'story')
        checkpoints = (
            [Path(artwork) / 'prompting.json'] if artwork else list((folder / 'video.artwork').glob('*/prompting.json'))
        )
        for path in checkpoints:
            payload = read(path)
            if not all(key in payload for key in allowed):
                continue
            payload = {key: value for key, value in payload.items() if key in (*allowed, 'lines', 'saved_at')}
            payload['saved_at'] = {key: value for key, value in payload.get('saved_at', {}).items() if key in allowed}
            contents[path.relative_to(folder).as_posix()] = payload
    return Versions(folder).capture(
        node,
        files(folder, node, artwork),
        {key: config[key] for key in SETTINGS[node] if key in config},
        force=force,
        contents=contents,
        run=config.get('run_started') if attempt is None else attempt,
        unset=[key for key in SETTINGS[node] if key not in config],
    )


def working_files(folder):
    """Include unfinished output branches when clearing the active working copy."""
    folder = Path(folder).resolve()
    result = set()
    for node in DEPENDENCIES:
        result.update(files(folder, node))
    for path in (folder / 'video.artwork').rglob('*'):
        if path.is_file() and not any(
            part.startswith(('.', 'archive', 'retired')) for part in path.relative_to(folder / 'video.artwork').parts
        ):
            if not path.name.endswith(('.lock', '.tmp', '.part')):
                result.add(path)
    return result


def preserve_existing(folder):
    """Import the current legacy project once, before a restart can remove outputs."""
    folder = Path(folder)
    if (folder / 'pipeline.json').exists():
        return
    has_prompts = any((folder / 'video.artwork').glob('*/illustrations.json'))
    has_images = any((folder / 'video.artwork').glob('*/*.png'))
    present = {
        'timing': (folder / 'video.timings.json').is_file(),
        'prompts': has_prompts or any((folder / 'video.artwork').glob('*/prompting.json')),
        'story': has_prompts or any((folder / 'video.artwork').glob('*/story.json')),
        'image-prompts': has_prompts,
        'images': has_images,
        'review': (folder / 'artwork-approved').exists() or (folder / 'video.mp4').exists(),
        'video': any((folder / 'video-clips').glob('*/clip.mp4')),
        'scene-scan': (folder / 'scene-lyrics.json').is_file()
        or any((folder / 'video-clips').glob('*/scene-suggestion.json')),
        'render': (folder / 'video.mp4').exists(),
        'final': (folder / 'video.mp4').exists(),
    }
    for node in DEPENDENCIES:
        if present[node]:
            capture(folder, node)
