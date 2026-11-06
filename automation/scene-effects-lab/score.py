"""Render and independently judge scene typography, retaining evidence for every round.

python automation/scene-effects-lab/score.py --round r01 --scenes quiet-focus plain-blocks
"""

import argparse
import base64
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
WEIGHTS = dict(spectacle=0.4, readability=0.2, choreography=0.2, craft=0.15, originality=0.05)
LINES = ((0.5, 'golden light upon the water'), (3.4, 'hold me close until the morning'), (6.6, 'do not let go'))
TIMES = (0.2, 0.35, 0.5, 0.65, 0.95, 1.4, 2.0, 2.65, 3.6, 4.15, 4.7, 5.45, 6.75, 7.35, 8.1, 8.7)
JUDGE_TIMES = (0.35, 0.65, 0.95, 1.4, 2.25, 4.15, 4.7, 8.1, 10.55)


def evidence(scene, folder, settings=None):
    import numpy as np
    from PIL import Image, ImageDraw
    from direction.typography import rules_plan
    from direction.theme import theme_for
    from effects.particles.scene_backdrops import scene_backdrop
    from render.compositor import Compositor
    from render.stage_3d import close_stage

    data = []
    for start, text in LINES:
        data.append(
            dict(
                text=text,
                words=[
                    dict(text=w, start=start + i * 0.4, end=start + i * 0.4 + 0.36) for i, w in enumerate(text.split())
                ],
                section_id=0,
                section_label='Verse',
            )
        )

    def make(size, background):
        plan = dict(rules_plan(data, theme_for('bright')), scene_flows=[dict(start=0, end=len(data), scene=scene)])
        art = scene_backdrop(folder, size, background)
        return Compositor(
            data,
            plan,
            *size,
            11.5,
            illustrations=[str(art)],
            illustration_lines=len(data),
            artwork_mode='fullscreen',
            reading_flow='mixed',
            entrance_effect='mixed',
            exit_effect='mixed',
            kinetic=dict(
                scenes=[scene],
                fade=False,
                beat_effect='none',
                beat_confetti=False,
                beat_blur=0.0,
                background_shake=0.0,
                scene_settings={scene: settings or {}},
            ),
        )

    c = make((640, 360), 'midnight')
    frames = [c.frame(i / 12).convert('RGB') for i in range(138)]
    frames[0].save(folder / 'animation.gif', save_all=True, append_images=frames[1:], duration=83, loop=0)
    sheet = Image.new('RGB', (1280, 800), '#080d16')
    draw = ImageDraw.Draw(sheet)
    for i, t in enumerate(TIMES):
        x, y = i % 4 * 320, i // 4 * 200
        sheet.paste(frames[round(t * 12)].resize((320, 180)), (x, y + 20))
        draw.text((x + 6, y + 3), f'{t:.2f}s', fill='white')
    sheet.save(folder / 'timeline.png')
    labels = []
    flat = [word for line in data for word in line['words']]
    for i, t in enumerate(JUDGE_TIMES):
        sung = next((w['text'] for w in flat if w['start'] <= t <= w['end']), 'pause / transition')
        label = f'{t:.2f}s | sung word: {sung}'
        labeled = Image.new('RGB', (640, 386), '#080d16')
        labeled.paste(frames[round(t * 12)], (0, 26))
        ImageDraw.Draw(labeled).text((8, 7), label, fill='white')
        labeled.save(folder / f'frame-{i:02d}.png')
        labels.append(label)
    (folder / 'frame-labels.json').write_text(json.dumps(labels), encoding='utf-8')
    c.frame(2.25).save(folder / 'settled.png')
    steps = [
        float(np.abs(np.asarray(b, dtype=float) - np.asarray(a, dtype=float)).mean() / 255)
        for a, b in zip(frames, frames[1:])
    ]
    metrics = dict(mean_frame_change=float(np.mean(steps)), maximum_frame_change=max(steps), frame_rate=12)
    close_stage()
    make((360, 640), 'midnight').frame(2.25).save(folder / 'portrait.png')
    close_stage()
    make((640, 360), 'porcelain').frame(2.25).save(folder / 'light.png')
    close_stage()
    return metrics


