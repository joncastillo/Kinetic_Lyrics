"""Prepare cached timeline stem waveforms without running speech recognition."""
from pathlib import Path
import shutil
import threading
import time

from core.files import file_digest
from core.paths import PROJECT_ROOT

_TASKS = {}
_LOCK = threading.Lock()
_BASE = PROJECT_ROOT/'.preview-cache'/'timeline-stems'
_NAMES = ('vocals', 'drums', 'bass', 'other')


def cached_folder(audio):
    folder = _BASE/file_digest(audio)
    return folder if _has_stems(folder, folder.name) else None


def _has_stems(folder, digest):
    marker = folder/'stems'/'source.sha256'
    return (marker.is_file() and marker.read_text(encoding='utf-8').strip() == digest
            and all((folder/'stems'/f'{name}.wav').is_file() for name in _NAMES))


def reuse_stems(audio, folder):
    """Carry preview separation into the generated project instead of separating it again."""
    source = cached_folder(audio)
    if source is None:
        return
    target = Path(folder)/'stems'
    target.mkdir(exist_ok=True)
    for name in (*[f'{stem}.wav' for stem in _NAMES], 'source.sha256'):
        shutil.copy2(source/'stems'/name, target/name)
    shutil.copyfile(source/'stems'/'vocals.wav', Path(folder)/'vocals.wav')


def request_stems(audio, busy, retry=False, source_folder=None):
    """Start or poll separation; requests return promptly while the worker runs."""
    audio = Path(audio)
    key = file_digest(audio)
    with _LOCK:
        task = _TASKS.get(key)
        if task is None or retry and task['status'] == 'failed':
            task = dict(status='queued', message='Preparing stem waveforms; word alignment stays unchanged.')
            _TASKS[key] = task
            threading.Thread(target=_prepare, args=(audio, key, busy, source_folder), daemon=True).start()
        return dict(task)


def _prepare(audio, key, busy, source_folder):
    def update(**values):
        with _LOCK:
            _TASKS[key].update(values)
    try:
        from filelock import FileLock
        from core.media import media_duration
        from models.separation.demucs import separate
        from studio.timeline_data import timeline_stems
        folder = _BASE/key
        folder.mkdir(parents=True, exist_ok=True)
        existing = next((candidate for candidate in (audio.parent, source_folder)
                         if candidate is not None and _has_stems(candidate, key)), None)
        if cached_folder(audio) is None and existing is not None:
            target = folder/'stems'
            target.mkdir(exist_ok=True)
            for name in (*[f'{stem}.wav' for stem in _NAMES], 'source.sha256'):
                shutil.copy2(existing/'stems'/name, target/name)
        if cached_folder(audio) is None:
            while True:
                if busy():
                    update(status='queued', message='Waiting for the active generation before separating stems.')
                    time.sleep(2)
                    continue
                with FileLock(str(PROJECT_ROOT/'.image-generation.lock'), timeout=-1):
                    if busy():
                        continue
                    update(status='running', message='Separating vocals, drums, bass and other instruments. ASR is disabled.')
                    if separate(audio, folder) is None:
                        raise ValueError('Stem separation failed. Check that Demucs is installed and its model can be downloaded.')
                    break
        stems = timeline_stems(folder)
        if not all(name in stems for name in _NAMES):
            raise ValueError('Stem separation did not produce all four waveforms. Retry loading waveforms.')
        update(status='complete', message='Stem waveforms ready. Word alignment is unchanged.',
               duration=media_duration(audio), stems=stems)
    except Exception as exc:
        update(status='failed', message=str(exc))
