"""Hand edits to word timing, lyric text and illustration start times, made in Studio's timeline editor.

The editor keeps the shape of the song: the same lines and the same number of words in each line, so the
art direction plan, the per-word effects and the illustration groups stay valid. Only text and times change.
"""
import json
import math
import re
import string
from pathlib import Path

ART_TIMES = 'video.art-times.json'
ONSET_VERSION = 2
MIN_WORD = .04


def tighten_line_starts(data):
    """Aligners stretch a line's first word back over the silence before it. Start it near its sung length.

    The song's own seconds-per-character rate (from non-initial words) bounds the first word; ends never move.
    Applying it twice changes nothing. Lines whose start was measured or placed by hand keep it.
    """
    from statistics import median
    rates = [(w['end']-w['start'])/max(1, len(w['text'].strip())) for line in data for w in line['words'][1:] if w['end'] > w['start']]
    if not rates:
        return data
    rate = median(rates)
    for line in data:
        word = line['words'][0]
        if word.get('onset'):
            continue
        limit = max(.35, rate*len(word['text'].strip(string.punctuation+' '))*1.6)
        if word['end']-word['start'] > limit:
            word['start'] = round(word['end']-limit, 3)
    return data


def illustration_starts(cues, count, illustration_lines, lead_in=1., line_groups=None):
    """When each illustration first appears: at its line group's first cue, or every N lines with a lead-in."""
    if line_groups is not None:
        return [cues[group[0]] for group in line_groups]
    art_cues = [max(0., cue-lead_in) for cue in cues]
    return [art_cues[i*illustration_lines] for i in range(min(count, math.ceil(len(art_cues)/illustration_lines)))]


def checked_art_times(times, count, duration=None):
    """Hand-placed illustration starts: one finite, increasing time per illustration."""
    if not isinstance(times, list) or len(times) != count:
        raise ValueError(f'Expected {count} illustration start times')
    result = []
    for time in times:
        if type(time) not in (int, float) or not math.isfinite(time) or time < 0 or (duration is not None and time > duration):
            raise ValueError('Illustration start times must lie inside the song')
        if result and time <= result[-1]:
            raise ValueError('Illustrations must start in order, each after the one before')
        result.append(round(float(time), 3))
    return result


def load_art_times(path):
    """Saved illustration starts from an art-times file, or None when there are none."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    starts = data.get('starts') if isinstance(data, dict) else None
    return starts if isinstance(starts, list) else None


def apply_edits(data, lines, duration):
    """Timing data with the editor's words applied. The line count and each line's word count must not change."""
    if not isinstance(lines, list) or len(lines) != len(data):
        raise ValueError('The timeline must keep every lyric line')
    result, previous = [], -1.
    for number, (line, words) in enumerate(zip(data, lines), 1):
        if not isinstance(words, list) or len(words) != len(line['words']):
            raise ValueError(f'Line {number} must keep {len(line["words"])} words')
        edited = []
        for original, word in zip(line['words'], words):
            if not isinstance(word, dict) or not isinstance(word.get('text'), str):
                raise ValueError(f'Line {number} has a word without text')
            text = ' '.join(word['text'].split())
            start, end = word.get('start'), word.get('end')
            if not text or not any(c.isalnum() for c in text):
                raise ValueError(f'Line {number}: every word needs at least one letter or digit')
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)):
                raise ValueError(f'Line {number}: word times must be numbers')
            start, end = round(float(start), 3), round(float(end), 3)
            if not 0 <= start or end - start < MIN_WORD - 1e-6 or end > duration + .05:
                raise ValueError(f'Line {number}: "{text}" must last at least {MIN_WORD:.2f}s inside the song')
            if start < previous:
                raise ValueError(f'Line {number}: "{text}" starts before the word ahead of it')
            previous = start
            edited.append(dict(original, text=text, start=start, end=end))
        first = line['words'][0]
        if edited[0]['start'] != round(float(first['start']), 3):
            edited[0].update(onset='manual', onset_version=ONSET_VERSION)
        result.append(dict(line, text=' '.join(w['text'] for w in edited), words=edited))
    return result


def rewrite_lyrics(source, lines):
    """Lyrics text with its lyric lines replaced in order; section labels and blank lines stay where they were."""
    output, index = [], 0
    from pipeline.timing import normalized_newlines
    for raw in normalized_newlines(source).splitlines():
        stripped = raw.strip()
        if stripped and not re.fullmatch(r'\[.*\]', stripped) and index < len(lines):
            output.append(lines[index])
            index += 1
        else:
            output.append(raw)
    output += lines[index:]
    return '\n'.join(output)+'\n'


