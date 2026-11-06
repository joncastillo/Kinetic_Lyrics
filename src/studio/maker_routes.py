"""The Image Maker's routes (see artwork.maker): its models, templates, saved prompts, reference library and runs."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import time
import threading
import secrets
import re
import hashlib
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs

from artwork.maker import FORMATS, MAX_COUNT, TEMPLATES, checked, free_path, maker_folder
from core.files import update_json, write_json_atomic, write_text_atomic
from core.paths import default_model_cache
from core.process import module_command, module_env
from models.image.catalog import MODELS

PICK_FOLDER = ('Add-Type -AssemblyName System.Windows.Forms;'
               '$owner=New-Object System.Windows.Forms.Form;$owner.TopMost=$true;'
               '$dialog=New-Object System.Windows.Forms.FolderBrowserDialog;'
               "$dialog.Description='Choose where Image Maker saves its pictures';"
               'if($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK){[Console]::Out.Write($dialog.SelectedPath)}')
running = None   # the worker of the current run
MAKER_LOCK = threading.RLock()
queue_watcher = None
recovered_home = None
reported_progress = {}


class AttachedWorker:
    """A still-running worker inherited from the previous Studio server."""
    def __init__(self, process):
        self.process, self.pid, self.returncode = process, process.pid, None

    def poll(self):
        if self.process.is_running():
            return None
        self.returncode = 0
        return 0


def recover(home):
    global running, recovered_home
    if recovered_home == home:
        return
    recovered_home = home
    if running is not None:
        return
    request = read_json(home/'request.json', {})
    status = read_json(home/'status.json', {})
    if not request or status.get('state') in ('idle', 'done', 'failed', 'stopped'):
        return
    import psutil
    # Also find workers from older Studio versions which did not persist their PID.
    for process in psutil.process_iter(['pid', 'cmdline']):
        command = process.info.get('cmdline') or []
        if 'artwork.maker' in command and any(str(home/'request.json').lower() == str(arg).lower() for arg in command):
            running = AttachedWorker(process)
            if request.get('request_id'):
                queued = read_json(home/'queue.json', [])
                write_json_atomic(home/'queue.json', [q for q in queued if q.get('request_id') != request['request_id']])
            return
    queued = read_json(home/'queue.json', [])
    if not any(q.get('request_id') == request.get('request_id') for q in queued) or not request.get('request_id'):
        queued.insert(0, request)
        write_json_atomic(home/'queue.json', queued)
    write_json_atomic(home/'status.json', dict(state='idle', message='Interrupted edit restored to the queue'))


def public_request(request):
    fields = ('request_id', 'template', 'subject', 'prompt', 'references', 'model', 'width', 'height', 'format', 'quality',
              'steps', 'seed', 'count', 'folder', 'name', 'output', 'motion', 'duration', 'edit_target', 'regions', 'region_source', 'preserve_outside_regions')
    result = {k: request[k] for k in fields if k in request}
    target = request.get('edit_target') or {}
    result['label'] = target.get('label') or (Path(request['references'][0]).stem if request.get('references') else
                                            str(request.get('name') or 'Edit').removesuffix('_edit'))
    return result


def is_edit(request):
    return bool(request.get('edit_target') or request.get('references') and str(request.get('name', '')).endswith('_edit'))


def edit_key(request):
    target = request.get('edit_target') or {}
    if target.get('id'):
        return ('reference', target.get('job'), target['id'])
    return ('request', request.get('request_id') or str(request.get('input_reference_folder') or request.get('name')))


def clean_queue(home, status):
    queued = read_json(home/'queue.json', [])
    request = read_json(home/'request.json', {})
    history = read_json(home/'history.json', [])
    completed = {i.get('request_id') for i in history if i.get('reference_applied')}
    signature = lambda r: tuple(str(r.get(k) or '') for k in ('name', 'prompt', 'model', 'references'))
    finished_legacy = {signature(i) for i in history if Path(str(i.get('path') or '')).is_file()}
    if status.get('state') == 'done' and request.get('request_id'):
        completed.add(request['request_id'])
    seen = {edit_key(request)} if running is not None else set()
    name_key = lambda r: re.sub(r'[^a-z0-9]', '', public_request(r)['label'].lower().removesuffix('_edit'))
    names = {name_key(request)} if running is not None else set()
    kept = []
    for item in queued:
        from studio import server
        from artwork.reference_lifecycle import validate_target
        target = item.get('edit_target') or {}
        project = server.JOBS.get(target.get('job'))
        if project is not None:
            try:
                validate_target(project.folder, target)
            except ValueError as exc:
                retired = read_json(home/'retired-edits.json', [])
                if not any(r.get('request_id') == item.get('request_id') for r in retired):
                    write_json_atomic(home/'retired-edits.json', retired+[dict(item, retired_reason=str(exc))])
                continue
        key = edit_key(item)
        if not item.get('edit_target') and name_key(item) in names:
            continue
        if not item.get('request_id') and is_edit(item) and signature(item) in finished_legacy:
            continue
        if key in seen or item.get('request_id') and item['request_id'] in completed:
            continue
        seen.add(key)
        names.add(name_key(item))
        kept.append(item)
    if kept != queued:
        write_json_atomic(home/'queue.json', kept)
    return kept


def forward_progress(home, request, status):
    """Expose edit progress in the owning project's ordinary status and log."""
    target = request.get('edit_target') or {}
    if not target.get('job'):
        return status
    if status.get('state') == 'painting':
        try:
            with (home/'run.log').open('rb') as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell()-8192))
                matches = re.findall(r'(\d+)%[^\r\n]*?\|\s*(\d+)/(\d+)\s*\[', stream.read().decode(errors='replace'))
            if matches:
                percent, step, steps = map(int, matches[-1])
                status = dict(status, step=step, steps=steps, percent=percent, message=f'Editing · step {step}/{steps}')
        except OSError:
            pass
    from studio import server
    with server.LOCK:
        job = server.JOBS.get(target['job'])
        if job is not None:
            label = public_request(request)['label']
            message = f'In-image edit @{label}: {status.get("message", "")}'
            signature = (request.get('request_id'), message)
            if reported_progress.get(target['job']) != signature:
                job.log(message, 'error' if status.get('state') == 'failed' else 'info')
                reported_progress[target['job']] = signature
            job.state['image_edit_status'] = message if status.get('state') in ('starting','planning','waiting','loading','painting','animating') else ''
    return status


