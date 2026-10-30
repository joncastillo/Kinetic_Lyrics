"""Instrument onsets from separated stems, for subtle audio-reactive frame effects."""
import json
from pathlib import Path
import numpy as np
from models.separation.demucs import STEMS, separate


VERSION = 1


SAMPLE_RATE = 22050


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
