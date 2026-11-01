"""Compact audio stem envelopes for the lyric timing editor."""

import json
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np


@lru_cache(maxsize=24)
def stem_envelope(name, modified, size, bins=4800):
    import soundfile as sf

    with sf.SoundFile(name) as source:
        frames, rate = len(source), source.samplerate
        values = []
        for index in range(bins):
            first, last = frames * index // bins, frames * (index + 1) // bins
            source.seek(first)
            samples = source.read(max(1, last - first), dtype='float32', always_2d=True)
            values.append(round(float(np.max(np.abs(samples))), 3) if samples.size else 0.)
    return dict(duration=frames / rate, peaks=values)


def draft_timings(folder, duration):
    """Timings to start from when Step 1 never finished: the lyric lines spread evenly over the song, so they
    can be dragged onto the vocals by hand and saved. Each line gets an equal share of the song (between a
    short intro and outro) and its words about .3 s each from the start of that share."""
    from kinetic_lyrics import lyrics_lines
    path = Path(folder) / 'lyrics.txt'
    if not path.is_file():
        raise ValueError('Word timings are not ready yet, and this song has no lyrics to place by hand. '
                         'Add lyrics and restart at Step 1: Timing.')
    lines = lyrics_lines(path)
    begin, end = min(5., duration * .05), duration * .97
    share = (end - begin) / len(lines)
    result = []
    for index, line in enumerate(lines):
        words = line.split()
        step = min(.3, share * .9 / len(words))
        start = begin + share * index
        result.append(dict(text=line, words=[dict(text=word, start=round(start + step * offset, 3),
                                                  end=round(start + step * (offset + .9), 3))
                                             for offset, word in enumerate(words)]))
    return result


def word_timings(folder, duration=None):
    """The job's timed lyrics, or a plain explanation of why the editor has nothing to show yet.

    With `duration`, a song whose timing step failed gets draft timings (see draft_timings) instead of an error."""
    path = Path(folder) / 'video.timings.json'
    if not path.is_file():
        if duration:
            return draft_timings(folder, duration)
        raise ValueError('Word timings are not ready yet. The timeline opens after Step 1 (Timing) '
                         'finishes for this song.')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('The saved word timings for this song could not be read. '
                         'Restart at Step 1: Timing to create them again.') from None


def song_duration(folder, audio):
    """Rendered length when a video exists; otherwise the audio length the pipeline aligned against."""
    render = Path(folder) / 'video.render.json'
    if render.is_file():
        try:
            return float(json.loads(render.read_text(encoding='utf-8'))['end'])
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Fall back to the audio itself.
    if not audio or not Path(audio).is_file():
        raise ValueError("This song's audio file is missing from its job folder, so the timeline "
                         'cannot play it. Choose the audio again and restart at Step 1: Timing.')
    try:
        duration = float(subprocess.check_output(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(audio)], text=True).strip())
    except FileNotFoundError:
        raise ValueError('FFmpeg is not installed or not on PATH, so the song length cannot be '
                         'measured. Install FFmpeg and restart the studio.') from None
    except (subprocess.CalledProcessError, ValueError):
        raise ValueError("The song's length could not be read from its audio file. "
                         'The file may be damaged; try choosing the audio again.') from None
    return duration


def timeline_stems(folder):
    result = {}
    for name in ('vocals', 'drums', 'bass', 'other'):
        path = Path(folder) / 'stems' / f'{name}.wav'
        if path.is_file():
            stat = path.stat()
            result[name] = stem_envelope(str(path), stat.st_mtime_ns, stat.st_size)
    return result
