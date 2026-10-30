"""Prepare every requested replacement prompt before loading an image pipeline."""
import copy
import json
from collections import defaultdict


def regenerate_prompts(worker,job,config,items):
    from ollama_gpu import gpu_chat,unload_model
    from gpu_models import resolve_prompt_model
    from ollama_service import local_json
    from subject_director import request_subjects,lengthen_short_subjects
    from verse_backgrounds import DIRECTOR_PROMPT, LANGUAGE_RULE, PEOPLE_RULE
    from kinetic_illustrations import image_prompt,subject_kind
    batches=defaultdict(list)
    for item in items:
        model=item.get('model') or config.get('ai_model','auto')
        model=resolve_prompt_model(local_json,model)
        batches[model].append(item)
    replacements={}
    for model,batch in batches.items():
        worker.emit('subjects',0,message=f'Preparing {len(batch)} replacement prompt(s) with {model}')
        system=(DIRECTOR_PROMPT if job.get('artwork_mode')=='verse' else LANGUAGE_RULE+PEOPLE_RULE+
            'Interpret each lyric group into one fresh English visual scene for an illustrator. '
            'The lyrics determine subject matter, including Tagalog. Describe only visible forms, '
            'action, materials, lighting and mood in a detailed 120 to 180 word description. Choose subjects that best express the lyrics, '
            'including objects, places, weather, nature or small scenes, and people only when the lyric shows someone; vary compositions naturally. '
            'Follow the assigned composition and orientation. '
            'No text, captions, logos or copied lyric lines. Return only JSON with a subjects array in input order. ')
        system+=' Invent a new interpretation rather than repeating the previous scene. Apply optional user guidance and additional image instructions when they fit the lyrics.'
        payload=dict(model=model,stream=False,think=False,keep_alive=-1,options=dict(num_ctx=8192),
            format=dict(type='object',properties=dict(subjects=dict(type='array',items=dict(type='string'))),required=['subjects']),
            messages=[dict(role='system',content=system),dict(role='user',content=json.dumps([
                dict(lyrics=job['groups'][i['index']],layout=job['layouts'][i['index']].get('prompt',''),
                     previous_scene=job.get('visual_descriptions',job['prompts'])[i['index']],guidance=i.get('prompt',''),
                     image_instructions=job.get('image_instructions',config.get('image_instructions',''))) for i in batch]))])
        meanings=[]
        indices=[i['index'] for i in batch]
        groups=[job['groups'][i] for i in indices]
        audit_groups=groups
        try:
            from song_gist import song_gist,attach_gist
            gist=job.get('song_gist') or song_gist(gpu_chat,model,[line for group in job['groups'] for line in group.split(' / ')],
                                                   job.get('image_instructions',config.get('image_instructions','')))
            if job.get('artwork_mode')=='verse':
                from verse_backgrounds import lyric_meanings
                guidance='\n'.join(str(item.get('prompt','')) for item in batch)
                meanings=lyric_meanings(gpu_chat,model,groups,
                                        image_instructions=(job.get('image_instructions',config.get('image_instructions',''))
                                                            +'\n'+guidance).strip(),song_gist=gist)
                inputs=json.loads(payload['messages'][1]['content'])
                for entry,meaning in zip(inputs,meanings):entry['lyric_meaning']=meaning
                payload['messages'][1]['content']=json.dumps(inputs)
                audit_groups=[f'Original lyric group: {group}\nEnglish meaning: {meaning}'
                              for group,meaning in zip(groups,meanings)]
            attach_gist(payload,gist)
            audit_groups=[f'Song message: {gist}\n{group}' for group in audit_groups]
            subjects=request_subjects(gpu_chat,payload,max_words=550 if job.get('artwork_mode')=='verse' else 180)
            subjects=lengthen_short_subjects(gpu_chat,payload,subjects,400 if job.get('artwork_mode')=='verse' else 120,
                                             max_words=550 if job.get('artwork_mode')=='verse' else 180)
            technique=job.get('style_prompt',config.get('style_prompt',''))
            extra=job.get('image_instructions',config.get('image_instructions',''))
            prompts=[image_prompt(subject,job['layouts'][index],technique,bool(job.get('reference_paths')))
                     + (' Additional image direction: '+extra if extra else '') for index,subject in zip(indices,subjects)]
            from prompt_audit import audit_prompts
            prompts=audit_prompts(gpu_chat,model,audit_groups,subjects,prompts,[job['layouts'][i] for i in indices],job.get('artwork_mode','cutout'))
            from prompt_fit import fit_prompts
            prompts=fit_prompts(gpu_chat,model,job['model'],prompts,technique)
        finally:unload_model(model)
        for item,subject,prompt in zip(batch,subjects,prompts):
            index=item['index'];updated=copy.deepcopy(job)
            updated.setdefault('visual_descriptions',list(job['prompts']))[index]=subject
            updated['prompts'][index]=prompt
            if meanings:
                updated.setdefault('lyric_meanings',['']*len(job['groups']))[index]=meanings[indices.index(index)]
            updated['prompt_audit']=dict(version=1,model=model)
            updated['song_gist']=gist
            if 'reference_modes' in updated:
                updated['reference_modes'][index]='technique_prompt_only' if job.get('artwork_mode')=='verse' or subject_kind(subject)=='object' else 'image_conditioning'
            replacements[index]=updated
        worker.emit('subjects',1,message=f'{len(batch)} replacement prompts ready; prompting model released')
    return replacements
