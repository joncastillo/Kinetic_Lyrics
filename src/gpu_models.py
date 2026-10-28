"""GPU-only model catalog, capacity detection and phase-sized recommendations.

VRAM figures are conservative planning budgets, not guarantees: context length,
image dimensions and the driver also affect peak allocation. Runtime admission
and residency checks remain authoritative.
"""
import csv
import io
import subprocess

GIB = 2**30
QWEN_IMAGE = 'Qwen/Qwen-Image-2512'
SMALL_IMAGE = 'Tongyi-MAI/Z-Image-Turbo'
PROMPT_MODELS = [
    dict(id='qwen3:4b', name='Qwen3 4B', vram_gib=4.0),
    dict(id='qwen3:8b', name='Qwen3 8B', vram_gib=6.0),
    dict(id='qwen3:14b', name='Qwen3 14B', vram_gib=11.0),
    dict(id='qwen3:30b', name='Qwen3 30B A3B', vram_gib=21.0),
    dict(id='qwen3:32b', name='Qwen3 32B', vram_gib=24.0),
]
VISION_MODELS = [
    dict(id='qwen3-vl:4b', name='Qwen3 VL 4B', vram_gib=5.5),
    dict(id='qwen3-vl:8b', name='Qwen3 VL 8B', vram_gib=9.0),
    dict(id='qwen3-vl:30b', name='Qwen3 VL 30B A3B', vram_gib=24.0),
]
PRESETS = [
    dict(vram_gib=8, image_model=SMALL_IMAGE, ai_model='qwen3:4b', vision_model='qwen3-vl:4b'),
    dict(vram_gib=16, image_model=SMALL_IMAGE, ai_model='qwen3:14b', vision_model='qwen3-vl:8b'),
    dict(vram_gib=24, image_model=QWEN_IMAGE, ai_model='qwen3:30b', vision_model='qwen3-vl:8b'),
    dict(vram_gib=32, image_model=QWEN_IMAGE, ai_model='qwen3:32b', vision_model='qwen3-vl:30b'),
]


def normalize(name):
    return name if ':' in name else name+':latest'


