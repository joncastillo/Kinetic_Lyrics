"""Optional structured progress stream for the local studio; CLI output stays intact."""
import json
import os

PREFIX = '@@KINETIC '


# Called with the path of every artifact (or manifest) a step reports, e.g. to refresh Studio's live gallery.
# core is the bottom layer, so the packages that care register here (artwork registers on import) instead of
# core importing them.
_artifact_listeners = []


def on_artifact(listener):
    if listener not in _artifact_listeners:
        _artifact_listeners.append(listener)
    return listener


def emit(stage, fraction=None, **details):
    artifact=details.get('artifact') or details.get('manifest')
    if artifact:
        for listener in list(_artifact_listeners):
            # Listeners are best-effort previews: one that fails must never fail the step that reported progress.
            try:listener(artifact)
            except Exception as exc:  # noqa: BLE001
                print('Warning: live preview update deferred: '+str(exc),flush=True)

    if os.environ.get('KINETIC_PROGRESS') == '1':
        print('\n' + PREFIX + json.dumps(dict(stage=stage, fraction=fraction, **details)), flush=True)


def counted(stage, start, end, what, suffix='', names=None):
    """Progress reporter for batched model work, e.g. 'Writing the scene for lyric group 3 of 12: "Hello..."'.

    Called with (first, last, total) before each batch. `names` labels single items."""
    def report(first, last, total):
        span = f'{first+1}' if last-first == 1 else f'{first+1}–{last}'
        label = ''
        if names and last-first == 1 and first < len(names) and str(names[first]).strip():
            text = ' '.join(str(names[first]).split())
            label = ': “'+(text if len(text) <= 48 else text[:47].rstrip()+'…')+'”'
        emit(stage, start+(end-start)*first/max(1, total), message=f'{what} {span} of {total}{suffix}{label}')
    return report


