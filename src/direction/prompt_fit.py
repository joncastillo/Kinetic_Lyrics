"""Rewrite each complete image prompt to the length the image model's text encoder can read."""
import json
import re

# Prompt token limits per pipeline, and a word budget that leaves room for retry wording.
TOKEN_LIMITS = dict(QwenImagePipeline=1024, ZImagePipeline=512)
WORD_BUDGETS = dict(QwenImagePipeline=700, ZImagePipeline=350)
# FLUX.2 cuts the prompt at 512 tokens, chat template included. 280 words (~380 tokens) leaves room for the
# template, the reference-image sentence put in front at generation time, and the no-lettering wording a retry
# appends, which would otherwise be the part cut off.
FLUX_TOKENS, FLUX_WORDS = 512, 280
TOKENS_PER_WORD = 1.35


def budget(image_model):
    """(words, tokens) the image model reads, or None when it has no known limit."""
    from models.image.catalog import model_spec
    pipeline = model_spec(image_model)['pipeline']
    if pipeline.startswith('Flux'):
        return FLUX_WORDS, FLUX_TOKENS
    return (WORD_BUDGETS[pipeline], TOKEN_LIMITS[pipeline]) if pipeline in WORD_BUDGETS else None


def over_budget(prompt, image_model):
    limit = budget(image_model)
    return bool(limit) and estimate(prompt)[1] > limit[1]


def refit(prompts, image_model, config, style=''):
    """Fit prompts written for another image model to `image_model`'s budget with the prompt model."""
    from models.ollama.catalog import resolve_prompt_model
    from models.ollama.gpu import gpu_chat, unload_model
    from models.ollama.service import local_json
    model = resolve_prompt_model(local_json, config.get('ai_model', 'auto'))
    try:
        return fit_prompts(gpu_chat, model, image_model, prompts, style)
    finally:
        unload_model(model)


def style_prefix(style):
    style = ' '.join(style.split()).rstrip('.')
    return f'Art style, the top priority for how everything is rendered: {style}. ' if style else ''


def trim(text, words):
    """Drop whole sentences or phrases from the end until `text` fits; details are ordered most important first."""
    kept = []
    for sentence in re.split(r'(?<=[.!?;,])\s+', text.strip()):
        if kept and len(' '.join(kept+[sentence]).split()) > words:
            break
        kept.append(sentence)
    result = ' '.join(kept) if len(' '.join(kept).split()) <= words else ' '.join(' '.join(kept).split()[:words])
    return result.rstrip(' ,;')


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
    prefix = style_prefix(style)
    style = ' '.join(style.split()).rstrip('.')
    scene_words = max(100, words-estimate(prefix)[0])
    # FLUX.2 and Z-Image read about half of what Qwen-Image does. Caption-style phrases carry about twice the scene
    # per token as full sentences; invented abbreviations would not, since the text encoders learned from captions.
    terse = words < 400
    from direction.scenes import request_subjects
    from core.progress import counted
    from models.ollama.trace import trace_stage
    system = (
        f'The image model reads at most {tokens} tokens, about {words} English words; anything beyond is ignored. '
        + (f'The art style below is placed before your text automatically, word for word, and takes priority over '
           f'everything else. Leave sentences about art style, technique, brushwork and mood out of your text, and '
           f'never describe a medium, style, palette or mood that conflicts with it. Art style: {style}. '
           if style else '')
        + f'Rewrite each supplied image-generation prompt as one complete standalone prompt of about {scene_words} words. '
        + ('Write it as dense, comma-separated visual phrases like an image caption, not full sentences: no articles, '
           'filler, explanations, story or general quality advice, only what is visible in this scene, each detail '
           'stated once. Short sentences are allowed only for prohibitions such as no lettering. ' if terse else '')
        +         'Each input states its current estimated length. If it is longer, condense it: remove repetition and general '
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
        verb = 'Condensing again' if note else 'Condensing'
        return [prefix+text for text in request_subjects(request, payload, batch_size=2, max_words=scene_words+30, avoid_repeats=False,
                progress=counted('fit', 0, 1, f'{verb} image prompt', f' to about {words} words for {image_model.split("/")[-1]}'))]

    fitted = list(prompts)
    with trace_stage('Fit image prompts to the image model limit'):
        for i, prompt in zip(range(len(prompts)), rewrite(range(len(prompts)), prompts)):
            fitted[i] = prompt
        over = [i for i, prompt in enumerate(fitted) if estimate(prompt)[1] > tokens]
        if over:
            scenes = [prompt[len(prefix):] for prompt in fitted]
            for i, prompt in zip(over, rewrite(over, scenes, f' These prompts are still too long. Condense each to at most {scene_words} words.')):
                fitted[i] = prompt
        # The image model silently drops whatever is past its limit, so never hand it more than it reads.
        for i, prompt in enumerate(fitted):
            if estimate(prompt)[1] > tokens:
                print(f'Image prompt {i+1} is still {estimate(prompt)[0]} words after condensing; '
                      f'trimming its last sentences to fit.', flush=True)
                fitted[i] = prefix+trim(prompt[len(prefix):] if prompt.startswith(prefix) else prompt, scene_words)
    for i, (before, after) in enumerate(zip(prompts, fitted)):
        print(f'Image prompt {i+1}: {estimate(before)[0]} -> {estimate(after)[0]} words '
              f'(~{estimate(after)[1]} of {tokens} tokens).', flush=True)
    return fitted
