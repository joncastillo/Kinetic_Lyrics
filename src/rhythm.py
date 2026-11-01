"""Instrument onsets from separated stems, for subtle audio-reactive frame effects.

Demucs splits the song into drums, bass, other (guitars, keys) and vocals once per project.
Onsets are detected per stem with a strength ranked within the song, so a quiet track still
gets visible accents and a loud one never overwhelms the picture.
"""
import json
import bisect
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

VERSION = 2
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


def audio_for_mode(audio, folder, mode='original'):
    """Return the original song or a cached, time-aligned instrumental mix."""
    audio = Path(audio)
    if mode == 'original':
        return audio
    if mode != 'karaoke':
        raise ValueError(f'Unknown audio mode: {mode}')
    folder = Path(folder)
    stems = separate(audio, folder)
    if stems is None:
        raise RuntimeError('Karaoke audio needs Demucs instrument stems; separation failed')
    sources = [stems/f'{name}.wav' for name in STEMS]
    target = folder/'instrumental.wav'
    if target.is_file() and target.stat().st_size and target.stat().st_mtime_ns >= max(p.stat().st_mtime_ns for p in sources):
        return target
    temporary = target.with_suffix('.partial.wav')
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
    for source in sources:
        command.extend(['-i', str(source)])
    command.extend(['-filter_complex',
                    '[0:a][1:a][2:a]amix=inputs=3:duration=longest:normalize=0,'
                    'alimiter=limit=0.95:level=0:latency=1[a]',
                    '-map', '[a]', '-c:a', 'pcm_s24le', str(temporary)])
    try:
        subprocess.run(command, check=True, capture_output=True)
        temporary.replace(target)
    except (OSError, subprocess.CalledProcessError) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError('Could not mix the karaoke instrumental stems') from exc
    return target


def onsets(path, kick_only=False):
    """[time, strength 0..1] for each onset in a stem; strength is the song-relative rank."""
    import librosa
    samples, _ = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    if kick_only:
        from scipy.signal import butter, sosfilt
        samples = sosfilt(butter(4, 150, fs=SAMPLE_RATE, btype='lowpass', output='sos'), samples)
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
    result = dict(version=VERSION, drums=floor_drum_events(onsets(stems/'drums.wav', kick_only=True)),
                  bass=onsets(stems/'bass.wav'), other=onsets(stems/'other.wav'))
    target.write_text(json.dumps(result), encoding='utf-8')
    return result


def rhythm_for(folder):
    folder = Path(folder)
    try:
        cached = json.loads((folder/'video.rhythm.json').read_text(encoding='utf-8'))
        if cached.get('version') == VERSION:
            return cached
        config = json.loads((folder/'config.json').read_text(encoding='utf-8'))
        return ensure_rhythm(config['audio'], folder)
    except (OSError, ValueError, KeyError, AttributeError):
        return None


@dataclass(frozen=True)
class Pulse:
    level: float = 0.
    hits: tuple = ()  # (ordinal, age, ranked strength), oldest first

    @property
    def hit(self):
        return self.hits[-1] if self.hits else None


def pulse(events, t, decay, window=1., hit_window=.52, minimum=.42):
    """One stem lookup supplies the glow envelope and recent hits to all visual effects."""
    if not events:
        return Pulse()
    end = bisect.bisect_right(events, [t, 2.])
    level, hits = 0., []
    for i in range(max(0, end-8), end):
        when, strength = events[i]
        age = t-when
        if 0 <= age <= window:
            level = max(level, (.35+.65*strength)*math.exp(-age/decay))
        if 0 <= age <= hit_window and strength >= minimum:
            hits.append((i, age, strength))
    return Pulse(level, tuple(hits))


def envelope(events, t, decay, window=1.):
    """Strongest decaying pulse from events at or just before t (events sorted by time)."""
    return pulse(events, t, decay, window).level


def four_floor_hits(events, minimum=.55):
    """Indices of strong drum onsets in runs of four near-equally spaced quarter notes."""
    strong = [i for i, (_, strength) in enumerate(events or ()) if strength >= minimum]
    found = set()
    for position, i in enumerate(strong):
        when = events[i][0]
        earlier = strong[max(0, position-18):position]
        for j in reversed(earlier):
            period = when-events[j][0]
            if period > .95:
                break
            if period < .28:
                continue
            sequence = [i, j]
            for beat in (2, 3):
                target = when-beat*period
                match = min(earlier, key=lambda k: abs(events[k][0]-target), default=None)
                if match is None or abs(events[match][0]-target) > .09 or match in sequence:
                    break
                sequence.append(match)
            if len(sequence) == 4:
                found.update(sequence)
                break
    return frozenset(found)


def floor_drum_events(events):
    """One low-frequency pulse per beat in steady four-on-the-floor runs."""
    candidates = [events[i] for i in sorted(four_floor_hits(events, minimum=0.))]
    one_track = []
    for event in candidates:
        if one_track and event[0]-one_track[-1][0] < .3:
            if event[1] > one_track[-1][1]:
                one_track[-1] = event
        else:
            one_track.append(event)
    return [[one_track[i][0], round(.6+.4*one_track[i][1], 3)]
            for i in sorted(four_floor_hits(one_track, minimum=0.))]
