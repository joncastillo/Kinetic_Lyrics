"""Which of the chosen models are on this computer, and which Ollama models are loaded in memory right now.
The studio header colours its model pills from this."""
from pathlib import Path
from core.paths import default_model_cache
from models.ollama.catalog import normalize


def ollama_state(name, installed, running):
    """off: not used; missing: not pulled yet; ready: pulled; loaded: in memory now."""
    if not name:
        return dict(state='off')
    key = normalize(name)
    state = 'loaded' if key in running else 'ready' if key in installed else 'missing'
    return dict(state=state, name=name)


def cache_folders(cache=''):
    """Where weights may sit: the folder the form names, the Hugging Face hub cache, the studio's default cache."""
    folders = [Path(cache).expanduser()] if cache else []
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        folders.append(Path(HF_HUB_CACHE))
    except ImportError:
        pass
    folders.append(default_model_cache())
    return folders


def weights_cached(repo, cache='', folders=None):
    """True when a Hugging Face snapshot of the repo sits in one of the cache folders with no download still in progress."""
    folders = cache_folders(cache) if folders is None else [Path(f) for f in folders]
    for folder in folders:
        root = folder/('models--'+repo.replace('/', '--'))
        snapshots = root/'snapshots'
        try:
            if snapshots.is_dir() and any(snapshots.iterdir()) and not any((root/'blobs').glob('*.incomplete')):
                return True
        except OSError:
            continue
    return False


def readiness(query, local_json=None, folders=None, held=None):
    """query: text, image, vision, video, end (end frame) model ids (empty when not used) and the cache folder. Text "auto" resolves
    to the model the studio would pick for this GPU."""
    if local_json is None:
        from models.ollama.service import local_json
    names = lambda payload: {normalize(m.get('name', m.get('model', ''))) for m in (payload or {}).get('models', [])}
    try:
        installed, running = names(local_json('tags')), names(local_json('ps'))
    except Exception:  # Ollama not running: nothing is installed as far as the studio can tell
        installed, running = set(), set()
    text = query.get('text', '')
    resolved = text
    if text == 'auto':
        try:
            from models.ollama.catalog import model_choices
            resolved = (model_choices(local_json, review=False).get('recommendation') or {}).get('ai_model', '')
        except Exception:
            resolved = ''
    result = dict(text=ollama_state(resolved, installed, running), vision=ollama_state(query.get('vision', ''), installed, running))
    if text == 'auto':
        result['text']['resolved'] = resolved
    held = loaded_models() or set(held or ())  # a live worker's report beats what a job says it holds
    for key in ('image', 'video', 'end'):
        repo = query.get(key, '')
        cached = weights_cached(repo, query.get('cache', ''), folders)
        if cached and key != 'video':  # a GGUF transformer lives in its own repository: both must be there
            try:
                from models.image.catalog import model_spec
                gguf = model_spec(repo).get('gguf')
            except ValueError:
                gguf = None
            cached = not gguf or weights_cached(gguf[0], query.get('cache', ''), folders)
        state = 'loaded' if repo in held else 'ready' if cached else 'missing'
        result[key] = dict(state='off') if not repo else dict(state=state, name=repo)
    return result


def loaded_models():
    """The image and video models a live worker holds on the GPU right now (each reports itself; see
    models.gpu.telemetry.publish_model)."""
    try:
        from models.gpu.telemetry import _worker_reports
        return {str(report.get('model') or '') for report in _worker_reports()}
    except Exception:  # noqa: BLE001 (the pills are a help, never a reason to fail)
        return set()
