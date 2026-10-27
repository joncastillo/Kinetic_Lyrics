"""Dedicated VRAM bounds, including Windows' per-process CUDA memory reporting."""
import os
from gpu_models import detect_gpus


def dedicated_memory(torch):
    cuda_free,cuda_total=torch.cuda.mem_get_info()
    index=torch.cuda.current_device()
    visible=os.environ.get('CUDA_VISIBLE_DEVICES','').split(',')
    identity=visible[index].strip() if visible!=[''] and index<len(visible) else str(index)
    cards=detect_gpus()
    card=next((g for g in cards if str(g['index'])==identity or g.get('uuid')==identity),None)
    if card is None:
        raise ValueError('Cannot read dedicated GPU memory. GPU-only model loading was stopped; check nvidia-smi.')
    return min(cuda_free,card['free_bytes']),min(cuda_total,card['total_bytes'])
