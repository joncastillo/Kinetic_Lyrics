"""Keep OCR-flagged artwork reviewable without aborting an image batch."""
import hashlib,json,time
from pathlib import Path


def mark_lettering(path,readings):
    path=Path(path);text=', '.join(str(r.get('text','')) for r in readings)
    report=dict(score=0,summary='OCR flagged possible lettering after three attempts: '+text,
        uncertain=True,issues=[dict(issue='Possible visible lettering: '+text,severity='high',location='background')],hand_checks=[],
        threshold=50,rejected=True,verdict='rejected',lettering_pending=True,validation_pending=True,ocr_readings=readings,model='ocr',advisory=True,
        image_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),reviewed_at=time.time())
    path.with_suffix('.review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


def mark_greenscreen(path):
    path=Path(path)
    report=dict(score=0,summary='No usable greenscreen sky after three attempts; the lyrics would have too little open sky.',
        uncertain=True,issues=[dict(issue='Chroma-key green sky missing or too small',severity='high',location='sky')],hand_checks=[],
        threshold=50,rejected=True,verdict='rejected',greenscreen_pending=True,model='greenscreen',advisory=True,
        image_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),reviewed_at=time.time())
    path.with_suffix('.review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


def propagate_lettering(source,target):
    source,target=Path(source),Path(target)
    if target.with_suffix('.selection.json').exists():return
    try:report=json.loads(source.with_suffix('.review.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return
    if not (report.get('lettering_pending') or report.get('greenscreen_pending')):return
    report['image_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


def require_review(paths,args):
    from artwork.queue import replacement_review_pending
    if replacement_review_pending(paths):
        args.review_artwork=True
        return
    for path in paths:
        try:report=json.loads(Path(path).with_suffix('.review.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if report.get('lettering_pending') or report.get('greenscreen_pending') or report.get('rejected'):
            args.review_artwork=True
            return


def needs_validation(paths,folder):
    try:config=json.loads((Path(folder)/'config.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return False
    if not config.get('auto_verify') or not config.get('vision_model'):return False
    for path in paths:
        path=Path(path)
        try:report=json.loads(path.with_suffix('.review.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return True
        if report.get('manual_skip') and report.get('image_sha256')==hashlib.sha256(path.read_bytes()).hexdigest():continue
        if report.get('validation_pending') or report.get('model')!=config['vision_model'] or type(report.get('score')) is not int or report.get('image_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest():return True
    return False
