"""Small antialiased pink petals, green leaves and whole garden flowers."""
import math
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw

FLOWERS = ('chrysanthemum','poppy','daisy')

@lru_cache(maxsize=32)
def botanical_photo(index):
    path=Path(__file__).with_name('assets')/'botanical-v2'/'atlas.png'
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


def botanical_sprite(kind,size,values):
    from PIL import ImageOps
    source=botanical_photo(photo_index(kind,values))
    return ImageOps.contain(source,(max(2,round(size)),max(2,round(size))),Image.Resampling.LANCZOS)


def procedural_botanical_sprite(kind, size, values):
    scale=3
    size=max(2,round(size));span=size+4;c=span*scale/2;r=size*scale*.46
    image=Image.new('RGBA',(span*scale,span*scale));draw=ImageDraw.Draw(image)
    def color(palette):return palette[min(len(palette)-1,int(values[2]*len(palette)))]
    if kind in ('petal','leaf'):
        ink=color([(245,155,184),(229,116,158),(255,192,207),(210,98,143)] if kind=='petal' else
                  [(76,139,74),(108,166,78),(55,119,78),(145,181,93)])
        fullness=.55 if kind=='petal' else .36
        points=[(c+(t/20-.5)*r*2,c+side*math.sin(t/20*math.pi)*r*fullness)
                for side in (1,-1) for t in (range(21) if side==1 else range(20,-1,-1))]
        draw.polygon(points,fill=(*ink,245))
        if kind=='leaf':
            draw.line((c-r*.85,c,c+r*.85,c),fill=(183,207,125,190),width=scale//2 or 1)
    else:
        ink=color([(245,175,199),(250,211,89),(237,116,107),(188,162,228),(247,237,211),(250,168,91)])
        if kind=='poppy':
            for n in range(5):
                a=n*math.tau/5;px=c+math.cos(a)*r*.34;py=c+math.sin(a)*r*.34
                draw.ellipse((px-r*.62,py-r*.62,px+r*.62,py+r*.62),fill=(*ink,248))
            draw.ellipse((c-r*.24,c-r*.24,c+r*.24,c+r*.24),fill=(51,48,49,255))
        else:
            rings=(1,.72,.45) if kind=='chrysanthemum' else (1,)
            for ring in rings:
                count=18 if kind=='chrysanthemum' else 10
                for n in range(count):
                    a=n*math.tau/count+ring*.3;u=(math.cos(a),math.sin(a));v=(-u[1],u[0])
                    end=r*ring;start=r*.12;width=r*(.12 if kind=='chrysanthemum' else .22)
                    draw.polygon([(c+u[0]*start,c+u[1]*start),
                                  (c+u[0]*end*.65+v[0]*width,c+u[1]*end*.65+v[1]*width),
                                  (c+u[0]*end,c+u[1]*end),
                                  (c+u[0]*end*.65-v[0]*width,c+u[1]*end*.65-v[1]*width)],fill=(*ink,247))
            draw.ellipse((c-r*.19,c-r*.19,c+r*.19,c+r*.19),fill=(225,169,58,255))
    return image.resize((span,span),Image.Resampling.LANCZOS)
