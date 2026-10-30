"""Read the whole song once for its message and hidden meanings, so every scene serves that reading."""
import json

GIST_RULE = (
    ' Every input includes song_gist: the whole song’s central message, hidden or symbolic meanings and visual '
    'thread. Show each lyric group’s own words, interpreted in the light of that message: make what its symbols '
    'stand for visible through concrete people, places and objects, so the scenes together tell the song’s story. '
    'Never draw the abstract message as text or replace the current lyric group with another part of the song.'
)


def song_gist(request, model, lines, image_instructions=''):
    """A short reading of the full lyrics: message, symbols and their meaning, narrator, arc and visual thread."""
    from direction.scenes import request_subjects
    from core.progress import emit
    from models.ollama.trace import trace_stage
    from direction.verse import LANGUAGE_RULE
    emit('subjects', .05, message='Reading the whole song for its message and hidden meanings')
    payload = dict(model=model, stream=False, think=False, keep_alive=-1, options=dict(num_ctx=8192),
        format=dict(type='object', properties=dict(subjects=dict(type='array', items=dict(type='string'))),
                    required=['subjects']),
        messages=[dict(role='system', content=LANGUAGE_RULE+(
            'Read the complete song lyrics as a thoughtful critic and explain, in plain English: the central message; '
            'the hidden, symbolic or widely recognised meanings of its key images and what each stands for; who the '
            'narrator is and what they want; the emotional arc from start to end; and one visual thread, such as a '
            'recurring place, light or object, that could connect illustrations of every section. '
            'Base this on the lyrics themselves; do not invent a story they do not support. '
            'Any supplied word-meaning clarifications from the user are authoritative. '
            'Return one paragraph as the only item of a JSON subjects array.')),
            dict(role='user', content=json.dumps([dict(lyrics='\n'.join(lines), image_instructions=image_instructions)],
                                                 ensure_ascii=False))])
    with trace_stage('Song gist / message and hidden meanings'):
        gist = request_subjects(request, payload, batch_size=1, max_words=200, avoid_repeats=False)[0]
    print('Song gist: '+gist, flush=True)
    return gist


def attach_gist(payload, gist):
    """Give every scene request the song's reading, including later retries made from this payload."""
    if not gist:
        return payload
    inputs = json.loads(payload['messages'][1]['content'])
    for entry in inputs:
        entry['song_gist'] = gist
    payload['messages'][1]['content'] = json.dumps(inputs)
    payload['messages'][0]['content'] += GIST_RULE
    return payload
