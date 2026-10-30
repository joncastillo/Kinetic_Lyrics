"""Claim later regeneration requests while a worker keeps its image model loaded."""
from core.paths import default_model_cache
import json
from pathlib import Path
from filelock import FileLock


def queue_path(root):return Path(root)/'regeneration-queue.json'


def update_queue(root,append=None,remove=()):
    path=queue_path(root)
    with FileLock(str(path)+'.lock',timeout=30):
        items=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        items=[item for item in items if item.get('request_id') not in remove]
        if append:items.append(append)
        temporary=path.with_suffix('.tmp.json');temporary.write_text(json.dumps(items),encoding='utf-8');temporary.replace(path)


def claim_queue(worker,root):
    path=queue_path(root)
    if not path.exists():return []
    with FileLock(str(path)+'.lock',timeout=30):
        items=json.loads(path.read_text(encoding='utf-8'))
        if items:
            temporary=path.with_suffix('.tmp.json');temporary.write_text('[]',encoding='utf-8');temporary.replace(path)
    if items:worker.emit('queue-claimed',0,message=f'Added {len(items)} queued image request(s) to the current worker',requests=items)
    return items


def generate_pending(worker,root,job,config,items):
    """Drain direct images before switching to a newly queued prompting phase."""
    from direction.prompt_regeneration import regenerate_prompts
    from models.gpu.lifecycle import current_session
    images=[];prompts=[];completed=[]
    def add(requests):
        for item in requests:
            (prompts if item.get('action','regenerate')=='reprompt' else images).append(item)
    add(items)
    while True:
        session=current_session()
        if prompts and (not images or session is None or session.pipe is None):
            if session:session.release()
            batch=prompts[:];prompts.clear()
            replacements=regenerate_prompts(worker,job,config,batch)
            for item in batch:images.append(dict(item,planned_job=replacements[item['index']]))
        if not images:
            add(claim_queue(worker,root))
            if images or prompts:continue
            return completed
        item=images.pop(0);index=item['index'];planned=item.get('planned_job',job)
        prompt=planned['prompts'][index] if 'planned_job' in item else item.get('prompt','')
        worker.emit('image-start',0,message=f'Generating replacement for illustration {index+1}',index=index)
        candidate=worker.generate_candidate(root,planned,index,Path(config['image_cache']),prompt)
        completed.append(dict(index=index,path=str(candidate),request_id=item.get('request_id')))
        worker.emit('candidate',1,message=f'New candidate ready for illustration {index+1}',artifact=str(candidate),index=index)
        add(claim_queue(worker,root))


def has_pending(root):
    path=queue_path(root)
    if not path.exists():return False
    with FileLock(str(path)+'.lock',timeout=30):
        return bool(json.loads(path.read_text(encoding='utf-8')))


def replacement_review_path(root):return Path(root)/'replacement-review-required.json'


def require_replacement_review(root,manifest,candidates):
    if not candidates:return
    path=replacement_review_path(root)
    previous=[]
    if path.exists():
        saved=json.loads(path.read_text(encoding='utf-8'))
        if saved.get('manifest')==str(manifest):previous=saved.get('candidates',[])
    latest={item['index']:item for item in previous+candidates}
    temporary=path.with_suffix('.tmp.json')
    temporary.write_text(json.dumps(dict(manifest=str(manifest),candidates=list(latest.values()))),encoding='utf-8')
    temporary.replace(path)


def replacement_review_pending(paths):
    if not paths:return False
    manifest=Path(paths[0]).parent/'illustrations.json';root=manifest.parent.parent.parent
    path=replacement_review_path(root)
    if not path.exists():return False
    saved=json.loads(path.read_text(encoding='utf-8'))
    if saved.get('manifest')!=str(manifest):return False
    for candidate in saved.get('candidates',[]):
        target=manifest.parent/f'{candidate["index"]:03d}.png'
        try:selection=json.loads(target.with_suffix('.selection.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return True
        if Path(selection.get('selected','')).resolve()!=Path(candidate['path']).resolve():return True
    return False


class ReplacementsPending(RuntimeError):pass


def before_video_render(output,args):
    """Process late image requests and require selection before any final render."""
    import subprocess,sys,time
    from core.progress import emit
    paths=getattr(args,'illustrations',None) or []
    if not paths:return False
    root=Path(output).parent;changed=False
    manifest=Path(paths[0]).parent/'illustrations.json'
    while has_pending(root):
        changed=True
        emit('illustrations',1,message='Processing queued image replacements before video rendering')
        cache=Path(getattr(args,'image_cache',None) or str(default_model_cache()))
        from core.process import module_command,module_env
        subprocess.run(module_command('artwork.generation',manifest,'--cache',cache),env=module_env(),check=True)
    if replacement_review_pending(paths):
        changed=True;approval=root/'artwork-approved';approval.unlink(missing_ok=True)
        emit('review',0,message='Replacement images are ready. Select an image, then approve to render.')
        while not approval.exists():time.sleep(.5)
    return changed
