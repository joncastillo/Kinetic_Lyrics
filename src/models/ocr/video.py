"""RapidOCR spelling check on encoded video frames."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
from core.process import run
from core.text import normalized


def validate_ocr(video, data, duration, report_path):
    """Inspect actual encoded frames. Flags are review hints, not alignment scores."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ValueError('OCR requires: python -m pip install rapidocr-onnxruntime') from exc
    engine = RapidOCR()
    results = []
    with tempfile.TemporaryDirectory(prefix='ocr-', dir=video.parent) as temp:
        for i, line in enumerate(data):
            last = line['words'][-1]
            end = min(duration, last['end'] + .6)
            if i + 1 < len(data):
                end = min(end, data[i + 1]['words'][0]['start'])
            sample = max(0, min(last['start'] + .7, (last['start'] + end) / 2))
            frame = Path(temp) / f'{i}.png'
            run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(sample),
                 '-i', str(video), '-frames:v', '1', '-y', str(frame)])
            found, _ = engine(str(frame))
            recognized = ' '.join(item[1] for item in (found or []))
            expected = normalized(line['text'])
            observed = normalized(recognized)
            results.append(dict(line=i + 1, time=sample, expected=line['text'],
                                observed=recognized, passed=expected in observed))
    report_path.write_text(json.dumps(dict(
        note='OCR checks visible spelling only; inspect flagged lines and listen to verify sync.',
        frames=results), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"OCR: {sum(r['passed'] for r in results)}/{len(results)} lines passed; {report_path}")
