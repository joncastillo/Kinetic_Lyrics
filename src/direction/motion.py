"""Motion direction for the video step: what visibly happens in each part of each animated illustration.

A long section is animated as several parts, each continuing from the last frame of the one before. The same
prompt for every part makes a minute of footage repeat itself, so the director model plans the section as one
continuous shot on a timeline (0-5 s, 5-10 s, ...): for every part, where the camera is, which cast members are in
frame and where, and what happens. Only the first part describes the painting; later parts continue "the same
shot" from their state, because restating "a woman and her dog in the mid-ground" after the camera has moved away
makes the video model put them back in wherever it now looks, duplicated or teleported.
"""
import json

GUARDRAILS = ('One continuous shot with no cuts. Keep the painting\'s style, colours, lighting and characters '
              'consistent. Every person and animal appears once and stays the same individual; nobody new appears, '
              'and no one who has left the frame reappears somewhere else. No text, lettering or logos.')
CONTINUE = 'The same continuous shot carries on from this exact frame.'
FALLBACK = ('Natural, continuous motion: people move and breathe, hair and fabric stir in the wind, water, foliage '
            'and light shift, and the camera moves slowly through the scene.')


def beat_text(beat):
    """A beat (the director's {shot, camera, in_frame, action} state, or plain text) as prompt sentences."""
    if isinstance(beat, dict):
        parts = [f"Shot plan: {str(beat.get('shot', '')).strip()}" if str(beat.get('shot', '')).strip() else '',
                 str(beat.get('action', '')).strip(),
                 f"Camera: {str(beat.get('camera', '')).strip()}" if str(beat.get('camera', '')).strip() else '',
                 f"In frame: {str(beat.get('in_frame', '')).strip()}" if str(beat.get('in_frame', '')).strip() else '']
        return ' '.join(p.rstrip('.')+'.' for p in parts if p)
    return str(beat or '').strip()


def part_prompt(scene, beat, first=True):
    """The video prompt for one part. The first describes the painting; later parts only continue the shot from
    their state, so characters the camera has left behind are not put back in."""
    opening = scene.strip() if first else CONTINUE
    return ' '.join(part for part in (opening, beat_text(beat) or FALLBACK, GUARDRAILS) if part)


def timeline(seconds, parts):
    """The parts of a clip as time ranges, e.g. ['0-5 s', '5-10 s', '10-14 s']."""
    step = seconds/max(1, parts)
    return [f'{round(n*step)}-{round(min(seconds, (n+1)*step))} s' for n in range(parts)]


