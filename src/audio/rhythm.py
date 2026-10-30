"""Instrument onsets from separated stems, for subtle audio-reactive frame effects."""
import json
import bisect
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from models.separation.demucs import STEMS, separate


VERSION = 1


SAMPLE_RATE = 22050


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
    from core.files import file_digest
    source = file_digest(audio)
    try:
        cached = json.loads(target.read_text(encoding='utf-8'))
        if cached.get('version') == VERSION and cached.get('audio') == source:
            return cached
    except (OSError, ValueError):
        pass
    stems = separate(audio, folder)
    if stems is None:
        return None
    result = dict(version=VERSION, audio=source, **{name: onsets(stems/f'{name}.wav') for name in STEMS})
    target.write_text(json.dumps(result), encoding='utf-8')
    return result


def rhythm_for(folder):
    try:
        return json.loads((Path(folder)/'video.rhythm.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
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


def four_floor_hits(events):
    """Indices of strong drum onsets in runs of four near-equally spaced quarter notes."""
    strong = [i for i, (_, strength) in enumerate(events or ()) if strength >= .55]
    found = set()
    for position, i in enumerate(strong):
        when = events[i][0]
        earlier = strong[max(0, position-18):position]
        for j in reversed(earlier):
            period = when-events[j][0]
            if period > .78:
                break
            if period < .36:
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
