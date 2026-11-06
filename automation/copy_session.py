"""Pick a session from another checkout and copy it into this checkout's Studio.

Run from the destination repository with its Python environment:
    .venv/Scripts/python.exe automation/copy_session.py ../kinetic_lyrics_pub

The source may also be a sessions folder (use that for an environment-only source
output override). Type a number and Enter, or press Escape to cancel. Existing
destination sessions are replaced; the previous copy is kept in .session-backups.
Restart the destination Studio after copying so it loads the imported state.
"""
from contextlib import closing, contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
import uuid


def read_json(path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def configured_folder(repo):
    settings = read_json(repo/'.runtime'/'studio-settings.json')
    if not isinstance(settings, dict):
        raise ValueError('Studio settings must contain a JSON object')
    value = settings.get('projects_folder')
    if not value:
        return None
    folder = Path(value).expanduser()
    return (folder if folder.is_absolute() else repo/folder).resolve()


def source_folder(path):
    path = path.expanduser().resolve(strict=True)
    if not (path/'src'/'studio'/'server.py').is_file():
        return path
    configured = configured_folder(path)
    if configured:
        return configured
    for folder in (path.parent/'output'/'lyric-studio', path/'output'/'lyric-studio'):
        if folder.is_dir():
            return folder.resolve()
    # Use this checkout's helper; never execute code from the supplied source.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
    from core.paths import documents_folder
    return (documents_folder()/'Kinetic Lyrics').resolve()


def destination_folder(repo, explicit=None):
    if explicit:
        return explicit.expanduser().resolve()
    if os.environ.get('KINETIC_LYRICS_OUTPUT'):
        return Path(os.environ['KINETIC_LYRICS_OUTPUT']).expanduser().resolve()
    return configured_folder(repo) or (repo/'output'/'lyric-studio').resolve()


def is_link(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def sessions(folder):
    if not folder.is_dir():
        raise ValueError(f'Sessions folder does not exist: {folder}')
    result = []
    for path in folder.iterdir():
        if path.name.startswith('.') or is_link(path) or not path.is_dir() or not (path/'config.json').is_file():
            continue
        try:
            config, state = read_json(path/'config.json'), read_json(path/'state.json')
            name, status = config.get('name') or path.name, state.get('status') or 'saved'
        except (ValueError, OSError, AttributeError):
            name, status = path.name, 'unreadable metadata'
        result.append(dict(path=path, name=str(name), status=str(status)))
    return sorted(result, key=lambda item: item['path'].name, reverse=True)


@contextmanager
def keyboard():
    if not sys.stdin.isatty():
        yield lambda: sys.stdin.read(1)
    elif os.name == 'nt':
        import msvcrt

        def key():
            char = msvcrt.getwch()
            if char in ('\x00', '\xe0'):
                msvcrt.getwch()
                return '\x00'
            return char
        yield key
    else:
        import termios
        import tty
        descriptor = sys.stdin.fileno()
        saved = termios.tcgetattr(descriptor)
        try:
            tty.setcbreak(descriptor)
            yield lambda: sys.stdin.read(1)
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, saved)


def choose(items, read_key, output=sys.stdout):
    clean = lambda text: ''.join(c if c.isprintable() else ' ' for c in text)
    for number, item in enumerate(items, 1):
        print(f"{number:>3}. {clean(item['name'])}  [{item['path'].name}]  {clean(item['status'])}", file=output)
    print('\nSession number + Enter; Escape cancels: ', end='', file=output, flush=True)
    value = ''
    while True:
        char = read_key()
        if char in ('', '\x1b', '\x03', '\x04'):
            print('\nCancelled. Nothing copied.', file=output)
            return None
        if char in ('\r', '\n'):
            if value and 1 <= int(value) <= len(items):
                print(file=output)
                return items[int(value)-1]['path']
            print('\nChoose a listed number, or Escape: ', end='', file=output, flush=True)
            value = ''
        elif char in ('\b', '\x7f') and value:
            value = value[:-1]
            print('\b \b', end='', file=output, flush=True)
        elif char in '0123456789' and len(value) < len(str(len(items)))+1:
            value += char
            print(char, end='', file=output, flush=True)


def inventory(folder):
    """Fingerprint a quiescent tree and refuse links, including Windows junctions."""
    result = {}
    if is_link(folder):
        raise ValueError('Session folders cannot be links or junctions')
    for parent, directories, files in os.walk(folder, followlinks=False):
        for name in directories + files:
            path = Path(parent)/name
            if is_link(path):
                raise ValueError(f'Session contains a link or junction: {path}')
            if path.is_file() and not path.name.endswith('.sqlite-shm'):
                info = path.stat()
                result[path.relative_to(folder).as_posix()] = (info.st_size, info.st_mtime_ns)
    return result


def require_idle(folder, destination=False):
    state = read_json(folder/'state.json')
    if not isinstance(state, dict):
        raise ValueError(f'Session state must contain a JSON object: {folder.name}')
    busy = ('running', 'queued', 'review') if destination else ('running', 'queued')
    if state.get('status') in busy or state.get('action'):
        raise ValueError(f'Stop the {"destination" if destination else "source"} session before copying: {folder.name}')
    if (folder/'pipeline'/'restore.json').exists():
        raise ValueError(f'Finish or recover the pipeline restore before copying: {folder.name}')


def path_mapper(source, destination):
    prefix = str(source).replace('\\', '/').rstrip('/')

    def move(value):
        if isinstance(value, str):
            normal = value.replace('\\', '/')
            a, b = (normal.casefold(), prefix.casefold()) if os.name == 'nt' else (normal, prefix)
            if a == b or a.startswith(b+'/'):
                relative = normal[len(prefix):].lstrip('/')
                if '..' in relative.split('/'):
                    return value
                target = destination/relative
                return str(target) if '\\' in value else target.as_posix()
            return value
        if isinstance(value, list):
            return [move(item) for item in value]
        if isinstance(value, tuple):
            return tuple(move(item) for item in value)
        if isinstance(value, dict):
            return {move(key): move(item) for key, item in value.items()}
        return value
    return move


def json_bytes(raw, move, hashes=None):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return raw
    changed = move(value)
    if hashes and isinstance(changed, dict) and isinstance(changed.get('files'), dict):
        changed['files'] = {name: hashes.get(digest, digest) for name, digest in changed['files'].items()}
    if changed == value:
        return raw
    return (json.dumps(changed, ensure_ascii=False, indent=2)+'\n').encode('utf-8')


def relocate_json(stage, move):
    """Rehash changed immutable JSON objects before updating their version manifests."""
    objects = stage/'pipeline'/'objects'
    hashes = {}
    candidates = set()
    for path in (stage/'pipeline').rglob('*.json'):
        if path.is_relative_to(objects):
            continue
        data = read_json(path)
        for name, digest in (data.get('files', {}) if isinstance(data, dict) else {}).items():
            if name.endswith('.json') and re.fullmatch(r'[0-9a-f]{64}', str(digest)):
                candidates.add(digest)
    for digest in sorted(candidates):
        original = objects/digest
        raw = original.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f'Pipeline object failed its checksum: {digest}')
        updated = json_bytes(raw, move)
        if updated != raw:
            new_digest = hashlib.sha256(updated).hexdigest()
            (objects/new_digest).write_bytes(updated)
            hashes[digest] = new_digest
    for path in stage.rglob('*.json'):
        if path.is_relative_to(objects):
            continue
        raw = path.read_bytes()
        updated = json_bytes(raw, move, hashes if path.is_relative_to(stage/'pipeline') else None)
        if updated != raw:
            path.write_bytes(updated)


