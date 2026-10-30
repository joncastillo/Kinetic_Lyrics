"""Recommended model combinations for the detected GPU."""
from models.gpu.devices import GIB, detect_gpus
from models.ollama.catalog import PROMPT_MODELS, VISION_MODELS, budget_for_model, normalize


QWEN_IMAGE = 'Qwen/Qwen-Image-2512'

SMALL_IMAGE = 'Tongyi-MAI/Z-Image-Turbo'

PRESETS = [
    dict(vram_gib=8, image_model=SMALL_IMAGE, ai_model='qwen3:4b', vision_model='qwen3-vl:4b'),
    dict(vram_gib=16, image_model=SMALL_IMAGE, ai_model='qwen3:14b', vision_model='qwen3-vl:8b'),
    dict(vram_gib=24, image_model=QWEN_IMAGE, ai_model='qwen3:30b', vision_model='qwen3-vl:8b'),
    dict(vram_gib=32, image_model=QWEN_IMAGE, ai_model='qwen3:32b', vision_model='qwen3-vl:30b'),
]


def gpu_catalog(installed=(), running=(), review=True):
    """Return hardware and explicit presets without modifying model residency."""
    from models.image.catalog import model_spec
    gpus=detect_gpus()
    for gpu in gpus:
        reclaimable=0
        for item in running:
            identities=item.get('gpu_ids') or item.get('gpu_uuids') or []
            if len(gpus)==1 or gpu['uuid'] in identities:
                reclaimable+=int(item.get('size_vram',0))
        gpu['reclaimable_bytes']=min(reclaimable,max(0,gpu['total_bytes']-gpu['free_bytes']))
        gpu['usable_bytes']=max(0,min(gpu['total_bytes']-.5*GIB,gpu['free_bytes']+gpu['reclaimable_bytes']-.5*GIB))
        gpu['prompt_usable_bytes']=max(0,min(gpu['total_bytes'],gpu['free_bytes']+gpu['reclaimable_bytes']))
    gpu=max(gpus,key=lambda g:g['usable_bytes'],default=None)
    installed_names={normalize(m.get('name',m.get('model',''))) for m in installed}
    prompts=[dict(m,installed=normalize(m['id']) in installed_names) for m in PROMPT_MODELS]
    visions=[dict(m,installed=normalize(m['id']) in installed_names) for m in VISION_MODELS]
    recommendation=None
    if gpu:
        budget=gpu['usable_bytes']/GIB
        capacity=gpu['total_bytes']/GIB
        candidates=[p for p in PRESETS if p['vram_gib']<=capacity+.6
                    and model_spec(p['image_model'])['vram_gib']<=budget
                    and (not review or budget_for_model(p['vision_model'],installed)/GIB<=budget)]
        if not review:
            from models.image.catalog import MODELS
            fitting=[m for m in MODELS if m['vram_gib']<=budget]
            if fitting:
                base=next((p for p in reversed(PRESETS) if p['vram_gib']<=capacity+.6),PRESETS[0])
                candidates=[dict(base,image_model=max(fitting,key=lambda m:m['vram_gib'])['id'])]
        if candidates:
            recommendation=dict(candidates[-1])
            prompt=next((m for m in reversed(PROMPT_MODELS) if budget_for_model(m['id'],installed)<=gpu['prompt_usable_bytes']),None)
            if prompt:recommendation['ai_model']=prompt['id']
            combined=model_spec(recommendation['image_model'])['vram_gib']+(budget_for_model(recommendation['vision_model'],installed)/GIB if review else 0)
            recommendation.update(gpu_index=gpu['index'],gpu_name=gpu['name'],available_gib=round(budget,2),
                                  prompt_available_gib=round(gpu['prompt_usable_bytes']/GIB,2),
                                  co_resident=review and combined<=budget,validation_enabled=review,
                                  missing=[name for name in ([recommendation['ai_model']]+([recommendation['vision_model']] if review else [])) if normalize(name) not in installed_names])
    return dict(gpus=gpus,gpu=gpu,presets=PRESETS,prompt_choices=prompts,vision_choices=visions,recommendation=recommendation,
                message='' if recommendation else 'No supported GPU-only combination fits the VRAM currently available. Free GPU memory and try Best again.')
