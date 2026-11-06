"""Let user-requested image edits take the GPU at the next saved-image boundary."""
import json
import time
from core.paths import PROJECT_ROOT
from core.files import write_json_atomic

MARKER = PROJECT_ROOT / '.image-edit-priority.json'


class YieldToEdits(Exception):
    pass


def publish(wanted):
    # A short renewable lease cannot strand generation after Studio crashes or closes.
    for attempt in range(6):
        try:
            write_json_atomic(MARKER, dict(until=time.time() + 5 if wanted else 0))
            return True
        except PermissionError:
            if attempt < 5:
                time.sleep(.05)
        except OSError:
            break
    # The old lease remains valid until expiry; a short-lived reader must not kill the queue watcher.
    return False


def pending():
    try:
        return float(json.loads(MARKER.read_text(encoding='utf-8'))['until']) > time.time()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def checkpoint():
    if pending():
        raise YieldToEdits()


def acquire(lock):
    while True:
        while pending():
            time.sleep(.2)
        lock.acquire()
        if not pending():
            return
        lock.release()
