"""Typography and motion planning: the local LLM's art direction, or explicit offline rules."""
from __future__ import annotations
import json
import math
import urllib.error
import urllib.request
from models.ollama.service import local_json

PALETTES = {
    'midnight': ('#101725', '#223348', '#EEE9DE', '#D29A80'),
    'paper': ('#EAE3D5', '#CDC2B3', '#20252C', '#923F48'),
    'wine': ('#291722', '#512939', '#F2E7DE', '#E5AF8F'),
    'slate': ('#25343C', '#3D555C', '#F0ECE1', '#EFC078'),
    'electric': ('#121522', '#283348', '#F8F5EC', '#CDFA55'),
    'violet': ('#291F3D', '#4D365B', '#FAF0E5', '#FFB9AA'),
}
FONTS = {'condensed': ['impact.ttf', 'DejaVuSansCondensed-Bold.ttf'],
         'grotesk': ['bahnschrift.ttf', 'DejaVuSans-Bold.ttf'],
         'heavy': ['seguibl.ttf', 'arialbd.ttf', 'DejaVuSans-Bold.ttf']}


MODES = ('push', 'drop', 'zoom', 'blocks', 'marquee', 'stack')

CAMERAS = ('push-in', 'pull-out', 'pan-left', 'pan-right', 'hold')

STYLES = ('poster', 'swiss', 'outline', 'cutout', 'neon', 'extrude', 'split')


