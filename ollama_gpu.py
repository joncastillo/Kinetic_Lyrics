"""Admit Ollama inference only after verifying full GPU residency."""
from contextlib import nullcontext
from pathlib import Path
import time
import urllib.error
from gpu_models import GIB, budget_for_model, detect_gpus, normalize


_MODEL_GPU = {}


class GPUCapacityError(ValueError):
    pass


def unload_model(model, request=None):
    if not model:return
    if request is None:
        from ollama_service import local_json as request
    running=request('ps').get('models',[])
    if not any(normalize(m.get('name',m.get('model','')))==normalize(model) for m in running):return
    try:
        request('chat',dict(model=model,messages=[],stream=False,keep_alive=0),timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code==404:return
        raise
    deadline=time.monotonic()+15
    while True:
        running=request('ps').get('models',[])
        if not any(normalize(m.get('name',m.get('model','')))==normalize(model) for m in running):return
        if time.monotonic()>=deadline:raise GPUCapacityError('Timed out unloading '+model+' from GPU memory')
        time.sleep(.1)


def fully_on_gpu(model):
    total=int(model.get('size',0));vram=int(model.get('size_vram',0))
    return total>0 and vram>=total


def ensure_loaded(request, model, options):
    installed=request('tags').get('models',[])
    if not any(normalize(m.get('name',m.get('model','')))==normalize(model) for m in installed):
        raise GPUCapacityError('Model not installed. Run: ollama pull '+model)
    required=budget_for_model(model,installed)
    running=request('ps').get('models',[])
    resident=next((m for m in running if normalize(m.get('name',m.get('model','')))==normalize(model)),None)
    binding=_MODEL_GPU.get(normalize(model))
    if resident and binding is not None and fully_on_gpu(resident) and int(resident.get('context_length',0))>=options.get('num_ctx',4096):
        return dict(num_gpu=999,main_gpu=binding)
    if resident:unload_model(model,request)
    gpus=detect_gpus()
    if not gpus:raise GPUCapacityError('A CUDA GPU is required. CPU inference is disabled.')
    gpu=max(gpus,key=lambda g:g['free_bytes'])
    if gpu['free_bytes']<required:
        for other in running:
            name=other.get('name',other.get('model',''))
            if name and normalize(name)!=normalize(model):unload_model(name,request)
        gpus=detect_gpus();gpu=max(gpus,key=lambda g:g['free_bytes'])
    tolerance=128*2**20
    if gpu['free_bytes']+tolerance<required:
        shortfall = (required - gpu['free_bytes']) / GIB
        raise GPUCapacityError(
            f'{model} requires an estimated {required/GIB:.2f} GiB free for GPU-only inference '
            '(including its runtime allowance); '
            f'{gpu["free_bytes"]/GIB:.2f} GiB is free, short by {shortfall:.2f} GiB. '
            'Free GPU memory and retry, or use Best / a smaller model. CPU fallback is disabled.')
    if gpu['free_bytes']<required:
        print(f'{model}: available VRAM is within 128 MiB of its estimate; verifying an all-GPU preload before inference.',flush=True)
    load_options=dict(num_gpu=999,main_gpu=gpu['index'],num_ctx=options.get('num_ctx',4096))
    request('chat',dict(model=model,messages=[],stream=False,keep_alive=-1,options=load_options),timeout=600)
    loaded=next((m for m in request('ps').get('models',[]) if normalize(m.get('name',m.get('model','')))==normalize(model)),None)
    if not loaded or not fully_on_gpu(loaded):
        unload_model(model,request)
        raise GPUCapacityError(model+' did not load entirely on GPU. Inference was stopped before generating any tokens; CPU fallback is disabled.')
    _MODEL_GPU[normalize(model)]=gpu['index']
    return dict(num_gpu=999,main_gpu=gpu['index'])


def gpu_chat(endpoint,payload=None,timeout=900):
    from ollama_service import local_json
    if endpoint!='chat' or not payload or not payload.get('messages'):
        return local_json(endpoint,payload,timeout=timeout)
    from model_lifecycle import current_session
    from filelock import FileLock
    lock=nullcontext() if current_session() else FileLock(str(Path(__file__).parent/'.image-generation.lock'),timeout=-1)
    query=dict(payload);query['options']={**payload.get('options',{}),'num_gpu':999}
    query['keep_alive']=-1
    with lock:
        query['options'].update(ensure_loaded(local_json,query['model'],query['options']))
        from llm_trace import log_request, log_response, log_failure
        call_id = log_request(query)
        try:
            result=local_json(endpoint,query,timeout=timeout)
            log_response(call_id, result)
            loaded=next((m for m in local_json('ps').get('models',[]) if normalize(m.get('name',m.get('model','')))==normalize(query['model'])),None)
            if not loaded or not fully_on_gpu(loaded):
                raise GPUCapacityError('GPU residency changed during inference. CPU fallback is not allowed.')
            return result
        except Exception as exc:
            log_failure(call_id, exc)
            raise
        finally:
            if payload.get('keep_alive')==0:unload_model(query['model'],local_json)
