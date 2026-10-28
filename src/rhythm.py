"""Instrument onsets from separated stems, for subtle audio-reactive frame effects.

Demucs splits the song into drums, bass, other (guitars, keys) and vocals once per project.
Onsets are detected per stem with a strength ranked within the song, so a quiet track still
gets visible accents and a loud one never overwhelms the picture.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

VERSION = 1
STEMS = ('drums', 'bass', 'other')
SAMPLE_RATE = 22050


def separate(audio, folder):
    """Four Demucs stems cached in the project's stems/ folder, or None when unavailable."""
    target = Path(folder)/'stems'
    if all((target/f'{name}.wav').is_file() for name in STEMS):
        return target
    with tempfile.TemporaryDirectory(prefix='stems-', dir=folder) as temp:
        result = subprocess.run([sys.executable, '-m', 'demucs', '-n', 'htdemucs', '-o', temp, str(audio)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        found = list(Path(temp).glob('htdemucs/*'))
        if result.returncode or not found:
            print(f'Warning: instrument separation unavailable; no audio-reactive accents. {result.stderr.strip()[-300:]}', flush=True)
            return None
        target.mkdir(exist_ok=True)
        for stem in found[0].glob('*.wav'):
            stem.replace(target/stem.name)
    return target


def onsets(path):
    """[time, strength 0..1] for each onset in a stem; strength is the song-relative rank."""
    import librosa
    samples, _ = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    envelope = librosa.onset.onset_strength(y=samples, sr=SAMPLE_RATE)
    frames = librosa.onset.onset_detect(onset_envelope=envelope, sr=SAMPLE_RATE, backtrack=False)
    if not len(frames):
        return []
    values = envelope[frames]
    floor = np.percentile(envelope, 75)
    keep = values > floor
    frames, values = frames[keep], values[keep]
    if not len(frames):
        return []
    ranks = np.argsort(np.argsort(values))/max(1, len(values)-1)
    times = librosa.frames_to_time(frames, sr=SAMPLE_RATE)
    return [[round(float(t), 3), round(float(r), 3)] for t, r in zip(times, ranks)]


def ensure_rhythm(audio, folder):
    folder = Path(folder)
    target = folder/'video.rhythm.json'
    try:
        cached = json.loads(target.read_text(encoding='utf-8'))
        if cached.get('version') == VERSION:
            return cached
    except (OSError, ValueError):
        pass
    stems = separate(audio, folder)
    if stems is None:
        return None
    result = dict(version=VERSION, **{name: onsets(stems/f'{name}.wav') for name in STEMS})
    target.write_text(json.dumps(result), encoding='utf-8')
    return result


def rhythm_for(folder):
    try:
        return json.loads((Path(folder)/'video.rhythm.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def envelope(events, t, decay, window=1.):
    """Strongest decaying pulse from events at or just before t (events sorted by time)."""
    if not events:
        return 0.
    import bisect
    end = bisect.bisect_right(events, [t, 2.])
    level = 0.
    for time, strength in events[max(0, end-8):end]:
        if t-time <= window:
            level = max(level, (.35+.65*strength)*np.exp(-(t-time)/decay))
    return float(level)
