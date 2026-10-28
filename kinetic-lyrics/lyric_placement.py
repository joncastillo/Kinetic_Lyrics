"""Find readable lyric areas on finished artwork while protecting visible faces."""
import base64,hashlib,io,json,math
from pathlib import Path
from PIL import Image,ImageOps,ImageFilter

VERSION=1


def box_valid(box):return isinstance(box,list) and len(box)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in box) and 0<=box[0]<box[2]<=1000 and 0<=box[1]<box[3]<=1000


def intersects(a,b,margin=0):
    return a[0]<b[2]+margin and a[2]>b[0]-margin and a[1]<b[3]+margin and a[3]>b[1]-margin


def choose_region(image,faces,candidates):
    """A face exclusion is a hard constraint, including a breathing margin."""
    faces=[box for box in faces if box_valid(box)]
    proposed=[c for c in candidates if box_valid(c.get('box'))]
    def safe(box):return all(not intersects(box,face,40) for face in faces)
    usable=[c for c in proposed if safe(c['box']) and c['box'][2]-c['box'][0]>=280 and c['box'][3]-c['box'][1]>=170]
    if usable:
        return max(usable,key=lambda c:float(c.get('score',50))+.00006*(c['box'][2]-c['box'][0])*(c['box'][3]-c['box'][1]))['box']
    import numpy as np
    gray=np.asarray(image.convert('L').resize((160,90)),dtype=float)
    edge=np.asarray(image.convert('L').resize((160,90)).filter(ImageFilter.FIND_EDGES),dtype=float)
    choices=[]
    for width in (280,340,420,550,680,800):
        for height in (170,240,340,460,580):
            for left in range(35,966-width,65):
                for top in range(35,966-height,55):
                    box=[left,top,left+width,top+height]
                    if not safe(box):continue
                    x0,x1=round(left*.16),round((left+width)*.16);y0,y1=round(top*.09),round((top+height)*.09)
                    region=gray[y0:y1,x0:x1];detail=edge[y0:y1,x0:x1]
                    score=width*height/10000-region.std()*.32-detail.mean()*.8
                    choices.append((score,box))
    if not choices:raise ValueError('No readable lyric region avoids the detected faces')
    return max(choices,key=lambda item:item[0])[1]


def face_fallback(image):
    try:
        import cv2,numpy as np
        gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
        classifier=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
        boxes=classifier.detectMultiScale(gray,scaleFactor=1.1,minNeighbors=6,minSize=(45,45))
        w,h=image.size
        return [[round(x/w*1000),round(y/h*1000),round((x+bw)/w*1000),round((y+bh)/h*1000)] for x,y,bw,bh in boxes]
    except (ImportError,AttributeError):return []


