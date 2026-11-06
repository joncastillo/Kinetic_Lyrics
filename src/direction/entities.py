"""Recurring entities: the characters, objects and places the storyline shows in more than one segment.

After the storyline is written, the director lists them with one fixed description each. The image worker paints a
reference picture of each one (entities/<id>.png next to the prompts) before the segment images, and every segment
that shows an entity gets its picture as a reference image, so it looks the same from scene to scene. The video
models cannot take a reference picture while starting from the painting, so each clip's prompts restate the looks
of the entities in its segment instead. Kept in story.json under `entities`.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

KINDS = ('character', 'object', 'place')   # also the order they claim the image model's few reference slots
MAX_ENTITIES = 18   # 8 cut the forms and objects of a long story (the bitten farmer, the notebook); a scene takes only its own
STORY_WORDS = 3000  # of the writer's own story the director reads
LOOKS_WORDS = 60
MAX_REFERENCES = 3                          # what the reference-taking image models read
REFERENCE_PIXELS = 1280                     # the long edge of a reference picture handed to the image model (720p of a 16:9 one)


def words(text, limit):
    parts = str(text or '').split()
    return ' '.join(parts[:limit])


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', str(name).lower()).strip('-')[:40] or 'entity'


def clean(entries, count):
    """Entities the rest of the app can rely on: a known kind, a description, unique ids, characters first, and shown
    in at least two valid segments counting every form of the same thing together: a changed form ("Arnel
    (injured)", "the vase (broken)") carries `base`, the id of the entry it is a form of (from the director's `base`
    field or from its name), and is kept even when it shows in one segment only, as long as the thing spans two.
    Anything else from the director is dropped."""
    result, seen, bases = [], set(), []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name, looks = words(entry.get('name'), 8), words(entry.get('looks'), LOOKS_WORDS)
        kind = str(entry.get('kind') or '').strip().lower()
        segments = sorted({int(i) for i in entry.get('segments') or [] if isinstance(i, (int, float)) and 0 <= int(i) < count})
        if not name or not looks or kind not in KINDS or not segments:
            continue
        key = slug(name)
        while key in seen:
            key += '-2'
        seen.add(key)
        result.append(dict(id=key, name=name, kind=kind, looks=looks, segments=segments, cast=bool(entry.get('cast')),
                           from_cast=bool(entry.get('from_cast')) and kind == 'character' and not entry.get('cast')))
        bases.append(str(entry.get('base') or ''))
    for entity, base in zip(result, bases):
        found = base_entity(entity, result, base)
        entity['base'] = found['id'] if found else ''
        if found and found.get('cast') and entity['kind'] == 'character':
            entity['from_cast'] = True
    # the segments of a thing: its own and every form's, so a form shown once still gets a picture that matches
    roots = {e['id']: root_of(e, result) for e in result}
    spanned = {}
    for entity in result:
        spanned.setdefault(roots[entity['id']], set()).update(entity['segments'])
    result = [e for e in result if len(spanned[roots[e['id']]]) >= 2]
    kept = {e['id'] for e in result}
    for entity in result:
        if entity['base'] not in kept:
            entity['base'] = ''
    result.sort(key=lambda e: (KINDS.index(e['kind']), -len(e['segments'])))
    return result[:MAX_ENTITIES]


def root_of(entity, entities):
    """The id of the form every form of this thing comes from (its own when it is a form of nothing)."""
    current, steps = entity, 0
    while current.get('base') and steps < MAX_ENTITIES:
        found = next((e for e in entities if e.get('id') == current['base']), None)
        if found is None:
            break
        current, steps = found, steps+1
    return current.get('id')


def form_stem(name):
    """The name without its bracketed form: "Arnel (injured)" -> "arnel", "the vase (broken)" -> "the vase"."""
    return re.sub(r'\s*\(.*?\)\s*$', '', str(name or '')).strip().lower()


def base_entity(entity, entities, base=''):
    """The entry `entity` is a changed form of: the one `base` names (an id or a name), else the one whose name is
    this one's name without its form ("Viktoria" for "Viktoria (mutated)"), of the same kind. None for a form of
    nothing listed, or of itself."""
    others = [e for e in entities if e is not entity and e.get('id') != entity.get('id') and e.get('kind') == entity.get('kind')]
    wanted = str(base or '').strip().lower()
    if wanted:
        for other in others:
            if wanted in (str(other.get('id') or '').lower(), str(other.get('name') or '').strip().lower()) or slug(wanted) == other.get('id'):
                return other
    stem = form_stem(entity.get('name'))
    if stem and stem != str(entity.get('name') or '').strip().lower():
        for other in others:
            if str(other.get('name') or '').strip().lower() == stem:
                return other
    return None


LEAD_TAG = re.compile(r"([A-Z][\w.'\u2019-]*(?:[ \t]+[A-Z][\w.'\u2019-]*){0,3})[ \t]*[(:,\u2013-]*[ \t]*"
                      r'@("[^"]+"|photo[ \t]*\d+(?!\w)|[\w\-]+(?:\.\w+)?)')


def lead_tags(text):
    """{name: tag} of the leads the writer declares in the story, as a name followed by a tag: "Dr. Viktoria Valderrama
    @photo1", "Arnel (@arnel.png)". The tag says which uploaded picture shows them."""
    return {match.group(1).strip(): match.group(2).strip('"').replace(' ', '') for match in LEAD_TAG.finditer(str(text or ''))}


def link_leads(entities, text):
    """`entities` with the leads the story declares marked: the character named by a tag is `cast` and keeps the tag in
    `photo`, and its forms are `from_cast`. A story that declares leads decides alone; one that declares none leaves
    the director's choice."""
    tags = lead_tags(text)
    if not tags:
        return entities
    linked = {}
    for name, tag in tags.items():
        wanted = {w for w in re.findall(r'[a-z]+', name.lower()) if len(w) > 2 and w not in TITLES}
        people = [e for e in entities if e.get('kind') == 'character' and not e.get('base')]
        for entity in people:
            if wanted & set(re.findall(r'[a-z]+', form_stem(entity.get('name')))):
                linked[entity['id']] = tag
                break
    if not linked:
        return entities
    for entity in entities:
        entity.pop('photo', None)
        entity['cast'] = entity['id'] in linked
        if entity['cast']:
            entity['photo'] = linked[entity['id']]
        entity['from_cast'] = root_of(entity, entities) in linked and not entity['cast'] and entity.get('kind') == 'character'
    return entities


def photo_index(tag, names):
    """The place in `names` (the project's pictures, in order) of the picture a tag means: photo2 is the second, else
    the file name with or without its extension; None for a tag that names none of them."""
    tag = str(tag or '')
    number = re.fullmatch(r'photo\s*(\d+)', tag, re.I)
    if number:
        index = int(number.group(1))-1
        return index if 0 <= index < len(names) else None
    key = lambda s: re.sub(r'[^a-z0-9]+', '', str(s).lower())
    for index, name in enumerate(names):
        if key(tag) in (key(Path(name).name), key(Path(name).stem)):
            return index
    return None


