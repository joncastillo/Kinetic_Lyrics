"""Measured VRAM blocks, with unattributed usage shown explicitly."""
import json
import os
from pathlib import Path
import threading
import time

REPORTS=Path(__file__).parent/'.runtime'/'gpu-memory'
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
        path=REPORTS/f'{os.getpid()}.json';temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(path)
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


def memory_blocks(gpus,running,workers):
    result=[]
    for gpu in gpus:
        total=int(gpu['total_bytes']);free=min(total,max(0,int(gpu['free_bytes'])))
        used=max(0,total-free);remaining=used;blocks=[]
        def add(label,size,kind):
            nonlocal remaining
            size=min(remaining,max(0,int(size)))
            if size:blocks.append(dict(label=label,bytes=size,kind=kind));remaining-=size
        for model in running:
            ids=model.get('gpu_ids') or model.get('gpu_uuids') or []
            if len(gpus)==1 or gpu['uuid'] in ids:
                add(model.get('name',model.get('model','Ollama model')),model.get('size_vram',0),'ollama')
        for worker in workers:
            uuid=worker.get('uuid','')
            if (uuid and uuid.lower().removeprefix('gpu-')==gpu['uuid'].lower().removeprefix('gpu-')) or (not uuid and len(gpus)==1):
                add(worker['model'],worker['bytes'],'image')
        if remaining:blocks.append(dict(label='Other apps / unknown',bytes=remaining,kind='other'))
        if free:blocks.append(dict(label='Free',bytes=free,kind='free'))
        result.append(dict(gpu,blocks=blocks,used_bytes=used))
    return result


def gpu_usage(force=False):
    global _CACHE,_CACHE_TIME
    with _CACHE_LOCK:
        if not force and _CACHE is not None and time.monotonic()-_CACHE_TIME<2:return _CACHE
        from gpu_models import detect_gpus
        from ollama_service import ready,local_json
        running=[]
        try:
            if ready():running=local_json('ps').get('models',[])
        except (OSError,ValueError):pass
        cards=memory_blocks(detect_gpus(),running,list(_worker_reports()))
        _CACHE=dict(gpus=cards,updated=time.time(),note='Model blocks are measured allocations. Other apps / unknown includes desktop, driver overhead and allocations that cannot be attributed to a model.')
        _CACHE_TIME=time.monotonic()
        return _CACHE