def judge(model, folder, rubric, metrics, design_brief='', raw_name='judge-raw.json', token_limit=4096):
    properties = {key: dict(type='number', minimum=0, maximum=100) for key in WEIGHTS}
    schema = dict(
        type='object',
        additionalProperties=False,
        properties=dict(
            scores=dict(type='object', properties=properties, required=list(properties), additionalProperties=False),
            evidence=dict(type='string'),
            critical_issues=dict(type='array', items=dict(type='string')),
            improvements=dict(type='array', items=dict(type='string')),
        ),
        required=['scores', 'evidence', 'critical_issues', 'improvements'],
    )
    paths = [*sorted(folder.glob('frame-*.png')), folder / 'portrait.png', folder / 'light.png']
    images = [base64.b64encode(path.read_bytes()).decode() for path in paths]
    content = (
        'Independently judge this rendered lyric scene. Do not flatter its author. Use the fixed rubric below. '
        'Images 1–9 are full-size chronological frames, each labeled with the currently sung word. '
        'Image 10 is the portrait hold; image 11 is the light-background hold, both at 2.25s, sung word WATER. '
        'An upcoming word may deliberately be small or partially revealed; assess the currently sung word. '
        'Camera moves and reveals can intentionally crop type during transitions; distinguish this from clipped held words. '
        'Design intent (not a quality claim): ' + design_brief + '. '
        'The sample phrases are ' + json.dumps(LINES) + '. The timeline contains deliberate entrances and exits; '
        'judge clipping on held text, not on intentional transitions. Neither ignore readability defects nor invent '
        'motion you cannot see. Give specific visible evidence.\n'
        + rubric
        + '\nDo not infer motion quality from the proportion of background pixels changing. Read the image sequence. '
        'Keep evidence concise and name the exact frame and sung word for any readability defect.'
    )
    payload = dict(
        model=model,
        stream=False,
        think=False,
        keep_alive=0,
        format=schema,
        options=dict(temperature=0, num_ctx=16384, num_predict=token_limit),
        messages=[dict(role='user', content=content, images=images)],
    )
    request = urllib.request.Request(
        'http://127.0.0.1:11434/api/chat', json.dumps(payload).encode(), {'Content-Type': 'application/json'}
    )
    response = json.load(urllib.request.urlopen(request, timeout=600))
    raw = response.get('message', {}).get('content', '')
    (folder / raw_name).write_text(json.dumps(dict(model=model, response=response), indent=2), encoding='utf-8')
    if response.get('done_reason') == 'length':
        raise ValueError('Judge response was truncated; no quality score recorded')
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError('Judge returned no valid assessment; no quality score recorded') from exc
    return grade(result)


