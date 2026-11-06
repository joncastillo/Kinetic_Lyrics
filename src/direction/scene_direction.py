"""Shared scene fields: supplied rendering style and the director's choice of action detail."""


def scene_direction(value):
    return 'summary' if value == 'summary' else 'timed'


def reference_style(job):
    """The user's Reference image prompt, with the project's first style photo's real tag."""
    from direction.illustration_prompts import style_only_prompt
    text = style_only_prompt(str(job.get('reference_prompt', job.get('style_prompt')) or '')).strip()
    if job.get('reference_paths'):
        text = 'Use @photo1 for the rendering style.\n' + text
    return text.strip()


def with_style(segment, job):
    return dict(segment, art_style=segment.get('art_style', reference_style(job)))


def video_style(text):
    """Video inherits reference style through its starting frame, not an unattached photo."""
    import re
    text = re.sub(r'Use @photo1 for the rendering style\.\s*', '', str(text or ''))
    return text.strip()