def rules_plan(data, theme):
    """Explicit offline alternative; never described as AI direction."""
    quiet = theme['name'] in ('solemn', 'romantic')
    palettes = ['midnight', 'slate', 'wine', 'paper'] if quiet else ['electric', 'violet', 'paper']
    return dict(version=1, director='rules', concept='Editorial blocks with measured contrast',
        scenes=[dict(mode=MODES[i % len(MODES)], style=STYLES[(i // 2) % len(STYLES)], palette=palettes[(i // 4) % len(palettes)],
                     font='condensed', align=('left', 'center', 'right')[i % 3],
                     background=('glow', 'diagonal', 'rings')[(i // 4) % 3],
                     emphasis=max(range(len(line['words'])), key=lambda j: len(line['words'][j]['text'])),
                     energy=.35 if quiet else .75) for i, line in enumerate(data)])


def validate_plan(plan, data):
    if not isinstance(plan, dict) or not isinstance(plan.get('scenes'), list) or len(plan['scenes']) != len(data):
        raise ValueError('Art direction must contain exactly one scene per lyric line.')
    for number, (scene, line) in enumerate(zip(plan['scenes'], data), 1):
        if not isinstance(scene, dict):
            raise ValueError('Each art direction scene must be an object.')
        scene.setdefault('style', {'blocks': 'cutout', 'stack': 'swiss', 'marquee': 'outline'}.get(scene.get('mode'), 'poster'))
        for key, options in [('mode', MODES), ('palette', PALETTES), ('font', FONTS),
                             ('style', STYLES),
                             ('align', ('left', 'center', 'right')),
                             ('background', ('glow', 'diagonal', 'rings'))]:
            if scene.get(key) not in options:
                raise ValueError(f'Invalid art direction {key}: {scene.get(key)!r}')
        scene.setdefault('camera', 'hold')
        if scene['camera'] not in CAMERAS:
            raise ValueError(f"Invalid camera move: {scene['camera']!r}")
        emphasis, energy = scene.get('emphasis'), scene.get('energy')
        if type(emphasis) is not int or not 0 <= emphasis < len(line['words']):
            raise ValueError('Art direction emphasis must be a valid zero-based word index.')
        if type(energy) not in (int, float) or not math.isfinite(energy) or not 0 <= energy <= 1:
            raise ValueError(f'Art direction energy must be between zero and one '
                             f'(scene {number}, value {energy!r}).')
    return plan

DIRECTION_RETRY_DELAY = 10.

DIRECTION_ATTEMPTS = ((None, 16384, 12000), (None, 16384, 12000), (12, 8192, 6000))


def direction_schema(count):
    return {'type': 'object', 'properties': {
        'concept': {'type': 'string'},
        'scenes': {'type': 'array', 'minItems': count, 'maxItems': count,
            'items': {'type': 'object', 'properties': {
                'camera': {'type': 'string', 'enum': list(CAMERAS)},
                'mode': {'type': 'string', 'enum': list(MODES)},
                'style': {'type': 'string', 'enum': list(STYLES)},
                'palette': {'type': 'string', 'enum': list(PALETTES)},
                'font': {'type': 'string', 'enum': list(FONTS)},
                'align': {'type': 'string', 'enum': ['left', 'center', 'right']},
                'background': {'type': 'string', 'enum': ['glow', 'diagonal', 'rings']},
                'emphasis': {'type': 'integer', 'minimum': 0},
                'energy': {'type': 'number', 'minimum': 0, 'maximum': 1}},
                'required': ['camera', 'mode', 'style', 'palette', 'font', 'align', 'background', 'emphasis', 'energy'],
                'additionalProperties': False}}},
        'required': ['concept', 'scenes'], 'additionalProperties': False}


def direction_brief(prompt):
    return ('Act as a motion design art director for a polished lyric video. '
            'Return JSON, one scene per input line in the same order. Choose a coherent visual arc, '
            'not random effects. Hold palettes and fonts across related lines; change at section shifts. '
            'Repeat visual motifs for repeated lyrics. Mostly condensed bold text. '
            'Mix distinct visual styles deliberately: poster is huge uppercase condensed type; '
            'swiss is calmer, lighter editorial capitals; neon is glowing letters for night or electric moods; '
            'extrude is bold 3D block letters for impact; split is two-tone letters for contrast and duality; '
            'outline is hollow display lettering '
            'with a solid emphasis word; cutout is colored paper-like word tiles. '
            'Use at least three styles across a full song. Avoid keeping any one treatment throughout. '
            'Use quiet swiss scenes as breathing space between dramatic poster and cutout sections. '
            'Use push for building phrases, drop for impact, zoom for emotional emphasis, '
            'blocks for graphic contrast, marquee sparingly for repetition, stack for quiet holds. '
            'Emphasis is a zero-based index into each line word array. '
            'Energy is a JSON number between 0 and 1 inclusive (for example 0.35), never a percentage. '
            'It controls motion strength; keep solemn songs restrained but visually bold. '
            'Choose camera push-in for emphasis, pull-out for release, pan-left or pan-right for movement, hold for stillness. '
            'Keep camera choices coherent over related lines. '
            'Backgrounds are subtle animated gradients: glow, diagonal or rings. '
            f'Palette colors (background, gradient, ink, accent): {json.dumps(PALETTES)}. '
            'You only have lyrics and word timing, not audio analysis; use phrasing and text meaning. '
            f'User direction: {prompt}')


def request_direction(data, prompt, model, num_ctx, num_predict, chunk=None, seed=None):
    """One schema-bound plan, optionally requested in consecutive line chunks."""
    from models.ollama.gpu import gpu_chat
    size = chunk or len(data)
    concept, scenes = None, []
    from core.progress import counted
    report = counted('direction', 0, 1, 'Planning typography and motion for lyric line')
    for first in range(0, len(data), size):
        part = data[first:first+size]
        report(first, first+len(part), len(data))
        brief = direction_brief(prompt)
        if chunk:
            brief += f' This request covers lines {first} to {first+len(part)-1} of {len(data)}; keep the arc consistent with a full song.'
        options = dict(temperature=.55, num_ctx=num_ctx, num_predict=num_predict)
        if seed is not None:
            options['seed'] = int(seed % (2**31))
        response = gpu_chat('chat', dict(model=model, stream=False, think=False,
            keep_alive=0, format=direction_schema(len(part)), options=options,
            messages=[dict(role='system', content=brief), dict(role='user', content=json.dumps([
                dict(line=first+i, words=[w['text'] for w in line['words']],
                     start=line['words'][0]['start'], end=line['words'][-1]['end'])
                for i, line in enumerate(part)]))]), timeout=900)
        result = json.loads(response['message']['content'])
        if not isinstance(result, dict) or not isinstance(result.get('scenes'), list) or len(result['scenes']) != len(part):
            raise ValueError('Art direction must contain exactly one scene per lyric line.')
        concept = concept or result.get('concept')
        scenes += result['scenes']
    return dict(concept=concept or 'Editorial lyric arc', scenes=scenes)


def bounded_plan(plan, data):
    adjusted = energy_adjusted = 0
    for scene, line in zip(plan['scenes'], data):
        if isinstance(scene, dict) and type(scene.get('emphasis')) is int:
            original = scene['emphasis']
            scene['emphasis'] = max(0, min(len(line['words'])-1, original))
            adjusted += original != scene['emphasis']
        if isinstance(scene, dict):
            energy = scene.get('energy')
            if type(energy) in (int, float) and math.isfinite(energy):
                scene['energy'] = max(0., min(1., energy))
                energy_adjusted += energy != scene['energy']
    if adjusted:
        print(f'Bound {adjusted} AI emphasis selection(s) to their lyric lines.', flush=True)
    if energy_adjusted:
        print(f'Bound {energy_adjusted} AI energy value(s) to the supported 0–1 range.', flush=True)
    return validate_plan(plan, data)


def direct(data, theme, prompt, model='auto', director='ollama', seed=None):
    """AI art direction that recovers from runner crashes and bad output without a human."""
    if director == 'rules':
        return rules_plan(data, theme)
    failure = None
    try:
        from models.ollama.catalog import resolve_prompt_model
        model = resolve_prompt_model(local_json, model)
    except (urllib.error.URLError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        failure = exc
    if failure is None:
        print(f'AI art direction: {model}; planning {len(data)} scenes locally...', flush=True)
        for attempt, (chunk, num_ctx, num_predict) in enumerate(DIRECTION_ATTEMPTS, 1):
            try:
                plan = bounded_plan(request_direction(data, prompt, model, num_ctx, num_predict, chunk, seed=seed), data)
                plan.update(version=1, director='ollama', model=model)
                return plan
            except (urllib.error.URLError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
                failure = exc
                print(f'Warning: AI art direction attempt {attempt}/{len(DIRECTION_ATTEMPTS)} failed: {exc}', flush=True)
                try:
                    from models.ollama.gpu import unload_model
                    unload_model(model)
                except (urllib.error.URLError, OSError, ValueError) as cleanup:
                    print(f'Warning: could not unload {model} before retrying: {cleanup}', flush=True)
                if attempt < len(DIRECTION_ATTEMPTS):
                    import time
                    time.sleep(DIRECTION_RETRY_DELAY)
    print(f'Warning: AI art direction unavailable ({failure}); continuing with the offline rules plan so the video can finish.', flush=True)
    plan = rules_plan(data, theme)
    plan.update(director='rules-fallback', fallback_reason=str(failure)[:500])
    return plan