def grade(result):
    """Compute the fixed weighted score; never invent absent scores or convert an error into a pass."""
    if (
        not isinstance(result, dict)
        or not isinstance(result.get('scores'), dict)
        or set(result['scores']) != set(WEIGHTS)
    ):
        raise ValueError('Judge omitted category scores')
    for key in WEIGHTS:
        if type(result['scores'].get(key)) not in (int, float) or not 0 <= result['scores'][key] <= 100:
            raise ValueError('Judge returned an invalid score')
    if not isinstance(result.get('critical_issues'), list) or any(
        not isinstance(issue, str) for issue in result['critical_issues']
    ):
        raise ValueError('Judge omitted critical issue assessment')
    if not isinstance(result.get('evidence'), str) or not result['evidence'].strip():
        raise ValueError('Judge omitted visible evidence')
    weighted = sum(result['scores'][key] * weight for key, weight in WEIGHTS.items())
    result['weighted_score'] = round(weighted, 4)
    result['score'] = min(94.0, result['weighted_score']) if result['critical_issues'] else result['weighted_score']
    result['passed'] = weighted >= 95 and not result['critical_issues']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round', required=True)
    parser.add_argument('--scenes', nargs='+')
    parser.add_argument('--model', default='qwen3.8:27b')
    parser.add_argument('--extra-packages', type=Path)
    parser.add_argument('--render-only', action='store_true')
    parser.add_argument('--settings', type=Path, help='Validated per-scene settings for a candidate preset')
    parser.add_argument(
        '--gpu-lock',
        type=Path,
        default=ROOT / '.image-generation.lock',
        help='Shared GPU lease used by other generation tasks',
    )
    args = parser.parse_args()
    if args.extra_packages:
        sys.path.insert(0, str(args.extra_packages.resolve()))
    from direction.scene_catalog import scene_catalog
    from direction.scene_controls import scene_settings
    from filelock import FileLock

    catalog = scene_catalog()
    overrides = scene_settings(json.loads(args.settings.read_text(encoding='utf-8')) if args.settings else {})
    scenes = args.scenes or list(catalog)
    if any(scene not in catalog for scene in scenes):
        parser.error('Unknown scene')
    if not args.round.replace('-', '').replace('_', '').isalnum():
        parser.error('Use a simple round name')
    rubric = (Path(__file__).parent / 'RUBRIC.md').read_text(encoding='utf-8')
    folder = ROOT / 'tmp' / 'scene-effects-lab' / args.round
    reviews = Path(__file__).parent / 'reviews'
    reviews.mkdir(exist_ok=True)
    if (folder / 'scores.json').exists() or (reviews / (args.round + '.json')).exists():
        parser.error('This round already has results; choose a new round name to preserve the evidence')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'RUBRIC.md').write_text(rubric, encoding='utf-8')
    with zipfile.ZipFile(folder / 'source.zip', 'w', compression=zipfile.ZIP_DEFLATED) as snapshot:
        for path in sorted((ROOT / 'src').rglob('*.py')):
            snapshot.write(path, path.relative_to(ROOT))
        for path in sorted((ROOT / 'assets' / 'scenes').glob('*.json')):
            snapshot.write(path, path.relative_to(ROOT))
        snapshot.write(__file__, 'score.py')
    manifest = dict(
        model=args.model,
        rubric_sha256=hashlib.sha256(rubric.encode()).hexdigest(),
        weights=WEIGHTS,
        threshold=95,
        evidence_folder=str(folder.relative_to(ROOT).as_posix()),
        source_snapshot='source.zip',
        settings=overrides,
        evidence_protocol='v2-full-size-sequence-with-vocal-labels',
        source_sha256=hashlib.sha256(
            b''.join(
                p.read_bytes()
                for p in [
                    *sorted((ROOT / 'src').rglob('*.py')),
                    *sorted((ROOT / 'assets/scenes').glob('*.json')),
                    Path(__file__),
                ]
            )
        ).hexdigest(),
        results={},
    )
    for scene in scenes:
        target = folder / scene
        target.mkdir(exist_ok=True)
        lease = FileLock(str(args.gpu_lock), timeout=-1)
        try:
            print('Waiting for GPU lease: ' + str(args.gpu_lock), flush=True)
            lease.acquire()
            print('Rendering ' + scene, flush=True)
            metrics = evidence(scene, target, overrides.get(scene))
            if args.render_only:
                result = dict(metrics=metrics, passed=False, unscored=True)
            else:
                print('Judging ' + scene, flush=True)
                result = dict(
                    judge(args.model, target, rubric, metrics, catalog[scene]['description']), metrics=metrics
                )
            manifest['results'][scene] = result
            (target / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(
                scene,
                'score=' + str(result.get('score', 'unscored')),
                'passed=' + str(result.get('passed')),
                flush=True,
            )
        except Exception as exc:
            manifest['results'][scene] = dict(error=str(exc), passed=False)
            print(scene, 'FAILED', str(exc), flush=True)
        finally:
            from render.stage_3d import close_stage

            close_stage()
            lease.release()
        (folder / 'scores.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        (reviews / (args.round + '.json')).write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return int(any(not r.get('passed') for r in manifest['results'].values()))


if __name__ == '__main__':
    raise SystemExit(main())
