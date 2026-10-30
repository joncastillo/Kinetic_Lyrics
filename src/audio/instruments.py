"""Which instruments a song confidently contains, when each plays, and what drives its motion.

The separated stems (see audio/rhythm.py) are tagged in overlapping windows by an AudioSet classifier. An
instrument only counts when it scores confidently over a real share of the song: nobody has to pick or
confirm anything, and an instrument the analysis is unsure of simply never appears. For each confident
instrument the result holds the stretches where it plays, its stem's hits, a loudness envelope and,
for melodic instruments, a pitch track (a trombone's slide follows it).
"""
import json
from pathlib import Path

import numpy as np

VERSION = 1
MODEL = 'MIT/ast-finetuned-audioset-10-10-0.4593'
WINDOW, HOP = 6., 3.
STEP = .05  # seconds between envelope and pitch samples

# name: (AudioSet labels, stem, motion, confidence needed)
INSTRUMENTS = {
    'drum kit': (('Drum kit', 'Drum', 'Snare drum', 'Bass drum', 'Drum roll', 'Drum machine'), 'drums', 'drum', .3),
    'bass guitar': (('Bass guitar',), 'bass', 'pluck', .25),
    'double bass': (('Double bass',), 'bass', 'bow', .3),
    'electric guitar': (('Electric guitar',), 'other', 'strum', .3),
    'acoustic guitar': (('Acoustic guitar', 'Guitar'), 'other', 'strum', .25),
    'ukulele': (('Ukulele',), 'other', 'strum', .3),
    'piano': (('Piano', 'Electric piano'), 'other', 'keys', .3),
    'organ': (('Organ', 'Hammond organ'), 'other', 'keys', .3),
    'synthesizer': (('Synthesizer',), 'other', 'keys', .35),
    'trombone': (('Trombone',), 'other', 'slide', .2),
    'trumpet': (('Trumpet',), 'other', 'blow', .2),
    'saxophone': (('Saxophone',), 'other', 'blow', .2),
    'flute': (('Flute',), 'other', 'blow', .2),
    'clarinet': (('Clarinet',), 'other', 'blow', .2),
    'harmonica': (('Harmonica',), 'other', 'blow', .25),
    'accordion': (('Accordion',), 'other', 'keys', .25),
    'violin': (('Violin, fiddle',), 'other', 'bow', .25),
    'cello': (('Cello',), 'other', 'bow', .25),
    'harp': (('Harp',), 'other', 'pluck', .25),
}
MELODIC = ('slide', 'blow', 'bow')
MAX_SHOWN = 3