def apply_completed_reference(home, request, status):
    """Apply a finished edit once, independently of whether the browser is open."""
    if status.get('state') != 'done' or not request.get('auto_apply', bool(request.get('edit_target'))) or status.get('reference_applied') or status.get('reference_error'):
        return status
    target = request.get('edit_target') or {}
    try:
        from studio import server
        source = Path(status['files'][-1])
        with server.LOCK:
            job = server.JOBS.get(target.get('job'))
            if job is None:
                raise ValueError('The target project is not loaded; use this result from edit history.')
            from artwork.reference_lifecycle import validate_target
            validate_target(job.folder, target)
            if target.get('type') == 'illustration':
                from studio.image_operations import ImageOperations
                from types import SimpleNamespace
                index = int(target['index'])
                manifest = job.manifest()
                count = len(json.loads(manifest.read_text(encoding='utf-8')).get('prompts', []))
                if not 0 <= index < count:
                    raise ValueError('Invalid illustration')
                ImageOperations._image_select(SimpleNamespace(respond=lambda value: value), job, 'replace', {},
                    {'replacement': [(source.name, source.read_bytes())]}, index, manifest, manifest.parent/f'{index:03d}.png')
            else:
                job.edit_entity('upload', dict(id=target['id'], image_origin='generated_edit'), (source.name, source.read_bytes()))
            job.save()
        server.keep_upload_name(server.store_image(home/'references', source.name, source.read_bytes()), source.name)
        status = dict(status, reference_applied=True, message='Edit complete; recurring reference updated')
        def mark(history):
            for item in history:
                if item.get('request_id') == request.get('request_id'):
                    item['reference_applied'] = True
        update_json(home/'history.json', mark)
    except Exception as exc:
        status = dict(status, reference_error=str(exc), message=f'Edit saved, but reference update failed: {exc}')
    write_json_atomic(home/'status.json', status)
    return status


