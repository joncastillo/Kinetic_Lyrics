"""Checks a recurring reference picture (direction.entities) with the vision model before the scenes are reviewed:
it shows only its subject (no stray lead or other person), matches its description, and is in the project's art
style. A sheet that fails is painted again (studio.worker.check_references bounds the rounds), then the images that
show it are painted again."""
import base64
import hashlib
import io
import json
import re
import time
from pathlib import Path


# What the vision model is told to check in a reference picture (References tab, editable). Before it is sent,
# {name} becomes the reference's name, {kind} character, object or place, {looks} its description and {style} the
# project's art style. The answer format (ANSWER) is added after it by the code, so editing this cannot break it.
REFERENCE_CHECK_PROMPT = (
    'This picture is the reference sheet for {name}, a {kind}: {looks}\n'
    'It should show only {name}, drawn several times from different angles (a place: several panels of the same '
    'place), in this art style: {style}\n'
    'Check:\n'
    '- For a character sheet, is anyone or anything else drawn in it? A different face, sex, age, hair or outfit in some of the views '
    'counts, such as a woman in a white dress among the views of a man.\n'
    '- Does it contradict the description (sex, age, build, species, colours, clothes, materials)?\n'
    '- Is it drawn in another style? A flat, simple cartoon when the style asks for modern anime, painterly or '
    'realistic rendering is a mismatch; stylisation within the style is fine. Judge the drawing technique only: '
    'words about the film\'s mood or content (dark, horror, gory, bloody, romantic) describe its scenes, not this '
    'sheet, so a clean sheet in that technique matches the style.\n'
    '- For a place, follow the described occupancy: include people when the description requires them. An object '
    'may be shown with no one holding it.\n'
    '- A still picture cannot show movement: words such as twitching, running or flowing describe the film, so a '
    'still pose matches them.\n'
    'Report only what you can see; do not invent problems.')

# Added for a changed form of a character, object or place ("Arnel (injured)", "the vase (broken)"); fixed.
CHANGED_FORM = ('\n- {name} is a changed form: is every lasting change the description names shown, exactly as stated, '
                'on the part and side named (a missing left eye is not a missing right one; a missing finger is not a '
                'bandaged one), in every view? A change that is missing, healed, softened or on the wrong side '
                'contradicts the description.')

# How the vision model answers; fixed, because the code reads these fields.
ANSWER = ('\n\nAnswer with: other_subjects (each person, animal or creature in the picture that is not {name}; empty '
          'when there is none), matches_description (false only for a clear contradiction), matches_style (false only '
          'for a clearly different style), issues (each problem and where it is), summary (one sentence).')
PLACE_RULES = ('\n\nPlace-specific rule, overriding generic empty-sheet and character-identity rules above: this is '
               'a location, not one character in several poses. If its description calls for patients, staff, relatives, '
               'crowds or other occupants, those people belong in the location. Do NOT list them in other_subjects or '
               'fail it merely for their presence. Different occupants may have different sex, age, hair and outfits '
               'across views; that is not a character consistency error. Check the location layout, materials and art '
               'style. Report only unrequested occupants, actual description contradictions or other visible errors. '
               'When the description explicitly requires an empty location, people are a contradiction.')
CHECK_VERSION = 2

# A second check, on the body parts. Told to expect a beak, the vision model passed huge pincers 8 times in 9; asked
# what is drawn without the description it named them every time. So it looks first, unprompted (LOOK), and a text
# model compares its account with the description (COMPARE). Comparing everything rejected half the good sheets
# (a moustache, a "white dress" for a gown), so only body parts are compared; a small text model finds nothing wrong
# anywhere, so only the chosen one does it (wrong_parts). Places are skipped.
LOOK = ('This is a model sheet: one {kind} drawn in several views. Describe only what is actually drawn; do not guess what '
        'it is meant to be. Name its body parts, if it has any: the shape of the head, the mouth and anything that sticks '
        'out of the head or face, the limbs, and anything else on the body. Answer with: seen (two or three sentences).')
COMPARE = ('A drawing of {name} must match this description:\n{looks}\n\nAn inspector who had not read it reports what is '
           'drawn:\n{seen}\n\nCompare body parts ONLY. Answer with `wrong_parts`: each body part the description names that '
           'the report says is drawn as a different kind of part (a trunk where the description says a snout, hooves where '
           'it says paws), and each large part of the body the report names that the description rules out, each as '
           '"drawn as ..., should be ...". Leave out everything else: hair, facial hair, age, build, size, shape words, '
           'colour, texture, clothes, wounds, marks, left and right, and anything the report does not mention. People have '
           'the ordinary parts of people, and those are never wrong; parts the description adds to a body grow beside them '
           'and replace none of them. The same kind of part in other words is not wrong: a limb is a limb whatever the '
           'report calls it, and whichever animal it compares it to. Empty when no part is wrong.')


