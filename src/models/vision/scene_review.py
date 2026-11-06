"""Ground illustration verification in the saved scene and its actual character-reference pictures."""
import base64
import hashlib
import io
import json
from pathlib import Path
from PIL import Image


def context_for(manifest, index):
    from direction.story import load
    from core.files import cached_digest
    story = load(manifest) or {}
    segment = next((s for s in story.get('segments', []) if s.get('index') == index), {})
    characters = []
    for entity in story.get('entities', []):
        if entity.get('kind') != 'character' or index not in entity.get('segments', []):
            continue
        path = Path(str(entity.get('image') or ''))
        characters.append(dict(id=entity['id'],name=entity['name'],looks=entity.get('looks',''),
                               path=str(path) if path.is_file() else '',sha=cached_digest(path) if path.is_file() else ''))
    context = dict(scene={k:segment.get(k,'') for k in ('moment','characters','environment','camera')},
                   opening_action=(segment.get('beats') or [{}])[0].get('action',''), characters=characters)
    context['signature'] = hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
    return context


def extend(payload, context):
    labels = []
    for character in context['characters']:
        if character['path']:
            with Image.open(character['path']) as source:
                picture=source.convert('RGB');picture.thumbnail((768,768));buffer=io.BytesIO();picture.save(buffer,'JPEG',quality=90)
            payload['messages'][0]['images'].append(base64.b64encode(buffer.getvalue()).decode())
            labels.append(dict(id=character['id'],name=character['name'],looks=character['looks'],reference_image=len(payload['messages'][0]['images'])))
        else:
            labels.append(dict(id=character['id'],name=character['name'],looks=character['looks'],reference_image=None))
    payload['messages'][0]['content'] += (
        '\nSCENE AND IDENTITY VERIFICATION: Image 1 is the scene being reviewed. Additional images are labelled '
        'character identity references, never alternative scenes or art-style identities. Compare each named person '
        'with their assigned reference: face, apparent age, hair, proportions and distinctive features. Clothing '
        'and deliberate transformations follow the scene instruction. Do not accept a different person just because '
        'the style and anatomy pass. Missing or obscured reference/face means matches=null and uncertain=true. '
        'Check the intended people, action, setting and relationships. This image is the opening frame; do not '
        'demand a later action outcome prematurely. Check natural poses and where eyes look: unrequested posing '
        'or looking straight at the viewer instead of the task is a pose/gaze mismatch when clearly visible. '
        'Direct-to-camera gaze is allowed if explicitly requested; never guess gaze on tiny/hidden faces. '
        'Return scene_check and one character_checks entry per supplied id, with concise visible evidence. '
        'Scene: '+json.dumps({k:v for k,v in context.items() if k not in ('characters','signature')})+
        '\nCharacter references: '+json.dumps(labels))
    check=dict(type='object',properties=dict(matches=dict(type=['boolean','null']),pose_gaze_matches=dict(type=['boolean','null']),
               evidence=dict(type='string'),uncertain=dict(type='boolean')),required=['matches','pose_gaze_matches','evidence','uncertain'])
    character=dict(type='object',properties=dict(id=dict(type='string'),name=dict(type='string'),matches=dict(type=['boolean','null']),
                   evidence=dict(type='string'),uncertain=dict(type='boolean')),required=['id','name','matches','evidence','uncertain'])
    payload['format']['properties'].update(scene_check=check,character_checks=dict(type='array',items=character))
    payload['format']['required'] += ['scene_check','character_checks']
    payload['options']['num_ctx']=max(16384,payload['options'].get('num_ctx',8192))


def validate(result, context):
    scene=result.get('scene_check')
    checks=result.get('character_checks')
    if not isinstance(scene,dict) or not isinstance(checks,list):
        raise ValueError('review omitted scene or character verification')
    if any(not isinstance(c,dict) or not isinstance(c.get('id'),str) or not isinstance(c.get('name'),str) for c in checks) or sorted(c.get('id','') for c in checks)!=sorted(c['id'] for c in context['characters']):
        raise ValueError('review omitted or duplicated a named character')
    for check in [scene,*checks]:
        if type(check.get('uncertain')) is not bool or not isinstance(check.get('evidence'),str):
            raise ValueError('review omitted visible scene/identity evidence')
        for key in (('matches','pose_gaze_matches') if check is scene else ('matches',)):
            if key not in check or check[key] is not None and type(check[key]) is not bool:
                raise ValueError('invalid scene/identity verdict')
            if check[key] is None and not check['uncertain']:
                raise ValueError('unassessed scene/identity must be marked uncertain')
    for expected,check in zip(sorted(context['characters'],key=lambda c:c['id']),sorted(checks,key=lambda c:c['id'])):
        if not expected['path'] and check['matches'] is not None:
            raise ValueError('identity cannot be verified without its reference image')


def apply_verdict(result):
    scene=result['scene_check']
    result['scene_mismatch']=not scene['uncertain'] and (scene['matches'] is False or scene['pose_gaze_matches'] is False)
    result['identity_mismatch']=any(c['matches'] is False and not c['uncertain'] for c in result['character_checks'])
    for check in [scene,*result['character_checks']]:
        if check['uncertain']:
            result['uncertain']=True
        elif check['matches'] is False or check is scene and check['pose_gaze_matches'] is False:
            result['issues'].append(dict(issue=check['evidence'],severity='high',location=check.get('name','Scene / pose / gaze')))
