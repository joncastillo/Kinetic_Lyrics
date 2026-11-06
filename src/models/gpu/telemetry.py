"""Measured VRAM blocks, with unattributed usage shown explicitly."""
import json
import os
from pathlib import Path
from core.paths import PROJECT_ROOT
import threading
import time

REPORTS=PROJECT_ROOT/'.runtime'/'gpu-memory'
_CACHE_LOCK=threading.Lock()
_CACHE=None
_CACHE_TIME=0


def publish_model(model,torch):
    """Called by an image worker; telemetry must never fail generation."""
    try:
        REPORTS.mkdir(parents=True,exist_ok=True)
        device=torch.cuda.current_device()
        props=torch.cuda.get_device_properties(device)
        value=dict(pid=os.getpid(),model=model,device=device,uuid=str(getattr(props,'uuid','')),
                   bytes=int(torch.cuda.memory_reserved(device)),updated=time.time())
        from core.files import write_text_atomic
        write_text_atomic(REPORTS/f'{os.getpid()}.json',json.dumps(value))
    except (OSError,ValueError,RuntimeError,AttributeError,TypeError):pass


def clear_model():
    try:(REPORTS/f'{os.getpid()}.json').unlink(missing_ok=True)
    except OSError:pass


def _alive(pid):
    if os.name!='nt':return Path('/proc',str(pid)).exists()
    import ctypes
    from ctypes import wintypes
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
    api.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=api.OpenProcess(0x1000,False,pid)
    if not handle:return False
    try:
        code=wintypes.DWORD()
        return bool(api.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
    finally:api.CloseHandle(handle)


def _worker_reports():
    for path in REPORTS.glob('*.json'):
        try:
            value=json.loads(path.read_text(encoding='utf-8'))
            if time.time()-float(value['updated'])>180 or not _alive(int(value['pid'])):continue
            yield value
        except (OSError,ValueError,KeyError,TypeError):continue


def memory_blocks(gpus,running,workers,unreported=()):
    result=[]
    for gpu in gpus:
        total=int(gpu['total_bytes']);free=min(total,max(0,int(gpu['free_bytes'])))
        used=max(0,total-free);remaining=used;blocks=[]
        def add(label,size,kind):
            nonlocal remaining
            size=min(remaining,max(0,int(size)))
            if size:blocks.append(dict(label=label,bytes=size,kind=kind,models=[label]));remaining-=size
        for model in running:
            ids=model.get('gpu_ids') or model.get('gpu_uuids') or []
            if len(gpus)==1 or gpu['uuid'] in ids:
                add(model.get('name',model.get('model','Ollama model')),model.get('size_vram',0),'ollama')
        for worker in workers:
            uuid=worker.get('uuid','')
            if (uuid and uuid.lower().removeprefix('gpu-')==gpu['uuid'].lower().removeprefix('gpu-')) or (not uuid and len(gpus)==1):
                add(worker['model'],worker['bytes'],'image')
        if remaining and unreported:  # a model a running job holds but that does not report its size
            blocks.append(dict(label=f"{', '.join(m.split('/')[-1] for m in unreported)} (estimate: includes other apps)",
                               bytes=remaining,kind='image',models=list(unreported)));remaining=0
        if remaining:blocks.append(dict(label='Other apps / unknown',bytes=remaining,kind='other'))
        if free:blocks.append(dict(label='Free',bytes=free,kind='free'))
        result.append(dict(gpu,blocks=blocks,used_bytes=used))
    return result


def unreported_models(held, workers):
    """What running jobs say they hold, when no worker reports. One GPU worker runs at a time (the image-generation
    lock), so a live report is what has the card: an animating job's video model is not loaded while its end frames
    are painted."""
    return [] if workers else list(held or ())


def gpu_usage(force=False, held=None):
    """The GPU's memory as blocks. `held` ({model: kind}) names models running jobs hold: with no worker reporting (one
    started before it reported) they take the memory nothing else accounts for, marked as an estimate."""
    global _CACHE,_CACHE_TIME
    with _CACHE_LOCK:
        if not force and _CACHE is not None and time.monotonic()-_CACHE_TIME<2 and _CACHE.get('held')==(held or {}):return _CACHE
        from models.gpu.devices import detect_gpus
        from models.ollama.service import ready, local_json
        running=[]
        try:
            if ready():running=local_json('ps').get('models',[])
        except (OSError,ValueError):pass
        workers=list(_worker_reports())
        cards=memory_blocks(detect_gpus(),running,workers,unreported_models(held,workers))
        _CACHE=dict(gpus=cards,held=held or {},updated=time.time(),note='Model blocks are measured allocations. Other apps / unknown includes desktop, driver overhead and allocations that cannot be attributed to a model.')
        _CACHE_TIME=time.monotonic()
        return _CACHE
