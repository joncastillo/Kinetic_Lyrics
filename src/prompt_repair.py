"""Create fresh image prompts from lyrics after a scored visual rejection."""
import copy
import json


def revise_repair_prompts(worker, job, config, items):
    from gpu_models import resolve_prompt_model
    from llm_trace import trace_stage
    from ollama_gpu import gpu_chat, unload_model
    from ollama_service import local_json
    from subject_director import request_subjects

    model = resolve_prompt_model(local_json, config.get('ai_model', 'auto'))
    worker.emit('subjects', 0, message=f'Generating {len(items)} fresh image prompt(s) from the lyrics with {model}')
    from verse_backgrounds import LANGUAGE_RULE
    system = LANGUAGE_RULE+(
        'Write an entirely NEW image-generation prompt from each supplied lyric group. '
        'Reinterpret the original lyrics from scratch; do not revise, append to, paraphrase or reuse the failed image prompt. '
        'The old prompt and its invented subject description are deliberately not supplied. '
        'Use only the original lyrics, same-section context, user art style/mood and reserved layout to decide the scene. '
        'Use the visual failure assessment only to avoid the rejected result, not to preserve its faulty interpretation. '
        'Choose a fresh, concrete, physically believable scene with coherent whole objects and relationships. '
        'Preserve what the lyrics actually say, without carrying forward invented objects or contradictory construction. '
        'For a streetlamp, describe one recognizable complete lamp with its light at the top; no accidental extra poles or mismatched tiny lamps. '
        'Check intended object count, functional construction, consistent scale at similar depth, gravity, attachments and perspective. '
        'Respect the user art style and quiet lyric area. Do not add unrelated figures or reuse rejected composition details. '
        'No lettering, words, captions, logos, frames or watermarks. '
        'Return one complete standalone image prompt per input in a JSON subjects array, in input order. '
        'No analysis or repair commentary.')
    payload = dict(model=model, stream=False, think=False, keep_alive=-1,
        options=dict(num_ctx=8192),
        format=dict(type='object', properties=dict(subjects=dict(type='array', items=dict(type='string'))),
                    required=['subjects']),
        messages=[dict(role='system', content=system), dict(role='user', content=json.dumps([
            dict(lyrics=job['groups'][item['index']],
                 art_style=config.get('style_prompt',''),mood=config.get('theme',''),
                 image_instructions=job.get('image_instructions',config.get('image_instructions','')),
                 layout=job.get('layouts', [{} for _ in job['prompts']])[item['index']],
                 assessment={key:item['review'][key] for key in
                             ('score', 'summary', 'issues', 'hand_checks', 'uncertain') if key in item['review']})
            for item in items]))])
    try:
        with trace_stage('Repair / fresh prompt from lyrics'):
            prompts = request_subjects(gpu_chat, payload, batch_size=2, max_words=220)
    finally:
        try:
            unload_model(model)
        except (OSError, ValueError) as exc:
            print(f'Warning: repair prompt model cleanup: {exc}', flush=True)
    planned = {}
    for item, prompt in zip(items, prompts):
        index = item['index']
        updated = copy.deepcopy(job)
        updated['prompts'][index] = prompt
        if 'visual_descriptions' in updated:
            updated['visual_descriptions'][index]=prompt
        updated['prompt_revision'] = dict(model=model,reason='fresh_from_lyrics_after_rejection',strategy='fresh_from_lyrics',score=item['review'].get('score'))
        planned[index] = updated
    return planned
