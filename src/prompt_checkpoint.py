"""Save each prompting sub-step as it finishes, so a crash resumes after the last finished one and a restart can
begin at any sub-step.

Sub-steps run in order: song (message and verse structure), meanings, scenes, audit (second pass) and fit (length
for the image model). A restart at one of them reuses every earlier sub-step from the latest saved run, even when
settings changed since, because the person asked for exactly that. Without a chosen sub-step, only work saved by
the current run is reused, which is what an automatic recovery needs."""
import json
import time
from pathlib import Path

SUBSTEPS = ('song', 'meanings', 'scenes', 'audit', 'fit')
FILE = 'prompting.json'


def _read(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):return {}


def from_manifest(manifest):
    """Sub-steps recoverable from a finished run saved before checkpoints existed. The second-pass prompts were not
    kept, so it can restart at Song, Meanings, Scenes or Check but not at Fit."""
    job = _read(manifest)
    if not job.get('prompts'):
        return {}
    saved = dict(lines=None, song=dict(gist=job.get('song_gist', ''), indices=job.get('line_groups'),
                                      structure=job.get('song_structure'), groups=job.get('groups'),
                                      layouts=job.get('layouts')))
    if job.get('lyric_meanings') or job.get('artwork_mode') != 'verse':
        saved['meanings'] = job.get('lyric_meanings') or []
    if job.get('visual_descriptions'):
        saved['scenes'] = job['visual_descriptions']
    return saved


def latest(artwork):
    """The most recent saved prompting run in a job's video.artwork folder: its checkpoint, or its finished manifest."""
    folder = Path(artwork)
    job_folder = folder.parent
    active = _read(job_folder/'active-artwork.json').get('manifest')
    candidates = sorted(folder.glob(f'*/{FILE}'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    if active and (job_folder/active).parent.joinpath(FILE).is_file():
        candidates.insert(0, (job_folder/active).parent/FILE)
    if candidates:
        return _read(candidates[0])
    manifests = sorted(folder.glob('*/illustrations.json'), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    if active and (job_folder/active).is_file():
        manifests.insert(0, job_folder/active)
    return from_manifest(manifests[0]) if manifests else {}


def restartable(artwork):
    """Prompting sub-steps a restart can begin at: those whose earlier sub-steps are all saved."""
    saved = latest(artwork)
    if not saved:
        return []
    result = ['song']
    for before, step in zip(SUBSTEPS, SUBSTEPS[1:]):
        if before not in saved:
            break
        result.append(step)
    return result


class Checkpoint:
    def __init__(self, key_folder, lines, config):
        self.path = Path(key_folder)/FILE
        self.lines = lines
        substep = config.get('start_substep') if config.get('start_step') == 'prompts' else ''
        own = _read(self.path)
        since = config.get('run_started', 0)
        self.data = {}
        # Work this run already saved before it crashed.
        if own.get('lines') == lines:
            self.data = {step: own[step] for step in SUBSTEPS
                         if step in own and own.get('saved_at', {}).get(step, 0) >= since and since}
        # A chosen sub-step reuses everything before it from the latest saved run.
        if substep in SUBSTEPS:
            source = latest(Path(key_folder).parent)
            if source.get('lines') in (None, lines):
                for step in SUBSTEPS[:SUBSTEPS.index(substep)]:
                    if step in source:
                        self.data.setdefault(step, source[step])
            for step in SUBSTEPS[SUBSTEPS.index(substep):]:
                self.data.pop(step, None)
        self.saved_at = {step: time.time() for step in self.data}
        reused = [step for step in SUBSTEPS if step in self.data]
        if reused:
            print(f'Reusing saved prompting work: {", ".join(reused)}.', flush=True)

    def get(self, step):
        return self.data.get(step)

    def save(self, step, value):
        self.data[step] = value
        self.saved_at[step] = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(dict(self.data, lines=self.lines, saved_at=self.saved_at),
                                        ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)