def watch_queue(home):
    """Advance pending edits even when every browser window is closed."""
    global queue_watcher
    while True:
        with MAKER_LOCK:
            run_status(home)
            pending = read_json(home/'queue.json', [])
            if not pending and running is None:
                queue_watcher = None
                return
            if pending and running is None:
                item = pending.pop(0)
                try:
                    launch(home, item)
                    write_json_atomic(home/'queue.json', pending)
                except Exception as exc:
                    write_json_atomic(home/'status.json', dict(state='failed', message=f'Could not start queued edit: {exc}'))
                    queue_watcher = None
                    return
        time.sleep(.5)


def read_json(path, fallback):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def on_disk(spec, cache):
    """True when the model need not be downloaded first."""
    repos = [spec['id']]+([spec['gguf'][0]] if spec.get('gguf') else [])
    return all((Path(cache)/('models--'+repo.replace('/', '--'))).is_dir() for repo in repos)


def model_list(cache):
    return [dict(id=m['id'], name=m['name'], references=bool(m['references']), max_references=m.get('max_references', 3) if m['references'] else 0,
                 steps=m['steps'], disk_gb=m.get('disk_gb'), license=m.get('license', ''), on_disk=on_disk(m, cache)) for m in MODELS]


def saved_prompts(home):
    return read_json(home/'prompts.json', [])


def save_prompt(home, entry):
    """Add a saved prompt, or replace the one of that name."""
    name = ' '.join(str(entry.get('name') or '').split())[:80]
    if not name:
        raise ValueError('Name the prompt to save it')
    kept = dict(entry, name=name, saved=time.time())
    if not (home/'prompts.json').exists():
        write_text_atomic(home/'prompts.json', '[]')

    def change(prompts):
        return [p for p in prompts if p.get('name') != name]+[kept]
    update_json(home/'prompts.json', change)
    return saved_prompts(home)


def delete_prompt(home, name):
    if (home/'prompts.json').exists():
        update_json(home/'prompts.json', lambda prompts: [p for p in prompts if p.get('name') != name])
    return saved_prompts(home)


def reference_list(home):
    return [p.name for p in sorted((home/'references').glob('*.png'), key=lambda p: p.name.lower())]


@lru_cache(maxsize=512)
def _picture_signature(path, modified, size):
    from PIL import Image
    with Image.open(path) as picture:
        return (picture.size, hashlib.sha256(picture.convert('RGBA').tobytes()).hexdigest())


def reference_usage(home, name, selected=()):
    """Human-readable uses of a library picture; compare pixels with project copies too."""
    uses = ['Selected for this edit'] if name in selected else []
    request = read_json(home/'request.json', {})
    state = read_json(home/'status.json', {}).get('state')
    if state in ('starting','planning','waiting','loading','painting','animating') and name in request.get('references', []):
        uses.append('Current edit: '+public_request(request)['label'])
    for item in read_json(home/'queue.json', []):
        if name in item.get('references', []):
            uses.append('Queued edit: '+public_request(item)['label'])
    for item in read_json(home/'history.json', []):
        if name in item.get('references', []) and Path(str(item.get('path') or '')).is_file():
            uses.append('Edit history: '+str(item.get('name') or item.get('id')))
    from studio import server
    target = home/'references'/name
    def signature(path):
        path = Path(path)
        stat = path.stat()
        return _picture_signature(str(path), stat.st_mtime_ns, stat.st_size)
    try:
        wanted = signature(target)
    except (OSError, ValueError):
        return list(dict.fromkeys(uses))
    from direction.story import load
    for job in list(server.JOBS.values()):
        try:
            manifest = job.manifest()
            story = load(manifest) or {}
            project = job.config.get('name') or job.folder.name
            candidates = [(e.get('image'), f'{project}: recurring reference {e.get("name", "")}') for e in story.get('entities', [])]
            candidates += [(p, f'{project}: illustration {s.get("index",0)+1} reference') for s in story.get('segments', []) for p in s.get('references', [])]
            record = read_json(manifest, {})
            candidates += [(p, f'{project}: project/art-style reference') for p in record.get('reference_paths', [])]
            for path, label in candidates:
                try:
                    if path and signature(path) == wanted:
                        uses.append(label)
                except (OSError, ValueError):
                    continue
        except (OSError, ValueError, KeyError):
            continue
    return list(dict.fromkeys(uses))