def find_entities(model, segments, request=None, character='', story=''):
    """The recurring entities of a storyline (a list of normalised story segments), from the director model; [] when
    there is no model or the call fails (the entities are a help, never a reason to stop the run). `story` is the
    writer's own text: the storyline condenses it, and lost what the pictures turned on (a lab flooded and never
    drained, a creature's beak), so the director reads both."""
    if not model or len(segments) < 2:
        return []
    if request is None:
        from models.ollama.gpu import gpu_chat
        request = lambda payload: gpu_chat('chat', payload, timeout=900, exact=True)  # a smaller model lists nothing
    entity_schema = dict(type='object', required=['name', 'kind', 'looks', 'segments', 'cast', 'from_cast', 'base'],
                         properties=dict(name=dict(type='string'), kind=dict(type='string', enum=list(KINDS)),
                                         looks=dict(type='string'), segments=dict(type='array', items=dict(type='integer')),
                                         cast=dict(type='boolean'), from_cast=dict(type='boolean'), base=dict(type='string')))
    schema = dict(type='object', required=['entities'], properties=dict(entities=dict(type='array', items=entity_schema)))
    payload = dict(model=model, stream=False, think=False, keep_alive=0, format=schema,
                   options=dict(num_ctx=32768, num_predict=4000, temperature=.2),
        messages=[dict(role='system', content=(
            'You prepare the reference pictures for a music video told in segments, one painted illustration each. '
            'You are given the storyline and, when there is one, the writer\'s original story, which is the authority: '
            'where the two differ, or the storyline leaves something out, follow the story. '
            'Read them and list every character (person or animal), every object a viewer would recognise '
            'again (a microscope, a notebook, a vase, a car, a weapon, a letter, a creature) and every place that is shown in TWO OR MORE '
            'segments, so an illustrator can draw it the same way every time; the film is judged on its '
            'consistency, so when in doubt list it. For each give: '
            '`name` (short, as the story calls it, e.g. "Mia" or "the red kite"); `kind` ("character", "object" or '
            '"place"); `looks` (one or two sentences with everything needed to draw it identically: for a character '
            'age, build, face, hair or fur, skin tone and the complete outfit from top to shoes, the main character '
            'included, in the clothes the story gives them, never the clothes of the user\'s picture; for an object its shape, its real size against '
            'a person\'s body ("fits in one hand", "as tall as a man"), colours and material; for a place its layout, materials, landmarks, its state (flooded, burned, crowded, worn) and its '
            'light; use the writer\'s own details, word for word where you can, and add only what they leave open, '
            'consistently, and nothing that contradicts them); `segments` (the index of every segment it is shown in); `cast` '
            '(true only for the main character described as the person in the user\'s reference picture, false '
            'otherwise); `from_cast` (true when this character IS that main character in another form: transformed, '
            'a hybrid, older or younger, in disguise; false for everyone else, and false for the main character '
            'itself); `base` (see below; "" for everything that is not a changed form). '
            'FORMS. When the story lastingly changes how a character, object or place looks, you must list it once '
            'per form, as separate entries, so each form gets its own reference picture: the normal form, with the '
            'segments up to and including the one in which the change happens (that segment begins before it), and '
            'each changed form, named after the normal one with the change in brackets, like "Mia (transformed)", '
            '"Arnel (injured)", "the vase (broken)", "the vase (fixed)", "the basement lab (dirty)", "the basement '
            'lab (burned)", with only the segments that begin after the change. Every segment belongs to one form '
            'only. This covers a deformity, mutation, transformation, ageing, a change of clothes that stays, clothes opened, torn or taken off, any '
            'injury a later segment still shows however small (a bitten or swollen hand, a cut, a bruise, a black '
            'eye, a bandage, blood on the clothes), and for objects and places breaking, repair, dirt, damage, '
            'fire, flood or decay. Set the changed form\'s `base` to the '
            'normal form\'s exact `name`. The changed form shows the change fully developed, and its `looks` starts '
            'with exactly what changed, precisely as the storyline states it and never softened, generalised or '
            'added to: which body part and which side (the left eye missing, a front tooth missing, the little '
            'finger of the right hand gone, a scar across the left cheek), how far, its colour and texture; for an '
            'object or place which parts are broken, missing, burnt, stained or replaced; and then repeats the '
            'face, hair, build, clothes, shape or layout of the normal form that did not change. A form shows what '
            'stays on it once the moment has passed: the mark and never what made it ("a deep cut across the left '
            'forearm", not "slashed by a sword"), since the blade, claw, tooth or limb belongs to whatever struck. For the main '
            'character the normal form keeps its usual `cast` value and the changed form has `cast` false and '
            '`from_cast` true. A thing counts as shown in two or more segments across all its forms: list every form '
            'of it, even a form shown in a single segment. '
            'Skip anything shown in only one segment in all its forms, crowds, weather and passing background things. '
            'List characters first. At most '+str(MAX_ENTITIES)+' entries.'
            +(f' The main character from the user\'s reference picture: {character.strip()}' if str(character or '').strip() else '')
            +' Return JSON {"entities":[{"name":"...","kind":"character","looks":"...","segments":[0,3],"cast":false,'
            '"from_cast":false,"base":""}]}.')),
            dict(role='user', content=json.dumps(dict(story=words(story, STORY_WORDS), segments=[
                dict(index=s.get('index', i), moment=words(s.get('moment'), 50), characters=words(s.get('characters'), 60),
                     environment=words(s.get('environment'), 40),
                     action=words(s.get('scene') or ' '.join(str(b.get('action', '')) for b in s.get('beats') or []), 60))
                for i, s in enumerate(segments)]), ensure_ascii=False))])
    try:
        reply = request(payload)
        content = reply['message']['content'] if isinstance(reply, dict) and 'message' in reply else reply
        result = json.loads(content) if isinstance(content, str) else content
    except Exception as exc:  # noqa: BLE001
        print(f'Warning: {model} could not list the recurring references ({exc}); every segment is painted without '
              'reference sheets, so characters will not match between images. Free the GPU and run this step again.', flush=True)
        return []
    entities = clean(result.get('entities') if isinstance(result, dict) else [], len(segments))
    entities = link_leads(entities, story)
    try:  # a second, narrower look: the one pass listed Viktoria's four forms and missed the farmer's bitten hand
        look = second_look(model, segments, entities, request, story)
        entities = complete_outfits(add_forms(entities, look.get('forms'), len(segments), look.get('missing')), look.get('outfits'))
    except Exception as exc:  # noqa: BLE001
        print(f'Missed forms could not be checked ({exc}); the references stand as listed.', flush=True)
    entities = link_leads(entities, story)  # the second look cleans the list again
    if not entities:
        print(f'Warning: {model} listed no recurring references; every segment is painted without reference sheets.', flush=True)
    for entity in entities:
        print(f"Recurring {entity['kind']}: {entity['name']} (segments {', '.join(str(i+1) for i in entity['segments'])})"
              + (f", a form of {entity['base']}" if entity.get('base') else ''), flush=True)
    return entities


