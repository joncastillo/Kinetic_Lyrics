"""Start the local Ollama server on demand without loading any models."""
import json
import io
import os
from pathlib import Path
from project_paths import PROJECT_ROOT
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from filelock import FileLock

BASE = 'http://127.0.0.1:11434/api/'


def http_error_detail(error):
    """Read a server error once without hiding its body from other handlers."""
    if hasattr(error,'detail'):return error.detail
    raw=error.read()
    error.detail=raw.decode('utf-8',errors='replace')
    error.file=error.fp=io.BytesIO(raw)
    error.read=error.fp.read
    return error.detail


class OllamaHTTPError(urllib.error.HTTPError):
    def __str__(self):
        text=super().__str__()
        detail=http_error_detail(self)
        try:detail=json.loads(detail).get('error',detail)
        except (ValueError,AttributeError):pass
        return text+(': '+str(detail)[:2000] if detail else '')


def _open(request,timeout):
    try:return urllib.request.urlopen(request,timeout=timeout)
    except urllib.error.HTTPError as error:
        raw=http_error_detail(error).encode('utf-8')
        raise OllamaHTTPError(error.url,error.code,error.msg,error.headers,io.BytesIO(raw)) from error

def connection_refused(exc):
    reason = getattr(exc, 'reason', exc)
    return isinstance(reason, ConnectionRefusedError) or getattr(reason, 'errno', None) in (61, 111, 10061) or getattr(reason, 'winerror', None) == 10061

def ready():
    try:
        with urllib.request.urlopen(BASE + 'version', timeout=1) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False

def ensure_running(timeout=30):
    if ready():
        return
    lock = PROJECT_ROOT / 'tmp' / 'ollama-start.lock'
    lock.parent.mkdir(exist_ok=True)
    with FileLock(str(lock), timeout=timeout+5):
        if ready():
            return
        executable = shutil.which('ollama')
        fallback = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Ollama' / 'ollama.exe'
        if not executable and fallback.is_file():
            executable = str(fallback)
        if not executable:
            raise RuntimeError('Ollama is not installed or could not be found. Install Ollama to enable local vision review.')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        with (lock.parent / 'ollama-server.log').open('ab') as log:
            process = subprocess.Popen([executable, 'serve'], stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ready():
                return
            if process.poll() is not None:
                raise RuntimeError('Ollama could not start. See tmp/ollama-server.log for details.')
            time.sleep(.25)
        raise RuntimeError('Ollama started but is not ready yet. Try Find models again; see tmp/ollama-server.log.')

def local_json(endpoint, payload=None, timeout=5):
    request = urllib.request.Request(BASE + endpoint,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        response = _open(request,timeout)
    except urllib.error.URLError as exc:
        if not connection_refused(exc):
            raise
        ensure_running()
        response = _open(request,timeout)
    with response:
        return json.load(response)
