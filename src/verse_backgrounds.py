"""Lyric-grounded full-frame paintings."""
import json
import re

# Every prompt that reads lyrics starts with this, so a song in Tagalog or any other language is understood in
# that language before anything is written in English, rather than guessed at word by word.
LANGUAGE_RULE = (
    'The lyrics may be in a language other than English, such as Tagalog, or mix languages. Read and understand them '
    'in their original language first, as a fluent native speaker would, including idioms, slang, figurative phrases '
    'and words that look like English but mean something else. Work out the intended meaning in that language before '
    'writing anything in English; never translate word by word or guess from a similar-looking English word. '
    'If any lyric is not in English, first translate it silently into natural, faithful English that keeps its '
    'meaning, tone and imagery, then base your interpretation and every detail you write on that translation '
    'rather than on the sound or spelling of the original words. Do not output the translation unless asked to. '
)
DIRECTOR_PROMPT = LANGUAGE_RULE+(
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
    'Write a richly detailed 400 to 500 word scene description. Specify the focal subject and action, foreground and '
    'background relationships, viewpoint, physical setting, surface details, weather or atmosphere where the '
    'lyric supports them, and the light that makes the action readable. Every detail must serve the supplied meaning. '
    'Describe only what the illustrator should draw. Do not explain the interpretation or quote the lyrics. '
    'When the lyric refers to writing, suggest its physical setting through unlettered marks, blank notices or worn surfaces; '
    'do not request readable words. No captions, logos, frames or borders. '
    'Return only JSON with a subjects array in input order.'
)


def translation_notes(instructions):
    """Explicit user glosses such as '"ambon" means drizzle', keyed by lyric word."""
    notes = {}
    for line in instructions.splitlines():
        match = re.search(r'["“‘]?([\w-]+)["”’]?\s+means\s+([^,.;\n]+)', line, re.I)
        if match:
            notes[match.group(1).casefold()] = match.group(2).strip().strip('"“”‘’ ')
    return notes


def notes_for_group(group, notes):
    return {word: meaning for word, meaning in notes.items()
            if re.search(r'(?<!\w)'+re.escape(word)+r'(?!\w)', group, re.I)}


def lyric_meanings(request, model, groups, contexts=None, image_instructions=''):
    """Resolve language and imagery before asking for visual interpretations."""
    from subject_director import request_subjects
    from llm_trace import trace_stage
    from kinetic_progress import emit
    emit('subjects', .1, message='Understanding each lyric group before planning its scene')
    notes = translation_notes(image_instructions)
    payload = dict(model=model, stream=False, think=False, keep_alive=-1, options=dict(num_ctx=8192),
        format=dict(type='object', properties=dict(subjects=dict(type='array', items=dict(type='string'))), required=['subjects']),
        messages=[dict(role='system', content=(
            LANGUAGE_RULE+
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
            'Any supplied word-meaning clarifications from the user are authoritative. Use them in the English meaning '
            'even if another interpretation of a word seems familiar. '
            'Return one short meaning brief per input in order, as JSON with a subjects array. '
            'The following song context is for interpretation only, not an additional input to translate: '+json.dumps(groups))),
            dict(role='user', content=json.dumps([dict(lyrics=group,section_context=contexts[i] if contexts else None,
                                                 image_instructions=image_instructions,
                                                 binding_translation_notes=notes_for_group(group, notes))
                                                for i,group in enumerate(groups)]))])
    with trace_stage('Lyric meaning / scene grounding'):
        meanings = request_subjects(request, payload, batch_size=1, max_words=85, avoid_repeats=False)
        for i, (group, meaning) in enumerate(zip(groups, meanings)):
            relevant = notes_for_group(group, notes)
            missing = {word: definition for word, definition in relevant.items()
                       if definition.casefold() not in meaning.casefold()}
            if not missing:
                continue
            from copy import deepcopy
            retry = deepcopy(payload)
            retry['messages'][0]['content'] += (
                ' The previous interpretation contradicted a binding user translation. '
                'Correct the meaning now. Include each supplied English definition verbatim in the meaning brief. '
                'Discard any unrelated object or place inferred from the misread word.')
            retry['messages'][1]['content'] = json.dumps([dict(
                lyrics=group, section_context=contexts[i] if contexts else None,
                binding_translation_notes=relevant, previous_incorrect_meaning=meaning)])
            revised = request_subjects(request, retry, batch_size=1, max_words=85, avoid_repeats=False)[0]
            if any(definition.casefold() not in revised.casefold() for definition in relevant.values()):
                raise ValueError(f'Lyric interpretation ignored the supplied translation for {", ".join(missing)}')
            meanings[i] = revised
        return meanings


def image_prompt(subject, layout, style_prompt):
    return (
        'Paint this specific lyric-grounded scene as a full-frame background: '+subject.strip()+'. '
        'Preserve the described subjects, actions, relationships and setting. '
        'The scene and its recognizable details take priority over decorative abstractions. '
        'Broad readable forms, delicate ink edges, soft hand-painted shading and a coherent environment. '
        +layout['visual_prompt']+' '
        'Stage the focal action clearly in the foreground, with supporting objects placed at believable distances. '
        'Describe depth through overlap, scale and natural light, while keeping the main lyric area calm enough for typography. '
        'Give fabrics, skin, stone, water or other visible materials their own tactile texture and weight when present. '
        'Keep gestures, weather and illumination consistent with the specific event in the lyric. '
        'Use a considered camera angle and readable silhouette so the central action is understood at a glance. '
        'Let smaller background details reinforce the same moment without competing with the subject. '
        'Use the following only for color, brushwork and mood, never to replace the scene: '+style_prompt+'. '
        'Use painterly simplification without obscuring the story or turning concrete objects into unrelated shapes. '
        'Draw one coherent scene with opaque, physically placed subjects. No superimposed scenes, double exposure, '
        'semi-transparent people, ghost silhouettes, floating haze, smoke or wispy overlays unless the lyric explicitly describes them. '
        'No lettering, written numbers, captions, logos or watermarks. '
        'No frame or border. Smooth clean pigment, no grain or noisy texture.'
    )
