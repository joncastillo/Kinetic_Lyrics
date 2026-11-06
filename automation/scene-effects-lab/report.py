"""Build a local, inspectable score ledger without silently promoting failed presets."""

import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from direction.scene_catalog import scene_catalog

    catalog = scene_catalog()
    history = {key: [] for key in catalog}
    for path in sorted((Path(__file__).parent / 'reviews').glob('*.json')):
        review = json.loads(path.read_text(encoding='utf-8'))
        for scene, result in review.get('results', {}).items():
            if scene in history:
                history[scene].append(
                    dict(
                        round=path.stem,
                        model=review.get('model', ''),
                        settings=review.get('settings', {}).get(scene, {}),
                        result=result,
                        evidence=review.get('evidence_folder', 'tmp/scene-effects-lab/' + path.stem),
                    )
                )
    output = ROOT / 'tmp/scene-effects-lab'
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    ledger = []
    passed = 0
    for scene, spec in catalog.items():
        trials = history[scene]
        scored = [trial for trial in trials if isinstance(trial['result'].get('score'), (int, float))]
        best = max(scored, key=lambda trial: trial['result']['score']) if scored else None
        if best:
            result = best['result']
            score = result['score']
            ok = bool(result.get('passed'))
            passed += ok
            folder = Path(best['evidence']) / scene
            link = (ROOT / folder / 'timeline.png').as_uri()
            video = ROOT / folder / 'animation.mp4'
            clip = (video if video.exists() else ROOT / folder / 'animation.gif').as_uri()
            issue = (
                '; '.join(result.get('critical_issues', []))
                or 'No critical defects reported; artistic target still applies.'
            )
            grade = f'{score:g}'
            settings = json.dumps(best['settings']) if best['settings'] else 'Default settings'
            summary = dict(
                scene=scene, name=spec['name'], score=score, passed=ok, round=best['round'], settings=best['settings']
            )
            row = f'<td><a href="{html.escape(link)}">{html.escape(spec["name"])}</a><small>{html.escape(spec["family"])}</small></td><td><b>{grade}</b><div class="meter"><i style="width:{score}%"></i><em></em></div></td><td>{"PASS" if ok else "Below 95"}</td><td>{html.escape(best["round"])}<small>{html.escape(settings)}</small><a href="{html.escape(clip)}">Animation</a></td><td>{html.escape(issue)}</td>'
        else:
            summary = dict(scene=scene, name=spec['name'], score=None, passed=False)
            row = f'<td>{html.escape(spec["name"])}</td><td>—</td><td>Unscored</td><td>—</td><td>No valid judge assessment.</td>'
        ledger.append(summary)
        rows.append('<tr>' + row + '</tr>')
    document = '''<!doctype html><html><head><meta charset="utf-8"><title>Scene score ledger</title>
<style>body{background:#111823;color:#e8edf2;font:14px/1.5 system-ui;margin:40px}h1{font-size:28px}p{max-width:900px;color:#b9c5d2}table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:12px;border-bottom:1px solid #344154;vertical-align:top}th{color:#b9c5d2}a{color:#a8ceef}small{display:block;color:#a0aebe;max-width:300px}td:nth-child(2){min-width:120px}td:last-child{max-width:550px}.meter{height:6px;background:#303a48;position:relative;margin-top:8px}.meter i{display:block;height:100%;background:#d8ae77}.meter em{position:absolute;left:95%;top:-3px;height:12px;border-left:2px solid white}</style></head><body>
<h1>Scene score ledger</h1><p><strong>PASS_COUNT of SCENE_COUNT presets have a recorded pass at 95/100.</strong></p>
<p>Best recorded score for each preset, including evaluated setting variants. Scores apply to the linked snapshots and configurations, not blanket approval of current code. Failed reviews are retained. The white marker is the 95-point target.</p>
<p>Weights: spectacle 40%, readability 20%, choreography 20%, craft 15%, originality 5%. These are vision-model judgments; inspect the animation and held frames alongside the critique.</p>
<table><thead><tr><th>Preset / family</th><th>Score</th><th>Status</th><th>Review / settings</th><th>Judge concerns</th></tr></thead><tbody>ROWS</tbody></table></body></html>'''
    document = (
        document.replace('PASS_COUNT', str(passed))
        .replace('SCENE_COUNT', str(len(catalog)))
        .replace('ROWS', ''.join(rows))
    )
    (output / 'index.html').write_text(document, encoding='utf-8')
    (Path(__file__).parent / 'ledger.json').write_text(
        json.dumps(dict(threshold=95, passed=passed, total=len(catalog), presets=ledger), indent=2), encoding='utf-8'
    )
    print(f'{passed}/{len(catalog)} passed. Report: {output / "index.html"}')


if __name__ == '__main__':
    main()
