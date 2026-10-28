"""Shared background model downloads with progress visible to the studio UI."""
from collections import OrderedDict
from project_paths import default_model_cache, ollama_models_dir
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from gpu_models import normalize, GIB, PROMPT_MODELS, VISION_MODELS

_LOCK=threading.RLock()
_TASKS=OrderedDict()
_DOWNLOAD_LOCK=threading.Lock()


class DownloadCancelled(RuntimeError):pass


def _update(task,**values):
    with _LOCK:
        task.update(values,updated=time.time())


def _public(task):
    return {key:value for key,value in task.items() if not key.startswith('_')}


def download_status(ids=None):
    with _LOCK:
        tasks=[_public(t) for key,t in _TASKS.items() if ids is None or key in ids]
    return dict(tasks=tasks)


def cancel_downloads(ids):
    with _LOCK:
        for key in ids:
            task=_TASKS.get(key)
            if task and task['status'] in ('queued','downloading'):
                task['_cancel'].set()
    return download_status(ids)


def _check_cancel(task):
    if task['_cancel'].is_set():raise DownloadCancelled('Download cancelled. Downloaded cache files are retained for resume.')


def _ollama_store(installed,request):
    if installed:
        info=request('show',{'model':installed[0]['name']},timeout=30)
        for line in info.get('modelfile','').splitlines():
            if line.startswith('FROM '):
                path=Path(line[5:].strip().strip('"'))
                if path.parent.name=='blobs':return path.parent.parent
    return ollama_models_dir()


def _pull_ollama(task):
    from ollama_service import local_json,ensure_running,BASE
    ensure_running()
    installed=local_json('tags').get('models',[])
    if any(normalize(m['name'])==normalize(task['model']) for m in installed):
        _update(task,status='complete',percent=100,message='Already installed');return
    store=_ollama_store(installed,local_json)
    parent=store
    while not parent.exists():parent=parent.parent
    known=next((m for m in PROMPT_MODELS+VISION_MODELS if normalize(m['id'])==normalize(task['model'])),None)
    minimum=(known['vram_gib']*.85+.5)*GIB if known else 0
    if minimum and shutil.disk_usage(parent).free<minimum:
        raise ValueError(f'Not enough free disk space on {parent.anchor} for {task["model"]}. '
                         'Choose an installed prompting model such as qwen3.8:27b, or move the Ollama model store to a drive with more space.')
    request=urllib.request.Request(BASE+'pull',data=json.dumps(dict(model=task['model'],stream=True)).encode(),headers={'Content-Type':'application/json'})
    layers={}
    with urllib.request.urlopen(request,timeout=120) as response:
        for raw in response:
            _check_cancel(task)
            if not raw.strip():continue
            event=json.loads(raw)
            if event.get('error'):raise ValueError(event['error'])
            digest=event.get('digest')
            if digest and event.get('total'):
                layers[digest]=(int(event.get('completed',0)),int(event['total']))
            completed=sum(v[0] for v in layers.values());total=sum(v[1] for v in layers.values())
            _update(task,completed=completed,total=total,percent=min(99,round(completed/total*100,1)) if total else None,
                    message=event.get('status','Downloading model'))
    if not any(normalize(m['name'])==normalize(task['model']) for m in local_json('tags').get('models',[])):
        raise ValueError('Download ended before Ollama registered the model. Retry to resume.')
    _update(task,status='complete',percent=100,message='Installed and ready')


def _pull_image(task):
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import tqdm
    from image_models import model_spec
    cache=Path(task['cache']).expanduser().resolve()
    cache.mkdir(parents=True,exist_ok=True)
    snapshots=cache/('models--'+task['model'].replace('/','--'))/'snapshots'
    if not snapshots.exists() and shutil.disk_usage(cache).free<(model_spec(task['model'])['disk_gb']+2)*GIB:
        raise ValueError('Not enough free disk space for the image model in '+str(cache))
    class DownloadProgress(tqdm):
        def __init__(self,*args,**kwargs):
            self._studio_bytes=kwargs.get('unit')=='B'
            self._studio_n=kwargs.get('initial',0)
            super().__init__(*args,**kwargs)
        def update(self,n=1):
            _check_cancel(task)
            self._studio_n+=n
            result=super().update(n)
            if self.total:
                unit='bytes' if self._studio_bytes else 'files'
                _update(task,completed=int(self._studio_n),total=int(self.total),unit=unit,
                        percent=min(99,round(self._studio_n/self.total*100,1)),message='Downloading image model: '+str(getattr(self,'desc','') or unit))
            return result
    path=snapshot_download(task['model'],cache_dir=cache,max_workers=1,tqdm_class=DownloadProgress)
    _check_cancel(task)
    marker=cache/('models--'+task['model'].replace('/','--'))/'lyric-studio-ready.json'
    marker.parent.mkdir(parents=True,exist_ok=True)
    marker.write_text(json.dumps(dict(snapshot=path,model=task['model'],time=time.time())),encoding='utf-8')
    _update(task,status='complete',percent=100,message='Image weights cached and ready')


def _run(task):
    try:
        with _DOWNLOAD_LOCK:
            _check_cancel(task)
            _update(task,status='downloading',message='Checking cached model files')
            if task['kind']=='ollama':_pull_ollama(task)
            else:_pull_image(task)
    except DownloadCancelled as exc:_update(task,status='cancelled',message=str(exc),error=str(exc))
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode('utf-8',errors='replace')
        try:detail=json.loads(detail).get('error',detail)
        except ValueError:pass
        _update(task,status='failed',message='Download failed',error=f'{task["model"]}: {detail or str(exc)}')
    except Exception as exc:_update(task,status='failed',message='Download failed',error=str(exc))


def request_downloads(specs):
    """Start missing/cached-weight checks once; return immediately for UI polling."""
    from image_models import MODELS
    if not isinstance(specs,list) or len(specs)>3:raise ValueError('Choose up to three models')
    ids=[]
    with _LOCK:
        for spec in specs:
            kind=spec.get('kind');model=spec.get('model','')
            if not isinstance(model,str) or len(model)>200 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*',model) or '..' in model or '://' in model:
                raise ValueError('Invalid model name')
            if kind not in ('ollama','image'):raise ValueError('Invalid model type')
            if kind=='image' and model not in {m['id'] for m in MODELS}:raise ValueError('Choose a supported image model')
            cache=str(Path(spec.get('cache') or str(default_model_cache())).expanduser().resolve()) if kind=='image' else ''
            key=hashlib.sha256(json.dumps([kind,model,cache]).encode()).hexdigest()[:20]
            old=_TASKS.get(key)
            if old and old['status'] in ('queued','downloading'):
                ids.append(key);continue
            task=dict(id=key,kind=kind,model=model,cache=cache,status='queued',percent=None,completed=0,total=0,
                      unit='bytes',message='Queued',error='',created=time.time(),_cancel=threading.Event())
            _TASKS[key]=task;ids.append(key)
            threading.Thread(target=_run,args=(task,),daemon=True).start()
    return dict(ids=ids,**download_status(ids))
