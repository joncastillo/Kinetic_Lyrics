"""Small antialiased pink petals, green leaves and whole garden flowers."""
from functools import lru_cache
from core.paths import PROJECT_ROOT
from PIL import Image

FLOWERS = ('chrysanthemum','poppy','daisy')

@lru_cache(maxsize=32)
def botanical_photo(index):
    path=PROJECT_ROOT/'assets'/'botanical-v2'/'atlas.png'
    with Image.open(path) as atlas:
        cell_w,cell_h=atlas.width//4,atlas.height//4
        x,y=(index%4)*cell_w,(index//4)*cell_h
        sprite=atlas.convert('RGBA').crop((x,y,x+cell_w,y+cell_h))
    box=sprite.getchannel('A').point(lambda a:255 if a>16 else 0).getbbox()
    return sprite.crop(box) if box else sprite


def photo_index(kind, values):
    if kind=='petal':return 0 if values[0]<.5 else 1
    if kind=='leaf':return 2 if values[0]<.5 else 3
    if kind=='chrysanthemum':return 4+min(2,int(values[2]*3))
    if kind=='poppy':return (7,8,9)[min(2,int(values[2]*3))]
    if kind=='daisy':return 10 if values[2]<.5 else 11
    if kind=='chrysanthemum-bud':return 12
    if kind=='chrysanthemum-opening':return 13
    if kind=='poppy-bud':return 14
    if kind=='poppy-opening':return 15
    return 10


def botanical_sprite(kind,size,values,angle=0.,squash=1.):
    """The photograph for `kind`, fitted into a `size` square, squashed then rotated in a single resample."""
    return _sprite(photo_index(kind,values),max(4,round(size*2)),round(angle)%360,max(1,min(20,round(squash*20)))).copy()


@lru_cache(maxsize=8192)
def _sprite(index,half_pixels,angle,twentieths):
    from core.imaging import SUPERSAMPLE, reduce_sprite
    return reduce_sprite(_working_photo(index,max(2,round(half_pixels/2*SUPERSAMPLE))),half_pixels/2,angle,twentieths/20)


@lru_cache(maxsize=1024)
def _working_photo(index,span):
    """The photograph reduced once to the working size of one sprite size, shared by every angle."""
    from PIL import ImageOps
    return ImageOps.contain(botanical_photo(index),(span,span),Image.Resampling.LANCZOS)


