"""Distinct glyph-bound frost, watercolor and embroidered-thread formation."""
import math
import random
import numpy as np
from PIL import Image,ImageDraw
from scipy.ndimage import distance_transform_edt,gaussian_filter
from particle_cache import sprite_key
from particle_choreography import entrance_opacity


def smooth(value):
    value=np.clip(value,0,1)
    return value*value*(3-2*value)


def geometry(sprite,effect,seed):
    mask=np.asarray(sprite.getchannel('A'));h,w=mask.shape
    rng=np.random.default_rng(seed);randoms=random.Random(seed)
    yy,xx=np.indices((h,w));ink=mask>100
    y,x=np.nonzero(ink)
    if not len(x):return None
    seeds=np.zeros((h,w),bool)
    for i in np.linspace(0,len(x)-1,min(16,max(3,w//24))).astype(int):seeds[y[i],x[i]]=True
    distance=distance_transform_edt(~seeds)
    noise=gaussian_filter(rng.random((h,w)),max(1,h*.025))
    birth=distance/max(1,np.max(distance[ink]))*.70+(xx/max(1,w))*.16+(noise-.5)*.24
    birth-=np.min(birth[ink]);birth/=max(.01,np.max(birth[ink]));birth*=.78
    texture=Image.new('RGBA',(w,h));draw=ImageDraw.Draw(texture)
    if effect.id=='frost-crystal-lettering':
        facet=((xx//max(3,h//10)+yy//max(3,h//8))%3)/2
        rgb=np.stack((135+90*facet,208+40*facet,235+20*facet),axis=-1).astype('uint8')
        texture=Image.fromarray(np.dstack((rgb,mask)),'RGBA');draw=ImageDraw.Draw(texture)
        for row in range(-h,w+h,max(5,h//8)):
            draw.line((row,0,row+h,h),fill=(235,253,255,180),width=max(1,h//45))
            draw.line((row+2,0,row+h+2,h),fill=(63,151,211,150),width=1)
    elif effect.id=='ink-bloom-lettering':
        pools=gaussian_filter(rng.random((h,w)),max(1,h*.06));pools=(pools-pools.min())/max(.001,np.ptp(pools))
        rgb=np.stack((150+100*pools,70+80*(1-pools),180+70*(1-pools)),axis=-1).astype('uint8')
        texture=Image.fromarray(np.dstack((rgb,mask)),'RGBA');draw=ImageDraw.Draw(texture)
        for _ in range(max(10,w//6)):
            cx=randoms.randrange(w);cy=randoms.randrange(h);r=randoms.uniform(1,max(2,h*.06))
            draw.ellipse((cx-r,cy-r,cx+r,cy+r),outline=(255,173,228,100),width=1)
    else:
        texture=Image.new('RGBA',(w,h),(45,40,63,255));draw=ImageDraw.Draw(texture)
        step=max(4,round(h*.065))
        for row in range(-step,h+step,step):
            for col in range(-step,w+step,step):
                color=(246,202,103,255) if ((row//step+col//step)%3) else (119,223,220,255)
                draw.line((col,row,col+step-1,row+step-1),fill=(73,46,27,255),width=3)
                draw.line((col,row-1,col+step-1,row+step-2),fill=color,width=2)
                draw.line((col+step-1,row,col,row+step-1),fill=(255,230,165,240),width=1)
        edge=(distance_transform_edt(ink)<1.6)&ink
        pixels=np.array(texture);pixels[edge,:3]=(244,210,140);texture=Image.fromarray(pixels,'RGBA')
    texture.putalpha(sprite.getchannel('A'))
    branches=[]
    for _ in range(12 if effect.id=='frost-crystal-lettering' else 18):
        i=randoms.randrange(len(x));px,py=float(x[i]),float(y[i])
        angle=math.atan2(py-h/2,px-w/2)+(randoms.random()-.5)*.7
        branches.append((px,py,angle,h*randoms.uniform(.15,.52),randoms.uniform(.16,.62),randoms.random()))
    return texture,birth,branches


def paint_growth(layer,sprite,x,y,progress,effect,seed,intensity=1.,cache=None,glyph_spans=None):
    if effect.family=='trees':
        from arboreal_growth import paint_growth as paint_tree
        return paint_tree(layer,sprite,x,y,progress,effect,seed,intensity,cache,glyph_spans)
    from ornate_growth import EFFECT_IDS
    if effect.id in EFFECT_IDS:
        from ornate_growth import paint_growth as paint_ornate
        return paint_ornate(layer,sprite,x,y,progress,effect,seed,intensity,cache)
    progress=max(0.,min(1.,progress));key=('material-growth-v1',sprite_key(sprite),effect,seed)
    if cache is None:parts=geometry(sprite,effect,seed)
    else:
        if key not in cache:cache[key]=geometry(sprite,effect,seed)
        parts=cache[key]
    if parts is None:return
    texture,birth,branches=parts
    if progress<=0:return
    reveal=smooth((progress-birth)/.22)*entrance_opacity(progress)
    photo=texture.copy();photo.putalpha(Image.fromarray((np.asarray(texture.getchannel('A'))*reveal).astype('uint8'),'L'))
    layer.alpha_composite(photo,(round(x),round(y)))
    draw=ImageDraw.Draw(layer)
    for px,py,angle,length,born,rand in branches:
        age=float(smooth((progress-born)/max(.1,1-born)))
        if age<=0:continue
        start=(x+px,y+py)
        if effect.id=='frost-crystal-lettering':
            end=(start[0]+math.cos(angle)*length*age,start[1]+math.sin(angle)*length*age)
            alpha=round(200*entrance_opacity(progress))
            draw.line((*start,*end),fill=(174,229,255,alpha),width=1)
            for fraction in (.3,.55,.78):
                if fraction>age:continue
                node=(start[0]+math.cos(angle)*length*fraction,start[1]+math.sin(angle)*length*fraction)
                for side in (-1,1):
                    direction=angle+side*.85;extent=length*.24*min(1,(age-fraction)*5)
                    draw.line((*node,node[0]+math.cos(direction)*extent,node[1]+math.sin(direction)*extent),fill=(217,248,255,alpha),width=1)
        elif effect.id=='ink-bloom-lettering' and progress>.2:
            radius=max(.6,min(2.8,sprite.height*.025))*age
            cx=start[0]+math.cos(angle)*length*.13;cy=start[1]+math.sin(angle)*length*.13
            draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill=(206,109,220,round(150*age)))
    if effect.id=='thread-stitch-lettering' and progress<.98:
        frontier=np.abs(birth-progress+.10)<.035
        glow=np.zeros((*frontier.shape,4),dtype='uint8');glow[:,:,:3]=(255,244,199)
        glow[:,:,3]=(frontier*(np.asarray(sprite.getchannel('A'))>150)*170).astype('uint8')
        layer.alpha_composite(Image.fromarray(glow,'RGBA'),(round(x),round(y)))


def grown_sprite(sprite,effect,seed,intensity=1.,cache=None,glyph_spans=None):
    key=('material-held-v2',sprite_key(sprite),effect,seed,intensity,tuple(glyph_spans or ()))
    if cache is not None and key in cache:return cache[key]
    padding=round(sprite.height*.7)
    image=Image.new('RGBA',(sprite.width+2*padding,sprite.height+2*padding))
    paint_growth(image,sprite,padding,padding,1.,effect,seed,intensity,cache,glyph_spans)
    result=image,padding
    if cache is not None:cache[key]=result
    return result