def public_history(home):
    """The newest pictures first, for the panel; those since moved or deleted are left out."""
    fields = ('id', 'template', 'prompt', 'sent_prompt', 'subject', 'references', 'model', 'width', 'height', 'format', 'quality', 'steps',
              'seed', 'name', 'folder', 'path', 'reference_folder', 'output', 'video', 'motion', 'source_image', 'loop', 'duration', 'scene', 'edit_target', 'request_id', 'reference_applied', 'regions', 'region_source', 'preserve_outside_regions')
    return [{k: item.get(k) for k in fields} for item in reversed(read_json(home/'history.json', []))
            if not item.get('discarded') and Path(str(item.get('path'))).is_file()][:60]


def delete_picture(home, picture_id):
    """Delete a picture this panel made, with its recipe. It is found by its id in the history, so only those can go."""
    item = next((i for i in read_json(home/'history.json', []) if i.get('id') == picture_id), None)
    if item is None:
        raise ValueError('That picture is no longer listed')
    path = Path(item['path'])
    path.unlink(missing_ok=True)
    path.with_suffix('.json').unlink(missing_ok=True)
    update_json(home/'history.json', lambda history: [i for i in history if i.get('id') != picture_id])
    folder = item.get('reference_folder')
    if folder and not any(i.get('reference_folder') == folder for i in read_json(home/'history.json', [])):
        for name in item.get('references') or []:   # only what the run put there, in case anything else was added
            (Path(folder)/Path(name).name).unlink(missing_ok=True)
        if Path(folder).is_dir() and not any(Path(folder).iterdir()):
            Path(folder).rmdir()


def restore_references(home, picture_id):
    """The reference pictures a picture was made with, back in the library from the copies kept beside it. A different
    picture now under the same name stays, and this one comes back as name-2. Returns (names, renamed, missing)."""
    item = next((i for i in read_json(home/'history.json', []) if i.get('id') == picture_id), None)
    if item is None:
        raise ValueError('That picture is no longer listed')
    kept = Path(str(item.get('reference_folder') or ''))
    names, renamed, missing = [], {}, []
    for name in item.get('references') or []:
        library, source = home/'references'/name, kept/name
        if not item.get('reference_folder') or not source.is_file():
            names.append(name) if library.is_file() else missing.append(name)
        elif not library.exists():
            shutil.copy2(source, library)
            names.append(name)
        elif library.read_bytes() == source.read_bytes():
            names.append(name)
        else:
            target = free_path(library.parent, library.stem, library.suffix)
            shutil.copy2(source, target)
            names.append(target.name)
            renamed[name] = target.name
    return names, renamed, missing


def run_status(home):
    global running
    recover(home)
    status = read_json(home/'status.json', dict(state='idle', message=''))
    if running is not None and running.poll() is not None:
        code, running = running.returncode, None
        if status.get('state') not in ('done', 'failed', 'stopped'):
            status = dict(status, state='failed', message=f'The run stopped unexpectedly (exit {code})')
            write_json_atomic(home/'status.json', status)
    elif running is None and status.get('state') not in ('done', 'failed', 'stopped', 'idle'):
        status = dict(status, state='stopped', message='The run ended when Studio closed')
    request = read_json(home/'request.json', {})
    status = apply_completed_reference(home, request, status)
    status = forward_progress(home, request, status)
    pending = clean_queue(home, status)
    from models.gpu.edit_priority import publish
    active = read_json(home/'request.json', {}) if running is not None else {}
    publish(is_edit(active) or any(is_edit(q) for q in pending))
    return status


