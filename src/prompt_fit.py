"""Rewrite each complete image prompt to the length the image model's text encoder can read."""
import json

# Prompt token limits per pipeline, and a word budget that leaves room for retry wording.
TOKEN_LIMITS = dict(QwenImagePipeline=1024, ZImagePipeline=512)
WORD_BUDGETS = dict(QwenImagePipeline=700, ZImagePipeline=350)
FLUX_TOKENS, FLUX_WORDS = 512, 250
TOKENS_PER_WORD = 1.35


def budget(image_model):
    """(words, tokens) the image model reads, or None when it has no known limit."""
    from image_models import model_spec
    pipeline = model_spec(image_model)['pipeline']
    if pipeline.startswith('Flux'):
        return FLUX_WORDS, FLUX_TOKENS
    return (WORD_BUDGETS[pipeline], TOKEN_LIMITS[pipeline]) if pipeline in WORD_BUDGETS else None


def estimate(prompt):
    words = len(prompt.split())
    return words, round(words*TOKENS_PER_WORD)


def fit_prompts(request, model, image_model, prompts, style=''):
    """Write every prompt to the model's budget, with the art style first and word for word.

    Long prompts are condensed and short ones enriched with detail of the same scene. The style is never handed to
    the rewrite, so it cannot be reworded or dropped; its words are reserved from the budget before the scene.
    """
    limit = budget(image_model)
    if not limit or not prompts:
        return prompts
    words, tokens = limit
    style = ' '.join(style.split()).rstrip('.')
    prefix = f'Art style, the top priority for how everything is rendered: {style}. ' if style else ''
    scene_words = max(100, words-estimate(prefix)[0])
    from subject_director import request_subjects
    from kinetic_progress import emit
    from llm_trace import trace_stage
    emit('subjects', .9, message=f'Fitting {len(prompts)} image prompt(s) to about {words} words (~{tokens} tokens)')
    system = (
        f'The image model reads at most {tokens} tokens, about {words} English words; anything beyond is ignored. '
        + (f'The art style below is placed before your text automatically, word for word, and takes priority over '
           f'everything else. Leave sentences about art style, technique, brushwork and mood out of your text, and '
           f'never describe a medium, style, palette or mood that conflicts with it. Art style: {style}. '
           if style else '')
        + f'Rewrite each supplied image-generation prompt as one complete standalone prompt of about {scene_words} words. '
        'Each input states its current estimated length. If it is longer, condense it: remove repetition and general '
        'advice before scene-specific details. If it is shorter, keep everything and spend the extra words on concrete, '
        'visible detail of the same scene: spatial layout, materials, textures, light direction, colour and atmosphere. '
        'Never add new subjects, people, objects, events or styles, and never contradict the prompt. '
        'Order: the focal subject, action, relationships and setting first; then composition, orientation, placement '
        'and the quiet lyric area; then materials, light and atmosphere. '
        'Keep each person’s stated gender, age and clothing. Keep every prohibition on lettering, captions, logos, frames and borders, and any instruction about '
        'backgrounds or cutouts. Return only JSON with a subjects array in input order.')

    def rewrite(indices, current, note=''):
        payload = dict(model=model, stream=False, think=False, keep_alive=-1, options=dict(num_ctx=8192),
            format=dict(type='object', properties=dict(subjects=dict(type='array', items=dict(type='string'))),
                        required=['subjects']),
            messages=[dict(role='system', content=system+note), dict(role='user', content=json.dumps([
                dict(image_prompt=current[i], estimated_words=estimate(current[i])[0],
                     estimated_tokens=estimate(current[i])[1], target_words=scene_words) for i in indices]))])
        return [prefix+text for text in request_subjects(request, payload, batch_size=2, max_words=scene_words+30, avoid_repeats=False)]

    fitted = list(prompts)
    with trace_stage('Fit image prompts to the image model limit'):
        for i, prompt in zip(range(len(prompts)), rewrite(range(len(prompts)), prompts)):
            fitted[i] = prompt
        over = [i for i, prompt in enumerate(fitted) if estimate(prompt)[1] > tokens]
        if over:
            scenes = [prompt[len(prefix):] for prompt in fitted]
            for i, prompt in zip(over, rewrite(over, scenes, f' These prompts are still too long. Condense each to at most {scene_words} words.')):
                fitted[i] = prompt
    for i, (before, after) in enumerate(zip(prompts, fitted)):
        print(f'Image prompt {i+1}: {estimate(before)[0]} -> {estimate(after)[0]} words '
              f'(~{estimate(after)[1]} of {tokens} tokens).', flush=True)
    return fitted
