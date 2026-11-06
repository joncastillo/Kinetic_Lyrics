"""Reusable local audio copies referenced by saved studio profiles."""
import hashlib
from pathlib import Path


def store_profile_audio(base, name, content, suffixes):
    suffix=Path(name).suffix.lower()
    if suffix not in suffixes or not content:
        raise ValueError('Choose a nonempty supported audio file')
    base=Path(base).resolve();base.mkdir(parents=True,exist_ok=True)
    path=base/(hashlib.sha256(content).hexdigest()+suffix)
    if not path.exists():
        temporary=path.with_suffix(suffix+'.tmp')
        temporary.write_bytes(content);temporary.replace(path)
    return path


def profile_audio_path(base, value, suffixes):
    base=Path(base).resolve();path=Path(value).resolve()
    if not path.is_relative_to(base) or path.suffix.lower() not in suffixes:
        raise ValueError('Audio path is outside the profile audio library; choose the file again')
    if not path.is_file():
        raise FileNotFoundError('Saved audio file is missing. Choose the audio track again: '+str(path))
    return path
