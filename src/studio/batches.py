"""Phase-ordered reviews and repairs, with selection fingerprints preserved."""
import hashlib
import json
from pathlib import Path
import shutil
import time
from filelock import FileLock
from models.vision.policy import rejected, DEFAULT_THRESHOLD, MAX_AUTO_REPAIRS


def review_one(worker, root, manifest, job, config, item):
    index = item['index']
    target = manifest.parent/f'{index:03d}.png'
    image = Path(item.get('candidate') or target)
    worker.emit('verification', 0, message=f'Inspecting illustration {index+1} with {item["model"]}')
    from artwork.metadata import variant_metadata
    intended=variant_metadata(image,job,index).get('prompt',job['prompts'][index])
    result=None
    if item.get('reuse_review'):
        try:
            with FileLock(str(image)+'.write.lock',timeout=30):
                report=json.loads(image.with_suffix('.review.json').read_text(encoding='utf-8'))
                fingerprint=hashlib.sha256(image.read_bytes()).hexdigest()
            if not report.get('validation_pending') and report.get('model')==item['model'] and type(report.get('score')) is int and report.get('image_sha256')==fingerprint:
                result=report
                worker.emit('verification',1,message=f'Illustration {index+1}: reusing saved quality {result["score"]}%')
        except (OSError,ValueError):pass
    if result is None:
        from models.vision.response import ReviewUnavailable
        try:
            result = worker.vision_review(image, item['model'], job['groups'][index], config['style_prompt'],
                                         intended, config.get('review_threshold',DEFAULT_THRESHOLD))
        except ReviewUnavailable as exc:
            with FileLock(str(image)+'.write.lock',timeout=30):
                fingerprint=hashlib.sha256(image.read_bytes()).hexdigest()
                try:previous=json.loads(image.with_suffix('.review.json').read_text(encoding='utf-8'))
                except (OSError,ValueError):previous={}
                failure=dict(model=item['model'],validation_pending=True,score=0,rejected=True,verdict='pending',
                    summary='Validation could not finish: '+str(exc),issues=[],hand_checks=[],uncertain=True,
                    image_sha256=fingerprint,image=str(image),reviewed_at=time.time(),advisory=True)
                if previous.get('image_sha256')==fingerprint and type(previous.get('score')) is int and not previous.get('validation_pending'):
                    report=image.with_name(image.stem+'.review-error.json')
                else:report=image.with_suffix('.review.json')
                report.write_text(json.dumps(failure,indent=2),encoding='utf-8')
            worker.emit('verification',1,message=f'Illustration {index+1}: validation pending; saved artwork retained. Continue reviewing the remaining images.')
            return
    else:
        if image.resolve()==target.resolve() and rejected(result,config.get('review_threshold',DEFAULT_THRESHOLD)):
            return dict(index=index,model=item['model'],expected_sha=result['image_sha256'],review=result)
        return
    with FileLock(str(image)+'.write.lock',timeout=30):
        unchanged = hashlib.sha256(image.read_bytes()).hexdigest() == result['image_sha256']
        report = image.with_suffix('.review.json') if unchanged else image.with_name(image.stem+'.earlier-review.json')
        report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    if image.resolve()!=target.resolve() and target.is_file():
        with FileLock(str(target)+'.write.lock',timeout=30):
            try:selection=json.loads(target.with_suffix('.selection.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):selection={}
            if Path(selection.get('selected','')).resolve()==image.resolve() and hashlib.sha256(target.read_bytes()).hexdigest()==result['image_sha256']:
                chosen=dict(result,image=str(target))
                target.with_suffix('.review.json').write_text(json.dumps(chosen,indent=2),encoding='utf-8')
    worker.emit('verification', 1, message=f'Illustration {index+1}: quality {result["score"]}%')
    if unchanged and rejected(result,config.get('review_threshold',DEFAULT_THRESHOLD)):
        repair=dict(index=index,model=item['model'],expected_sha=result['image_sha256'],review=result)
        if image.resolve()!=target.resolve():repair['candidate']=str(image)
        return repair


def repair_batch(worker, root, manifest, items, threshold=None):
    config=json.loads((root/'config.json').read_text(encoding='utf-8'))
    job=json.loads(manifest.read_text(encoding='utf-8'))
    threshold=config.get('review_threshold',DEFAULT_THRESHOLD) if threshold is None else threshold
    pending=[]
    for item in items:
        item=dict(item);target=Path(item.get('candidate') or manifest.parent/f'{item["index"]:03d}.png')
        if hashlib.sha256(target.read_bytes()).hexdigest()!=item['expected_sha']:
            worker.emit('repair-complete',1,message='Selection changed; automatic repair skipped',repaired=False,index=item['index'])
            continue
        report=item.get('review') or json.loads(target.with_suffix('.review.json').read_text(encoding='utf-8'))
        if report.get('validation_pending'):
            worker.emit('repair-complete',1,message=f'Illustration {item["index"]+1}: retry validation before requesting an image repair.',repaired=False,index=item['index'])
            continue
        if report.get('image_sha256')==item['expected_sha'] and rejected(report,threshold):
            from artwork.metadata import variant_metadata
            metadata=variant_metadata(target,job,item['index'])
            item.update(prompt=metadata['prompt'],subject=metadata['subject'])
            item['review']=report;pending.append(item)
    for attempt in range(MAX_AUTO_REPAIRS):
        if not pending:break
        pending=[item for item in pending if hashlib.sha256(
            Path(item.get('candidate') or manifest.parent/f'{item["index"]:03d}.png').read_bytes()).hexdigest()==item['expected_sha']]
        if not pending:break
        from models.gpu.lifecycle import current_session
        from direction.prompt_repair import revise_repair_prompts
        session=current_session()
        if session:
            session.release()
            session.unload_vision()
        planned=revise_repair_prompts(worker,job,config,pending)
        candidates=[]
        for item in pending:
            index=item['index'];target=Path(item.get('candidate') or manifest.parent/f'{index:03d}.png')
            if hashlib.sha256(target.read_bytes()).hexdigest()!=item['expected_sha']:continue
            worker.emit('repair',attempt/MAX_AUTO_REPAIRS,message=f'Generating repair round {attempt+1}: illustration {index+1}')
            revised=planned[index]
            prompt=revised['prompts'][index]
            candidate=worker.generate_candidate(root,revised,index,Path(config['image_cache']),prompt)
            candidates.append((item,candidate,prompt))
        pending=[]
        for item,candidate,prompt in sorted(candidates,key=lambda pair:pair[0]['model']):
            index=item['index'];target=manifest.parent/f'{index:03d}.png'
            from models.vision.response import ReviewUnavailable
            try:
                report=worker.vision_review(candidate,item['model'],job['groups'][index],config['style_prompt'],
                                           prompt,threshold)
            except ReviewUnavailable as exc:
                report=dict(score=0,validation_pending=True,rejected=True,verdict='pending',model=item['model'],
                    summary='Validation could not finish: '+str(exc),issues=[],hand_checks=[],uncertain=True,
                    image_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),image=str(candidate),advisory=True)
                candidate.with_suffix('.review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                worker.emit('repair-complete',1,message=f'Illustration {index+1}: repair candidate saved; validation needs retry.',repaired=False,index=index)
                continue
            candidate.with_suffix('.review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            if rejected(report,threshold):
                item.update(review=report,prompt=prompt);pending.append(item);continue
            if item.get('candidate'):
                from artwork.queue import require_replacement_review
                require_replacement_review(root,manifest,[dict(index=index,path=str(candidate))])
                worker.emit('candidate',1,message=f'Prompt-revised replacement ready for illustration {index+1}',artifact=str(candidate),index=index)
                worker.emit('repair-complete',1,message=f'Illustration {index+1}: revised prompt passed validation ({report["score"]}%); choose the replacement.',repaired=False,index=index)
                continue
            with FileLock(str(target)+'.write.lock',timeout=30):
                if hashlib.sha256(target.read_bytes()).hexdigest()!=item['expected_sha']:
                    worker.emit('repair-complete',1,message='Selection changed; reviewed repair saved as a candidate',repaired=False,index=index)
                    continue
                versions=root/'versions'/f'{index:03d}';versions.mkdir(parents=True,exist_ok=True)
                shutil.copy2(target,versions/f'{time.time_ns()}.png')
                temporary=target.with_suffix('.repair.tmp.png');shutil.copy2(candidate,temporary);temporary.replace(target)
                target.with_suffix('.selection.json').write_text(json.dumps(dict(selected=str(candidate),automatic=True,time=time.time())),encoding='utf-8')
                report['image']=str(target)
                target.with_suffix('.review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                from artwork.metadata import select_metadata
                select_metadata(manifest,index,dict(prompt=prompt))
                job['prompts'][index]=prompt
            worker.emit('repair-complete',1,message=f'Illustration {index+1} repaired and selected ({report["score"]}%)',repaired=True,index=index)
    for item in pending:
        worker.emit('repair-complete',1,message=f'Illustration {item["index"]+1}: retry limit reached; manual review needed.',repaired=False,index=item['index'])


def process_batch(worker, root, manifest, operation, items):
    config=json.loads((root/'config.json').read_text(encoding='utf-8'))
    job=json.loads(manifest.read_text(encoding='utf-8'))
    if operation=='verify':
        repairs=[]
        for item in sorted(items,key=lambda item:item['model']):
            result=review_one(worker,root,manifest,job,config,item)
            if result:repairs.append(result)
        if config.get('auto_repair',True):repair_batch(worker,root,manifest,repairs)
    elif operation=='repair':
        repair_batch(worker,root,manifest,items)
    elif operation in ('regenerate','reprompt'):
        from artwork.queue import generate_pending, require_replacement_review
        candidates=generate_pending(worker,root,job,config,[dict(item,action=item.get('action',operation)) for item in items])
        require_replacement_review(root,manifest,candidates)
        if config.get('auto_verify') and config.get('vision_model') and candidates:
            process_batch(worker,root,manifest,'verify',[dict(index=c['index'],candidate=c['path'],model=config['vision_model']) for c in candidates])
    else:
        raise ValueError('Unsupported batch operation: '+operation)
