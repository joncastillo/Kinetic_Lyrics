"""A second prompting pass that reviews complete automatic image prompts."""
import json


def audit_prompts(request,model,groups,subjects,prompts,layouts,mode='cutout'):
    from direction.scenes import request_subjects
    from core.progress import emit
    emit('subjects',.6,message='Second pass: reviewing every image prompt for relevance and conflicting instructions')
    system=(
        'Review and improve every supplied image-generation prompt before it is sent to an image model. '
        'Return one complete corrected image prompt per input, in a JSON subjects array in input order. '
        'Preserve the intended lyric meaning, chosen subject, visual metaphor and requested art technique. '
        'Make only changes needed to fix an identifiable contradiction, unrelated addition or unclear '
        'instruction. If a prompt is already coherent, return it unchanged. Do not replace a deliberate '
        'creative choice with your preferred composition or invent new restrictions. '
        'Do not quote or transcribe lyrics. A request for roads, scenery or shadows must not '
        'simultaneously forbid those elements. Preserve intentional portraits, people, silhouettes, '
        'gestures and symbolic motifs when they serve the intended scene. Keep object and landscape '
        'scenes faithful to their chosen subjects; omit unrelated characters or portrait styling. '
        'Describe one clear composition with a coherent subject, palette, light and material treatment. '
        'Retain the supplied orientation, staging and quiet lyric area. No typography, logos or watermarks. '
        'Anatomy guidance applies only to visible body parts; hidden fingers need not be shown. '
        +('These are lyric-grounded painted scenes. Check the intended scene against the supplied English '
          'meaning and the original lyrics. Preserve recognizable lyric-specific people, actions, objects '
          'and settings. If a prompt has lost those anchors and describes only a generic mood, colored '
          'forms or decorative motifs, restore the relevant concrete scene or a clear connected metaphor. '
          'Let abstraction simplify the rendering rather than replace the meaning. Keep a quiet lyric area. '
          if mode=='verse' else
          'These are greenscreen scenery plates. Keep the horizon or skyline scenery tied to the lyric, keep the '
          'instruction that everything above the skyline is flat, uniform pure #00FF00 chroma-key green with nothing in it, '
          'even when the scene names a sky colour, and keep the absence of a main character or dominant figure. '
          if mode=='matte' else
          'These are complete full-frame scenes; preserve atmospheric surroundings and the quiet lyric area. '
          if mode=='fullscreen' else
          'These are cutout illustrations. Keep the subject and essential immediate supporting scene on '
          'a uniform removable background. Do not erase essential props, surfaces or cast shadows from the described subject. ')
        +'Keep each complete image prompt clear and concise. Return only JSON.'
    )
    payload=dict(model=model,stream=False,think=False,keep_alive=-1,options=dict(num_ctx=8192),
        format=dict(type='object',properties=dict(subjects=dict(type='array',items=dict(type='string'))),required=['subjects']),
        messages=[dict(role='system',content=system),dict(role='user',content=json.dumps([
            dict(lyrics=lyrics,intended_scene=subject,image_prompt=prompt,layout=layout.get('visual_prompt',layout.get('prompt','')))
            for lyrics,subject,prompt,layout in zip(groups,subjects,prompts,layouts)]))])
    from models.ollama.trace import trace_stage
    with trace_stage('Second pass / image prompt review'):
        reviewed=request_subjects(request,payload,batch_size=2,max_words=180,avoid_repeats=False)
    if len(reviewed)!=len(prompts):raise ValueError('Prompt review must return one corrected prompt per scene')
    emit('subjects',1,message='Second pass complete: image prompts reviewed')
    return reviewed
