"""Illustration timing and reference identity shared by story planning and rendering."""
import json
from pathlib import Path


def main_character(illustrations):
    """The reference person's description when the run casts them as the main character ('' otherwise)."""
    record = Path(illustrations[0]).parent/'illustrations.json'
    try:
        job = json.loads(record.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ''
    return str(job.get('main_character') or '').strip() if job.get('reference_use') == 'likeness' else ''


def section_starts(illustrations, data, duration, args):
    """When each illustration's section starts in the song, as the compositor places it (hand-placed times win);
    None when they cannot be worked out. A clip starts playing at 0 s for the first illustration, otherwise here."""
    from render.timeline import checked_art_times, illustration_starts
    cues = [line['words'][0]['start'] for line in data]
    record = Path(illustrations[0]).parent/'illustrations.json'
    groups = None
    if record.is_file():
        groups = json.loads(record.read_text(encoding='utf-8')).get('line_groups')
        if groups is not None and len(groups) != len(illustrations):
            groups = None
    starts = illustration_starts(cues, len(illustrations), getattr(args, 'illustration_lines', 2) or 2,
                                 getattr(args, 'lead_in', 1.), groups)
    if getattr(args, 'art_times', None) is not None:
        starts = checked_art_times(args.art_times, len(illustrations), duration)
    return starts if len(starts) == len(illustrations) else None