def sheet_picture(image):
    """The sheet as the vision model is given it: base64 JPEG, at most 1536 pixels."""
    from PIL import Image
    with Image.open(image) as source:
        picture = source.convert('RGB')
    picture.thumbnail((1536, 1536))
    data = io.BytesIO()
    picture.save(data, format='JPEG', quality=92)
    return base64.b64encode(data.getvalue()).decode()


def ask_vision(payload):
    """The vision model's answer (request_check) inside or outside a GPU session."""
    from models.ollama.gpu import gpu_chat
    from models.gpu.lifecycle import current_session
    session = current_session()
    if session:
        payload['keep_alive'] = -1
        session.before_review(payload['model'])
    return request_check(lambda query: session.review_request(gpu_chat, query) if session
                         else gpu_chat('chat', query, timeout=600), payload)


def look_at_sheet(image, entity, model):
    """What the vision model says is drawn, without having read the description."""
    schema = dict(type='object', properties=dict(seen=dict(type='string')), required=['seen'])
    return str(ask_vision(dict(model=model, stream=False, keep_alive='30m', think=False, format=schema,
                               options=dict(temperature=.1, num_ctx=8192),
                               messages=[dict(role='user', content=LOOK.format(kind=entity.get('kind') or 'character'),
                                              images=[sheet_picture(image)])])).get('seen') or '').strip()


def wrong_parts(entity, seen, model):
    """The body parts in `seen` (look_at_sheet) that contradict the entity's description, from the text model and no
    smaller one."""
    from models.ollama.gpu import gpu_chat
    from models.gpu.lifecycle import current_session
    session = current_session()
    if session:
        session.before_prompting(model)
    schema = dict(type='object', properties=dict(wrong_parts=dict(type='array', items=dict(type='string'))), required=['wrong_parts'])
    text = COMPARE.format(name=entity.get('name') or '', looks=entity.get('looks') or '', seen=seen)
    result = request_check(lambda query: gpu_chat('chat', query, timeout=600, exact=True),
                           dict(model=model, stream=False, keep_alive='30m', think=False, format=schema,
                                options=dict(temperature=.1, num_ctx=8192), messages=[dict(role='user', content=text)]))
    return [str(part) for part in result.get('wrong_parts') or [] if str(part).strip()]


def review_sheet(image, entity, style, model, prompt=None):
    """{passed, other_subjects, matches_description, matches_style, issues, summary} for one sheet."""
    kind = entity.get('kind') or 'character'
    template = str(prompt).strip() if str(prompt or '').strip() else REFERENCE_CHECK_PROMPT
    fields = dict(name=entity.get('name') or '', kind=kind, looks=entity.get('looks') or '', style=style or 'the project style')
    # a changed form: the marks the story gives it must all be there, exactly (the side and part named)
    changed = (CHANGED_FORM if entity.get('base') or re.search(r'\(.+\)$', str(entity.get('name') or '')) else '')
    instruction = re.sub(r'\{(name|kind|looks|style)\}', lambda m: str(fields[m.group(1)]), template+changed+ANSWER+(PLACE_RULES if kind=='place' else ''))
    schema = dict(type='object', properties=dict(
        summary=dict(type='string'), other_subjects=dict(type='array', items=dict(type='string')),
        matches_description=dict(type='boolean'), matches_style=dict(type='boolean'),
        issues=dict(type='array', items=dict(type='string'))),
        required=['summary', 'other_subjects', 'matches_description', 'matches_style', 'issues'])
    payload = dict(model=model, stream=False, keep_alive='30m', think=False, format=schema,
                   options=dict(temperature=.1, num_ctx=8192),
                   messages=[dict(role='user', content=instruction, images=[sheet_picture(image)])])
    result = ask_vision(payload)
    others = [str(o) for o in result.get('other_subjects') or [] if str(o).strip()]
    result.update(other_subjects=others, passed=not others and result.get('matches_description', True) is not False
                  and result.get('matches_style', True) is not False)
    return result


# A thinking model such as qwen3-vl reasons before the JSON even when told not to. Its answers took at most 3,500
# tokens over 72 checks; one that passes 4,096 has fallen into a loop ("Wait, ..." 97 times in one) that a larger
# budget only prolongs (8,192 came back just as empty), and the picture went unchecked. So each try has the same
# budget, and a warmer temperature to leave the loop instead of walking into it again.
BUDGET = 4096
TEMPERATURES = (.1, .5, .8)  # one per try


