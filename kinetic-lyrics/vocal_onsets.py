"""Move each lyric line's first word to where the voice actually starts, measured on a separated vocal stem."""
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

RISE_DB = 9.
SUSTAIN_DB = 15.
ONSET_VERSION = 2


def vocal_stem(audio, folder):
    """Cached Demucs vocal stem for the project, or None when separation is unavailable."""
    target = Path(folder)/'vocals.wav'
    if target.is_file() and target.stat().st_mtime >= Path(audio).stat().st_mtime:
        return target
    with tempfile.TemporaryDirectory(prefix='vocals-', dir=folder) as temp:
        result = subprocess.run([sys.executable, '-m', 'demucs', '--two-stems', 'vocals', '-n', 'htdemucs', '-o', temp, str(audio)],
                                capture_output=True, text=True)
        stems = list(Path(temp).glob('htdemucs/*/vocals.wav'))
        if result.returncode or not stems:
            print(f'Warning: vocal separation unavailable; line starts keep the aligned timing. {result.stderr.strip()[-300:]}', flush=True)
            return None
        stems[0].replace(target)
    return target


def read_mono(path):
    import soundfile
    samples, rate = soundfile.read(str(path))
    return (samples.mean(1) if samples.ndim > 1 else samples), rate


def loudness(samples, rate):
    hop = int(rate*.01)
    frames = len(samples)//hop
    rms = np.sqrt(np.mean(samples[:frames*hop].reshape(frames, hop)**2, 1))
    return np.convolve(20*np.log10(rms+1e-6), np.ones(3)/3, 'same')


def rising_edge(db, floor, start, end):
    """Strongest jump into sustained singing inside the aligned word, in seconds, or None."""
    best, at = RISE_DB, None
    for k in range(int(start*100), int(max(start+.1, end-.15)*100)):
        if k+20 > len(db):
            break
        rise = db[k+8]-db[max(0, k-2):k+1].min()
        if rise > best and db[k+8:k+20].min() > floor+SUSTAIN_DB:
            best, at = rise, k
    return None if at is None else (at+5)/100


def syllable_onset(samples, rate, start, end):
    """Strongest spectral onset inside the word: a new syllable even when singing never paused."""
    hop, size = rate//100, 2048
    first, last = int(start*100), int(max(start+.1, end-.12)*100)
    offsets = hop*np.arange(first-1, last)[:, None]+np.arange(size)[None, :]
    if first < 1 or offsets[-1, -1] >= len(samples):
        return None
    spectrum = np.abs(np.fft.rfft(samples[offsets]*np.hanning(size), axis=1))
    freqs = np.fft.rfftfreq(size, 1/rate)
    magnitude = np.log1p(spectrum[:, (freqs > 150) & (freqs < 5000)]*100)
    flux = np.convolve(np.maximum(0, np.diff(magnitude, axis=0)).sum(1), np.ones(3)/3, 'same')
    if not len(flux) or flux.max() <= 0:
        return None
    return (first+int(np.argmax(flux >= .6*flux.max())))/100


def refine_line_starts(data, audio, folder):
    """Aligners often stretch a line's first word back over the silence before it. Returns lines moved."""
    pending = [line for line in data if line['words'][0].get('onset') != 'measured' and line['words'][0].get('onset_version', 0) < ONSET_VERSION]
    if not pending:
        return 0
    stem = vocal_stem(audio, folder)
    if stem is None:
        return 0
    samples, rate = read_mono(stem)
    db = loudness(samples, rate)
    floor = float(np.percentile(db, 20))
    moved = 0
    for line in pending:
        word = line['words'][0]
        onset = rising_edge(db, floor, word['start'], word['end'])
        if onset is None:
            onset = syllable_onset(samples, rate, word['start'], word['end'])
        word['onset'] = 'measured' if onset else 'aligned'
        word['onset_version'] = ONSET_VERSION
        if onset and onset > word['start']+.05:
            word['start'] = round(min(onset, word['end']-.12), 3)
            moved += 1
    return moved
