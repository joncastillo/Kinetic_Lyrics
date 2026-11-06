"""Render the whole scene catalogue and optionally verify every exposed control changes output.

python automation/review_scenes.py --output tmp/scene-review --check-controls
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'tmp/scene-review')
    parser.add_argument('--extra-packages', type=Path)
    parser.add_argument('--check-controls', action='store_true')
    parser.add_argument('--scenes', nargs='+', help='Review only these scene IDs')
    args = parser.parse_args()
    if args.extra_packages:
        sys.path.insert(0, str(args.extra_packages.resolve()))
    from PIL import Image, ImageDraw
    from direction.scene_catalog import scene_catalog
    from direction.theme import theme_for
    from direction.typography import rules_plan
    from render.compositor import Compositor
    from render.stage_3d import close_stage

    catalog = scene_catalog()
    if args.scenes:
        unknown = set(args.scenes) - set(catalog)
        if unknown:
            parser.error('Unknown scenes: ' + ', '.join(sorted(unknown)))
        catalog = {key: value for key, value in catalog.items() if key in args.scenes}
    words = [
        dict(text=w, start=1 + i * 0.5, end=1.4 + i * 0.5) for i, w in enumerate('a quiet light stays here'.split())
    ]
    data = [dict(text='a quiet light stays here', words=words)]
    args.output.mkdir(parents=True, exist_ok=True)

    def make(scene, settings=None, size=(480, 270)):
        plan = dict(rules_plan(data, theme_for('bright')), scene_flows=[dict(start=0, end=1, scene=scene)])
        return Compositor(
            data,
            plan,
            *size,
            5.0,
            reading_flow='mixed',
            entrance_effect='none',
            exit_effect='none',
            kinetic=dict(fade=False, scene_settings={scene: settings or {}}),
        )

    report = dict(rendered=[], errors=[], unchanged_controls=[])
    sheet = Image.new('RGB', (4 * 480, ((len(catalog) + 3) // 4) * 310), '#111822')
    draw = ImageDraw.Draw(sheet)
    times = (0.85, 1.06, 1.23, 1.68, 2.08, 2.35, 3.17, 3.72)
    for number, (scene_id, scene) in enumerate(catalog.items()):
        try:
            c = make(scene_id)
            sample = c.frame(2.08)
            sample.save(args.output / f'{scene_id}.png')
            x, y = number % 4 * 480, number // 4 * 310
            sheet.paste(sample, (x, y + 30))
            draw.text((x + 12, y + 8), scene['name'], fill='white')
            # Also render entry/hold/exit for portrait frames; the sheet contains the middle frame.
            portrait = make(scene_id, size=(270, 480))
            for t in (0.85, 2.08, 3.72):
                portrait.frame(t)
            portrait.frame(2.08).save(args.output / f'{scene_id}-portrait.png')
            if args.check_controls:
                plain = [c.frame(t).tobytes() for t in times]
                for spec in scene['controls']:
                    if spec['type'] == 'color':
                        value = '#38cab5'
                    elif spec['type'] == 'select':
                        value = spec['options'][-1]
                    elif spec['key'] == 'variant':
                        value = 1
                    else:
                        value = spec['min'] if spec['min'] != spec['default'] else spec['max']
                    modified = make(scene_id, {spec['key']: value})
                    if not any(modified.frame(t).tobytes() != original for t, original in zip(times, plain)):
                        report['unchanged_controls'].append([scene_id, spec['key'], value])
            report['rendered'].append(scene_id)
            print(f"Reviewed {scene['name']}", flush=True)
        except Exception as exc:
            report['errors'].append([scene_id, repr(exc)])
            print(f'FAILED {scene_id}: {exc}', flush=True)
        finally:
            close_stage()
    sheet.save(args.output / 'catalogue.png')
    (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return int(bool(report['errors'] or report['unchanged_controls']))


if __name__ == '__main__':
    raise SystemExit(main())
