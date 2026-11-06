"""Admit Ollama inference only after verifying full GPU residency."""
from contextlib import nullcontext
from core.paths import PROJECT_ROOT
import time
import urllib.error
from models.gpu.devices import GIB, detect_gpus; from models.ollama.catalog import budget_for_model, normalize


_MODEL_GPU = {}


class GPUCapacityError(ValueError):
    pass


def unload_model(model, request=None):
    if not model:return
    if request is None:
        from models.ollama.service import local_json as request
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


def release_model(model, label='prompt model'):
    """Unload `model` when a step is done with it. A failure is reported, never raised: it runs in `finally`
    blocks, where raising would hide the error that actually stopped the step."""
    try:
        unload_model(model)
    except Exception as exc:  # noqa: BLE001
        print(f'Warning: {label} cleanup ({model}): {exc}', flush=True)


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


def smaller_models(request, model):
    """Installed text models smaller than `model` that can stand in for it: the same model's smaller sizes first,
    then the others, largest first. Vision, speech and embedding models never stand in for a text model."""
    def size(entry):
        return int(entry.get('size', 0) or 0)
    installed = request('tags').get('models', [])
    current = next((m for m in installed if normalize(m.get('name', m.get('model', ''))) == normalize(model)), None)
    limit = size(current) if current else float('inf')
    import re
    family_of = lambda name: (re.match(r'[a-z]+', normalize(name).split('/')[-1].lower()) or [''])[0]  # qwen3.8 and qwen3: qwen
    family = family_of(model)
    def text_model(name):
        lowered = name.lower()
        return not any(mark in lowered for mark in ('-vl', 'vision', 'asr', 'whisper', 'embed', 'llava'))
    names = [(m.get('name', m.get('model', '')), size(m)) for m in installed]
    names = [(n, s) for n, s in names if n and text_model(n) and s < limit and normalize(n) != normalize(model)]
    names.sort(key=lambda item: (family_of(item[0]) != family, -item[1]))
    return [n for n, _ in names]


def load_or_smaller(request, query):
    """Load the asked model on the GPU; when it does not fit right now, the next smaller installed text model takes
    this call (said in the log) instead of the step failing. A model that is not installed still fails."""
    try:
        return ensure_loaded(request, query['model'], query['options'])
    except GPUCapacityError as exc:
        if 'not installed' in str(exc).lower():
            raise
        reason = exc
    for smaller in smaller_models(request, query['model']):
        try:
            options = ensure_loaded(request, smaller, query['options'])
        except GPUCapacityError:
            continue
        short = str(reason).split('short by ')[-1].split(' GiB')[0] if 'short by' in str(reason) else ''
        print(f"{query['model']} does not fit on the GPU right now" + (f' (short by {short} GiB)' if short else '')
              + f'; using {smaller} for this step.', flush=True)
        query['model'] = smaller
        return options
    raise reason


def wait_for_model(request, query, wait=600, pause=15):
    """Load the asked model and no other, waiting up to `wait` seconds for the memory something else holds: for a
    step a smaller model does badly (the director's references: qwen3:14b standing in listed none, and the run went on
    without them). GPUCapacityError when it still does not fit."""
    deadline = time.monotonic()+wait
    waiting = False
    while True:
        try:
            return ensure_loaded(request, query['model'], query['options'])
        except GPUCapacityError as exc:
            if 'not installed' in str(exc).lower() or time.monotonic() >= deadline:
                raise
            if not waiting:
                print(f"Waiting up to {wait//60} minutes for GPU memory for {query['model']}: {exc}", flush=True)
                waiting = True
        time.sleep(pause)


def gpu_chat(endpoint,payload=None,timeout=900,exact=False):
    from models.ollama.service import local_json
    if endpoint!='chat' or not payload or not payload.get('messages'):
        return local_json(endpoint,payload,timeout=timeout)
    from models.gpu.lifecycle import current_session
    from filelock import FileLock
    lock=nullcontext() if current_session() else FileLock(str(PROJECT_ROOT/'.image-generation.lock'),timeout=-1)
    query=dict(payload);query['options']={**payload.get('options',{}),'num_gpu':999}
    # Kept loaded for the call (its GPU residency is checked afterwards). A caller's own keep_alive such as '30m'
    # is honoured; 0 (unload when done) is done explicitly below, after that check.
    query['keep_alive']=-1 if payload.get('keep_alive') in (None,0) else payload['keep_alive']
    with lock:
        query['options'].update((wait_for_model if exact else load_or_smaller)(local_json,query))
        from models.ollama.trace import log_request, log_response, log_failure
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
