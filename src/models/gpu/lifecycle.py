"""Keep image weights across a batch; evict competing models only under VRAM pressure."""
from contextvars import ContextVar
import gc
import models.gpu.memory as gpu_memory
from pathlib import Path
from core.paths import PROJECT_ROOT

_ACTIVE = ContextVar('image_model_session', default=None)
GIB = 2**30


def current_session():
    return _ACTIVE.get()


class ModelSession:
    def __init__(self, vision_models=()):
        self.pipe = self.torch = self.key = None
        self.guidance = None
        self.peak = 0
        self.vision_models = set(filter(None,vision_models))
        self.phase = None
        self.offload = False
        self._reported=0
        self.review_limits=None

    def __enter__(self):
        from filelock import FileLock
        self.lock = FileLock(str(PROJECT_ROOT/'.image-generation.lock'), timeout=-1)
        self.lock.acquire()
        self.token = _ACTIVE.set(self)
        return self

    def __exit__(self, *args):
        try:
            self.release()
        finally:
            _ACTIVE.reset(self.token)
            self.lock.release()

    def publish(self,force=False):
        if self.pipe is None or not self.key:return
        import time
        if not force and time.monotonic()-self._reported<2:return
        from models.gpu.telemetry import publish_model
        publish_model(self.key[0],self.torch);self._reported=time.monotonic()

    def release(self):
        pipe, self.pipe = self.pipe, None
        self.phase = None
        if self.torch is None:
            return
        had_pipeline = pipe is not None
        try:
            self.torch.cuda.synchronize()
            if pipe is not None:
                pipe.maybe_free_model_hooks()
        finally:
            del pipe
            gc.collect()
            self.torch.cuda.empty_cache()
            if had_pipeline:
                from models.gpu.telemetry import clear_model
                clear_model()
                print('Released image weights at the batch boundary.', flush=True)

    def before_generation(self, model):
        if self.phase == ('generation',model):return
        from models.ollama.service import local_json
        from models.ollama.gpu import unload_model
        from models.image.catalog import model_spec
        import torch
        torch.cuda.empty_cache()
        free, _ = gpu_memory.dedicated_memory(torch)
        observed=self.peak if self.key and self.key[0]==model else 0
        required = max(observed,model_spec(model)['vram_gib']*GIB)+.5*GIB
        available = free+torch.cuda.memory_reserved()
        if available < required:
            running=local_json('ps').get('models',[])
            for item in running:
                name=item.get('name',item.get('model',''))
                if name:unload_model(name,local_json)
            print('Unloaded completed language-model phases before the image batch.',flush=True)
        else:
            print('GPU headroom permits keeping existing models resident.',flush=True)
        self.phase = ('generation',model)

    def acquire(self, model, cache, torch, loader):
        self.before_generation(model)
        key = (model, str(cache))
        if self.pipe is not None and self.key == key:
            print('Reusing the loaded image model for the next illustration.', flush=True)
            return self.pipe, self.guidance
        self.release()
        self.torch = torch
        torch.cuda.reset_peak_memory_stats()
        self.pipe, self.guidance = (loader(model, cache, torch, offload=True)
                                    if self.offload else loader(model, cache, torch))
        self.key = key
        self.phase = ('generation',model)
        self.publish(force=True)
        return self.pipe, self.guidance

    def generation_done(self):
        if self.torch is not None:
            self.peak = max(self.peak, self.torch.cuda.max_memory_reserved())
            self.publish(force=True)

    def before_review(self, model):
        self.vision_models.add(model)
        if self.phase == ('review',model):return
        self.phase = ('review',model)
        if self.pipe is None:return
        from models.ollama.service import local_json
        from models.ollama.catalog import budget_for_model, normalize
        self.torch.cuda.empty_cache()
        free, _ = gpu_memory.dedicated_memory(self.torch)
        running=local_json('ps').get('models',[])
        resident=next((m for m in running if normalize(m.get('name',m.get('model','')))==normalize(model)),None)
        from models.ollama.gpu import fully_on_gpu
        required=.5*GIB if resident and fully_on_gpu(resident) else budget_for_model(model,local_json('tags').get('models',[]))+.5*GIB
        if free>=required:
            print('Image and validation models fit together; retaining image weights.',flush=True)
        else:
            self.release()
            print('Image batch complete; released image weights before the validation batch.',flush=True)

    def unload_vision(self):
        from models.ollama.gpu import unload_model
        for name in sorted(self.vision_models):unload_model(name)

    def run_generation(self, generate, manifest, cache):
        retry = False
        try:
            return generate(manifest,cache)
        except RuntimeError as exc:
            if 'out of memory' not in str(exc).lower():
                raise
            print(f'Image generation ran out of GPU memory: {exc}', flush=True)
            retry = True
        if retry:
            self.release()
            self.unload_vision()
            self.offload = True
            print('Cleared failed allocations; retrying once with inactive image components offloaded to RAM. Inference remains on CUDA.',flush=True)
            return generate(manifest,cache)

    def review_payload(self,payload):
        """After an OOM, bound review inputs for the rest of this session."""
        import copy
        query=copy.deepcopy(payload)
        if self.review_limits is None:return query
        import base64,io
        from PIL import Image
        options=query.setdefault('options',{})
        expanded=options.get('num_ctx',8192)>=16384
        options['num_ctx']=min(options.get('num_ctx',8192),16384 if expanded else 4096)
        options['num_predict']=min(options.get('num_predict',2200),8192 if expanded else 2048)
        for message in query.get('messages',[]):
            images=[]
            for encoded in message.get('images',[]):
                with Image.open(io.BytesIO(base64.b64decode(encoded))) as source:
                    if max(source.size)<=1024:
                        images.append(encoded);continue
                    source=source.convert('RGB');source.thumbnail((1024,1024))
                    output=io.BytesIO();source.save(output,format='JPEG',quality=94)
                    images.append(base64.b64encode(output.getvalue()).decode())
            if 'images' in message:message['images']=images
        return query

    def review_request(self, request, payload):
        import time,urllib.error
        from models.ollama.gpu import GPUCapacityError, unload_model
        from models.ollama.service import http_error_detail
        for attempt in range(2):
            query=self.review_payload(payload)
            memory_failure=False
            try:
                return request('chat',query,timeout=600)
            except GPUCapacityError:
                if attempt or self.pipe is None:raise
            except urllib.error.HTTPError as exc:
                detail=http_error_detail(exc)
                memory_failure=any(term in detail.lower() for term in
                    ('out of memory','not enough memory','insufficient memory','unable to allocate'))
                if not memory_failure:raise
                if attempt:
                    from models.vision.response import ReviewUnavailable
                    raise ReviewUnavailable('Vision validation still ran out of GPU memory after recovery. '
                        'Generated images and completed reviews are saved; resume image review to retry. '
                        +detail[:1200]) from exc
            self.release()
            if memory_failure:
                self.review_limits=(1024,4096,2048)
                unload_model(payload['model'])
                print('Vision GPU memory exhausted; resetting the same model and retrying this image once '
                      'at 1024px, 4096 context and 2048 output tokens. Completed reviews are retained.',flush=True)
                time.sleep(.5)
            else:
                print('Vision needs more VRAM; retrying once with image weights released.',flush=True)