def motion_beats(model, clips, request=None, direction=''):
    """{illustration index: [beat per part]} for clips given as dicts with index, scene, lyrics, seconds, parts.

    One call for the whole song keeps the motion of neighbouring sections consistent. Returns {} when no model
    is available or it fails, and the parts then use FALLBACK; the video step must not fail over motion text."""
    clips = [c for c in clips if c.get('parts')]
    if not clips:
        return {}
    if not model:
        print('No director model chosen; clips use generic natural motion.', flush=True)
        return {}
    if request is None:
        from models.ollama.gpu import gpu_chat
        request = lambda payload: gpu_chat('chat', payload, timeout=900)
    beat_schema = dict(type='object', required=['time', 'camera', 'in_frame', 'action'],
                       properties=dict(time=dict(type='string'), camera=dict(type='string'),
                                       in_frame=dict(type='string'), action=dict(type='string')))
    clip_schema = dict(type='object', required=['index', 'cast', 'shot', 'beats'],
                       properties=dict(index=dict(type='integer'), cast=dict(type='string'), shot=dict(type='string'),
                                       beats=dict(type='array', items=beat_schema)))
    schema = dict(type='object', required=['clips'], properties=dict(clips=dict(type='array', items=clip_schema)))
    payload = dict(model=model, stream=False, think=False, keep_alive=0, options=dict(num_ctx=16384), format=schema,
        messages=[dict(role='system', content=(
            'You direct motion for an image-to-video model that animates painted illustrations of a song. '
            'Each clip is ONE continuous shot that starts on its painting and is made in parts; each part continues '
            'from the last frame of the one before and sees only that frame and its own beat. Plan each clip on the '
            'given `timeline` (one entry per part, in seconds). First state the `cast`: exactly the people and '
            'animals in the painting, each once (for example "one woman with blonde hair; one fawn-and-white '
            'bulldog"). Then storyboard the whole clip in `shot`: one sentence giving the single camera path and '
            'the story arc from first to last second, for example "a slow, continuous push-in along the track '
            'behind the woman and her dog, easing into a tilt up to the sky for the final third". Then write '
            'exactly one beat per timeline entry, each the next stretch of that storyboard, with: `time` (the '
            'entry, e.g. "5-10 s"); '
            '`camera` (where the camera is and its one slow move: push in, pull back, pan, tilt up to the sky, rise, '
            'orbit); `in_frame` (which cast members are visible at that moment and where, or "no one"); `action` '
            '(one or two present-tense sentences of visible, physical motion: what the cast does, how wind, water, '
            'fabric, hair, foliage, light and weather move). Camera rules: every beat continues the storyboard\'s '
            'path in the same direction at a slow, steady pace; never reverse a move (forward then back, left then '
            'right) and never repeat one; a change of move happens at most once, as a gentle transition the '
            'storyboard announced. Continuity rules: the cast never changes; nobody is '
            'duplicated; anyone who leaves the frame stays out of it and never reappears somewhere else; the camera '
            'stays within this scene and never travels to a distant place; when the camera turns away from the '
            'cast, let it settle on landscape or sky rather than finding people again. Make the action develop '
            'across the beats instead of repeating, and fit the mood of the lyrics being sung. Never add '
            'characters, cuts, scene changes, text or lettering. Keep it physically plausible and in keeping with '
            'a family-friendly music video. Let the scenery lead: '
            'landscape, water, sky, light and weather carry most of the motion and camera moves favour the place; '
            'people and animals already in the painting move naturally but stay part of the scene. '
            +(f'Follow the user\'s creative direction for this video: {direction.strip()} ' if direction.strip() else '')+
            'Return JSON {"clips":[{"index":n,"cast":"...","shot":"...","beats":[{"time":"0-5 s","camera":"...",'
            '"in_frame":"...","action":"..."}, ...]}]} covering every clip.')),
            dict(role='user', content=json.dumps([dict(index=c['index'], scene=c['scene'], lyrics=c['lyrics'],
                                                       seconds=round(c['seconds'], 1), parts=c['parts'],
                                                       timeline=timeline(c['seconds'], c['parts']))
                                                  for c in clips], ensure_ascii=False))])
    try:
        reply = request(payload)
        content = reply['message']['content'] if isinstance(reply, dict) and 'message' in reply else reply
        result = json.loads(content) if isinstance(content, str) else content
    except Exception as exc:
        print(f'Motion direction unavailable ({exc}); clips use generic natural motion.', flush=True)
        return {}
    wanted = {c['index']: c['parts'] for c in clips}
    beats = {}
    for clip in result.get('clips', []) if isinstance(result, dict) else []:
        index = clip.get('index') if isinstance(clip, dict) else None
        lines = [b for b in clip.get('beats', []) if beat_text(b)] if index in wanted else []
        shot = str(clip.get('shot', '')).strip() if isinstance(clip, dict) else ''
        if shot:   # every part's prompt carries the storyboard, so each knows the direction the shot is going
            lines = [dict(b, shot=shot) if isinstance(b, dict) else b for b in lines]
        if lines:
            # Too few beats: the last one carries on; too many: the extra ones are dropped.
            beats[index] = (lines+[lines[-1]]*wanted[index])[:wanted[index]]
    missing = sorted(set(wanted)-set(beats))
    if missing:
        print(f'Motion direction gave no beats for illustration(s) {", ".join(str(i+1) for i in missing)}; '
              'those use generic natural motion.', flush=True)
    return beats
