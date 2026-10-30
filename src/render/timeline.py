"""Hand edits to word timing, lyric text and illustration start times, made in Studio's timeline editor.

The editor keeps the shape of the song: the same lines and the same number of words in each line, so the
art direction plan, the per-word effects and the illustration groups stay valid. Only text and times change.
"""
import json
import math
import re
import string
import subprocess
from pathlib import Path

ART_TIMES = 'video.art-times.json'
ONSET_VERSION = 2
MIN_WORD = .04
WAVEFORM_RATE = 100
WAVEFORM_VERSION = 1
STEM_NAMES = ('vocals', 'drums', 'bass', 'other')


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


def save_art_times(folder, starts):
    target = Path(folder)/ART_TIMES
    if starts is None:
        target.unlink(missing_ok=True)
        return
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(dict(starts=starts), indent=2), encoding='utf-8')
    temporary.replace(target)


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
    for raw in source.splitlines():
        stripped = raw.strip()
        if stripped and not re.fullmatch(r'\[.*\]', stripped) and index < len(lines):
            output.append(lines[index])
            index += 1
        else:
            output.append(raw)
    output += lines[index:]
    return '\n'.join(output)+'\n'


def stem_sources(folder, audio):
    """Audio files the editor can draw and play: the full mix plus any separated stems."""
    folder = Path(folder)
    sources = {'mix': Path(audio)}
    for name in STEM_NAMES:
        for candidate in (folder/'stems'/f'{name}.wav', folder/f'{name}.wav'):
            if candidate.is_file():
                sources[name] = candidate
                break
    return {name: path for name, path in sources.items() if path.is_file()}


def waveform(path, cache):
    """Peak and RMS loudness, 0-255, WAVEFORM_RATE times a second; cached until the audio changes."""
    import numpy as np
    path, cache = Path(path), Path(cache)
    stat = path.stat()
    signature = [WAVEFORM_VERSION, stat.st_size, stat.st_mtime_ns]
    try:
        cached = json.loads(cache.read_text(encoding='utf-8'))
        if cached.get('signature') == signature:
            return cached
    except (OSError, ValueError):
        pass
    rate = 8000
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1', '-ar', str(rate), '-f', 's16le', '-'],
                         check=True, capture_output=True).stdout
    samples = np.frombuffer(raw, dtype='<i2').astype(np.float32)/32768
    hop = rate//WAVEFORM_RATE
    count = max(1, len(samples)//hop)
    frames = np.pad(samples, (0, count*hop-len(samples)))[:count*hop].reshape(count, hop) if len(samples) else np.zeros((1, hop))
    peak, rms = np.abs(frames).max(1), np.sqrt((frames**2).mean(1))
    scale = max(float(peak.max()), 1e-6)
    result = dict(signature=signature, rate=WAVEFORM_RATE, duration=len(samples)/rate,
                  peak=np.round(peak/scale*255).astype(int).tolist(), rms=np.round(np.minimum(1, rms/scale*1.6)*255).astype(int).tolist())
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result), encoding='utf-8')
    return result