def start(home, request, cache):
    with MAKER_LOCK:
        return enqueue(home, request, cache)


def enqueue(home, request, cache, reference_folder=None):
    global queue_watcher
    run_status(home)
    request = edit_dimensions(request)
    if request.get('source_id'):
        item = next((i for i in read_json(home/'history.json', []) if i.get('id') == request['source_id']), None)
        if not item or not Path(item['path']).is_file() or Path(item['path']).suffix.lower() == '.mp4':
            raise ValueError('Choose an existing still image to animate')
        # The still already exists; its old reference library and image prompt are not needed to animate it.
        clean = checked(dict(request, template='none', prompt='Animate the existing image', subject='', references=[]),
                        home/'references')
        clean.update(source_image=item['path'], count=1)
    else:
        clean = checked(request, reference_folder or home/'references')
    clean['ai_model'] = str(request.get('ai_model') or 'auto')
    target = request.get('edit_target')
    if isinstance(target, dict) and target.get('job') and target.get('id'):
        from studio import server
        from artwork.reference_lifecycle import validate_target
        project = server.JOBS.get(str(target['job']))
        if project is not None:
            validate_target(project.folder, target)
        clean['edit_target'] = dict(job=str(target['job'])[:200], id=str(target['id'])[:200], label=str(target.get('label') or target['id'])[:200])
        clean['edit_target']['reference_generation'] = str(target.get('reference_generation') or '')
        clean['edit_target']['reference_edit_revision'] = str(target.get('reference_edit_revision') or '')
        if target.get('type') == 'illustration':
            index = int(target.get('index', -1))
            if index < 0:
                raise ValueError('Choose a valid illustration')
            clean['edit_target'].update(type='illustration', index=index, id=f'illustration-{index}')
        clean.update(auto_apply=True, count=1, output='image')
    pending = read_json(home/'queue.json', [])
    active = read_json(home/'request.json', {}) if running is not None else {}
    if clean.get('edit_target') and any(all((item.get('edit_target') or {}).get(k) == clean['edit_target'][k] for k in ('job', 'id')) for item in [active, *pending]):
        raise ValueError('This reference already has an edit running or queued. Other references can be queued now.')
    clean['cache'] = str(cache)
    clean['request_id'] = secrets.token_hex(12)
    home.mkdir(parents=True, exist_ok=True)
    # Snapshot inputs now: edits queued later may replace the same library filename.
    snapshots = home/'queued-references'/secrets.token_hex(12)
    snapshots.mkdir(parents=True)
    for name in clean['references']:
        shutil.copy2((reference_folder or home/'references')/name, snapshots/name)
    clean['input_reference_folder'] = str(snapshots)
    if running is not None or pending:
        pending.append(clean)
        pending.sort(key=lambda item: 0 if item.get('edit_target') else 1)
        write_json_atomic(home/'queue.json', pending)
    else:
        launch(home, clean)
    run_status(home)
    if queue_watcher is None or not queue_watcher.is_alive():
        queue_watcher = threading.Thread(target=watch_queue, args=(home,), daemon=True)
        queue_watcher.start()
    return clean


