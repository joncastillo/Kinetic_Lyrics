"""Botanical pieces follow glyph contours and remain readable during the hold.

The letters are tiled with photographic petals, leaves and small flowers. For the blown letterings the pieces
arrive as a stream from one side (or spiral in) and settle into the letters in a relay along the wind, each
landing with a small overshoot; a dark outline is drawn round each letter as it fills, so the mosaic reads as
the word on any painting. Every frame is a pure function of progress."""
from effects.particles.cache import sprite_key

from dataclasses import dataclass
import math
import random
import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps
from scipy.ndimage import distance_transform_edt
from effects.growth.botanical_materials import botanical_sprite, FLOWERS

# (fill, rim) of the blossom bed under each word's petals
BEDS = (((214, 92, 128), (96, 24, 52)), ((168, 120, 214), (62, 34, 104)), ((242, 168, 52), (120, 62, 10)),
        ((246, 236, 226), (110, 76, 70)))


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
    h=sprite.height
    spacing=max(2.2,h*.03)/math.sqrt(max(.3,intensity*effect.density))
    indices=list(range(len(xx)));rng.shuffle(indices)
    indices.sort(key=lambda i:distance[yy[i],xx[i]]>2.2)
    cells={};particles=[];edge_count=0
    for candidate in indices[:24000]:
        x,y=float(xx[candidate]),float(yy[candidate]);cell=(int(x//spacing),int(y//spacing))
        neighbors=[p for a in range(cell[0]-1,cell[0]+2) for b in range(cell[1]-1,cell[1]+2) for p in cells.get((a,b),[])]
        if any((x-px)**2+(y-py)**2<spacing**2 for px,py in neighbors):continue
        clearance=float(distance[int(y),int(x)]);edge=clearance<=2.2
        if edge and edge_count>=360:continue
        edge_count+=int(edge)
        cells.setdefault(cell,[]).append((x,y));values=tuple(rng.random() for _ in range(6))
        choice=values[0]
        kind=('petal' if choice<.6 else 'leaf') if edge else ('petal' if choice<.5 else 'leaf' if choice<.84 else FLOWERS[min(2,int(values[1]*3))])
        # pieces are big enough to read as petals, a little wider than the stroke they sit in
        size=(h*.045+values[3]*h*.03 if edge else min(h*.22,clearance*2.6+h*.03,h*.06+values[3]*h*.14))
        if kind in FLOWERS:size=min(size,h*.14)
        particles.append(BotanicalParticle(x,y,values,botanical_sprite(kind,size,values),kind,edge,size))
        if len(particles)>=700:break
    return particles


def _outline(sprite,cache):
    """A dark ring just outside the letters, as an L image padded by its width."""
    width=max(2,min(6,round(sprite.height*.022)))
    key=('petal-outline-v1',sprite_key(sprite),width)
    if cache is not None and key in cache:return cache[key]
    glyph=ImageOps.expand(sprite.getchannel('A').point(lambda a:255 if a>160 else 0),border=width)
    ring=ImageChops.subtract(glyph.filter(ImageFilter.MaxFilter(width*2+1)),glyph).filter(ImageFilter.GaussianBlur(.6))
    result=(ring,width)
    if cache is not None:cache[key]=result
    return result


def paint_petal_formation(layer,sprite,x,y,amount,effect,seed,intensity=1.,cache=None):
    growing=effect.trajectory=='grow'
    progress=max(0.,min(1.,1-amount))
    if growing:
        from effects.growth.botanical import paint_growth
        paint_growth(layer,sprite,x,y,progress,effect,seed,intensity,cache)
        return
    if amount>=1:return
    key=('botanical-formation-v4',sprite_key(sprite),effect,seed,intensity)
    if cache is None:particles=_petals(sprite,effect,seed,intensity)
    else:
        if key not in cache:cache[key]=_petals(sprite,effect,seed,intensity)
        particles=cache[key]
    # The swarm is on screen from the first frame, within a word height or so of the word, and settles into
    # the letters in a relay along the wind: the upwind letters fill first, so the stream visibly pours into
    # letter after letter. Each piece slows into its place with a small overshoot and locks its turn.
    w,h=sprite.size
    def order_of(px,py):
        along=px/max(1,w)
        if effect.trajectory=='right':return 1-along   # blown from the right: the right-hand letters fill first
        if effect.trajectory=='spiral':return .5+.5*math.sin(math.atan2(py-h/2,px-w/2))  # round the word
        return along                                     # blown from the left
    # the outline follows the fill, column by column
    ring,width=_outline(sprite,cache)
    columns=np.arange(ring.width)-width
    start=.06 if effect.trajectory=='spiral' else .14
    reveal=np.clip((progress-(start+.5*np.array([order_of(c,h/2) for c in columns])))/.06,0,1)
    reveal=reveal*reveal*(3-2*reveal)
    base,rim_colour=BEDS[seed%len(BEDS)]  # each word its own blossom: rose, lilac, marigold or white
    outline=Image.new('RGBA',ring.size,(*rim_colour,255))
    outline.putalpha(Image.fromarray((np.asarray(ring,dtype=np.float32)*reveal[None,:]).astype('uint8'),'L'))
    layer.alpha_composite(outline,(round(x)-width,round(y)-width))
    # a solid rose bed inside a crisp letter mask, so the letters read as clean shapes however the petals lie
    mask=np.asarray(sprite.getchannel('A'),dtype=np.float32)*(np.asarray(sprite.getchannel('A'))>120)
    bed=Image.new('RGBA',sprite.size,(*base,255))
    bed.putalpha(Image.fromarray((mask*reveal[None,width:width+sprite.width]).astype('uint8'),'L'))
    layer.alpha_composite(bed,(round(x),round(y)))
    settled=[]
    for particle in particles:
        px,py,values=particle.x,particle.y,particle.random
        order=order_of(px,py)
        delay=.05+.5*order+.12*values[1]
        arrival=max(0.,min(1.,(progress-delay)/.32))
        eased=arrival*arrival*(3-2*arrival)
        q=1-eased
        settle=1+.14*math.sin(math.pi*max(0.,min(1.,(arrival-.75)/.25)))  # a little overshoot as it lands
        if effect.trajectory=='spiral':
            travel=h*(.35+.35*values[2])*q
            angle=values[4]*math.tau+q*effect.twist
            dx,dy=math.cos(angle)*travel*1.1,math.sin(angle)*travel*.65
        else:
            direction=1 if effect.trajectory=='right' else -1
            travel=h*(.5+.4*values[2]+.6*order)*q  # the later pieces wait further upwind: a long stream
            dx=direction*travel
            dy=(values[3]-.5)*h*.9*q+math.sin(q*7+values[4]*math.tau)*h*.2*q
            if effect.trajectory=='left':  # a gust: the petals overshoot their place downwind, then bounce back
                gust=max(0.,min(1.,(arrival-.3)/.45))
                dx+=w*.3*math.sin(math.pi*gust)**.6*(1-max(0.,(arrival-.75)/.25))  # overshoot, hang, snap back
        dx+=math.sin(q*5+values[5]*math.tau)*h*.08*q
        tumble=(values[4]-.5)*90+q*(values[5]-.5)*420*effect.spin
        piece=botanical_sprite(particle.kind,particle.size*settle,values,angle=tumble)
        if q<=0:settled.append((piece,px,py));continue
        layer.alpha_composite(piece,(round(x+px+dx-piece.width/2),round(y+py+dy-piece.height/2)))
    if settled:  # pieces at rest sit on top of the ones still flying past, clipped to the letter shapes
        rest=Image.new('RGBA',sprite.size)
        for piece,px,py in settled:
            rest.alpha_composite(piece,(round(px-piece.width/2),round(py-piece.height/2)))
        clip=np.asarray(rest.getchannel('A'),dtype=np.float32)*np.clip(mask/255,0,1)
        rest.putalpha(Image.fromarray(clip.astype('uint8'),'L'))
        layer.alpha_composite(rest,(round(x),round(y)))


def petal_word(sprite,effect,seed,intensity=1.,cache=None):
    key=('botanical-word-v6',sprite_key(sprite),effect,seed,intensity)
    if cache is not None and key in cache:return cache[key]
    result=Image.new('RGBA',sprite.size)  # the outline fits in the sprite's own padding
    paint_petal_formation(result,sprite,0,0,0.,effect,seed,intensity,cache)
    if cache is not None:cache[key]=result
    return result
