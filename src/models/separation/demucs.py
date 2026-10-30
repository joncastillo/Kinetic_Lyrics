"""Demucs stem separation: the vocal stem and the four instrument stems, cached per project."""
from pathlib import Path
import subprocess
import sys
import tempfile

STEMS = ('drums', 'bass', 'other')


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

def separate(audio, folder):
    """Four Demucs stems cached in the project's stems/ folder, or None when unavailable."""
    target = Path(folder)/'stems'
    if all((target/f'{name}.wav').is_file() for name in STEMS):
        return target
    with tempfile.TemporaryDirectory(prefix='stems-', dir=folder) as temp:
        result = subprocess.run([sys.executable, '-m', 'demucs', '-n', 'htdemucs', '-o', temp, str(audio)],
                                capture_output=True, text=True)
        found = list(Path(temp).glob('htdemucs/*'))
        if result.returncode or not found:
            print(f'Warning: instrument separation unavailable; no audio-reactive accents. {result.stderr.strip()[-300:]}', flush=True)
            return None
        target.mkdir(exist_ok=True)
        for stem in found[0].glob('*.wav'):
            stem.replace(target/stem.name)
    return target