def request_check(request, payload):
    """The checker's answer as a dict: asks again, warmer and told to answer at once, when the reply is empty (the
    budget went on reasoning), cut short, or not JSON. ValueError when every try fails."""
    import copy
    last = None
    for attempt, temperature in enumerate(TEMPERATURES):
        query = copy.deepcopy(payload)
        query['options'] = {**query.get('options', {}), 'num_predict': BUDGET, 'temperature': temperature}
        if attempt:
            query['messages'][0]['content'] += '\nAnswer at once with the JSON object only; no reasoning before it.'
        reply = request(query)
        content = reply['message']['content'] if isinstance(reply, dict) and 'message' in reply else reply
        if not isinstance(content, str):
            if isinstance(content, dict):
                return content
            last = 'the model answered nothing'
            continue
        content = content.strip()
        fenced = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', content, re.S | re.I)
        if fenced:
            content = fenced.group(1)
        if not content:
            last = ('the model used its whole answer budget on reasoning' if isinstance(reply, dict)
                    and reply.get('done_reason') == 'length' else 'the model answered nothing')
            continue
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            last = f'the answer was not JSON (character {exc.pos})'
            continue
        if isinstance(result, dict):
            return result
        last = 'the answer was not an object'
    raise ValueError(f'{last}, after {len(TEMPERATURES)} tries')


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def review_references(manifest, model, style, log=print, prompt=None, repaint=True, max_repaints=1, text_model=None):
    """Check every painted reference picture not checked yet in its current form. Returns the ids of those that
    failed and have not been painted again for a failed check before (one retry each); records each result in the
    storyline (entity['sheet_review']) so a picture is checked once. With `text_model`, a sheet that passes has its
    body parts checked too: every look first, then every comparison, so the models change places once."""
    from core.files import update_json
    from direction.entities import current_sheet
    from direction.story import load, story_path
    story = load(manifest) or {}
    results, accounts, checked = {}, {}, []
    for entity in story.get('entities') or []:
        image = Path(str(entity.get('image') or ''))
        if entity.get('uploaded') or not image.is_file() or not current_sheet(entity):
            continue
        digest = fingerprint(image)
        if (entity.get('sheet_review') or {}).get('sha') == digest and (entity.get('sheet_review') or {}).get('rules_version') == CHECK_VERSION:
            continue
        try:
            result = review_sheet(image, entity, style, model, prompt)
        except Exception as exc:  # noqa: BLE001 (a check is a help, never a reason to stop the run)
            log(f"Warning: the reference picture of {entity.get('name')} could not be checked ({exc}).")
            continue
        results[entity['id']] = dict(sha=digest, passed=bool(result['passed']), at=time.time(), rules_version=CHECK_VERSION,
                                     issues=(result.get('other_subjects') or [])+(result.get('issues') or []),
                                     style=result.get('matches_style'), description=result.get('matches_description'),
                                     summary=result.get('summary', ''))
        checked.append(entity)
        if text_model and result['passed'] and entity.get('kind') != 'place':
            try:
                accounts[entity['id']] = look_at_sheet(image, entity, model)
            except Exception as exc:  # noqa: BLE001
                log(f"Warning: the body parts of {entity.get('name')} could not be checked ({exc}).")
    for entity in checked:
        seen = accounts.get(entity['id'])
        if not seen:
            continue
        try:
            parts = wrong_parts(entity, seen, text_model)
        except Exception as exc:  # noqa: BLE001
            log(f"Warning: the body parts of {entity.get('name')} could not be compared ({exc}).")
            continue
        if parts:
            results[entity['id']].update(passed=False, description=False, issues=parts)
    for entity in checked:
        outcome = results[entity['id']]
        from core.files import write_json_atomic
        write_json_atomic(Path(entity['image']).with_suffix('.sheet-review.json'), outcome)
        log(f"Reference picture of {entity.get('name')}: " + ('passed the check.' if outcome['passed'] else
            'failed the check: '+'; '.join(outcome['issues'][:4] or [outcome['summary']])))
    retry = []

    def record(saved):
        from direction.reference_choices import apply
        apply(manifest,saved)
        for entry in saved.get('entities') or []:
            if entry.get('uploaded'):
                continue  # a manual selection made during this check must stand
            outcome = results.get(entry.get('id'))
            if not outcome:
                continue
            entry['sheet_review'] = outcome
            if repaint and not outcome['passed'] and int(entry.get('review_repaints') or 0) < max_repaints:
                entry['review_repaints'] = int(entry.get('review_repaints') or 0)+1
                entry['repaint'] = int(entry.get('repaint') or 0)+1
                entry.pop('image', None)
                retry.append(entry['id'])
    if results:
        update_json(story_path(manifest), record)
    return retry
