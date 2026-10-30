"""Vision-model review of generated artwork through Ollama."""
import base64
import hashlib
from pathlib import Path
import time
from models.vision.policy import rejected, DEFAULT_THRESHOLD


def vision_review(image, model, lyrics, prompt, subject="", threshold=DEFAULT_THRESHOLD):
    from PIL import Image
    import io
    from filelock import FileLock
    with FileLock(str(image)+'.write.lock',timeout=30):
        snapshot=Path(image).read_bytes()
    fingerprint=hashlib.sha256(snapshot).hexdigest()
    with Image.open(io.BytesIO(snapshot)) as source:
        source.thumbnail((1536, 1536))
        data = io.BytesIO()
        rgba = source.convert('RGBA')
        canvas = Image.new('RGBA',rgba.size,'#f5f2e9')
        canvas.alpha_composite(rgba)
        canvas.convert('RGB').save(data, format='JPEG', quality=94)
    instruction = (
        'Review this illustration, not the reference image. Report only visible issues. '
        'Inspect each visible hand separately for six or more digits, fused fingers, impossible '
        'joint directions, twisted wrists, disconnected fingers, duplicated limbs and malformed appendages; '
        'anatomical continuity, faces, accidental lettering, cropping and relevance to the lyric meaning. '
        'Check believable object construction and physical relationships, not anatomy alone. '
        'Inspect lamp posts and fixtures: light heads should have plausible mounts and recognizable construction; '
        'flag an unexplained light embedded halfway through a pole or disconnected from its fixture. '
        'Check gravity, contact with surfaces, supports, attachment points, consistent scale and perspective, '
        'and obviously conflicting light or shadow directions. Look for floating parts, melted rigid objects, '
        'impossible joints, misplaced functional parts and incoherent object geometry. '
        'Unless explicitly requested otherwise, street lamps must have their light head at the top of the lamp post. '
        'An unrequested light mounted halfway up a continuing pole is an implausible default streetlamp design; flag it and score below 50. '
        'Side-mounted fixtures are acceptable only when explicitly requested. Intentional fantasy must be supported by the requested scene. '
        'Evaluate the entire arrangement, not each object in isolation. Compare repeated objects at similar depth. '
        'Flag abrupt unexplained differences in height, size, proportions or design that do not follow perspective. '
        'For example, a tall lamp post immediately beside a tiny lamp post, or a lit short post beside a taller bare pole, '
        'is an unusual construction unless the requested scene clearly calls for it. '
        'Check for accidental duplicate supports, extra poles, redundant fixtures, mismatched paired objects, '
        'and objects that could not function or coexist naturally in that arrangement. '
        'Do not excuse these defects merely because one individual lamp head is correctly top-mounted. '
        'Distinguish a legitimately more distant smaller object from an implausibly undersized nearby object. '
        'Where one focal streetlamp is intended, an unexplained additional pole or contradictory fixture is a substantial defect. '
        'Describe the relationship and visible evidence, and score below 50 for a clear central scene-level inconsistency. '
        'Stylized brushwork is acceptable; clearly broken construction is still a defect. '
        'Report visible evidence and exact locations; uncertain physical interpretation is not proof. '
        'Do not flag hands merely because some fingers are hidden. If unclear, say uncertain. '
        'Do not deduct any points for fingers that are hidden, occluded, cropped out or not visible. '
        'A closed fist, overlapping hands or no visible fingers is not an anatomical defect. '
        'When no hands are visible, hand anatomy is not applicable and hand_checks must be empty. '
        'Never infer missing or extra fingers from an unseen area. Penalize only defects supported by visible evidence. '
        'Describe visual evidence and location for every reported defect. Do not invent defects. '
        'If a hand is occluded, foreshortened or too small to count, mark it uncertain rather than normal. '
        'SCORING AND ANATOMY POLICY:\n'
        '- The reference image and generated artwork are stylized illustrations/paintings, NOT real photographs. '
        'Artistic license, painterly anatomy, Mucha-style linework, expressive faces, and stylized proportions are acceptable. '
        '- In cases other than extra digits or abnormal appendages (such as stylized faces, painterly brushwork, minor asymmetry, or artistic anatomy), PENALIZE ONLY SLIGHTLY (deduct at most 5 to 10 points; score should remain high: 75-90+). '
        '- Apply a SEVERE, HIGH PENALTY (score must drop below 35, triggering rejection) ONLY for: '
        '  * Extra digits (6 or more fingers on a hand, extra thumbs, duplicate fingers, polydactyly) '
        '  * Abnormal appendages (extra arms, extra legs, extra hands, duplicated limbs, disconnected floating body parts) '
        '  * One body that mixes male and female sex characteristics, such as a woman with a moustache, beard or stubble, a beard combined with breasts, or exposed genitals '
        '  * Clearly legible unwanted lettering, words, numbers or logos in the generated image. Do not mistake decorative strokes for letters. '
        '- A missing focal subject, unrelated scene or severely cropped important subject is a substantial defect and should score below 50. '
        '- Clearly impossible construction or physical relationships central to the subject are substantial defects and should score below 50. '
        '- 50 means usable with minor flaws; below 50 means a substantial visible defect warrants regeneration. '
        'For an object study, anatomy, faces, hair, clothing and human figures are NOT APPLICABLE. '
        'Never penalize an object for lacking human features. '
        'Do not reject a relevant isolated object simply because its drawing technique is understated. '
        'Uncertainty is not proof of a defect; report evidence without inventing problems. '
        'This is an advisory review, never a guarantee. '
        f'Intended visual subject: {subject or "Infer the subject from the actual image and lyrics; do not assume a portrait."}\n'

        f'Lyrics: {lyrics}\nRequested art style: {prompt}')
    schema = dict(type='object', properties=dict(
        summary=dict(type='string'), score=dict(type='integer',minimum=0,maximum=100), uncertain=dict(type='boolean'),
        issues=dict(type='array',items=dict(type='object',properties=dict(
            issue=dict(type='string'),severity=dict(type='string',enum=['low','medium','high']),
            location=dict(type='string')),required=['issue','severity','location'])),
        hand_checks=dict(type='array',items=dict(type='object',properties=dict(
            hand=dict(type='string'),visible_fingers=dict(type=['integer','null']),
            assessment=dict(type='string'),uncertain=dict(type='boolean')),
            required=['hand','visible_fingers','assessment','uncertain']))),
        required=['summary','score','issues','uncertain','hand_checks'])
    payload = dict(model=model, stream=False, keep_alive="30m", think=False, format=schema,
                   options=dict(temperature=.1,num_ctx=8192,num_predict=2200),
                   messages=[dict(role='user', content=instruction,
                                  images=[base64.b64encode(data.getvalue()).decode()])])
    from models.ollama.gpu import gpu_chat as local_json
    from models.gpu.lifecycle import current_session
    session = current_session()
    if session:
        payload['keep_alive']=-1
        session.before_review(model)
    from models.vision.response import request_review
    def request(query):
        return session.review_request(local_json, query) if session else local_json('chat', query, timeout=600)
    result = request_review(request, payload, lambda message: print('Warning: '+message, flush=True))
    result['threshold']=threshold
    result['rejected']=rejected(result,threshold)
    result['verdict']='rejected' if result['rejected'] else 'accepted'
    return dict(**result, model=model, review_policy_version=2, advisory=True, image=str(image), image_sha256=fingerprint, reviewed_at=time.time())
