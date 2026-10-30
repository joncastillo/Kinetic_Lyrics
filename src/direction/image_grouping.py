"""Choose a useful lyric-line span for each illustration after timing is known."""
import json
import math


def estimate_lines(data, model='auto', request=None):
    """Let the local text model balance scene changes with image generation cost."""
    count = len(data)
    if count < 2:
        return 1
    if request is None:
        from models.ollama.gpu import gpu_chat
        request = gpu_chat
    lyrics = [dict(section=line.get('section_label', ''), text=line['text']) for line in data[:150]]
    try:
        if model == 'auto':
            from models.ollama.service import local_json
            from artwork.vector_clipart import preferred_model
            model = preferred_model(local_json, model)
    except (OSError, ValueError, TypeError, KeyError):
        model = None
    payload = dict(model=model, think=False, stream=False, keep_alive=0,
                   format={'type': 'object', 'properties': {
                       'lines_per_image': {'type': 'integer', 'minimum': 1, 'maximum': 8},
                       'reason': {'type': 'string'}},
                       'required': ['lines_per_image', 'reason']},
                   options={'num_ctx': 8192, 'num_predict': 180, 'temperature': 0},
                   messages=[dict(role='system', content=(
                       'Choose ONE fixed number of lyric lines per illustration, 1 to 8. '
                       'Use the lyric meaning, section changes, line length, and narrative pace. '
                       'Short vivid lines can share a scene; major new imagery needs a new image. '
                       'Avoid a new expensive image for every word or repeated refrain. '
                       'Prefer roughly 8 to 24 illustrations for a typical song, but preserve meaningful changes. '
                       'Return a number and brief reason, no lyrics.')),
                       dict(role='user', content=json.dumps({'line_count': count, 'lyrics': lyrics}, ensure_ascii=False)[:14000])])
    try:
        if model is None:
            raise ValueError('No available local text model')
        response = request('chat', payload, timeout=75)
        choice = json.loads(response.get('message', {}).get('content') or '{}').get('lines_per_image')
        if type(choice) is int and 1 <= choice <= 8:
            print(f'AI chose {choice} lyric line(s) per illustration for {count} lines.', flush=True)
            return choice
    except (OSError, ValueError, TypeError, KeyError):
        pass
    fallback = min(8, max(2, math.ceil(count/18)))
    print(f'Using {fallback} lyric line(s) per illustration (text model unavailable).', flush=True)
    return fallback
