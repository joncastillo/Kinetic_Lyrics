"""Photographic tree and flight assets, cropped from a transparent 4x5 atlas."""
from functools import lru_cache
from pathlib import Path
from project_paths import PROJECT_ROOT
import numpy as np
from PIL import Image,ImageOps

@lru_cache(maxsize=24)
def asset(index):
    with Image.open(PROJECT_ROOT/'assets'/'tree-flock-v1'/'atlas.png') as image:
        x,y=index%4,index//4;w,h=image.width/4,image.height/5
        photo=image.convert('RGBA').crop((round(x*w),round(y*h),round((x+1)*w),round((y+1)*h)))
    if index in (6,7):
        margin=round(min(photo.size)*.06)
        return photo.crop((margin,margin,photo.width-margin,photo.height-margin))
    box=photo.getchannel('A').point(lambda a:255 if a>24 else 0).getbbox()
    return photo.crop(box) if box else photo

@lru_cache(maxsize=256)
def sized_asset(index,size):
    return ImageOps.contain(asset(index),(max(2,size),max(2,size)),Image.Resampling.LANCZOS)

def glyph_ranges(sprite,spans=None):
    if spans:return [(max(0,int(a)),min(sprite.width,int(b))) for a,b in spans if b>a]
    ink=np.asarray(sprite.getchannel('A'))>120;columns=np.any(ink,axis=0)
    changes=np.diff(np.r_[False,columns,False].astype(int));starts=np.flatnonzero(changes==1);ends=np.flatnonzero(changes==-1)
    return list(zip(starts,ends))