def relocate_msgpack(raw, move):
    """Transform serialized data without importing or instantiating checkpoint objects."""
    try:
        import msgpack
    except ImportError as exc:
        raise ValueError('Run with the project .venv Python; msgpack is needed to copy saved checkpoints.') from exc

    def unpack(value):
        return msgpack.unpackb(value, raw=False, use_list=False, strict_map_key=False)

    def visit(value):
        if isinstance(value, msgpack.ExtType):
            try:
                payload = unpack(value.data)
            except (ValueError, TypeError, UnicodeError):
                return value
            if (value.code == 1 and isinstance(payload, tuple) and len(payload) == 3
                    and payload[0] == 'pathlib' and payload[1] in ('PosixPath', 'WindowsPath', 'Path')):
                kind = PureWindowsPath if payload[1] == 'WindowsPath' else PurePosixPath
                before = str(kind(*payload[2]))
                after = move(before)
                if after != before:
                    payload = (payload[0], payload[1], kind(after).parts)
            else:
                payload = visit(payload)
            return msgpack.ExtType(value.code, msgpack.packb(payload, use_bin_type=True))
        if isinstance(value, dict):
            return {visit(key): visit(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return tuple(visit(item) for item in value)
        return move(value)
    return msgpack.packb(visit(unpack(raw)), use_bin_type=True)


def relocate_database(path, move):
    def payload(kind, raw):
        if kind == 'msgpack':
            return relocate_msgpack(raw, move)
        if kind == 'json':
            return json_bytes(raw, move)
        if kind in ('bytes', 'bytearray', 'null'):
            return raw
        raise ValueError(f'Unsupported checkpoint encoding {kind!r}; destination has not been replaced')

    with closing(sqlite3.connect(path)) as database, database:
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'checkpoints' in tables:
            for row, thread, kind, raw, metadata in database.execute(
                    'SELECT rowid, thread_id, type, checkpoint, metadata FROM checkpoints').fetchall():
                database.execute('UPDATE checkpoints SET thread_id=?, checkpoint=?, metadata=? WHERE rowid=?',
                                 (move(thread), payload(kind, raw), json_bytes(metadata, move) if metadata else metadata, row))
        if 'writes' in tables:
            for row, thread, kind, raw in database.execute('SELECT rowid, thread_id, type, value FROM writes').fetchall():
                database.execute('UPDATE writes SET thread_id=?, value=? WHERE rowid=?', (move(thread), payload(kind, raw), row))
        if database.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Copied checkpoint database failed its integrity check')


def copy_session(source, destination_root):
    source = Path(source).absolute()
    destination_root = Path(destination_root).resolve()
    if not re.fullmatch(r'[\w-]{1,80}', source.name):
        raise ValueError('Session folder name is not a valid Studio session ID')
    if is_link(source):
        raise ValueError('Source session is a link or junction')
    source = source.resolve(strict=True)
    destination = destination_root/source.name
    if destination.exists() and (is_link(destination) or not destination.is_dir()):
        raise ValueError('Destination session must be an ordinary directory')
    if source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('Source and destination sessions overlap; choose a separate --destination folder')
    if not isinstance(read_json(source/'config.json'), dict) or not (source/'config.json').is_file():
        raise ValueError('Source session has no valid config.json')
    require_idle(source)
    if destination.exists():
        require_idle(destination, destination=True)
    before = inventory(source)
    destination_before = inventory(destination) if destination.exists() else None
    destination_root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='.session-copy-', dir=destination_root))
    stage, backup = scratch/'session', None
    try:
        shutil.copytree(source, stage, symlinks=True, ignore=lambda folder, names: [name for name in names if name.endswith(('.sqlite', '.sqlite-wal', '.sqlite-shm'))])
        inventory(stage)
        move = path_mapper(source, destination)
        for name in before:
            if not name.endswith('.sqlite'):
                continue
            target = stage/name
            target.parent.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()

            def progress(*_):
                if time.monotonic()-started > 30:
                    raise TimeoutError('Timed out reading a busy checkpoint database')

            with closing(sqlite3.connect(source.joinpath(name).as_uri()+'?mode=ro', uri=True)) as original:
                with closing(sqlite3.connect(target)) as copied:
                    original.backup(copied, pages=256, progress=progress)
            if name.endswith('.graph.sqlite'):
                relocate_database(target, move)
        relocate_json(stage, move)
        if inventory(source) != before:
            raise ValueError('Source session changed during copying; stop its work and try again')
        require_idle(source)
        if destination.exists():
            require_idle(destination, destination=True)
            if destination_before is None or inventory(destination) != destination_before:
                raise ValueError('Destination session changed during copying; nothing was replaced')
            backups = destination_root/'.session-backups'
            if backups.exists() and is_link(backups):
                raise ValueError('Backup folder cannot be a link or junction')
            backups.mkdir(exist_ok=True)
            backup = backups/(source.name+'-'+uuid.uuid4().hex[:12])
            destination.rename(backup)
        elif destination_before is not None:
            raise ValueError('Destination session disappeared during copying; nothing was replaced')
        try:
            stage.rename(destination)
        except BaseException:
            if backup is not None:
                backup.rename(destination)
            raise
        return destination, backup
    finally:
        assert scratch.resolve().parent == destination_root and scratch.name.startswith('.session-copy-')
        shutil.rmtree(scratch)


