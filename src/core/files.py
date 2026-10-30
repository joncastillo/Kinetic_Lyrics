"""Content fingerprints, so caches built from an input file notice when that file is replaced."""
import hashlib


def file_digest(path):
    """SHA-256 of the file's contents, or None when it does not exist."""
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as source:
            for block in iter(lambda: source.read(1 << 20), b''):
                digest.update(block)
    except FileNotFoundError:
        return None
    return digest.hexdigest()