def second_look(model, segments, entities, request, story=''):
    """A narrower second pass over the director's list: {forms, missing, outfits}. `forms` are lasting changes of
    appearance left out, one reference at a time ([{base, name, looks, segment}], `segment` being the index of the
    segment in which the change happens; the form shows from the next one); `missing` are recurring references the
    list left out entirely ([{name, kind, looks, segments}]); `outfits` complete the clothes of characters whose
    looks stop short ([{name, outfit}]). One pass over the whole storyline split the lead into four forms and never
    noticed the farmer's bitten hand, dropped the hospital ward one run in three, and dressed the lead in "a lab coat
    over a black t-shirt", which the painter finished with shorts. `story` is the writer's own text."""
    if not entities:
        return {}
    form_schema = dict(type='object', required=['base', 'name', 'looks', 'segment'],
                       properties=dict(base=dict(type='string'), name=dict(type='string'), looks=dict(type='string'),
                                       segment=dict(type='integer')))
    missing_schema = dict(type='object', required=['name', 'kind', 'looks', 'segments'],
                          properties=dict(name=dict(type='string'), kind=dict(type='string', enum=list(KINDS)),
                                          looks=dict(type='string'), segments=dict(type='array', items=dict(type='integer'))))
    outfit_schema = dict(type='object', required=['name', 'outfit'], properties=dict(name=dict(type='string'), outfit=dict(type='string')))
    schema = dict(type='object', required=['forms', 'missing', 'outfits'],
                  properties=dict(forms=dict(type='array', items=form_schema), missing=dict(type='array', items=missing_schema),
                                  outfits=dict(type='array', items=outfit_schema)))
    listed = [dict(name=e['name'], kind=e['kind'], looks=e['looks'], segments=e['segments'],
                   form_of=next((b['name'] for b in entities if b['id'] == e.get('base')), '')) for e in entities]
    payload = dict(model=model, stream=False, think=False, keep_alive=0, format=schema,
                   options=dict(num_ctx=32768, num_predict=4000, temperature=.1),
        messages=[dict(role='system', content=(
            'You check the reference list of a music video told in segments, one painted illustration each, for what '
            'was missed. You are given the storyline segments, the writer\'s original story when there is one (it is '
            'the authority: where the two differ, follow the story), and the references listed so far (a reference '
            'with `form_of` is a changed form of that one, already listed). The film is judged on its consistency: '
            'every character, object and place shown in two or more segments needs a reference, and every lasting '
            'change of one needs its own. Answer with three lists. '
            '`forms`: lasting changes of appearance that were missed. For EACH listed reference, forms included (a '
            'change can come on top of an earlier one), read its segments in order and name every lasting change to '
            'how it looks that a later segment still shows and that is not listed as a form yet: for a character any '
            'injury however small (a bitten, '
            'swollen, bandaged or bleeding hand, a cut, a bruise, a black eye, a lost eye, tooth or finger), a '
            'mutation, transformation, ageing, a change of clothes that stays, or clothes opened, torn or taken off; for an object or place breaking, '
            'repair, dirt, damage, fire, flood or decay. Only changes the storyline or story actually shows, and that '
            'still show once the moment has passed: in a later segment, or at the end of the last segment the thing is '
            'shown in, where a story often ends on its worst change. For each give: `base` (the exact name of the listed '
            'reference it changes, the latest form when there is one); `name` (the thing\'s name with the change in '
            'brackets, e.g. "The farmer (injured)", "the vase (broken)"); `looks` (start with exactly what changed as '
            'written: which part, which side, how far, its colour and texture, nothing softened or added; then '
            'repeat the base\'s unchanged looks, outfit and earlier changes included; the mark and never what made '
            'it: "a deep cut across the left forearm", not "slashed by a sword"); `segment` (the index of the segment '
            'in which the change happens; the form shows from the next segment on, or in that segment when it is the '
            'last one the thing is shown in). '
            '`missing`: every character (person or animal), recognisable object and place that is shown in TWO OR '
            'MORE segments and that the list leaves out entirely: the place several segments are set in, an object '
            'or creature several segments show. For each give `name`, `kind` (character, object or place), `looks` '
            '(one or two sentences with everything needed to draw it identically every time, from the writer\'s '
            'details) and `segments` (the index of every segment it is shown in). Leave out what is listed already, '
            'crowds, weather and passing things. '
            '`outfits`: for every listed character who is a person and whose `looks` do not state a complete outfit '
            '(top, bottom and footwear), the complete outfit in one sentence: the clothes the writer gives them, '
            'completed where the writer says nothing with plain clothes that suit who they are, never the clothes of '
            'the user\'s own picture. Each as {"name": the listed name, "outfit": "..."}. '
            'Return JSON {"forms":[{"base":"...","name":"...","looks":"...","segment":1}],"missing":[{"name":"...",'
            '"kind":"place","looks":"...","segments":[2,3]}],"outfits":[{"name":"...","outfit":"..."}]}, each list '
            'empty when nothing was missed.')),
            dict(role='user', content=json.dumps(dict(story=words(story, STORY_WORDS), references=listed, segments=[
                dict(index=s.get('index', i), moment=words(s.get('moment'), 50), characters=words(s.get('characters'), 60),
                     environment=words(s.get('environment'), 40),
                     action=words(s.get('scene') or ' '.join(str(b.get('action', '')) for b in s.get('beats') or []), 80))
                for i, s in enumerate(segments)]), ensure_ascii=False))])
    reply = request(payload)
    content = reply['message']['content'] if isinstance(reply, dict) and 'message' in reply else reply
    result = json.loads(content) if isinstance(content, str) else content
    if not isinstance(result, dict):
        return {}
    return {key: [f for f in (result.get(key) or []) if isinstance(f, dict)] for key in ('forms', 'missing', 'outfits')}


LOWER_GARMENTS = re.compile(r'\b(trousers|pants|jeans|slacks|chinos|shorts|skirt|dress|gown|robe|overalls|dungarees|'
                            r'leggings|tights|scrubs|kimono|sarong|jumpsuit|suit|habit|cassock|toga|loincloth)\b', re.I)


def complete_outfits(entities, outfits):
    """`entities` with the `outfits` of second_look written into the looks of the characters whose looks name no lower
    garment ("a lab coat over a black t-shirt" was painted with shorts): "Full outfit: ..." is appended."""
    by_name = {str(e.get('name') or '').strip().lower(): e for e in entities}
    for item in outfits or []:
        entity = by_name.get(str(item.get('name') or '').strip().lower())
        outfit = words(item.get('outfit'), 40).strip().rstrip('.')
        if entity is None or entity.get('kind') != 'character' or not outfit or LOWER_GARMENTS.search(entity.get('looks') or ''):
            continue
        entity['looks'] = entity['looks'].rstrip('.') + f'. Full outfit: {outfit}.'
        print(f"Outfit completed: {entity['name']}: {outfit}", flush=True)
    return entities


def add_forms(entities, forms, count, missing=()):
    """`entities` (cleaned) with the missed `forms` (see second_look) added. A form comes from whichever form of the
    thing is showing right after the change, which may be a form itself (paralysed, then pierced): it takes that one's
    segments after the one in which the change happens, and that one keeps those up to and including it. A change in
    the last segment the thing is shown in takes that segment: a story often ends on it. A form that would leave the
    one it comes from nothing begins where it does, so it is the same change listed again and adds nothing, as does a
    name already listed, a base not listed, or a change in no segment the thing is shown in. `missing` references are
    added whole unless one of that name is listed. Cleaned again."""
    if not forms and not missing:
        return entities
    raw = [dict(e) for e in entities]
    by_name = {str(e.get('name') or '').strip().lower(): e for e in raw}
    for entry in missing or []:
        name = words(entry.get('name'), 8)
        if not name or form_stem(name) in {form_stem(e.get('name')) for e in raw}:
            continue
        raw.append(dict(name=name, kind=entry.get('kind'), looks=entry.get('looks'), segments=entry.get('segments'),
                        cast=False, from_cast=False, base=''))
        print(f'Missed reference added: {name}', flush=True)
    for form in forms or []:
        named = by_name.get(str(form.get('base') or '').strip().lower())
        name, looks = words(form.get('name'), 8), words(form.get('looks'), LOOKS_WORDS)
        try:
            at = int(form.get('segment'))
        except (TypeError, ValueError):
            continue
        if named is None or not name or not looks or name.lower() in by_name:
            continue
        stem = form_stem(named['name'])
        family = [e for e in raw if form_stem(e.get('name')) == stem and e.get('kind') == named.get('kind')]
        if not any(s > at for e in family for s in e['segments']):
            at -= 1  # its last segment: that segment shows the form
        showing = [(min(s for s in e['segments'] if s > at), not e.get('base'), i, e)
                   for i, e in enumerate(family) if any(s > at for s in e['segments'])]
        if not showing:
            continue
        base = min(showing, key=lambda item: item[:3])[3]  # a form before the one it comes from, where both claim the segment
        later = [s for s in base['segments'] if s > at]
        kept = [s for s in base['segments'] if s <= at]
        if not kept:
            continue
        base['segments'] = kept
        added = dict(name=name, kind=base['kind'], looks=looks, segments=later, cast=False,
                     from_cast=bool(base.get('cast') or base.get('from_cast')) and base['kind'] == 'character', base=base['name'])
        raw.append(added)
        by_name[name.lower()] = added  # the same answer can build on it
        print(f"Missed form added: {name} (segments {', '.join(str(s+1) for s in later)}), a form of {base['name']}", flush=True)
    return clean(raw, count)


