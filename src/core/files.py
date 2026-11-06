"""Content fingerprints and safe writes, so caches notice replaced inputs and readers never see half a file."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


def content_digest(path):
    """SHA-256 of the file's contents, read in blocks rather than whole; FileNotFoundError when it is missing."""
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


_DIGESTS = {}  # (path, size, modified) -> digest, for files hashed again and again (Studio polls)


def cached_digest(path):
    """content_digest(path), remembered while the file keeps its size and modification time."""
    stat = os.stat(path)  # FileNotFoundError, as content_digest raises
    key = (os.fspath(path), stat.st_size, stat.st_mtime_ns)
    if key not in _DIGESTS:
        while len(_DIGESTS) >= 4096:
            _DIGESTS.pop(next(iter(_DIGESTS)))
        _DIGESTS[key] = content_digest(path)
    return _DIGESTS[key]


def file_digest(path):
    """SHA-256 of the file's contents, or None when it does not exist."""
    try:
        return content_digest(path)
    except FileNotFoundError:
        return None


def replace_file(source, target, attempts=40, delay=.25):
    """os.replace(source, target), retried for a while on Windows' PermissionError: a reader (Studio streaming the
    video to a browser) may have the target open for a moment."""
    import time
    for attempt in range(attempts):
        try:
            return os.replace(source, target)
        except PermissionError:
            if attempt == attempts-1:
                raise
            time.sleep(delay)


def write_text_atomic(path, text, encoding='utf-8'):
    """Write `text` to a temporary file beside `path`, then swap it in, so a crash never leaves a torn file."""
    path = Path(path)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name+'.', suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding=encoding, newline='') as target:
            target.write(text)
        replace_file(temporary, path, attempts=8, delay=.025)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def keyed_cache(path, key, compute):
    """A JSON result cached in `path` for as long as `key` (version, input digests...) is unchanged.

    The file holds the result with the key's fields merged in, which is what callers read back. `compute()` runs
    only on a miss; when it returns None (nothing to cache, e.g. no stem) nothing is written. Writes are atomic.
    """
    key = json.loads(json.dumps(key))  # the form it is saved in, so it compares equal when read back
    try:
        cached = json.loads(Path(path).read_text(encoding='utf-8'))
        if isinstance(cached, dict) and all(cached.get(field) == value for field, value in key.items()):
            return cached
    except (OSError, ValueError):
        pass
    result = compute()
    if result is None:
        return None
    result = dict(result, **key)
    write_json_atomic(path, result, indent=None)
    return result


def update_json(path, change, timeout=60):
    """Read a JSON file, apply `change` (which edits the value in place, or returns a new one) and write it back
    atomically, all under a cross-process lock beside the file. Studio and its workers both update the artwork
    manifest; without the lock, one would overwrite the other's change. Keep `change` quick: no model calls."""
    from filelock import FileLock
    path = Path(path)
    with FileLock(str(path)+'.lock', timeout=timeout):
        value = json.loads(path.read_text(encoding='utf-8'))
        changed = change(value)
        value = value if changed is None else changed
        write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2))
    return value


def write_json_atomic(path, value, indent=2, **options):
    write_text_atomic(path, json.dumps(value, indent=indent, **options))
