"""Atomic gallery snapshots readable by older running Studio servers."""
import json
import uuid
import time
from pathlib import Path


def publish_gallery(manifest):
    manifest=Path(manifest).resolve()
    if manifest.parent.parent.name!='video.artwork' or not manifest.is_file():return
    folder=manifest.parent.parent.parent
    def read(path):
        try:return json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}
    config=read(folder/'config.json')
    def snapshot(path):
        data=read(path);images=[];ready=0
        for i,prompt in enumerate(data.get('prompts',[])):
            variants=[]
            for file,is_raw in ((path.parent/f'{i:03d}.png',False),(path.parent/f'{i:03d}.raw.png',True)):
                if not file.is_file():continue
                stat=file.stat();review=read(file.with_suffix('.review.json')) or None
                variants.append(dict(path=file.relative_to(folder).as_posix(),modified=stat.st_mtime_ns,current=not is_raw,raw=is_raw,review=review,prompt=prompt,subject=data.get('visual_descriptions',data.get('prompts',[]))[i]))
            ready+=bool(variants)
            images.append(dict(index=i,subject=data.get('visual_descriptions',data.get('prompts',[]))[i],lyrics=data.get('groups',data.get('prompts',[]))[i],prompt=prompt,variants=variants,pending=''))
        return dict(manifest=path.relative_to(folder).as_posix(),seed=data.get('seed'),artwork_mode=data.get('artwork_mode','cutout'),images=images,ready=ready)
    current=snapshot(manifest)
    if current['seed']!=config.get('image_seed'):
        current=dict(current,previous_attempt=True)
    if not current['ready']:
        for other in sorted((folder/'video.artwork').glob('*/illustrations.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True):
            if other.resolve()==manifest:continue
            previous=snapshot(other)
            if previous['ready']:
                current=dict(current,previous=previous);break
    target=folder/'live-artwork.json';temporary=folder/('.live-artwork-'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(current,ensure_ascii=False),encoding='utf-8')
        for attempt in range(8):
            try:
                temporary.replace(target)
                break
            except PermissionError:
                if attempt==7:raise
                time.sleep(.01*(attempt+1))
    finally:
        temporary.unlink(missing_ok=True)