def edited(entry, count, taken=()):
    """An entry from the references editor, checked: a name, a known kind, a description, the images it appears
    in (1-based in the editor, 0-based here) and `base`, the id of the reference it is a changed form of ('' for
    none). Raises ValueError with what is wrong."""
    name = words(entry.get('name'), 8)
    kind = str(entry.get('kind') or '').strip().lower()
    looks = words(entry.get('looks'), LOOKS_WORDS)
    if not name:
        raise ValueError('Give the reference a name')
    if kind not in KINDS:
        raise ValueError('Choose character, object or place')
    if not looks:
        raise ValueError(f'Describe how {name} looks')
    try:
        images = sorted({int(n)-1 for n in entry.get('images') or []})
    except (TypeError, ValueError):
        raise ValueError('Images are numbers, e.g. 1-3, 16') from None
    if any(i < 0 or i >= count for i in images):
        raise ValueError(f'Images go from 1 to {count}')
    key = entry.get('id') or slug(name)
    while not entry.get('id') and key in taken:
        key += '-2'
    base = str(entry.get('base') or '').strip()
    if base and base == key:
        raise ValueError(f'{name} cannot be a form of itself')
    return dict(id=key, name=name, kind=kind, looks=looks, segments=images, base=base,
                cast=bool(entry.get('cast')) and kind == 'character', photo=str(entry.get('photo') or '').strip())


MOOD = ' Visual mood and materials: '


def mood_first(technique):
    """The project's style with the user's visual style and mood ("Dark, horror short, drawn like modern anime...")
    put first: after the generic technique words it was too weak to set the look."""
    text = ' '.join(str(technique or '').split())
    if MOOD.strip() not in text:
        return text
    style, mood = text.split(MOOD.strip(), 1)
    mood = mood.strip().rstrip('.')
    return f'{mood}. {style.strip()}'.strip() if mood else style.strip()


def without_mood(technique):
    """The project's technique without the user's visual style and mood: a place or object sheet painted with "Dark,
    body-horror short. Bloody and gory on death scenes" first got a bleeding woman in three of its four panels."""
    text = ' '.join(str(technique or '').split())
    if MOOD.strip() not in text:
        return text
    return text.split(MOOD.strip(), 1)[0].strip()


def mood_of(technique):
    """The user's visual style and mood alone ('' without one)."""
    text = ' '.join(str(technique or '').split())
    return text.split(MOOD.strip(), 1)[1].strip().rstrip('.') if MOOD.strip() in text else ''


def sheet_style(job, mood=True):
    """The style a sheet is painted in: the project's art style (job['style'], e.g. "...inspired by Alphonse Mucha")
    first, then the user's visual style and mood, then the technique notes. The sheets got only the technique and the
    mood ("drawn like modern anime") and came out as flat cartoons; the scenes kept the art style through the
    project's reference painting, which a sheet may not have (it shows the lead). Without `mood` (a place or an
    object: see without_mood) the mood is left out."""
    from direction.illustration_prompts import style_only_prompt
    style_prompt = style_only_prompt(job.get('style_prompt') or '')
    technique = (mood_first if mood else without_mood)(style_prompt)
    if without_mood(style_prompt).strip():  # the project's own style prompt leads, as it leads every scene prompt
        return technique
    style = art_style_of(job.get('style') or '')  # the app's built-in style only when the project has none
    return f'{style}. {technique}' if style and technique else style or technique


CUTOUT_RULES = re.compile(r'plain white|no scenery|silhouette inside|surrealism|printed marks|blank surfaces|isolated subjects', re.I)


def art_style_of(style):
    """The art-style sentences of the project's style text (direction.illustration_prompts.STYLE), without its
    cut-out rules: "Isolated subjects on plain white, no scenery, shadows or glow" led every sheet and painted it flat
    on white, whatever backdrop and shading the sheet asked for."""
    sentences = re.split(r'(?<=[.!?])\s+', ' '.join(str(style or '').split()))
    return ' '.join(s for s in sentences if s and not CUTOUT_RULES.search(s)).rstrip('.')


def sheet_check_style(technique):
    """What the vision model is told the sheet's style is: the technique, then the mood as the film's, not the
    sheet's (told "bloody and gory" plainly, it failed every clean character sheet for showing no gore)."""
    mood = mood_of(technique)
    return without_mood(technique) + (f" (the mood of the film, which this sheet need not show: {mood})" if mood else '')


def painted_prompt(entity, job):
    """(prompt, exact) for an entity's picture: what it was painted from, as recorded when it was painted, or for a
    sheet painted before that was kept, the prompt built again from today's settings. An uploaded picture was not
    painted, so it has none."""
    if entity.get('uploaded'):
        return '', False
    recorded = str(entity.get('painted_prompt') or '')
    return (recorded, True) if recorded else (sheet_prompt(entity, sheet_style(job, mood=entity.get('kind') == 'character')), False)


WIDE_PANELS = 3   # a place's sheet: three views of it and a close-up, which no scene is staged from


def scene_view(picture, entity, panel=0):
    """What a scene is given of an entity's picture: one view of its sheet (single_view). A place's sheet is cut to one
    panel, which would leave a quarter of a photo of the place, so an uploaded place stays whole."""
    if entity.get('uploaded') and entity.get('kind') == 'place':
        return picture
    return single_view(picture, entity.get('kind'), panel)


def place_panel(entity, segment):
    """Which view of a place's sheet a segment is staged from: its views in turn along the segments that show the place.
    One view for all of them gave every scene there the same shot, so the clips all began alike."""
    segments = sorted(entity.get('segments') or [])
    return segments.index(segment) % WIDE_PANELS if segment in segments else 0


def place_picture(entity, segment):
    """The view of a place a segment is given (scene_view, place_panel), or None without a picture on disk."""
    from PIL import Image
    path = Path(str(entity.get('image') or ''))
    if not entity.get('image') or not path.is_file():
        return None
    with Image.open(path) as source:
        picture = scene_view(source.convert('RGB'), entity, place_panel(entity, segment))
    picture.thumbnail((REFERENCE_PIXELS, REFERENCE_PIXELS))
    return picture