def detect_gpus():
    """Read capacity only; never load or evict a model here."""
    try:
        result=subprocess.run(['nvidia-smi','--query-gpu=index,name,uuid,memory.total,memory.free',
                               '--format=csv,noheader,nounits'],capture_output=True,text=True,
                              encoding='utf-8',errors='replace',check=True,timeout=8,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return [dict(index=int(row[0]),name=row[1].strip(),uuid=row[2].strip(),
                     total_bytes=int(float(row[3])*2**20),free_bytes=int(float(row[4])*2**20))
                for row in csv.reader(io.StringIO(result.stdout)) if len(row)==5]
    except (OSError,ValueError,subprocess.SubprocessError):
        return []


def budget_for_model(name, installed=()):
    known=next((m['vram_gib']*GIB for m in PROMPT_MODELS+VISION_MODELS if normalize(m['id'])==normalize(name)),0)
    item=next((m for m in installed if normalize(m.get('name',m.get('model','')))==normalize(name)),None)
    if not item:
        if known:return int(known)
        raise ValueError('Model is not installed: '+name+'. Install it with: ollama pull '+name)
    return int(max(known,item.get('size',0)*1.2+1.25*GIB))


def gpu_catalog(installed=(), running=(), review=True):
    """Return hardware and explicit presets without modifying model residency."""
    from image_models import model_spec
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
            from image_models import MODELS
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


def supports_prompting(name, metadata):
    """Keep VL specialists for scoring; general Qwen 3.5+ can also write text."""
    capabilities=metadata.get('capabilities',[])
    if 'completion' not in capabilities:return False
    if 'vision' not in capabilities:return True
    details=metadata.get('details') or {}
    family=details.get('family') or metadata.get('model_info',{}).get('general.architecture')
    return family=='qwen35' and '-vl' not in name.lower()


def model_choices(local_json,review=True):
    """Discover installed non-coding models; never choose a coder as a default."""
    installed=local_json('tags').get('models',[])
    running=local_json('ps').get('models',[])
    catalog=gpu_catalog(installed,running,review=review)
    text=[];vision=[]
    for item in installed:
        name=item['name']
        if any(part in name.lower() for part in ('coder','code-','codellama','codestral','asr','embed','whisper')):continue
        metadata=local_json('show',{'model':name},timeout=30)
        caps=metadata.get('capabilities',[])
        if 'vision' in caps:vision.append(name)
        if supports_prompting(name,metadata):text.append(name)
    capacity=(catalog['gpu']['total_bytes']/GIB if catalog['gpu'] else 0)
    preset=next((p for p in reversed(PRESETS) if p['vram_gib']<=capacity+.6),PRESETS[0])
    recommended=dict(catalog['recommendation'] or preset)
    installed_names={normalize(m['name']) for m in installed}
    if catalog['gpu']:
        budget=catalog['gpu']['prompt_usable_bytes']
        alternatives=[m for m in installed if m['name'] in text and budget_for_model(m['name'],installed)<=budget]
        if alternatives:
            recommended['ai_model']=max(alternatives,key=lambda m:m.get('size',0))['name']
            if catalog['recommendation']:
                catalog['recommendation']=dict(catalog['recommendation'],ai_model=recommended['ai_model'])
                catalog['recommendation']['missing']=[name for name in ([recommended['ai_model']]+([recommended['vision_model']] if review else [])) if normalize(name) not in installed_names]
    return dict(catalog,models=vision,vision_models=vision,prompt_models=text,
                default_model=recommended['vision_model'],default_prompt_model=recommended['ai_model'])


def pick_prompt_model(local_json):
    catalog=model_choices(local_json)
    recommended=catalog['default_prompt_model']
    installed={normalize(name) for name in catalog['prompt_models']}
    models=local_json('tags').get('models',[])
    gpu=catalog['gpu'];budget=gpu['prompt_usable_bytes'] if gpu else 0
    if (normalize(recommended) not in installed
            or budget_for_model(recommended,models)>budget):
        raise ValueError('No installed text-only prompting model fits the available GPU memory. '
                         'Free GPU memory or install/select a smaller general-purpose text model. '
                         'Vision models are reserved for image scoring.')
    return recommended


def resolve_prompt_model(local_json, selected):
    """Resolve saved VL selections to a text model before any prompting."""
    if selected in ('', 'auto', None):
        selected = pick_prompt_model(local_json)
    metadata = local_json('show', {'model': selected}, timeout=30)
    capabilities = metadata.get('capabilities', [])
    if 'vision' not in capabilities or supports_prompting(selected, metadata):
        return selected
    alternative = pick_prompt_model(local_json)
    print(f'Text prompting: {selected} is reserved for image scoring; '
          f'using installed text model {alternative} for direction, prompts and revisions.', flush=True)
    return alternative


def image_dimensions(width,height,total_gib):
    """Bound activation memory on smaller cards; preserve aspect ratio."""
    ceiling=512*512 if total_gib<12 else 1024*1024 if total_gib<20 else 1536*1024
    if width*height<=ceiling:return width,height
    scale=(ceiling/(width*height))**.5
    return max(64,int(width*scale)//64*64),max(64,int(height*scale)//64*64)


def validate_selected_models(prompt,vision,review=True):
    from ollama_service import local_json
    if prompt in ('','auto'):prompt=pick_prompt_model(local_json)
    selected=[prompt]+([vision] if review and vision else [])
    installed={normalize(m['name']) for m in local_json('tags').get('models',[])}
    missing=[name for name in selected if normalize(name) not in installed]
    if missing:raise ValueError('Selected models are not installed: '+', '.join(missing)+'. Wait for Model downloads in the left panel before starting generation.')
    for name in selected:
        caps=local_json('show',{'model':name},timeout=30).get('capabilities',[])
        if name==prompt and 'completion' not in caps:raise ValueError(name+' cannot generate illustration prompts.')
        if review and name==vision and 'vision' not in caps:raise ValueError(name+' cannot validate images. Choose a vision model.')
    return resolve_prompt_model(local_json,prompt)