def edit_dimensions(request):
    """Reference edits inherit source proportions, bounded to the model's supported image sizes."""
    if not request.get('edit_target'):
        return request
    width, height = int(request.get('width') or 1024), int(request.get('height') or 1024)
    if width <= 0 or height <= 0:
        raise ValueError('Reference image dimensions must be positive')
    scale = min(1., 2048/width, 2048/height)
    return dict(request, width=max(256, int(width*scale)//32*32), height=max(256, int(height*scale)//32*32))


def find_request(home, args):
    requests = [read_json(home/'request.json', {}), *read_json(home/'queue.json', [])]
    if args.get('request_id'):
        matches = [r for r in requests if r.get('request_id') == args['request_id']]
    elif args.get('entity'):
        matches = [r for r in requests if (r.get('edit_target') or {}).get('id') == args['entity']
                   and (not args.get('job') or (r.get('edit_target') or {}).get('job') == args['job'])]
    else:
        matches = [r for r in requests if r.get('name') == (args.get('original_name') or args.get('name'))]
    if not matches:
        raise ValueError('This edit is no longer queued; open its result in image edit history.')
    return matches[0]


def revise(home, args, cache):
    with MAKER_LOCK:
        run_status(home)
        old = find_request(home, args)
        from studio import server
        from artwork.reference_lifecycle import validate_target
        target = old.get('edit_target') or {}
        project = server.JOBS.get(target.get('job'))
        if project is not None:
            validate_target(project.folder, target)
        updated = edit_dimensions(dict(args, edit_target=old.get('edit_target') or args.get('edit_target')))
        source = Path(old.get('input_reference_folder') or home/'references')
        staged = home/'queued-references'/secrets.token_hex(12)
        staged.mkdir(parents=True)
        for name in updated.get('references') or []:
            if Path(name).name != name:
                raise ValueError('Invalid reference name')
            picture = source/name if name in old.get('references', []) and (source/name).is_file() else home/'references'/name
            shutil.copy2(picture, staged/name)
        checked(updated, staged)  # validate before stopping work or changing the queue
        active = read_json(home/'request.json', {})
        if running is not None and (old.get('request_id') == active.get('request_id') if old.get('request_id') else old == active):
            stop_current(home)
        pending = read_json(home/'queue.json', [])
        position = pending.index(old) if old in pending else 0
        write_json_atomic(home/'queue.json', [r for r in pending if r != old])
        new = enqueue(home, updated, cache, reference_folder=staged)
        pending = read_json(home/'queue.json', [])
        if new in pending:
            pending.remove(new)
            pending.insert(min(position, len(pending)), new)
            write_json_atomic(home/'queue.json', pending)


def launch(home, clean):
    global running
    from models.gpu.edit_priority import publish
    publish(is_edit(clean) or any(is_edit(q) for q in read_json(home/'queue.json', [])))
    path = home/'request.json'
    write_text_atomic(path, json.dumps(clean, indent=2, ensure_ascii=False))
    write_json_atomic(home/'status.json', dict(state='starting', message='Starting', done=0, total=clean['count'], files=[], at=time.time()))
    log = (home/'run.log').open('wb')
    running = subprocess.Popen(module_command('artwork.maker', path), env=module_env(), stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                               start_new_session=os.name != 'nt')
    log.close()


def stop(home):
    with MAKER_LOCK:
        stop_current(home)


def stop_current(home):
    global running
    if running is not None and running.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(running.pid), '/T', '/F'], capture_output=True)
        else:
            import signal
            os.killpg(running.pid, signal.SIGTERM)
    running = None
    write_json_atomic(home/'status.json', dict(read_json(home/'status.json', {}), state='stopped', message='Stopped'))


