"""Per-word melody features from the separated vocal stem, ranked across the song.

Each word gets its sung pitch, loudness and local singing rate, plus song-relative
ranks (0..1) that typography can react to without knowing the absolute key or mix level.
"""
import json
from pathlib import Path

import numpy as np

VERSION = 1
SAMPLE_RATE = 16000
HOP = 160


def rank(values):
    """Song-relative percentile of each value, 0 lowest .. 1 highest; None stays None."""
    present = sorted(v for v in values if v is not None)
    if len(present) < 2:
        return [None if v is None else .5 for v in values]
    return [None if v is None else float(np.searchsorted(present, v, side='right')-1)/(len(present)-1) for v in values]


def word_features(f0, rms, words):
    """Median voiced pitch (Hz), mean loudness and syllables-per-second around each word."""
    loud = rms >= np.percentile(rms, 55)
    features = []
    for index, word in enumerate(words):
        first, last = int(word['start']*SAMPLE_RATE/HOP), max(int(word['start']*SAMPLE_RATE/HOP)+1, int(word['end']*SAMPLE_RATE/HOP))
        voiced = f0[first:last][loud[first:last]]
        pitch = float(np.median(voiced)) if len(voiced) >= 3 else None
        energy = float(rms[first:last].mean()) if last > first else None
        neighbours = words[max(0, index-2):index+3]
        span = max(.15, neighbours[-1]['end']-neighbours[0]['start'])
        features.append(dict(pitch=pitch, loudness=energy, rate=len(neighbours)/span, duration=word['end']-word['start']))
    return features


def analyze(vocals, data):
    import librosa
    samples, _ = librosa.load(str(vocals), sr=SAMPLE_RATE, mono=True)
    f0 = librosa.yin(samples, fmin=70, fmax=1000, sr=SAMPLE_RATE, frame_length=1024, hop_length=HOP)
    rms = librosa.feature.rms(y=samples, frame_length=1024, hop_length=HOP)[0]
    words = [word for line in data for word in line['words']]
    features = word_features(f0, rms, words)
    for key in ('pitch', 'loudness', 'rate', 'duration'):
        for feature, value in zip(features, rank([f[key] for f in features])):
            feature[key+'_rank'] = value
    lines, position = [], 0
    for line in data:
        lines.append(features[position:position+len(line['words'])])
        position += len(line['words'])
    return dict(version=VERSION, lines=lines)


def ensure_melody(data, folder):
    """Cached melody features for the project, or None without a vocal stem."""
    folder = Path(folder)
    target, vocals = folder/'video.melody.json', folder/'vocals.wav'
    signature = [[(w['text'], round(w['start'], 3), round(w['end'], 3)) for w in line['words']] for line in data]
    try:
        cached = json.loads(target.read_text(encoding='utf-8'))
        if cached.get('version') == VERSION and cached.get('signature') == signature:
            return cached
    except (OSError, ValueError):
        pass
    if not vocals.is_file():
        return None
    result = dict(analyze(vocals, data), signature=signature)
    target.write_text(json.dumps(result), encoding='utf-8')
    return result