def window_scores(path, model, extractor, torch):
    """[(start, {label: probability})] for each window of a stem that is not near-silent."""
    import librosa
    samples, rate = librosa.load(str(path), sr=16000, mono=True)
    if not len(samples):
        return []
    hop, size = int(HOP*rate), int(WINDOW*rate)
    loudness = [float(np.sqrt(np.mean(samples[i:i+size]**2))) for i in range(0, max(1, len(samples)-size//2), hop)]
    floor = .12*np.percentile(loudness, 90) if loudness else 0
    labels = model.config.id2label
    result = []
    device = next(model.parameters()).device
    for n, start in enumerate(range(0, max(1, len(samples)-size//2), hop)):
        if loudness[n] < floor:
            continue
        chunk = samples[start:start+size]
        inputs = extractor(chunk, sampling_rate=rate, return_tensors='pt').to(device)
        with torch.no_grad():
            probabilities = torch.sigmoid(model(**inputs).logits)[0].float().cpu().numpy()
        result.append((start/rate, {labels[i]: float(p) for i, p in enumerate(probabilities) if p > .05}))
    return result


def confident(windows, labels, threshold, duration):
    """Stretches [(start, end)] where an instrument is confidently heard, or [] if it never really is."""
    scores = [(start, max((s.get(label, 0.) for label in labels), default=0.)) for start, s in windows]
    hits = [start for start, score in scores if score >= threshold]
    if len(hits) < 4 or len(hits) < .15*len(scores):
        return []
    held = sorted(start for start, score in scores if score >= threshold*.7)
    spans = []
    for start in held:
        if spans and start <= spans[-1][1]+HOP:
            spans[-1][1] = start+WINDOW
        else:
            spans.append([start, start+WINDOW])
    spans = [(max(0., a-1.), min(duration, b+1.)) for a, b in spans if b-a >= 2*WINDOW-HOP]
    return [(round(a, 2), round(b, 2)) for a, b in spans]


def drivers(path, motion):
    """Loudness envelope (0..1) and, for melodic instruments, pitch in MIDI notes (None when unvoiced)."""
    import librosa
    samples, rate = librosa.load(str(path), sr=22050, mono=True)
    hop = int(rate*STEP)
    rms = librosa.feature.rms(y=samples, hop_length=hop)[0]
    level = np.clip(rms/max(1e-6, np.percentile(rms, 95)), 0, 1)
    pitch = None
    if motion in MELODIC:
        f0 = librosa.yin(samples, fmin=55, fmax=1400, sr=rate, hop_length=hop)
        midi = librosa.hz_to_midi(f0)
        midi = np.where(level[:len(midi)] > .15, midi, np.nan)
        pitch = [None if not np.isfinite(m) else round(float(m), 2) for m in midi]
    return [round(float(v), 3) for v in level], pitch


def analyse(stems, duration, cache):
    import torch
    from transformers import ASTForAudioClassification, AutoFeatureExtractor
    extractor = AutoFeatureExtractor.from_pretrained(MODEL, cache_dir=str(cache))
    model = ASTForAudioClassification.from_pretrained(MODEL, cache_dir=str(cache)).eval()
    if torch.cuda.is_available():
        model = model.to('cuda')
    windows = {stem: window_scores(Path(stems)/f'{stem}.wav', model, extractor, torch)
               for stem in ('drums', 'bass', 'other') if (Path(stems)/f'{stem}.wav').is_file()}
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    found = []
    for name, (labels, stem, motion, threshold) in INSTRUMENTS.items():
        spans = confident(windows.get(stem, []), labels, threshold, duration)
        if not spans:
            continue
        scores = [max((s.get(label, 0.) for label in labels), default=0.) for _, s in windows[stem]]
        strength = float(np.mean(sorted(scores)[-max(1, len(scores)//4):]))
        found.append(dict(name=name, stem=stem, motion=motion, spans=spans, confidence=round(strength, 3),
                          coverage=round(sum(b-a for a, b in spans)/max(1., duration), 3)))
    # One instrument per stem and kind of motion, the most confident first, at most MAX_SHOWN in all.
    found.sort(key=lambda item: -item['confidence']*item['coverage'])
    chosen, taken = [], set()
    for item in found:
        if (item['stem'], item['motion']) in taken or (item['stem'] != 'other' and item['stem'] in {s for s, _ in taken}):
            continue
        taken.add((item['stem'], item['motion']))
        chosen.append(item)
        if len(chosen) == MAX_SHOWN:
            break
    for item in chosen:
        item['level'], item['pitch'] = drivers(Path(stems)/f"{item['stem']}.wav", item['motion'])
    return chosen


def ensure_instruments(audio, folder, duration, cache=None):
    """The confident instruments of a song (cached in video.instruments.json), or [] when none or unavailable."""
    folder = Path(folder)
    target = folder/'video.instruments.json'
    stems = folder/'stems'
    try:
        cached = json.loads(target.read_text(encoding='utf-8'))
        if cached.get('version') == VERSION:
            return cached['instruments']
    except (OSError, ValueError, KeyError):
        pass
    if not (stems/'other.wav').is_file():
        return []
    if cache is None:
        from core.paths import default_model_cache
        cache = default_model_cache()
    try:
        print('Listening for instruments in the separated stems...', flush=True)
        instruments = analyse(stems, duration, cache)
    except Exception as exc:  # the video is still made without instruments
        print(f'Warning: instrument recognition unavailable ({exc}); no animated instruments.', flush=True)
        return []
    names = ', '.join(f"{i['name']} ({i['confidence']:.0%})" for i in instruments) or 'none confidently heard'
    print(f'Instruments: {names}.', flush=True)
    target.write_text(json.dumps(dict(version=VERSION, instruments=instruments)), encoding='utf-8')
    return instruments
