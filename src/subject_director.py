"""Generate bounded, validated batches of illustration descriptions."""
import copy
import json


def _parse_subjects(response, count):
    if not isinstance(response, dict):
        raise ValueError('model response is not an object')
    message = response.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        reason = ('model returned reasoning but no final JSON'
                  if isinstance(message, dict) and message.get('thinking')
                  else 'model returned no final JSON')
        if response.get('done_reason') == 'length':
            reason += ' (output limit reached)'
        raise ValueError(reason)
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        reason = ('response reached its output limit with incomplete JSON'
                  if response.get('done_reason') == 'length'
                  else f'model returned invalid JSON at character {exc.pos}')
        raise ValueError(reason) from exc
    items = result.get('subjects') if isinstance(result, dict) else None
    if (not isinstance(items, list) or len(items) != count
            or any(not isinstance(item, str) or not item.strip() for item in items)):
        raise ValueError('expected one nonempty description per lyric group')
    return items


def request_subjects(local_json, payload, batch_size=6, max_words=60, avoid_repeats=True, progress=None):
    inputs = json.loads(payload['messages'][1]['content'])
    subjects = []

    def request(batch, retry=True):
        query = copy.deepcopy(payload)
        schema = query['format']['properties']['subjects']
        schema.update(minItems=len(batch), maxItems=len(batch))
        query['messages'][1]['content'] = json.dumps(batch)
        query['think'] = False
        # About three tokens per allowed word covers long descriptions plus JSON overhead.
        budget = max(4096, len(batch)*max_words*3)
        if not retry:
            budget = budget*3//2
        options = query.get('options', {})
        query['options'] = {**options, 'temperature': options.get('temperature', 0), 'num_predict': budget,
                            'num_ctx': max(options.get('num_ctx', 8192), budget+4096)}
        query['messages'][0]['content'] += (
            f' Keep each description to at most {max_words} words.'
            f' Return only one JSON object with exactly {len(batch)} subjects in input order.'
            ' Write the final JSON directly, without analysis, commentary or Markdown.'
            ' JSON schema: '+json.dumps(query['format'], separators=(',', ':')))
        if not retry:
            query['messages'][0]['content'] += (
                ' The previous attempt did not produce usable final JSON.'
                ' Give the concise final object now; do not discuss or recheck the instructions.')
        if subjects and avoid_repeats:
            query['messages'].append(dict(role='user', content='Avoid repeating these earlier scenes: '+json.dumps(subjects)))
        response = local_json('chat', query, timeout=900)
        try:
            return _parse_subjects(response, len(batch))
        except ValueError as exc:
            model = payload.get('model', 'Illustration director')
            message = response.get('message') if isinstance(response, dict) else None
            content = message.get('content') if isinstance(message, dict) else None
            if len(batch) > 1 and isinstance(content, str) and content.strip():
                middle = len(batch)//2
                print(f'{model}: {exc}; retrying in smaller scene batches', flush=True)
                return request(batch[:middle]) + request(batch[middle:])
            if retry:
                print(f'{model}: {exc}; retrying once with a direct JSON instruction '
                      'and a larger output budget (thinking requested off)', flush=True)
                return request(batch, retry=False)
            raise ValueError('Illustration director returned incomplete or invalid JSON after retries. '
                             f'{model}: {exc}. Select an installed non-thinking/instruct text model '
                             'for illustration prompting and retry. No model was switched automatically.') from exc

    for start in range(0, len(inputs), batch_size):
        if progress:
            progress(start, min(len(inputs), start+batch_size), len(inputs))
        subjects.extend(request(inputs[start:start+batch_size]))
    return subjects


def repair_duplicate_subjects(local_json, payload, subjects, max_rounds=2):
    """Revise only repeated scenes while the same prompting model is loaded."""
    inputs = json.loads(payload['messages'][1]['content'])
    result = list(subjects)
    def normalized(subject):
        return ' '.join(subject.split()).casefold()
    seen = set()
    targets = []
    for index, subject in enumerate(result):
        key = normalized(subject)
        if key in seen:
            targets.append(index)
        seen.add(key)
    fixed = set(range(len(result))) - set(targets)
    def repeated_indices():
        seen = {normalized(result[index]) for index in fixed}
        repeated = []
        for index in targets:
            key = normalized(result[index])
            if key in seen:
                repeated.append(index)
            seen.add(key)
        return repeated
    for attempt in range(max_rounds):
        repeated = repeated_indices()
        if not repeated:
            return result
        print(f'Revising {len(repeated)} repeated illustration scene(s) '
              f'(attempt {attempt+1}/{max_rounds}).', flush=True)
        query = copy.deepcopy(payload)
        query['messages'][0]['content'] += (
            ' These scenes repeated an existing description. Invent a different '
            'lyric-relevant visual interpretation for each input, preserving its '
            'assigned layout. Repeated lyrics can use a different visual metaphor, '
            'physical subject, action or viewpoint. Do not just reword the same scene. '
            'Return one revised description per input in the original order.')
        query['messages'][1]['content'] = json.dumps([
            dict(scene=inputs[index], previous_description=result[index])
            for index in repeated])
        query['messages'].append(dict(role='user', content=(
            'Keep these other scenes unchanged and avoid repeating any of them: '
            +json.dumps(list(dict.fromkeys(result))))))
        query['options'] = {**query.get('options', {}), 'temperature': 0.75}
        from kinetic_progress import counted
        replacements = request_subjects(local_json, query, progress=counted(
            'scenes', .6, .75, f'Round {attempt+1} of {max_rounds}: rewriting repeated scene',
            names=[(inputs[index] or {}).get('lyrics', '') if isinstance(inputs[index], dict) else '' for index in repeated]))
        for index, replacement in zip(repeated, replacements):
            result[index] = replacement
    remaining = repeated_indices()
    if remaining:
        print(f'Applied visual perspective variations to {len(remaining)} scene(s) to resolve remaining duplicates.', flush=True)
        perspectives = [
            ' Viewed from an extreme low angle looking upward, with dramatic chiaroscuro shadows and expressive edge rim lighting.',
            ' Framed as an intimate cinematic close-up with soft atmospheric depth-of-field and warm directional light.',
            ' Captured in an expansive wide establishing perspective with moody mist, deep cool ambient backlight, and rich environmental details.',
            ' Seen from a high overhead vantage point, revealing geometric patterns and striking contrast between light and dark silhouettes.',
            ' Rendered with intense side-lighting, long raking cast shadows, and vivid atmospheric contrast.'
        ]
        seen_all = {normalized(result[idx]) for idx in fixed}
        for i, idx in enumerate(remaining):
            variation = perspectives[i % len(perspectives)]
            candidate = result[idx].rstrip('. ') + '.' + variation
            if normalized(candidate) in seen_all:
                candidate = candidate.rstrip('. ') + f' (Perspective alternative {i+1}).'
            result[idx] = candidate
            seen_all.add(normalized(candidate))
    return result
