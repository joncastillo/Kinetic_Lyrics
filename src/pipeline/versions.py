"""Immutable node outputs and saved selections of compatible node versions.

pipeline.json is the index. Node manifests live in pipeline/<node>/vN/;
file contents are shared, immutable SHA-256 objects. The ordinary project files
are a working copy so existing renderers and editors keep their path contracts.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from filelock import FileLock
from core.files import cached_digest, content_digest, replace_file, write_json_atomic


DEPENDENCIES = {
    'timing': (),
    'prompts': ('timing',),
    'story': ('prompts',),
    'image-prompts': ('story',),
    'images': ('image-prompts',),
    'review': ('images',),
    'render': ('timing', 'review'),
    'video': ('review',),
    'scene-scan': ('timing', 'video'),
    'final': ('render', 'video', 'scene-scan'),
}


def ancestors(node):
    result = set()
    for parent in DEPENDENCIES[node]:
        result.add(parent)
        result.update(ancestors(parent))
    return result


class Versions:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.root = self.folder / 'pipeline'
        self.index = self.folder / 'pipeline.json'

    def safe(self, name):
        path = self.folder / name
        if Path(name).is_absolute() or not path.resolve().is_relative_to(self.folder) or path.is_symlink():
            raise ValueError('Version path leaves the project')
        if any(part in ('.', '..') for part in Path(name).parts):
            raise ValueError('Invalid version path')
        return path

    def blob(self, digest):
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Invalid version object')
        return self.safe(f'pipeline/objects/{digest}')

    @contextmanager
    def locked(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.index) + '.lock'):
            self.root.mkdir(exist_ok=True)
            journal = self.root / 'restore.json'
            if journal.exists():
                rollback = json.loads(journal.read_text(encoding='utf-8'))
                self.install(rollback['files'], rollback['managed'], rollback.get('times'))
                write_json_atomic(self.index, rollback['index'])
                journal.unlink()
            if self.index.exists():
                data = json.loads(self.index.read_text(encoding='utf-8'))
                if data.get('schema') != 1:
                    raise ValueError('Unsupported pipeline history schema')
            else:
                data = dict(schema=1, active=None, sequences=[], versions={key: [] for key in DEPENDENCIES})
            yield data

    def active(self, data):
        return next((dict(s['nodes']) for s in data['sequences'] if s['id'] == data['active']), {})

    def metadata(self, data, node, version):
        if node not in DEPENDENCIES:
            raise ValueError('Unknown pipeline node')
        found = next((v for v in data['versions'][node] if v['id'] == version), None)
        if found is None:
            raise ValueError('Unknown node version')
        return found

    def manifest(self, node, version):
        if node not in DEPENDENCIES or not isinstance(version, int) or version < 1:
            raise ValueError('Invalid node version')
        return json.loads(self.safe(f'pipeline/{node}/v{version}/manifest.json').read_text(encoding='utf-8'))

    def inputs(self, node, selected):
        return {parent: selected.get(parent) for parent in sorted(ancestors(node))}

    def compatible(self, version, selected):
        return all(selected.get(key) == value for key, value in version['inputs'].items())

    def cascade(self, data, selected, changed):
        for node in DEPENDENCIES:
            if changed in ancestors(node):
                candidates = [v for v in data['versions'][node] if self.compatible(v, selected)]
                selected[node] = candidates[-1]['id'] if candidates else None
        return selected

    def sequence(self, data, selected, reason):
        number = max((s['id'] for s in data['sequences']), default=0) + 1
        selected = {node: selected.get(node) for node in DEPENDENCIES}
        data['sequences'].append(
            dict(id=number, parent=data['active'], created=time.time(), reason=reason, nodes=dict(selected))
        )
        data['active'] = number
        write_json_atomic(self.index, data)
        return number

    def store(self, path):
        path = Path(path)
        existing = cached_digest(path)
        if self.blob(existing).is_file():
            return existing
        # Copy before hashing: a snapshot must never point at different bytes than its object ID.
        objects = self.root / 'objects'
        objects.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=objects, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copyfile(path, temporary)
            digest = content_digest(temporary)
            target = self.blob(digest)
            if not target.exists():
                replace_file(temporary, target)
            return digest
        finally:
            temporary.unlink(missing_ok=True)

    def capture(self, node, paths, settings=None, force=False, contents=None, run=None, unset=()):
        """Publish only a completed output. Identical reused output keeps its version."""
        if node not in DEPENDENCIES:
            raise ValueError('Unknown pipeline node')
        with self.locked() as data:
            selected = self.active(data)
            inputs = self.inputs(node, selected)
            files, times = {}, {}
            for path in paths:
                if Path(path).is_symlink():
                    raise ValueError('Version output cannot be a symlink')
                relative = Path(path).resolve().relative_to(self.folder).as_posix()
                path = self.safe(relative)
                if path.is_file():
                    files[relative] = self.store(path)
                    times[relative] = path.stat().st_mtime_ns
            for relative, value in (contents or {}).items():
                self.safe(relative)
                temporary = self.root / 'payload.json'
                write_json_atomic(temporary, value)
                files[relative] = self.store(temporary)
                temporary.unlink()
            settings = settings or {}
            unset = sorted(unset)
            previous = selected.get(node)
            if previous:
                old = self.manifest(node, previous)
                if (
                    old['files'] == files
                    and old['inputs'] == inputs
                    and old['settings'] == settings
                    and old.get('unset', []) == unset
                    and (not force or run is not None and old.get('run') == run)
                ):
                    return previous
            number = max((v['id'] for v in data['versions'][node]), default=0) + 1
            # Never reuse a directory left by an interrupted publication.
            while (self.root / node / f'v{number}').exists():
                number += 1
            target = self.safe(f'pipeline/{node}/v{number}/manifest.json')
            target.parent.mkdir(parents=True)
            metadata = dict(id=number, inputs=inputs, created=time.time(), run=run)
            write_json_atomic(target, dict(metadata, files=files, settings=settings, times=times, unset=unset))
            data['versions'][node].append(metadata)
            selected[node] = number
            self.cascade(data, selected, node)
            self.sequence(data, selected, f'{node} v{number} completed')
            return number

    def install(self, files, managed, times=None):
        for name in files:
            self.safe(name)
            if not self.blob(files[name]).is_file():
                raise ValueError(f'Missing saved output: {name}')
        for name in managed:
            path = self.safe(name)
            if name not in files and path.is_file():
                path.unlink()
        for name, digest in files.items():
            path = self.safe(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
            try:
                shutil.copyfile(self.blob(digest), temporary)
                replace_file(temporary, path)
                if name in (times or {}):
                    os.utime(path, ns=(times[name], times[name]))
            finally:
                temporary.unlink(missing_ok=True)

    def restore(self, data, selected, reason, extra_managed=()):
        files, settings, managed, times = {}, {}, set(), {}
        removed_settings = set()
        for path in extra_managed:
            managed.add(Path(path).resolve().relative_to(self.folder).as_posix())
        for node in DEPENDENCIES:
            for version in data['versions'][node]:
                managed.update(self.manifest(node, version['id'])['files'])
            if selected.get(node):
                saved = self.manifest(node, selected[node])
                if not self.compatible(saved, selected):
                    raise ValueError('This pipeline selection contains incompatible versions')
                files.update(saved['files'])
                for key in saved.get('unset', []):
                    settings.pop(key, None)
                    removed_settings.add(key)
                settings.update(saved['settings'])
                times.update(saved.get('times', {}))
        # Preflight every object before touching the working copy.
        for name, digest in files.items():
            self.safe(name)
            if not self.blob(digest).is_file() or content_digest(self.blob(digest)) != digest:
                raise ValueError(f'Missing or damaged saved output: {name}')
        config = self.folder / 'config.json'
        if config.is_file():
            saved_config = json.loads(config.read_text(encoding='utf-8'))
            for key in removed_settings:
                saved_config.pop(key, None)
            saved_config.update(settings)
            saved_config.pop('gallery_since', None)
            temporary = self.root / 'selected-config.json'
            write_json_atomic(temporary, saved_config)
            files['config.json'] = self.store(temporary)
            temporary.unlink()
            managed.add('config.json')
        rollback = {name: self.store(self.safe(name)) for name in managed if self.safe(name).is_file()}
        rollback_times = {name: self.safe(name).stat().st_mtime_ns for name in rollback}
        journal = self.root / 'restore.json'
        write_json_atomic(journal, dict(files=rollback, managed=sorted(managed), index=data, times=rollback_times))
        # Keep unfinished or manually edited working files too; they need not match
        # any completed node version and must not leak into the restored selection.
        backup = self.root / 'working-copies' / f'{time.time_ns()}.json'
        backup.parent.mkdir(exist_ok=True)
        write_json_atomic(backup, dict(files=rollback, times=rollback_times, sequence=data['active']))
        try:
            self.install(files, managed, times)
            data.setdefault('working_copies', []).append(backup.relative_to(self.folder).as_posix())
            self.sequence(data, selected, reason)
        except BaseException:
            self.install(rollback, managed, rollback_times)
            write_json_atomic(self.index, json.loads(journal.read_text(encoding='utf-8'))['index'])
            journal.unlink()
            raise
        else:
            journal.unlink()

    def select(self, node=None, version=None, sequence=None, extra_managed=()):
        with self.locked() as data:
            if sequence is not None:
                saved = next((s for s in data['sequences'] if s['id'] == sequence), None)
                if saved is None:
                    raise ValueError('Unknown pipeline version')
                selected = dict(saved['nodes'])
                reason = f'Restored pipeline v{sequence}'
            else:
                selected = self.active(data)
                chosen = self.metadata(data, node, version)
                if not self.compatible(chosen, selected):
                    raise ValueError('Select the matching upstream versions first')
                selected[node] = version
                self.cascade(data, selected, node)
                reason = f'Selected {node} v{version}'
            self.restore(data, selected, reason, extra_managed)
        return self.summary()

    def summary(self):
        if not self.index.exists():
            return dict(active=None, nodes={}, sequences=[])
        with self.locked() as data:
            selected = self.active(data)
            return dict(
                active=data['active'],
                sequences=data['sequences'],
                nodes={
                    node: dict(
                        current=selected.get(node),
                        versions=[dict(v, compatible=self.compatible(v, selected)) for v in data['versions'][node]],
                    )
                    for node in DEPENDENCIES
                },
            )
