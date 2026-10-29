"""Condense complete image prompts that would overflow the image model's text encoder."""
import json

# Words that fit each pipeline's prompt token limit (about 1.35 tokens per English word):
# Qwen Image reads 1024 tokens, Z-Image and the FLUX models 512.
WORD_LIMITS = dict(QwenImagePipeline=750, ZImagePipeline=350)
FLUX_WORDS = 250


def word_limit(image_model):
    from image_models import model_spec
    pipeline = model_spec(image_model)['pipeline']
    return FLUX_WORDS if pipeline.startswith('Flux') else WORD_LIMITS.get(pipeline)


def fit_prompts(request, model, image_model, prompts):
    """Summarize each prompt longer than the image model can read; prompts that fit are unchanged."""
    limit = word_limit(image_model)
    long = [i for i, prompt in enumerate(prompts) if limit and len(prompt.split()) > limit+30]
    if not long:
        return prompts
    from subject_director import request_subjects
    from kinetic_progress import emit
    from llm_trace import trace_stage
    emit('subjects', .9, message=f'Condensing {len(long)} image prompt(s) to about {limit} words for the image model')
    system = (
        f'Condense each supplied image-generation prompt to about {limit} words for an image model that ignores '
        'text beyond its limit. Rewrite it as one complete standalone prompt, not a description of the prompt. '
        'Keep the focal subject, action, relationships and setting first, then the composition, orientation, '
        'placement and quiet lyric area, then the art style, materials, light and atmosphere. '
        'Keep every prohibition on lettering, captions, logos, frames and borders, and any instruction about '
        'backgrounds or cutouts. Remove repetition and general advice before removing scene-specific details. '
        'Do not add new subjects, objects or styles. Return only JSON with a subjects array in input order.')
    payload = dict(model=model, stream=False, think=False, keep_alive=-1, options=dict(num_ctx=8192),
        format=dict(type='object', properties=dict(subjects=dict(type='array', items=dict(type='string'))),
                    required=['subjects']),
        messages=[dict(role='system', content=system),
                  dict(role='user', content=json.dumps([dict(image_prompt=prompts[i]) for i in long]))])
    with trace_stage('Condense image prompts to the image model limit'):
        condensed = request_subjects(request, payload, batch_size=2, max_words=limit+50, avoid_repeats=False)
    fitted = list(prompts)
    for i, prompt in zip(long, condensed):
        fitted[i] = prompt
    return fitted
