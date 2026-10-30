"""Prepare every requested replacement prompt before loading an image pipeline."""
import copy
import json
from collections import defaultdict


def regenerate_prompts(worker,job,config,items):
    from ollama_gpu import gpu_chat,unload_model
    from gpu_models import resolve_prompt_model
    from ollama_service import local_json
    from subject_director import request_subjects
    from verse_backgrounds import DIRECTOR_PROMPT
    if job.get('artwork_mode')=='matte':
        from greenscreen import DIRECTOR_PROMPT
    from kinetic_illustrations import image_prompt,subject_kind
    batches=defaultdict(list)
    for item in items:
        model=item.get('model') or config.get('ai_model','auto')
        model=resolve_prompt_model(local_json,model)
        batches[model].append(item)
    replacements={}
    for model,batch in batches.items():
        worker.emit('subjects',0,message=f'Preparing {len(batch)} replacement prompt(s) with {model}')
        system=(DIRECTOR_PROMPT if job.get('artwork_mode') in ('verse','matte') else
            'Interpret each lyric group into one fresh English visual scene for an illustrator. '
            'The lyrics determine subject matter, including Tagalog. Describe only visible forms, '
            'action, materials, lighting and mood. Choose subjects that best express the lyrics, '
            'including objects, portraits, people, gestures or small scenes; vary compositions naturally. '
            'Follow the assigned composition and orientation. '
            'No text, captions, logos or copied lyric lines. Return only JSON with a subjects array in input order. ')
        system+=' Invent a new interpretation rather than repeating the previous scene. Apply optional user guidance.'
        payload=dict(model=model,stream=False,think=False,keep_alive=-1,options=dict(num_ctx=8192),
            format=dict(type='object',properties=dict(subjects=dict(type='array',items=dict(type='string'))),required=['subjects']),
            messages=[dict(role='system',content=system),dict(role='user',content=json.dumps([
                dict(lyrics=job['groups'][i['index']],layout=job['layouts'][i['index']].get('prompt',''),
                     previous_scene=job.get('visual_descriptions',job['prompts'])[i['index']],guidance=i.get('prompt','')) for i in batch]))])
        meanings=[]
        indices=[i['index'] for i in batch]
        groups=[job['groups'][i] for i in indices]
        audit_groups=groups
        try:
            if job.get('artwork_mode') in ('verse','matte'):
                from verse_backgrounds import lyric_meanings
                meanings=lyric_meanings(gpu_chat,model,groups)
                inputs=json.loads(payload['messages'][1]['content'])
                for entry,meaning in zip(inputs,meanings):entry['lyric_meaning']=meaning
                payload['messages'][1]['content']=json.dumps(inputs)
                audit_groups=[f'Original lyric group: {group}\nEnglish meaning: {meaning}'
                              for group,meaning in zip(groups,meanings)]
            subjects=request_subjects(gpu_chat,payload)
            technique=job.get('style_prompt',config.get('style_prompt',''))
            prompts=[image_prompt(subject,job['layouts'][index],technique,bool(job.get('reference_paths'))) for index,subject in zip(indices,subjects)]
            from prompt_audit import audit_prompts
            prompts=audit_prompts(gpu_chat,model,audit_groups,subjects,prompts,[job['layouts'][i] for i in indices],job.get('artwork_mode','cutout'))
        finally:unload_model(model)
        for item,subject,prompt in zip(batch,subjects,prompts):
            index=item['index'];updated=copy.deepcopy(job)
            updated.setdefault('visual_descriptions',list(job['prompts']))[index]=subject
            updated['prompts'][index]=prompt
            if 'plate_prompts' in updated:
                from greenscreen import plate_prompt
                updated['plate_prompts'][index]=plate_prompt(subject,job['layouts'][index],job.get('style_prompt',config.get('style_prompt','')))
            if meanings:
                updated.setdefault('lyric_meanings',['']*len(job['groups']))[index]=meanings[indices.index(index)]
            updated['prompt_audit']=dict(version=1,model=model)
            if 'reference_modes' in updated:
                updated['reference_modes'][index]='technique_prompt_only' if job.get('artwork_mode') in ('verse','matte') or subject_kind(subject)=='object' else 'image_conditioning'
            replacements[index]=updated
        worker.emit('subjects',1,message=f'{len(batch)} replacement prompts ready; prompting model released')
    return replacements
