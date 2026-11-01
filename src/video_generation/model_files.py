"""Resumable, verified downloads of a video model's files into a plain folder that the loader reads from.

huggingface_hub 2.x never resumes across runs: every attempt downloads to a new uniquely named temporary file,
deletes it on failure, and its Xet client assembles each file in RAM. A crash or restart therefore loses
everything in flight, which for a 120 GB model means hours. Here each file streams to `<name>.part` on disk,
continues from that size with an HTTP Range request after any interruption or restart, and is checked against
the repository's SHA-256 before it is renamed into place. Files already in the Hugging Face cache are hard-linked,
which costs neither time nor space.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from core.progress import emit

CHUNK = 8 << 20
ATTEMPTS = 30


def model_folder(cache, model):
    return Path(cache)/'video-models'/model.replace('/', '--')


def wanted_files(model, components):
    """(revision, [(path, size, sha256 or None)]) for the components' folders and the top-level config files."""
    from huggingface_hub import HfApi
    info = HfApi().model_info(model, files_metadata=True)
    prefixes = tuple(component+'/' for component in components)
    chosen = [s for s in info.siblings
              if ('/' not in s.rfilename and s.rfilename.endswith('.json')) or s.rfilename.startswith(prefixes)]
    # Repositories can ship the same weights several ways (a single file, 4 shards and 8 shards side by side).
    # Where a folder has a weight index, only the files that index lists are loaded, so only those are fetched.
    from huggingface_hub import hf_hub_download
    listed = {}
    for s in chosen:
        if s.rfilename.endswith('.safetensors.index.json'):
            folder = s.rfilename.rsplit('/', 1)[0] if '/' in s.rfilename else ''
            index = json.loads(Path(hf_hub_download(model, s.rfilename, revision=info.sha)).read_text(encoding='utf-8'))
            listed.setdefault(folder, set()).update((folder+'/' if folder else '')+f for f in index['weight_map'].values())
    files = []
    for s in chosen:
        folder = s.rfilename.rsplit('/', 1)[0] if '/' in s.rfilename else ''
        if folder in listed and s.rfilename.endswith('.safetensors') and s.rfilename not in listed[folder]:
            continue
        files.append((s.rfilename, s.size or 0, s.lfs.sha256 if s.lfs else None))
    return info.sha, files


def _from_hub_cache(model, revision, name):
    from huggingface_hub import try_to_load_from_cache
    found = try_to_load_from_cache(model, name, revision=revision)
    return Path(found).resolve() if isinstance(found, str) else None


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def _fetch(model, revision, name, target, size, sha256):
    import requests
    from huggingface_hub import hf_hub_url
    from huggingface_hub.utils import build_hf_headers
    url = hf_hub_url(model, name, revision=revision)
    part = target.with_name(target.name+'.part')
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(ATTEMPTS):
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink(); have = 0
        if have == size:
            break
        headers = build_hf_headers()
        if have:
            headers['Range'] = f'bytes={have}-'
        try:
            with requests.get(url, headers=headers, stream=True, timeout=(30, 120)) as response:
                if response.status_code in (401, 403):
                    raise ValueError(f'Access required for {model}: request it at https://huggingface.co/{model}.')
                response.raise_for_status()
                if have and response.status_code != 206:
                    have = 0  # the server ignored the range: start this file again
                with open(part, 'ab' if have else 'wb') as handle:
                    for block in response.iter_content(CHUNK):
                        handle.write(block)
        except (requests.RequestException, OSError) as exc:
            delay = min(60, 5*(attempt+1))
            print(f'Download of {name} interrupted ({exc}); resuming from '
                  f'{(part.stat().st_size if part.exists() else 0)/2**30:.2f} GiB in {delay}s.', flush=True)
            time.sleep(delay)
    else:
        raise ValueError(f'Could not download {name} after {ATTEMPTS} attempts; run again to resume.')
    if part.stat().st_size != size:
        raise ValueError(f'{name} downloaded to the wrong size; run again to resume.')
    if sha256 and _sha256(part) != sha256:
        part.unlink()
        raise ValueError(f'{name} failed its checksum and was discarded; run again to download it afresh.')
    part.replace(target)


class _Progress:
    """Emits 'Downloading … X of Y GiB (Z%)' every few seconds from the bytes on disk."""

    def __init__(self, model, root, files, interval=5.):
        self.model, self.root, self.files, self.interval = model, root, files, interval
        self.total = sum(size for _, size, _ in files)
        self.stop = threading.Event()

    def on_disk(self):
        done = 0
        for name, size, _ in self.files:
            target = self.root/name
            part = target.with_name(target.name+'.part')
            done += size if target.is_file() else part.stat().st_size if part.is_file() else 0
        return done

    def run(self):
        last_print = 0
        while not self.stop.wait(self.interval):
            done = self.on_disk()
            fraction = done/max(1, self.total)
            message = f'Downloading {self.model}: {done/2**30:.1f} of {self.total/2**30:.1f} GiB ({fraction*100:.1f}%)'
            emit('model', fraction, message=message)
            if time.time()-last_print > 30:
                print(message, flush=True); last_print = time.time()

    def __enter__(self):
        threading.Thread(target=self.run, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        return False


def fetch(model, components, cache):
    """Make every file of `components` present and verified under model_folder(); returns that folder."""
    revision, files = wanted_files(model, components)
    root = model_folder(cache, model)
    pending = []
    for name, size, sha256 in files:
        target = root/name
        if target.is_file() and target.stat().st_size == size:
            continue
        cached = _from_hub_cache(model, revision, name)
        if cached and cached.is_file() and cached.stat().st_size == size:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(cached, target)
                continue
            except OSError:
                pass
        pending.append((name, size, sha256))
    if pending:
        print(f'{len(pending)} file(s) of {model} to download '
              f'({sum(size for _, size, _ in pending)/2**30:.1f} GiB); interrupted downloads resume.', flush=True)
        with _Progress(model, root, files):
            for name, size, sha256 in pending:
                _fetch(model, revision, name, root/name, size, sha256)
    return root


def local_sources(root, model, components):
    """{component: folder} for components stored in `model`'s own repository (others keep their own source)."""
    index = json.loads((root/'modular_model_index.json').read_text(encoding='utf-8'))
    return {name: str(root) for name in components
            if isinstance(index.get(name), list) and len(index[name]) == 3
            and isinstance(index[name][2], dict) and index[name][2].get('pretrained_model_name_or_path') == model}
