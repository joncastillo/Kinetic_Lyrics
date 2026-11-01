"""Motion direction for the video step: what visibly happens in each part of each animated illustration.

A long section is animated as several parts, each continuing from the last frame of the one before. The same
prompt for every part makes a minute of footage repeat itself, so the director model writes one short beat per
part that develops the action across the section, grounded in what was painted and in the lyrics being sung.
"""
import json

GUARDRAILS = ('One continuous shot with no cuts. Keep the painting\'s style, colours, lighting and characters '
              'consistent. No text, lettering or logos.')
FALLBACK = ('Natural, continuous motion: people move and breathe, hair and fabric stir in the wind, water, foliage '
            'and light shift, and the camera moves slowly through the scene.')


def part_prompt(scene, beat):
    """The video prompt for one part: what the painting shows, what happens now, and the guardrails."""
    return ' '.join(part for part in (scene.strip(), (beat or FALLBACK).strip(), GUARDRAILS) if part)


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
    clip_schema = dict(type='object', required=['index', 'beats'],
                       properties=dict(index=dict(type='integer'), beats=dict(type='array', items=dict(type='string'))))
    schema = dict(type='object', required=['clips'], properties=dict(clips=dict(type='array', items=clip_schema)))
    payload = dict(model=model, stream=False, think=False, keep_alive=0, options=dict(num_ctx=16384), format=schema,
        messages=[dict(role='system', content=(
            'You direct motion for an image-to-video model that animates painted illustrations of a song. '
            'Each clip starts from its painting and is made in parts of about ten seconds; each part continues '
            'from the last frame of the one before. For every clip, write exactly `parts` beats, one per part, '
            'in order. A beat is one or two present-tense sentences describing visible, physical motion: what the '
            'people or animals in the painting do, how wind, water, fabric, hair, foliage, light and weather move, '
            'and one clear camera move (push in, pull back, pan, orbit, rise). Make the action develop across the '
            'beats instead of repeating, and fit the mood of the lyrics being sung. Only use people, objects and '
            'places already in the scene; never add characters, cuts, scene changes, text or lettering. Keep it '
            'physically plausible and in keeping with a family-friendly music video. Let the scenery lead: '
            'landscape, water, sky, light and weather carry most of the motion and camera moves favour the place; '
            'people and animals already in the painting move naturally but stay part of the scene. '
            +(f'Follow the user\'s creative direction for this video: {direction.strip()} ' if direction.strip() else '')+
            'Return JSON {"clips":[{"index":n,"beats":["...", ...]}]} covering every clip.')),
            dict(role='user', content=json.dumps([dict(index=c['index'], scene=c['scene'], lyrics=c['lyrics'],
                                                       seconds=round(c['seconds'], 1), parts=c['parts'])
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
        lines = [str(b).strip() for b in clip.get('beats', []) if str(b).strip()] if index in wanted else []
        if lines:
            # Too few beats: the last one carries on; too many: the extra ones are dropped.
            beats[index] = (lines+[lines[-1]]*wanted[index])[:wanted[index]]
    missing = sorted(set(wanted)-set(beats))
    if missing:
        print(f'Motion direction gave no beats for illustration(s) {", ".join(str(i+1) for i in missing)}; '
              'those use generic natural motion.', flush=True)
    return beats
