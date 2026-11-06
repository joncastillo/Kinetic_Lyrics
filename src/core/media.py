"""Facts about audio and video files, read with FFmpeg's ffprobe."""

import math
import os
from pathlib import Path
import subprocess


_DURATIONS = {}  # (path, size, modified) -> seconds


def media_duration(path):
    """Length of an audio or video file in seconds. ValueError, with a plain reason, when it cannot be read.
    Remembered while the file keeps its size and modification time: Studio asks for the same lengths on every
    panel refresh, sometimes while holding its lock."""
    try:
        stat = os.stat(path)
        key = (os.fspath(path), stat.st_size, stat.st_mtime_ns)
    except OSError:
        key = None
    if key in _DURATIONS:
        return _DURATIONS[key]
    duration = _measure(path)
    if key is not None:
        while len(_DURATIONS) >= 1024:
            _DURATIONS.pop(next(iter(_DURATIONS)))
        _DURATIONS[key] = duration
    return duration


def _measure(path):
    name = Path(path).name
    try:
        output = subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-show_entries',
                'format=duration',
                '-of',
                'default=noprint_wrappers=1:nokey=1',
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
        ).stdout
    except FileNotFoundError:
        raise ValueError(
            'FFmpeg is not installed or not on PATH, so media lengths cannot be measured. Install FFmpeg and try again.'
        ) from None
    except subprocess.CalledProcessError as exc:
        reason = (exc.stderr or '').strip().splitlines()[-1:] or ['no details']
        raise ValueError(f'The length of {name} could not be read: {reason[0][:300]}') from None
    try:
        duration = float(output.strip())
    except ValueError:
        raise ValueError(f'{name} has no readable length.') from None
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f'{name} has no playable length.')
    return duration