def inspect_image(path,width,height,model,session):
    from ollama_gpu import gpu_chat
    path=Path(path);raw=path.read_bytes();fingerprint=hashlib.sha256(raw).hexdigest()
    image=ImageOps.fit(Image.open(io.BytesIO(raw)).convert('RGB'),(width,height),Image.Resampling.LANCZOS)
    faces=face_fallback(image);candidates=[];source='image contrast and face detection'
    if model:
        sample=image.copy();sample.thumbnail((1024,1024));buffer=io.BytesIO();sample.save(buffer,format='JPEG',quality=90)
        bbox=dict(type='array',items=dict(type='integer',minimum=0,maximum=1000),minItems=4,maxItems=4)
        schema=dict(type='object',properties=dict(faces=dict(type='array',maxItems=20,items=bbox),safe_regions=dict(type='array',minItems=1,maxItems=5,items=dict(type='object',properties=dict(box=bbox,score=dict(type='integer',minimum=0,maximum=100)),required=['box','score']))),required=['faces','safe_regions'])
        payload=dict(model=model,stream=False,think=False,keep_alive=-1,format=schema,options=dict(num_ctx=8192,num_predict=4096,temperature=0),messages=[dict(role='user',content=(
            'Choose clear areas for a large multiline lyric block on this finished image. '
            'Return every visible face bounding box, plus up to five suitable text rectangles ranked by score. '
            'All boxes use [left,top,right,bottom], coordinates0..1000 over the entire image. '
            'Prefer nearby quiet walls, sky or empty space around the main subject. '
            'Avoid faces, heads, important objects, intricate patterns and high-contrast details. '
            'Protect every face with extra space. Text areas should be wide enough for several large words. '
            'Do not assume the center, top or bottom is best. Inspect this actual image. '
            'Return only short final JSON with faces and safe_regions; no prose.'),images=[base64.b64encode(buffer.getvalue()).decode()])])
        for attempt in range(2):
            try:
                query=dict(payload,options=dict(payload['options'],num_ctx=16384 if attempt else 8192,num_predict=8192 if attempt else 4096))
                response=session.review_request(gpu_chat,query)
                answer=json.loads(response.get('message',{}).get('content') or '{}')
                inferred=answer.get('faces');regions=answer.get('safe_regions')
                if not isinstance(inferred,list) or not isinstance(regions,list) or not regions:raise ValueError('Incomplete placement JSON')
                faces+= [b for b in inferred if box_valid(b)]
                candidates=[c for c in regions if isinstance(c,dict) and box_valid(c.get('box'))]
                source='vision and image contrast';break
            except (ValueError,OSError) as exc:
                if attempt:print(f'Placement model unavailable for {path.name}; using image analysis: {exc}',flush=True)
    chosen=choose_region(image,faces,candidates)
    return dict(version=VERSION,model=model,image_sha256=fingerprint,canvas=[width,height],faces=faces,safe_regions=candidates,chosen=chosen,source=source)


def cached_placement(path,width,height,image_sha256=None):
    path=Path(path)
    try:
        report=json.loads(path.with_suffix('.placement.json').read_text(encoding='utf-8'))
        if report.get('version')==VERSION and report.get('canvas')==[width,height] and report.get('image_sha256')==(image_sha256 or hashlib.sha256(path.read_bytes()).hexdigest()) and box_valid(report.get('chosen')):return report
    except (OSError,ValueError):pass
    return None


def fit_crop(size,canvas):
    """The source rectangle ImageOps.fit keeps when filling the video canvas."""
    width,height=size;aspect=canvas[0]/canvas[1]
    if width/height>aspect:
        crop=height*aspect;return (width-crop)/2,0.,crop,float(height)
    crop=width/aspect;return 0.,(height-crop)/2,float(width),crop


def image_area(box,size,canvas):
    """Canvas box (0..1000) as fractions of the original image, for drawing on the gallery preview."""
    x,y,w,h=fit_crop(size,canvas)
    return [round((x+box[0]/1000*w)/size[0],4),round((y+box[1]/1000*h)/size[1],4),
            round((x+box[2]/1000*w)/size[0],4),round((y+box[3]/1000*h)/size[1],4)]


def text_area(path,width,height,image_sha256=None):
    report=cached_placement(path,width,height,image_sha256)
    if not report:return None
    with Image.open(path) as image:size=image.size
    return dict(box=image_area(report['chosen'],size,(width,height)),source=report.get('source',''))


def save_manual_area(path,fractions,width,height):
    """Store a hand-drawn lyric area; it is reused like a measured one and survives re-measuring."""
    path=Path(path)
    if not (isinstance(fractions,list) and len(fractions)==4 and all(type(v) in (int,float) and math.isfinite(v) for v in fractions)):
        raise ValueError('Draw a rectangle on the image first')
    raw=path.read_bytes()
    with Image.open(io.BytesIO(raw)) as image:size=image.size
    x,y,w,h=fit_crop(size,(width,height))
    (left,right),(top,bottom)=sorted(fractions[0::2]),sorted(fractions[1::2])
    convert=lambda value,origin,span,total:max(0,min(1000,round((value*total-origin)/span*1000)))
    box=[convert(left,x,w,size[0]),convert(top,y,h,size[1]),convert(right,x,w,size[0]),convert(bottom,y,h,size[1])]
    if box[2]-box[0]<40 or box[3]-box[1]<40:raise ValueError('The text area is too small or outside the video frame')
    previous=cached_placement(path,width,height) or {}
    report=dict(version=VERSION,model=None,image_sha256=hashlib.sha256(raw).hexdigest(),canvas=[width,height],
                faces=previous.get('faces',[]),safe_regions=previous.get('safe_regions',[]),chosen=box,source='manual')
    temporary=path.with_suffix('.placement.tmp.json');temporary.write_text(json.dumps(report,indent=2),encoding='utf-8');temporary.replace(path.with_suffix('.placement.json'))
    return report


