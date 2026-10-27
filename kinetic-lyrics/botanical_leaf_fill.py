"""Overlapping photographic leaves fill glyph strokes without closing counters."""
import random
import numpy as np
from PIL import Image,ImageEnhance
from botanical_materials import botanical_sprite
from particle_cache import sprite_key
from particle_choreography import entrance_opacity


def leaf_texture(sprite,seed=0,cache=None):
    key=('large-leaf-glyph-v1',sprite_key(sprite),seed)
    if cache is not None and key in cache:return cache[key]
    rng=random.Random(seed);w,h=sprite.size
    result=Image.new('RGBA',sprite.size,(30,68,37,255))
    size=max(24,min(68,h*.46));step=max(6,round(size*.24))
    for row,y in enumerate(range(-step,h+step,step)):
        for x in range(-step,w+step,step):
            values=tuple(rng.random() for _ in range(6))
            photo=botanical_sprite('leaf',size*(.8+values[2]*.45),values)
            photo=ImageEnhance.Brightness(photo).enhance(.78+values[4]*.35)
            photo=photo.rotate((-38 if row%2 else 48)+(values[3]-.5)*65,Image.Resampling.BICUBIC,expand=True)
            cx=x+(step*.5 if row%2 else 0)+(values[0]-.5)*step*.5
            cy=y+(values[1]-.5)*step*.5
            result.alpha_composite(photo,(round(cx-photo.width/2),round(cy-photo.height/2)))
    result.putalpha(sprite.getchannel('A'))
    if cache is not None:cache[key]=result
    return result


def paint_leaf_fill(layer,sprite,x,y,progress,seed=0,cache=None):
    if progress<=0:return
    texture=leaf_texture(sprite,seed,cache)
    if progress>=1:
        layer.alpha_composite(texture,(round(x),round(y)))
        return
    yy,xx=np.indices((sprite.height,sprite.width))
    birth=.04+.18*xx/max(1,sprite.width)+.03*np.sin(yy/max(1,sprite.height)*6.28)
    reveal=np.clip((progress-birth)/.58,0,1)
    reveal=reveal*reveal*(3-2*reveal)*entrance_opacity(progress)
    image=texture.copy();image.putalpha(Image.fromarray((np.asarray(texture.getchannel('A'))*reveal).astype('uint8')))
    layer.alpha_composite(image,(round(x),round(y)))
