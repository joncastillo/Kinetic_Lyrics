"""Lyric-grounded full-frame paintings."""
import json

DIRECTOR_PROMPT = (
    'Turn each lyric group and its supplied English meaning into a distinct painted scene for a kinetic lyric video. '
    'The meaning determines the visible subject, action, relationships and setting. '
    'Include recognizable details from this specific lyric group so a viewer can connect the picture to the words. '
    'Preserve concrete places, objects and events instead of replacing them with generic colored shapes. '
    'When the lyric is metaphorical, choose a clear visual metaphor tied to its meaning and describe its visible scene. '
    'Do not use an unrelated glowing shape, flowing fabric, a generic horizon or a stock figure merely to suggest a mood. '
    'Describe the main subject and what is happening first, then the supporting environment, light and atmosphere. '
    'People, objects, interiors, streets and landscapes are welcome when the lyric calls for them. '
    'Do not invent extra people or supernatural events that the supplied meaning does not support. '
    'Use painterly simplification to unify the scene, without losing the lyric-specific anchors. '
    'Keep a coherent rendering style across the song while allowing each lyric to determine its imagery. '
    'Describe only what the illustrator should draw. Do not explain the interpretation or quote the lyrics. '
    'When the lyric refers to writing, suggest its physical setting through unlettered marks, blank notices or worn surfaces; '
    'do not request readable words. No captions, logos, frames or borders. '
    'Return only JSON with a subjects array in input order.'
)


def lyric_meanings(request, model, groups,contexts=None):
    """Resolve language and imagery before asking for visual interpretations."""
    from subject_director import request_subjects
    from llm_trace import trace_stage
    from kinetic_progress import emit
    emit('subjects', .1, message='Understanding each lyric group before planning its scene')
    payload = dict(model=model, stream=False, think=False, keep_alive=-1, options=dict(num_ctx=8192),
        format=dict(type='object', properties=dict(subjects=dict(type='array', items=dict(type='string'))), required=['subjects']),
        messages=[dict(role='system', content=(
            'Explain what each supplied lyric group means in concise plain English, including Tagalog or other languages. '
            'Preserve the people, actions, relationships, physical objects, places and events actually mentioned. '
            'Distinguish literal events from metaphors; state the central idea of a metaphor without inventing a different story. '
            'Keep the speaker and listener roles accurate, including implied first-person speech. '
            'Recognize direct address and personification: calling an abstract thing a friend does not imply a second human character. '
            'Explain the metaphor and who addresses whom in a normal English sentence; do not return a slash-separated literal translation. '
            'A short closing line or refrain belongs to its supplied verse context, not the next verse. '
            'Use the surrounding song only to clarify context. Do not replace specific details with a generic mood. '
            'These are meaning briefs, not illustration prompts: do not add colors, shapes, painting styles or visual composition. '
            'Translate only the current input group, without advancing to adjacent lines or replacing its nouns and verbs. '
            'Return one short meaning brief per input in order, as JSON with a subjects array. '
            'The following song context is for interpretation only, not an additional input to translate: '+json.dumps(groups))),
            dict(role='user', content=json.dumps([dict(lyrics=group,section_context=contexts[i] if contexts else None) for i,group in enumerate(groups)]))])
    with trace_stage('Lyric meaning / scene grounding'):
        return request_subjects(request, payload, batch_size=1, max_words=85, avoid_repeats=False)


def image_prompt(subject, layout, style_prompt):
    return (
        'Paint this specific lyric-grounded scene as a full-frame background: '+subject.strip()+'. '
        'Preserve the described subjects, actions, relationships and setting. '
        'The scene and its recognizable details take priority over decorative abstractions. '
        'Broad readable forms, delicate ink edges, soft hand-painted shading and a coherent environment. '
        +layout['visual_prompt']+' '
        'Use the following only for color, brushwork and mood, never to replace the scene: '+style_prompt+'. '
        'Use painterly simplification without obscuring the story or turning concrete objects into unrelated shapes. '
        'No lettering, written numbers, captions, logos or watermarks. '
        'No frame or border. Smooth clean pigment, no grain or noisy texture.'
    )