def revision_key(image_sha256,placement):
    """Rendered-section identity: the artwork plus the lyric area drawn over it."""
    return image_sha256+('@'+','.join(map(str,placement['chosen'])) if placement else '')


def revision_matches(recorded,image_sha256,placement):
    if recorded==revision_key(image_sha256,placement):return True
    return recorded==image_sha256 and (placement or {}).get('source')!='manual'


def dimensions_path(output):
    output=Path(output);return output.with_name(output.stem+'.dimensions.json')


def run_dimensions(paths,options,output,force=False):
    """Step 5: decide where lyrics can sit on every finished image, saved for reuse by the video step."""
    from kinetic_progress import emit
    paths=[Path(p) for p in paths or []];mode=options.get('artwork_mode','cutout')
    width,height=options.get('width',1280),options.get('height',720)
    if options.get('reading_flow') == 'realtime':
        emit('dimensions',1,message='Real-time flow places lyrics with the camera; no text areas to measure')
        return None
    emit('dimensions',0,message='Measuring text areas on the finished artwork')
    if force:
        for path in paths:
            report=cached_placement(path,width,height)
            if not report or report.get('source')!='manual':path.with_suffix('.placement.json').unlink(missing_ok=True)
    ensure_placements(paths,options,output)
    images=[]
    for index,path in enumerate(paths):
        report=cached_placement(path,width,height)
        images.append(dict(index=index,image=path.name,image_sha256=report['image_sha256'] if report else None,
                           text_box=report['chosen'] if report else None,source=report['source'] if report else 'artwork layout'))
    summary=dict(version=VERSION,canvas=[width,height],artwork_mode=mode,images=images)
    target=dimensions_path(output);temporary=target.with_suffix('.tmp.json')
    temporary.write_text(json.dumps(summary,indent=2),encoding='utf-8');temporary.replace(target)
    measured=sum(1 for item in images if item['text_box'])
    emit('dimensions',1,message=f'Text areas ready for {measured} image(s)' if measured else 'Text areas follow the planned artwork layout')
    return summary


def ensure_placements(paths,options,output=None):
    if not paths or options.get('artwork_mode','cutout') not in ('verse','fullscreen'):return
    width,height=options.get('width',1280),options.get('height',720)
    pending=[Path(p) for p in paths if cached_placement(p,width,height) is None]
    if not pending:return
    config={}
    if output:
        try:config=json.loads((Path(output).parent/'config.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
    model=options.get('vision_model') or config.get('vision_model')
    from model_lifecycle import ModelSession
    from kinetic_progress import emit
    from ollama_gpu import unload_model
    try:
        with ModelSession([model]) as session:
            for index,path in enumerate(pending):
                emit('dimensions',index/len(pending),message=f'Finding a clear lyric area: image {index+1}/{len(pending)}')
                report=inspect_image(path,width,height,model,session)
                temporary=path.with_suffix('.placement.tmp.json');temporary.write_text(json.dumps(report,indent=2),encoding='utf-8');temporary.replace(path.with_suffix('.placement.json'))
    finally:
        if model:
            try:unload_model(model)
            except (OSError,ValueError) as exc:print('Placement model cleanup: '+str(exc),flush=True)
