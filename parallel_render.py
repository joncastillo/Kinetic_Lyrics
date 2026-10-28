"""Bounded, ordered CPU frame batches; one encoder keeps audio/video continuous."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import importlib
import multiprocessing
import os
from types import SimpleNamespace

_COMPOSITOR=None
IN_FLIGHT=2


def initialize(module,data,plan,duration,options):
    global _COMPOSITOR
    _COMPOSITOR=importlib.import_module(module).render_compositor(data,plan,duration,SimpleNamespace(**options))


def render_batch(task):
    first,count,start,fps=task
    return first,count,b''.join(_COMPOSITOR.frame(start+i/fps).tobytes() for i in range(first,first+count))


WORKER_MEMORY=.35*2**30
REALTIME_WORKER_MEMORY=.6*2**30
MAX_AUTO_WORKERS=16
MEMORY_RESERVE=3*2**30


def hardware():
    """Physical cores and currently available RAM, falling back to logical CPUs when psutil is absent."""
    logical=os.cpu_count() or 1
    try:
        import psutil
        return psutil.cpu_count(logical=False) or logical,psutil.virtual_memory().available
    except ImportError:
        return logical,None


def worker_count(args,count):
    selected=int(getattr(args,'render_workers',0))
    limit=os.cpu_count() or 1
    if not 0<=selected<=limit:raise ValueError(f'Render workers must be between 0 (auto) and {limit}')
    if selected:return selected
    if count<args.fps*10:return 1
    cores,available=hardware()
    scale=max(1.,args.width*args.height/(1280*720))
    budget=REALTIME_WORKER_MEMORY if getattr(args,'reading_flow','preview')=='realtime' else WORKER_MEMORY
    by_memory=int((available-MEMORY_RESERVE)//(budget*scale)) if available else cores
    return max(1,min(cores-1,MAX_AUTO_WORKERS,by_memory))


def frame_batches(module,data,plan,duration,args,compositor,start,count,workers):
    batch=max(1,min(6,round(16*2**20/(args.width*args.height*3))))
    tasks=iter((first,min(batch,count-first),start,args.fps) for first in range(0,count,batch))
    if workers<=1:
        for first,length,_,fps in tasks:
            yield first,length,b''.join(compositor.frame(start+i/fps).tobytes() for i in range(first,first+length))
        return
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),
            initializer=initialize,initargs=(module,data,plan,duration,vars(args))) as pool:
        pending=deque()
        for _ in range(workers*IN_FLIGHT):
            task=next(tasks,None)
            if task is not None:pending.append(pool.submit(render_batch,task))
        try:
            while pending:
                result=pending.popleft().result()
                yield result
                task=next(tasks,None)
                if task is not None:pending.append(pool.submit(render_batch,task))
        finally:
            for future in pending:future.cancel()
