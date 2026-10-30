"""Botanical pieces follow glyph contours and remain readable during the hold."""
from effects.particles.cache import sprite_key

from dataclasses import dataclass
import math
import random
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from effects.growth.botanical_materials import botanical_sprite, FLOWERS
from effects.particles.choreography import entrance_opacity

@dataclass
class BotanicalParticle:
    x: float
    y: float
    random: tuple
    image: Image.Image
    kind: str
    edge: bool
    size: float


def _petals(sprite, effect, seed, intensity):
    rng=random.Random(seed);mask=np.asarray(sprite.getchannel('A'))>160
    distance=distance_transform_edt(mask)
    yy,xx=np.nonzero(mask)
    spacing=max(1.6,sprite.height*.012)/math.sqrt(max(.3,intensity*effect.density))
    indices=list(range(len(xx)));rng.shuffle(indices)
    indices.sort(key=lambda i:distance[yy[i],xx[i]]>1.7)
    cells={};particles=[];edge_count=0
    for candidate in indices[:24000]:
        x,y=float(xx[candidate]),float(yy[candidate]);cell=(int(x//spacing),int(y//spacing))
        neighbors=[p for a in range(cell[0]-1,cell[0]+2) for b in range(cell[1]-1,cell[1]+2) for p in cells.get((a,b),[])]
        if any((x-px)**2+(y-py)**2<spacing**2 for px,py in neighbors):continue
        clearance=float(distance[int(y),int(x)]);edge=clearance<=1.7
        if edge and edge_count>=640:continue
        edge_count+=int(edge)
        cells.setdefault(cell,[]).append((x,y));values=tuple(rng.random() for _ in range(6))
        choice=values[0]
        kind=('petal' if choice<.55 else 'leaf') if edge else ('petal' if choice<.43 else 'leaf' if choice<.83 else FLOWERS[min(2,int(values[1]*3))])
        size=(2+values[3]*.8 if edge else min(11,sprite.height*.17,clearance*1.8,3+values[3]*7))
        if kind in FLOWERS:size=min(size,8.5)
        particles.append(BotanicalParticle(x,y,values,botanical_sprite(kind,size,values),kind,edge,size))
        if len(particles)>=1200:break
    return particles


def paint_petal_formation(layer,sprite,x,y,amount,effect,seed,intensity=1.,cache=None):
    growing=effect.trajectory=='grow'
    progress=max(0.,min(1.,1-amount))
    if growing:
        from effects.growth.botanical import paint_growth
        paint_growth(layer,sprite,x,y,progress,effect,seed,intensity,cache)
        return
    if amount>=1:return
    key=('botanical-formation-v2',sprite_key(sprite),effect,seed,intensity)
    if cache is None:particles=_petals(sprite,effect,seed,intensity)
    else:
        if key not in cache:cache[key]=_petals(sprite,effect,seed,intensity)
        particles=cache[key]
    for particle in particles:
        px,py,values,leaf=particle.x,particle.y,particle.random,particle.image
        delay=effect.stagger*values[1]
        arrival=max(0.,min(1.,(progress-delay)/(1-delay)))
        eased=arrival*arrival*(3-2*arrival);q=1-eased
        travel=(sprite.width*.8+sprite.height*effect.spread)*q
        dx=-travel*(.75+values[2]*.5);dy=(values[3]-.5)*sprite.height*3*q
        if effect.trajectory=='right':dx=-dx
        elif effect.trajectory=='up':dx,dy=dy*.55,-travel
        elif effect.trajectory=='spiral':
            angle=values[4]*math.tau+q*effect.twist;dx,dy=math.cos(angle)*travel,math.sin(angle)*travel*.65
        dy+=math.sin(q*8+values[4]*math.tau)*sprite.height*.3*q
        dx+=math.sin(q*5+values[5]*math.tau)*sprite.height*.12*q
        angle=(values[4]-.5)*90+q*(values[5]-.5)*540*effect.spin
        piece=botanical_sprite(particle.kind,particle.size,values,angle=angle)
        alpha=entrance_opacity(progress)
        piece.putalpha(piece.getchannel('A').point(lambda a:round(a*alpha)))
        layer.alpha_composite(piece,(round(x+px+dx-piece.width/2),round(y+py+dy-piece.height/2)))


def petal_word(sprite,effect,seed,intensity=1.,cache=None):
    key=('botanical-word-v2',sprite_key(sprite),effect,seed,intensity)
    if cache is not None and key in cache:return cache[key]
    result=Image.new('RGBA',sprite.size)
    paint_petal_formation(result,sprite,0,0,0.,effect,seed,intensity,cache)
    if cache is not None:cache[key]=result
    return result
