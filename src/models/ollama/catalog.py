"""Ollama text and vision model catalog, capability checks and model choice."""
from models.gpu.devices import GIB


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

def normalize(name):
    return name if ':' in name else name+':latest'

def supports_prompting(name, metadata):
    """Keep VL specialists for scoring; general Qwen 3.5+ can also write text."""
    capabilities=metadata.get('capabilities',[])
    if 'completion' not in capabilities:return False
    if 'vision' not in capabilities:return True
    details=metadata.get('details') or {}
    family=details.get('family') or metadata.get('model_info',{}).get('general.architecture')
    return family=='qwen35' and '-vl' not in name.lower()

def model_choices(local_json,review=True):
    from models.gpu.presets import PRESETS, gpu_catalog
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

def validate_selected_models(prompt,vision,review=True):
    from models.ollama.service import local_json
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


def budget_for_model(name, installed=()):
    known=next((m['vram_gib']*GIB for m in PROMPT_MODELS+VISION_MODELS if normalize(m['id'])==normalize(name)),0)
    item=next((m for m in installed if normalize(m.get('name',m.get('model','')))==normalize(name)),None)
    if not item:
        if known:return int(known)
        raise ValueError('Model is not installed: '+name+'. Install it with: ollama pull '+name)
    return int(max(known,item.get('size',0)*1.2+1.25*GIB))
