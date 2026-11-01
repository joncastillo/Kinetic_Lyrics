"""Optional structured progress stream for the local studio; CLI output stays intact."""
import json
import os

PREFIX = '@@KINETIC '


def emit(stage, fraction=None, **details):
    artifact=details.get('artifact') or details.get('manifest')
    if artifact:
        from pathlib import Path
        from artwork.gallery import publish_gallery
        source=Path(artifact)
        manifest=source if source.name=='illustrations.json' else source.parent/'illustrations.json'
        try:publish_gallery(manifest)
        except (OSError,ValueError,IndexError) as exc:
            print('Warning: live preview update deferred: '+str(exc),flush=True)

    if os.environ.get('KINETIC_PROGRESS') == '1':
        print('\n' + PREFIX + json.dumps(dict(stage=stage, fraction=fraction, **details)), flush=True)


def counted(stage, start, end, what, suffix='', names=None):
    """Progress reporter for batched model work: 'Writing the scene for lyric group 3 of 12: “Hello…”'.

    It is called with (first, last, total) before each batch; `names` labels single items."""
    def report(first, last, total):
        span = f'{first+1}' if last-first == 1 else f'{first+1}–{last}'
        label = ''
        if names and last-first == 1 and first < len(names) and str(names[first]).strip():
            text = ' '.join(str(names[first]).split())
            label = ': “'+(text if len(text) <= 48 else text[:47].rstrip()+'…')+'”'
        emit(stage, start+(end-start)*first/max(1, total), message=f'{what} {span} of {total}{suffix}{label}')
    return report


def diffusion_callback(image, total, attempt, attempts, steps):
    def callback(pipe, step, timestep, kwargs):
        from models.gpu.lifecycle import current_session
        session=current_session()
        if session:session.publish()
        emit('illustrations', ((image + (step+1)/steps) / total),
             image=image+1, images=total, step=step+1, steps=steps,
             attempt=attempt+1, attempts=attempts,
             message=f'Illustration {image+1}/{total} · step {step+1}/{steps} · attempt {attempt+1}')
        return kwargs
    return callback
