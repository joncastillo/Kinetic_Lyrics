"""Check a judge's basic visual grounding before trusting its aesthetic scores.

Uses fixed rendered evidence plus a blank control, not a preferred aesthetic score.
"""

import argparse
import base64
import json
from pathlib import Path
import urllib.request

from filelock import FileLock
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', nargs='+', default=['qwen3.8:27b', 'qwen3-vl:8b'])
    parser.add_argument('--gpu-lock', type=Path, default=ROOT / '.image-generation.lock')
    args = parser.parse_args()
    folder = ROOT / 'tmp/scene-effects-lab/calibration'
    folder.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (640, 360), (235, 238, 240)).save(folder / 'blank.png')
    paths = [
        ROOT / 'tmp/scene-effects-lab/r08/plain-blocks/settled.png',
        ROOT / 'tmp/scene-effects-lab/r08/plain-blocks/light.png',
        folder / 'blank.png',
    ]
    item = dict(
        type='object',
        properties=dict(
            has_text=dict(type='boolean'),
            foreground=dict(type='string', enum=['light', 'dark', 'none']),
            background=dict(type='string', enum=['light', 'dark']),
            words=dict(type='array', items=dict(type='string')),
        ),
        required=['has_text', 'foreground', 'background', 'words'],
    )
    schema = dict(
        type='object', properties={f'image_{i}': item for i in (1, 2, 3)}, required=[f'image_{i}' for i in (1, 2, 3)]
    )
    results = {}
    for model in args.models:
        print('Calibrating ' + model, flush=True)
        request = dict(
            model=model,
            stream=False,
            think=False,
            keep_alive=0,
            format=schema,
            options=dict(temperature=0, num_ctx=8192, num_predict=4096),
            messages=[
                dict(
                    role='user',
                    content='Describe each of the three images independently. Is there visible text? Is the text primarily light or dark? Is the background primarily light or dark? Read any visible words. Do not discuss artistic quality or infer colors from a different image. Return only the requested JSON.',
                    images=[base64.b64encode(p.read_bytes()).decode() for p in paths],
                )
            ],
        )
        with FileLock(str(args.gpu_lock), timeout=-1):
            response = json.load(
                urllib.request.urlopen(
                    urllib.request.Request(
                        'http://127.0.0.1:11434/api/chat',
                        json.dumps(request).encode(),
                        {'Content-Type': 'application/json'},
                    ),
                    timeout=600,
                )
            )
        try:
            answer = json.loads(response['message']['content'])
            correct = (
                answer['image_1']['has_text']
                and answer['image_1']['foreground'] == 'light'
                and answer['image_1']['background'] == 'dark'
                and answer['image_2']['has_text']
                and answer['image_2']['foreground'] == 'dark'
                and answer['image_2']['background'] == 'light'
                and not answer['image_3']['has_text']
                and answer['image_3']['words'] == []
                and answer['image_3']['background'] == 'light'
            )
            results[model] = dict(passed=bool(correct), answer=answer)
        except (ValueError, KeyError):
            results[model] = dict(passed=False, error='No complete structured visual assessment')
        results[model]['raw'] = response
        print(model, json.dumps({k: v for k, v in results[model].items() if k != 'raw'}), flush=True)
        (folder / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return int(not any(r['passed'] for r in results.values()))


if __name__ == '__main__':
    raise SystemExit(main())