def lead_view(picture):
    """The lead's picture as a scene is given it: a full figure on a plain backdrop is cut to its head and shoulders. Given
    the whole figure the painter copied its pose and its empty backdrop into every scene, whatever the prompt said. A
    portrait, or a photo with a real background, is left as it is."""
    import numpy as np
    a = np.asarray(picture.convert('RGB')).astype(np.int16)
    h, w = a.shape[:2]
    if h < 32 or w < 32:
        return picture
    border = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3), a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
    if np.abs(border-np.median(border, axis=0)).sum(axis=1).mean() > 30:
        return picture  # no plain backdrop: a real photo, whose setting is not a blank page
    mask = np.abs(a-np.median(border, axis=0)).sum(axis=2) > 40
    if not mask.any():
        return picture
    ys, xs = np.where(mask.any(axis=1))[0], np.where(mask.any(axis=0))[0]
    top, bottom, left, right = ys[0], ys[-1]+1, xs[0], xs[-1]+1
    if (bottom-top) < 1.5*(right-left):
        return picture  # not a standing figure
    tall = int(.3*(bottom-top))
    head = mask[top:top+tall//2]  # the head's own columns, which the arms and skirt below do not widen
    cols = np.where(head.any(axis=0))[0]
    middle, half = (cols[0]+cols[-1])//2, tall//2+tall//4
    return picture.crop((max(0, middle-half), max(0, top-tall//10), min(w, middle+half), top+tall))


def _runs(flags, min_gap):
    """[(start, end)] of the True runs in `flags`, joining runs split by fewer than `min_gap` False entries."""
    out, start, gap, end = [], None, 0, 0
    for i, flag in enumerate(flags):
        if flag:
            if start is None:
                start = i
            gap, end = 0, i+1
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                out.append((start, end))
                start = None
    if start is not None:
        out.append((start, end))
    return out


def single_view(picture, kind, panel=0):
    """One view cut from a reference sheet, for a scene: the first full-body figure of a character, the first view of
    an object, a panel of a place (`panel` counts along the rows from the top left). Given the whole sheet, Qwen Image Edit edited its rows of repeated views
    into the scene instead of painting the scene. The sheet itself is returned when no view can be told apart."""
    import numpy as np
    a = np.asarray(picture.convert('RGB')).astype(np.int16)
    h, w = a.shape[:2]
    if h < 32 or w < 32:
        return picture
    border = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3), a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
    mask = np.abs(a-np.median(border, axis=0)).sum(axis=2) > 40
    if not mask.any():
        return picture

    def trimmed(left, top, right, bottom, pad=.04):
        sub = mask[top:bottom, left:right]
        ys, xs = np.where(sub.any(axis=1))[0], np.where(sub.any(axis=0))[0]
        if not len(ys) or not len(xs):
            return None
        t, b, l, r = top+ys[0], top+ys[-1]+1, left+xs[0], left+xs[-1]+1
        p = int(pad*max(b-t, r-l))
        return max(0, l-p), max(0, t-p), min(w, r+p), min(h, b+p)
    if kind == 'place':  # four panels, in a grid or in a row: the first one, found by the gaps between them
        panel_rows = _runs(mask.mean(axis=1) > .2, max(4, h//200))
        panel_cols = _runs(mask.mean(axis=0) > .2, max(4, w//200))
        if len(panel_rows)*len(panel_cols) >= 2:
            cells = [(row, col) for row in panel_rows for col in panel_cols]
            row, col = cells[panel % len(cells)]
            box = trimmed(col[0], row[0], col[1], row[1], pad=0)
            if box:
                return picture.crop(box)
        whole = trimmed(0, 0, w, h, pad=0)
        if not whole:
            return picture
        l, t, r, b = whole
        box = trimmed(l, t, l+(r-l)//2, t+(b-t)//2, pad=0)
        return picture.crop(box) if box else picture
    rows = _runs(mask.mean(axis=1) > .004, max(4, h//60))
    if not rows:
        return picture
    top, bottom = max(rows, key=lambda r: r[1]-r[0])  # the tallest band: the full-body row
    cols = _runs(mask[top:bottom].mean(axis=0) > .004, max(4, w//80))
    if len(cols) < 2 and len(rows) < 2:
        return picture
    left, right = cols[0] if cols else (0, w)
    box = trimmed(left, top, right, bottom, pad=.06)
    if not box:
        return picture
    box = list(box)
    if box[2]-box[0] > .6*w:  # views whose gaps could not be told from the backdrop: the left half of them
        box[2] = box[0]+(box[2]-box[0])//2
    return picture.crop(tuple(box))


def sheet_prompt(entity, technique):
    """The prompt that paints an entity's reference picture, as an artist's model sheet: a character in turnaround
    views with a row of expressions (poses for an animal), an object from several sides, a place in one wide view."""
    if str(entity.get('prompt') or '').strip():  # written by the user in the Repaint dialog
        return str(entity['prompt']).strip()
    name, looks = entity['name'], entity['looks'].rstrip('.')
    # a changed form: every mark the story gives it, exactly (a missing left eye is not a scar over the right one)
    exact = ('' if not entity.get('base') and not re.search(r'\(.+\)$', name) else
             f'{name} is a changed form of the same {entity["kind"]}: show every lasting change exactly as the '
             'description states it, on the side and part named, nothing softened, nothing added, nothing healed, '
             'in every view and close-up; everything the description does not change stays as it was. Left and right '
             'are its own, not the viewer\'s: in a front view its left side is on the right of the picture. The '
             'change is exactly as large and as severe as stated, and every view that shows that part shows it the '
             'same. A change on a surface a relaxed pose hides, such as a palm or the inside of an arm, is shown by '
             'turning or raising that part towards the viewer in every view that shows it, so the named surface is '
             'the one seen. The change stays only on the part named: the face, head and every other part keep their '
             'looks. The last picture on the sheet is not a portrait: it shows only the changed part itself, large '
             'and clear, cut off from the rest. ')
    looks = f'{looks}. {exact}'.rstrip() if exact else looks
    # Drawn on its own: a description often says where it is ("in the corner of the room"), and the sheet must not
    # paint that room, or the scene would be copied instead of the thing itself.
    alone = ('Drawn alone and isolated, taken out of any room, landscape or scene the description mentions: no '
             'furniture, walls, floor or background objects. ')
    # rendered as fully as a finished scene, in its mood: a "model sheet" on flat grey light came out as a flat cartoon;
    # how lines and brushwork look is the project style's to say, so none are named here
    rendered = ('Every view fully rendered in the art style above, with the same shading, lighting, texture and detail '
                'as a finished illustration in that mood, not a flat cartoon turnaround and not an unfinished drawing. '
                'A plain, pure white backdrop with nothing on it. ')
    if (entity['kind'] == 'character' and re.search(r'\bcolou?r\b', str(technique), re.I)
            and not re.search(r'\b(monochrome|gr[ae]yscale|black[ -]and[ -]white)\b', str(technique), re.I)):
        rendered += ('Render in full colour, with natural skin undertones, distinct warm and cool hues and coloured '
                     'shadows. Pale skin and white clothing retain subtle reflected colour. ')
    if entity['kind'] == 'character':
        body = (f'Character reference sheet of {name}: {looks}. {alone}{rendered}'
                'The same single character drawn several times as separate, non-overlapping figures with identical '
                'proportions, colours and outfit, each from a different camera angle: a top row of full-body views '
                '(front, three-quarter, side profile, back), and a bottom row of head-and-shoulders close-ups with '
                'expressions that fit the story\'s mood or, for an animal or creature, poses that fit it. Only this '
                'one character: every figure on the sheet is this same character (or the same animal or creature), '
                'and no other person, animal or creature appears anywhere, not in the background either.')
    elif entity['kind'] == 'object':
        # the object by itself, said positively: Qwen Image 2.1 takes no negative prompt, so "no person, no hand" drew
        # a person and a hand
        body = (f'Object reference sheet of {name}: {looks}. The object by itself, resting untouched on the backdrop, '
                f'the only thing on the sheet. {alone}{rendered}'
                'The same object drawn four times as separate, non-overlapping views from different camera angles, '
                'evenly spaced in a row: from the front, from the side, from three-quarter above, and a close-up of '
                'its surface detail. Identical shape, size, material and colour in every view; each view is this '
                'object alone on the plain backdrop.')
    else:
        # separate panels, not one composed view: a single scene-like picture was repainted by the edit model instead
        # of the segment's own scene; an empty place, said positively (see the object sheet)
        # the style says how it is drawn, not what is there: "Mucha poster" built a palace in the rice paddy, hung
        # medallions in the ward and made the close-up panel a poster of a woman; three panels also came out alike
        body = (f'Location reference sheet of {name}: {looks}. Include the occupants explicitly described, such as '
                'patients, staff or relatives; otherwise the place stands empty and unoccupied. Show only what the description names, indoors if it is indoors and outdoors under open sky '
                'if it is outdoors. The art style above decides only how it is drawn, never what is there: this is an '
                'ordinary, real place, plain and undecorated, exactly as described, with nothing added. '
                'Fully rendered and lit to suit its mood. Four separate wide panels in a two-by-two grid, with clear '
                'white gaps between them on a plain, pure white backdrop, each from its own camera position in the same place. '
                'Top left: a wide view from one end. Top right: the camera turned right around at the far end, looking back '
                'the other way, so what was ahead is now behind it and left and right are swapped. Bottom left: a view from '
                'beside it, close and low, looking straight across at one side. Bottom right: a tight close-up of one real '
                'feature named in the description. No two panels share a viewpoint or a composition. All four show the same '
                'moment, at one time of day in one light: where the description says the light changes, use the first it '
                'names. Layout, materials and colours stay the same across them, and every panel shows the place with its described occupancy.')
    # the art style leads, word for word as it leads every scene prompt, so the sheet is painted like the scenes; a
    # place or an object is painted without the mood (see without_mood)
    from direction.prompt_fit import style_prefix
    technique = mood_first(technique) if entity['kind'] == 'character' else without_people(without_mood(technique))
    return style_prefix(technique) + body + ' No text of any kind: no title, name, labels such as "front view", captions, arrows, signatures or printed marks.'


PEOPLE_WORDS = re.compile(r'\b(hair|face|faces|skin|eyes?|figures?|bod(?:y|ies)|person|people|portraits?|characters?|'
                          r'anatomy|hands?(?!-)|lips|expressions?)\b', re.I)


def without_people(technique):
    """The technique without its clauses about people ("hair drawn as a few long smooth strands"): on a place or
    object sheet each one put a woman with long hair into every panel, there being nobody to draw it on."""
    parts = re.split(r'(?<=[.;])\s+', ' '.join(str(technique or '').split()))
    kept = []
    for part in parts:
        clauses = [c for c in re.split(r';\s*', part) if c.strip()]
        clean_ones = [c for c in clauses if not PEOPLE_WORDS.search(c)]
        if clean_ones:
            kept.append('; '.join(c.rstrip('.;') for c in clean_ones) + (part[-1] if part[-1] in '.;' else ''))
    return ' '.join(kept).replace(';.', '.')


SHEET_WIDTH, SHEET_HEIGHT = 2560, 1440   # 16:9, 1440p: each of a character's four full-body views is about 720p tall


def sheet_size(entity):
    """A sheet is wide (several views side by side); so is a place. Painted at 1440p so that the one view a scene is
    cut (single_view) is clear at about 720p: at 1536x864 each figure was some 350 pixels wide, and the small marks
    the story turns on (a missing eye, tooth or finger) were lost. models.image.catalog.sheet_dimensions bounds it
    for the card."""
    return SHEET_WIDTH, SHEET_HEIGHT


# How sheets are painted. 1 handed the model a finished scene or the user's photo whatever the sheet showed, which
# leaked the lead into other characters; 2 painted from the description alone, losing the art style and the lead's
# face in a character that is the lead transformed; 3 gives each picture one role (see sheet_inputs); 4 paints in the
# project's art style before its mood (see sheet_style: 3 came out as flat cartoons). A picture painted another way is
# painted again. 5: the lead's sheet also takes the reference picture's art style (LEAD_ROLE). 6: with Qwen Image
# 2.1 every sheet took a person photo as its style guide. 7: no sheet does (the person was painted into the lab,
# the hallway and the possum, and every check failed on her); the style comes from the words alone. 8: sheets are
# 2560x1440 (sheet_size); a changed form (base) is painted from the sheet of the form it comes from (BASE_ROLE); the
# cast gets a sheet of its own, from the lead's photo (CAST_ROLE).
SHEET_VERSION = 8


TITLES = {'dr', 'mr', 'mrs', 'ms', 'miss', 'sir', 'lady', 'lord', 'the', 'detective', 'officer', 'professor', 'prof'}


def lead_names(story):
    """Words of the main character's name as the storyline calls them ("Dr. Aris Thorne" -> aris, thorne): the
    cast entity's name, else the name most segments introduce first in their characters ("Name: looks")."""
    names = [e.get('name', '') for e in (story or {}).get('entities') or [] if e.get('cast')]
    if not names:
        from collections import Counter
        firsts = Counter()
        others = {str(e.get('name') or '').lower() for e in (story or {}).get('entities') or []}
        for segment in (story or {}).get('segments') or []:
            match = re.match(r'\s*([A-Z][\w.\' -]{1,40}?):', str(segment.get('characters') or ''))
            if match and match.group(1).strip().lower() not in others:  # a listed reference is not the lead
                firsts[match.group(1).strip()] += 1
        names = [firsts.most_common(1)[0][0]] if firsts else []
    return {w for name in names for w in re.findall(r"[a-z]+", name.lower()) if len(w) > 2 and w not in TITLES}


def from_lead(entity, story, depth=0):
    """This character is the lead in another form (the director said so, it is a form of the cast entity, or it
    carries the lead's name)."""
    if entity.get('kind') != 'character' or entity.get('cast'):
        return False
    if entity.get('from_cast'):
        return True
    base = base_of(story, entity)
    if base is not None and depth < MAX_ENTITIES:
        return bool(base.get('cast')) or from_lead(base, story, depth+1)
    own = set(re.findall(r'[a-z]+', str(entity.get('name') or '').lower()))
    return bool(own & lead_names(story))


# The project's reference picture is often an illustration, not a photograph: it is the art style as well as the person.
LEAD_ROLE = ('Picture 1 shows the person this character is and sets the art style: keep their face, features and skin tone '
             'recognisable, changed exactly as the description says, and paint the whole sheet in exactly its linework, '
             'shading, palette and finish. Do not copy its clothes, pose, background, frame or lettering. ')
CAST_ROLE = ('Picture 1 shows {name}, this character, and sets the art style: paint the whole sheet in exactly its '
             'linework, shading, palette and finish, and give every figure exactly this face, features, hair, skin '
             'tone, age and build. Every figure '
             'wears only the outfit the description below gives, from top to shoes: nothing the photo shows them '
             'wearing (no skirt, top, dress, shoes or jewellery from the photo), and not the photo\'s pose, '
             'background, frame or lettering. Where the description names no shoes, plain simple closed shoes that '
             'suit the outfit, never the photo\'s sandals or shoes. ')
STYLE_ROLE = ('Picture 1 shows the art style only: match its rendering technique, brushwork and colour treatment; do '
              'not copy its people, objects or composition. ')
BASE_ROLE = {
    'character': ('Picture 1 is the reference sheet of {base}, who {name} is: the same person (or animal) in the same art '
                  'style. Keep the face, features, skin tone, hair, build, proportions and colours exactly as in picture 1, '
                  'in the same views and layout, and change only what the description says changed, exactly as it says: '
                  'the part and side named, nothing else, nothing softened. The clothes are the ones the description '
                  'names, from top to shoes, in every full-body view AND every close-up, even where they differ from '
                  'picture 1; only where it names none are they picture 1\'s. Do not copy picture 1 unchanged. '),
    'object': ('Picture 1 is the reference sheet of {base}, which {name} is: the same object in the same art style. Keep '
               'its shape, size, material, colours and details exactly as in picture 1, in the same views, and change only '
               'what the description says changed, exactly as it says: the parts named, nothing else. Do not copy '
               'picture 1 unchanged. '),
    'place': ('Picture 1 is the reference sheet of {base}, which {name} is: the same place in the same art style. Keep its '
              'layout, materials, landmarks and viewpoints exactly as in picture 1, panel for panel, and change only what '
              'the description says changed, exactly as it says: the areas named, nothing else. Do not copy picture 1 '
              'unchanged. ')}


def base_of(story, entity):
    """The entity this one is a changed form of (its `base` id, or its name without the form), or None."""
    entities = (story or {}).get('entities') or []
    return base_entity(entity, entities, entity.get('base') or '')


def base_sheet(story, entity):
    """The painted picture of the form this entity comes from, as a PIL image, or None when it has none on disk yet
    (an uploaded picture of it counts)."""
    base = base_of(story, entity)
    path = Path(str(base.get('image') or '')) if base else None
    if not path or not path.is_file() or not (current_sheet(base) or base.get('uploaded')):
        return None
    from PIL import Image
    with Image.open(path) as source:
        picture = source.convert('RGB')
    picture.thumbnail((REFERENCE_PIXELS, REFERENCE_PIXELS))
    return picture


def painting_order(entities, story):
    """These entities with every form's base before it, pulling in a base that has no current picture yet (the form
    is painted from it, so it must come first), each once."""
    listed = {e.get('id'): e for e in (story or {}).get('entities') or []}
    ordered, seen = [], set()

    def add(entity, depth=0):
        if entity.get('id') in seen or depth > MAX_ENTITIES:
            return
        from direction.reference_edits import dependencies
        for dependency in dependencies(entity, story):
            base = listed.get(dependency)
            if base is None:
                continue
            if not (base.get('image') and Path(str(base['image'])).is_file() and (current_sheet(base) or base.get('uploaded'))):
                add(base, depth+1)
        seen.add(entity.get('id'))
        ordered.append(entity)
    for entity in entities:
        add(entity)
    return ordered


def sheet_inputs(entity, story, references, likeness, takes_pictures, edits=True, base_picture=None, lead_picture=None):
    """(pictures, role sentence) a sheet is painted with. `references` are (picture, kind) pairs, kind being what the
    vision model said the picture shows ('person', 'animal', 'object', 'place', 'unclear', or None when it was never
    described). A changed form gets the sheet of the form it comes from (`base_picture`, see base_sheet), so
    Viktoria (mutated) is painted from Viktoria's sheet; the cast and the lead in another form get the lead's photo;
    any other sheet gets, as its style guide, a picture of an object or a place, and nothing else: a photo of a
    person or an animal is never a style guide, whichever model paints (Qwen Image Edit and Qwen Image 2.1 both drew
    the person into other sheets, and every check failed on her). Without a picture the sheet is painted from the
    words, which carry the art style. `edits` is kept for callers; it no longer changes the choice."""
    if not takes_pictures:
        return [], ''
    if base_picture is not None:
        base = base_of(story, entity)
        return [base_picture], BASE_ROLE.get(entity.get('kind'), BASE_ROLE['object']).format(
            base=(base or {}).get('name') or 'the original', name=entity.get('name') or 'this one')
    if lead_picture is not None:  # the writer's tag says which picture shows them, whatever the project's other settings
        if entity.get('cast'):
            return [lead_picture], CAST_ROLE.format(name=entity.get('name') or 'the main character')
        return [lead_picture], LEAD_ROLE
    if not references:
        return [], ''
    people = [picture for picture, kind in references if kind == 'person']
    if entity.get('cast') and people and likeness:
        return [people[0]], CAST_ROLE.format(name=entity.get('name') or 'the main character')
    if from_lead(entity, story) and people and likeness:
        return [people[0]], LEAD_ROLE
    styles = [picture for picture, kind in references if kind in ('object', 'place')]
    if styles:
        return [styles[0]], STYLE_ROLE
    return [], ''
    people = [picture for picture, kind in references if kind == 'person']
    if from_lead(entity, story) and people and likeness:
        return [people[0]], LEAD_ROLE
    styles = [picture for picture, kind in references if kind in ('object', 'place')]
    if styles:
        return [styles[0]], STYLE_ROLE
    return [], ''


def photo_kind(path):
    """What the vision model said a reference picture shows ('person', 'animal', 'object', 'place', 'unclear'), or
    None when it has not been described."""
    try:
        data = Path(path).read_bytes()
        cached = json.loads(Path(path).with_name(f'subject.{hashlib.sha256(data).hexdigest()[:16]}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    subject = cached.get('subject') if isinstance(cached, dict) else None
    return subject.get('kind') if isinstance(subject, dict) else None


def earlier_sheets(manifest, entity, limit=None):
    """The entity's earlier pictures still on disk (each repaint writes a new file next to the old one), newest
    first, without the one in use. Shown to the user to look at; none is ever put back in use, since each was
    replaced after a failed check or on request."""
    current = Path(str(entity.get('image') or '')).resolve() if entity.get('image') else None
    folder = Path(manifest).parent/'entities'
    found = [p for p in folder.glob(f"{entity.get('id', '')}.*.png")
             if '.tmp' not in p.name and (current is None or p.resolve() != current)] if entity.get('id') else []
    found += [Path(p) for p in entity.get('image_history', []) if Path(p).is_file() and Path(p).resolve() != current]
    # Regeneration archives old output, but the editor must still offer those versions for explicit selection.
    for archive in Path(manifest).parent.glob('previous-*'):
        found += list(archive.rglob(f"{entity.get('id', '')}.*.png")) if entity.get('id') else []
        for name in ('story-before.json', 'story.json'):
            try:
                previous = json.loads((archive/name).read_text(encoding='utf-8'))
                entry = next((e for e in previous.get('entities', []) if e.get('id') == entity.get('id')), {})
                found += [Path(p) for p in [entry.get('image'), *entry.get('image_history', [])] if p and Path(p).is_file()]
            except (OSError, ValueError):
                pass
    from direction.reference_edits import project_root
    try:
        discarded = set(json.loads((project_root(manifest)/'reference-discarded.json').read_text(encoding='utf-8')).get(entity.get('id'), []))
    except (OSError, ValueError):
        discarded = set()
    found = [p for p in found if p.resolve() != current and str(p.resolve()) not in discarded and '.tmp' not in p.name]
    found = list(dict.fromkeys(found))
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def current_sheet(entity):
    """The entity's linked picture was painted the current way (see SHEET_VERSION)."""
    return int(entity.get('sheet_version') or 1) == SHEET_VERSION or bool(entity.get('uploaded'))


def sheet_path(manifest, entity, technique, model):
    """Where an entity's picture is kept; the name changes with what it shows (name, kind, looks), the technique, the
    image model and its repaint count, so a picture painted for an older description, or one the user asked to
    repaint, is never reused. The prompt's wording is left out on purpose: rewording the sheet template must not
    make every painted picture look out of date."""
    fields = (entity.get('name'), entity.get('kind'), entity.get('looks'), str(technique or '').strip().rstrip('.'),
              model or '', str(entity.get('repaint') or 0), str(entity.get('prompt') or '').strip(), f'v{SHEET_VERSION}')
    if entity.get('reference_generation'):
        fields += (entity['reference_generation'],)
    if entity.get('reference_edit_revision'):
        fields += (entity['reference_edit_revision'],)
    digest = hashlib.sha256('\n'.join(str(f or '') for f in fields).encode()).hexdigest()[:10]
    return Path(manifest).parent/'entities'/f"{entity['id']}.{digest}.png"


PICTURED = ('character', 'object', 'place')  # a place as a location sheet in panels (see sheet_prompt)


def segment_entities(story, index, painted=True, pictured=False):
    """The entities shown in segment `index`, in reference order; with `painted` only those that have a picture,
    with `pictured` only the kinds that get one. A place is painted as a location sheet in separate panels: one whole
    composed view was repainted by the edit model (Qwen Image Edit) instead of the segment's own scene. Places come
    last (KINDS), so they only take a reference slot the scene's characters and objects leave free."""
    return [e for e in (story or {}).get('entities') or []
            if index in e.get('segments', []) and (not pictured or e.get('kind') in PICTURED)
            and (not painted or Path(str(e.get('image') or '')).is_file())]


# What the scene prompts say when every reference is a style reference; wrong once some show who is in the scene.
TECHNIQUE_ONLY = (('Reference images guide technique only, never subject matter. ', ''),
                  ('REFERENCE ROLE: rendering technique ONLY. ', 'REFERENCE ROLE: as listed at the start. '),
                  ('Do not copy reference people, clothes, objects or composition. ', ''))


# The project's pictures set the art style of every scene, so the model is told that first and plainly; a
# reference sheet's title, labels and frame must not turn into the scene's layout.
STYLE_JOB = ('sets the art style of the whole picture: paint everything in its linework, shading, palette and '
             'finish; never copy its layout, frame, labels or lettering')
# An edit model takes its first picture as the one to change, and left alone it hands back that picture with the
# scene's subject pasted on, on the picture's own white backdrop.
NEW_PICTURE = ('Paint a new full-frame picture of the scene described below, its setting filling the whole background. '
               'No reference image is the picture to edit: never keep the backdrop, blank space or layout of any of them.')


def reference_order(entities):
    """(characters and objects, places). The pictures go to the model as the project's, these characters and objects,
    the illustration's own, then the places. Qwen does not document what the order does. Seen on 2026-11-04 with Qwen
    Image 2.1: with a white object sheet last it handed that sheet back, and with a place last it painted the place."""
    return [e for e in entities if e.get('kind') != 'place'], [e for e in entities if e.get('kind') == 'place']


def reference_role(first, entities, own, rest, likeness, rest_names=None):
    """What each reference image is for, in the order they are given: the project's references (the art style, and
    in likeness mode who the main character is), then the segment's own references, then the entities' pictures.
    It leads the prompt so a token limit never cuts it. In likeness mode `rest_names` names who each project photo
    shows, or None for a photo of someone not in this scene, which then guides the style only."""
    parts, n = [], 1
    for k in range(rest):
        name = rest_names[k] if likeness and rest_names and k < len(rest_names) else None
        if name:
            parts.append(f'Reference image {n} shows {name} and {STYLE_JOB}. Draw them with exactly this face, hair '
                         'or coat, build, age and colouring, with clothing and pose from this scene.')
        elif likeness and not rest_names:
            parts.append(f'Reference image {n} shows the main character and {STYLE_JOB}. Keep their face, hair, skin '
                         'tone, age and gender.')
        else:
            parts.append(f'Reference image {n} {STYLE_JOB}. Do not draw its people or objects in this scene.')
        n += 1
    subjects, places = reference_order(entities)
    for entity in subjects:
        what = ('them ONCE, with exactly this look (face, hair, build, clothes, colours, proportions), in this '
                "scene's pose and setting" if entity['kind'] == 'character' else
                'it ONCE, with exactly this shape and colour, at its real size where this scene places it')
        parts.append(f"Reference image {n} shows {entity['name']} alone on a plain backdrop: draw {what}, "
                     "painted in the same rendering and light as the rest of the scene; never copy its pose or its "
                     "plain backdrop.")
        n += 1
    if own:
        parts.append(f'Reference image{"s" if own > 1 else ""} {", ".join(str(n+k) for k in range(own))}: who or what '
                     "this scene is about; keep their looks, painted in this scene's own pose, viewpoint and composition. "
                     'Where one has several panels or views, they show one subject: never copy its panels, labels, '
                     'arrows or backdrop.')
        n += own
    for entity in places:
        parts.append(f"Reference image {n} is one view of {entity['name']}: keep its layout, materials, colours "
                     "and landmarks, painted from this scene's own viewpoint and composition; do not copy the view "
                     "itself.")
        n += 1
    if parts:
        for old, new in TECHNIQUE_ONLY:
            first = first.replace(old, new)
    if not likeness:
        from direction.illustration_prompts import style_only_prompt
        first = style_only_prompt(first)
    if parts and any(e.get('kind') == 'character' for e in entities):
        first += ' Characters look at the people, objects or action they are engaged with, not at the camera, unless direct-to-camera gaze is explicitly requested in this scene.'
    return ' '.join([NEW_PICTURE]+parts)+' '+first if parts else first


def reference_tags(prompt, own_names=(), rest=0, entities=()):
    """Tags in a scene prompt that name a reference picture, each turned into the number the model sees that picture
    under (see reference_order): @photo1, @photo2 for the project's reference photos; @image1, @image2, @image3 or
    @<file name> (@Stick_Insect.png, @Stick_Insect) for the illustration's own pictures; and @<Name> (@Stick_Insects,
    @The_Lab, @"The Lab") for a recurring reference shown in the image. A tag naming nothing the model is given is
    dropped."""
    own = len(own_names)
    key = lambda s: re.sub(r'[^a-z0-9]+', '', str(s).lower())
    subjects, places = reference_order(entities)
    before_own = rest+len(subjects)
    numbers = {}
    for k, name in enumerate(own_names):
        numbers.setdefault(key(name), before_own+k+1)
        numbers.setdefault(key(Path(name).stem), before_own+k+1)
    for k, entity in enumerate(subjects):
        numbers.setdefault(key(entity.get('name', '')), rest+k+1)
    for k, entity in enumerate(places):
        numbers.setdefault(key(entity.get('name', '')), before_own+own+k+1)

    def swap(match):
        tag = match.group(1) or match.group(2)
        if re.fullmatch(r'image\s*\d+', tag, re.I):
            k = int(re.sub(r'\D', '', tag))
            return f'reference image {before_own+k}' if 1 <= k <= own else ''
        if re.fullmatch(r'photo\s*\d+', tag, re.I):
            k = int(re.sub(r'\D', '', tag))
            return f'reference image {k}' if 1 <= k <= rest else ''
        number = numbers.get(key(tag))
        return f'reference image {number}' if number else ''
    text = re.sub(r'@(?:"([^"]+)"|((?:image|photo)\s*\d+(?!\w|\.\w)|[\w\-]+(?:\.\w+)?))', swap, str(prompt or ''))   # a name, or a file name
    text = re.sub(r'\s+([,.;:!?])', r'\1', re.sub(r'[ \t]{2,}', ' ', text))   # a dropped tag leaves no stray spaces
    return re.sub(r',([.;:!?])', r'\1', text).strip()                           # nor a comma before the full stop


def own_picture_tags(prompt, own, rest=0):
    """@imageN tags only (see reference_tags), for callers that know just how many own pictures there are."""
    return reference_tags(prompt, [f'own-{k+1}' for k in range(own)], rest)


PERSON_WORDS = r'\b(she|her|he|him|they|woman|women|man|men|girl|boy|lady|person|people|detective|traveller|figure)\b'


def photo_subject(path):
    """The saved vision description of a reference photo ({kind, who, ...}; see reference_character.describe_subject),
    or None when it has not been described."""
    try:
        data = Path(path).read_bytes()
        cached = json.loads(Path(path).with_name(f'subject.{hashlib.sha256(data).hexdigest()[:16]}.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    subject = cached.get('subject') if isinstance(cached, dict) else None
    return subject if isinstance(subject, dict) and subject.get('kind') in ('person', 'animal') else None


def shows_subject(subject, text):
    """Whether a scene, from its text, shows the subject of a reference photo: a person for a person photo, the
    animal named in the photo's description (a bulldog, so also 'dog') for an animal photo. Unknown subjects count
    as shown, so a photo the vision model never described is still passed on as before."""
    if not subject:
        return True
    text = str(text or '').lower()
    if subject.get('kind') == 'person':
        return bool(re.search(PERSON_WORDS, text))
    nouns = re.findall(r'[a-z]+', str(subject.get('who') or '').lower())
    keys = {nouns[-1]} if nouns else set()
    for family, extra in (('dog', ('dog', 'puppy')), ('cat', ('cat', 'kitten')), ('horse', ('horse', 'pony'))):
        if any(n.endswith(family) for n in nouns):
            keys.update(extra)
    return any(re.search(rf'\b{re.escape(k)}s?\b', text) for k in keys)


def choose_references(own, entities, rest, likeness, limit=MAX_REFERENCES):
    """(entities used, project references used) for one image within the model's `limit`: the segment's own
    references first, then the entities shown in it, then the project's references; one slot always stays for the
    project's references, which set every scene's art style (and in likeness mode show the cast)."""
    keep = 1 if rest else 0
    entities = list(entities)[:max(0, limit-own-keep)]
    return entities, list(rest)[:max(0, limit-own-len(entities))]


def uses_entity_sheet(entity, likeness, has_project_references):
    """A lead's photo substitutes for its sheet only in likeness mode; an edited sheet always wins."""
    return bool(entity.get('uploaded') or not entity.get('cast') or not likeness or not has_project_references)