def remember_destination(repo, folder):
    settings = repo/'.runtime'/'studio-settings.json'
    value = read_json(settings)
    if not isinstance(value, dict):
        raise ValueError('Copied session, but Studio settings are not a JSON object; set the projects folder manually')
    value['projects_folder'] = str(folder)
    settings.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=settings.parent, delete=False) as stream:
        json.dump(value, stream, indent=2)
        temporary = Path(stream.name)
    try:
        os.replace(temporary, settings)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', type=Path, help='source repository or its sessions folder')
    parser.add_argument('--destination', type=Path, help='override this checkout\'s sessions folder')
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    try:
        origin = source_folder(args.source)
        target = destination_folder(repo, args.destination)
        items = sessions(origin)
        print(f'Source: {origin}\nDestination: {target}\n')
        if not items:
            print('No saved sessions found. Nothing copied.')
            return 0
        with keyboard() as read_key:
            selected = choose(items, read_key)
        if selected is None:
            return 0
        print(f'Copying {selected.name}…', flush=True)
        result, backup = copy_session(selected, target)
        print(f'Copied to {result}')
        if backup:
            print(f'Previous destination saved in {backup}')
        remember_destination(repo, target)
        print('Restart the destination Studio to load the copied session.')
        return 0
    except KeyboardInterrupt:
        print('\nCancelled.')
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