class MakerRoutes:
    def _maker_home(self):
        from studio import server
        home = maker_folder(server.ROOT)
        (home/'references').mkdir(parents=True, exist_ok=True)
        return home

    def _maker_state(self, home):
        global queue_watcher
        with MAKER_LOCK:
            status = run_status(home)
            request = read_json(home/'request.json', {})
            queued = [public_request(q) for q in read_json(home/'queue.json', [])]
            if (queued or running is not None) and (queue_watcher is None or not queue_watcher.is_alive()):
                queue_watcher = threading.Thread(target=watch_queue, args=(home,), daemon=True)
                queue_watcher.start()
        return dict(status=status, request=public_request(request), request_name=request.get('name', 'Image edit'), edit_target=request.get('edit_target'), queued=queued,
                    history=public_history(home), references=reference_list(home), prompts=saved_prompts(home))

    def _get_maker(self, url):
        """GET path.startswith('/api/image-maker')"""
        home = self._maker_home()
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == '/api/image-maker':
            cache = default_model_cache()
            return self.respond(dict(self._maker_state(home), models=model_list(cache), templates=TEMPLATES, formats=list(FORMATS),
                                     max_count=MAX_COUNT, default_folder=str(home/'images')))
        if url.path == '/api/image-maker/status':
            return self.respond(self._maker_state(home))
        if url.path == '/api/image-maker/request':
            with MAKER_LOCK:
                return self.respond(dict(request=public_request(find_request(home, query))))
        if url.path == '/api/image-maker/request-reference':
            requests = [read_json(home/'request.json', {}), *read_json(home/'queue.json', []), *read_json(home/'history.json', [])]
            request = next((r for r in requests if str(r.get('request_id', '')) == query.get('request_id', '')), {})
            name = Path(str(query.get('name', ''))).name
            if name not in request.get('references', []):
                return self.respond(dict(error='Reference not found'), 404)
            path = Path(request.get('input_reference_folder') or home/'references')/name
        elif url.path == '/api/image-maker/reference':
            path = home/'references'/Path(str(query.get('name'))).name
        elif url.path == '/api/image-maker/picture':
            item = next((i for i in read_json(home/'history.json', []) if i.get('id') == query.get('id')), None)
            path = Path(str((item or {}).get('path')))
        else:
            return self.respond(dict(error='Not found'), 404)
        if not path.is_file():
            return self.respond(dict(error='File not found'), 404)
        return self._respond_file(path)

    def _post_maker(self, route, body):
        from studio import server
        home = self._maker_home()
        action = route.rsplit('/', 1)[1]
        if action == 'reference':
            _, files = server.parse_form(body, self.headers.get('Content-Type', ''))
            added = []
            for name, content in files.get('reference') or []:
                added.append(server.keep_upload_name(server.store_image(home/'references', name, content), name).name)
            return self.respond(dict(self._maker_state(home), added=added))
        args = server.json_body(body)
        if action == 'project-references':
            from artwork.reference_lifecycle import sync_library
            with MAKER_LOCK, server.LOCK:
                job = server.JOBS.get(str(args.get('job') or ''))
                if job is None:
                    raise ValueError('This project is no longer loaded.')
                result = sync_library(home, job, args)
            return self.respond(dict(self._maker_state(home), **result))
        if action == 'reference-delete':
            path = home/'references'/Path(str(args.get('name'))).name
            with MAKER_LOCK:
                used = reference_usage(home, path.name, args.get('selected_references') or [])
                if used:
                    return self.respond(dict(error='Cannot delete this reference. '+ '; '.join(used), uses=used), 409)
                path.unlink(missing_ok=True)
        elif action == 'reference-usage':
            name = Path(str(args.get('name'))).name
            return self.respond(dict(uses=reference_usage(home, name, args.get('selected_references') or [])))
        elif action == 'picture-references':
            names, renamed, missing = restore_references(home, args.get('id'))
            return self.respond(dict(self._maker_state(home), used=names, renamed=renamed, missing=missing))
        elif action == 'picture-delete':
            delete_picture(home, args.get('id'))
        elif action == 'prompt':
            save_prompt(home, args)
        elif action == 'prompt-delete':
            delete_prompt(home, args.get('name'))
        elif action == 'generate':
            start(home, args, default_model_cache())
        elif action == 'revise':
            revise(home, args, default_model_cache())
        elif action == 'stop':
            stop(home)
        elif action == 'choose-folder':
            answer = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-Command', PICK_FOLDER], capture_output=True,
                                    text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return self.respond(dict(folder=answer.stdout.strip()))
        else:
            return self.respond(dict(error='Not found'), 404)
        return self.respond(self._maker_state(home))
