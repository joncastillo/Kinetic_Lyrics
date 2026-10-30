"""Weathered oak and autumn maple trunks with shaded branching depth."""
from dataclasses import dataclass,replace
import math,random
import numpy as np
from PIL import Image,ImageDraw,ImageChops,ImageEnhance,ImageFilter
from effects.growth.assets import asset, sized_asset, glyph_ranges
from effects.particles.cache import sprite_key
from effects.particles.choreography import entrance_opacity

@dataclass(frozen=True)
class Bough:
    points:tuple
    birth:float
    duration:float
    width:float

@dataclass(frozen=True)
class Foliage:
    point:tuple
    birth:float
    size:int
    angle:float
    index:int


OAK_TONE,MAPLE_TONE=(150,112,70,255),(170,104,58,255)
WOOD_RIM,WOOD_LIGHT=(28,20,14,255),(236,214,170,255)
RIM_SIZE=7


def ease(v):v=max(0.,min(1.,v));return v*v*(3-2*v)

def geometry(sprite,effect,seed,glyph_spans=None):
    rng=random.Random(seed);w,h=sprite.size;mask=np.asarray(sprite.getchannel('A'))>120
    oak=effect.id=='old-oak-lettering';boughs=[];foliage=[]
    def branch(start,angle,length,birth,level):
        points=[]
        for t in np.linspace(0,1,26):
            bend=angle+math.sin(t*4+level)*.16
            points.append((start[0]+math.cos(bend)*length*t,start[1]+math.sin(bend)*length*t,start[2]+math.sin(t*math.pi*1.5)*h*.12))
        span=max(.14,.40-level*.065);boughs.append(Bough(tuple(points),birth,span,max(.8,(5 if oak else 3.7)-level*.85)))
        if level<3:
            for fraction,side in ((.56,-1),(.86,1)):
                branch(points[round(fraction*25)],angle+side*(.52+rng.random()*.25),length*(.58+rng.random()*.10),birth+span*fraction,level+1)
        for fraction in (.65,.94):
            point=points[round(fraction*25)]
            if level>0:
                size=rng.randint(10,25);index=(0 if rng.random()<.8 else 1) if oak else rng.choice((2,3,4,5))
                foliage.append(Foliage(point,birth+span*fraction,size,rng.uniform(-150,150),index))
                if oak and rng.random()<.15:foliage.append(Foliage(point,birth+span*fraction+.04,10,rng.uniform(-30,30),10))
    for number,(left,right) in enumerate(glyph_ranges(sprite,glyph_spans)):
        yy,xx=np.nonzero(mask[:,left:right])
        if not len(xx):continue
        xx=xx+left;chosen=int(np.argmin((xx-(left+right)/2)**2+(yy-h*.2)**2))
        root=(float(xx[chosen]),float(yy[chosen]),0.)
        foliage.append(Foliage(root,.12,round(min(58,h*(.18 if oak else .32))),0.,8 if oak else 9))
        branch(root,-math.pi/2+rng.uniform(-.30,.30),h*(.5 if oak else .55),.03+(number%3)*.035,0)
    final=max([b.birth+b.duration for b in boughs]+[leaf.birth+.2 for leaf in foliage]+[1.])
    scale=.95/final
    boughs=[replace(b,birth=b.birth*scale,duration=b.duration*scale) for b in boughs]
    foliage=[replace(leaf,birth=leaf.birth*scale) for leaf in foliage]
    bark=asset(6 if oak else 7);tile=bark.resize((max(20,round(h*.85)),h),Image.Resampling.LANCZOS)
    texture=Image.new('RGBA',sprite.size)
    for x in range(0,w,tile.width):texture.alpha_composite(tile,(x,0))
    texture=ImageEnhance.Contrast(texture).enhance(.55 if oak else .65)
    texture=Image.blend(texture,Image.new('RGBA',texture.size,OAK_TONE if oak else MAPLE_TONE),.35 if oak else .25)
    texture=ImageEnhance.Brightness(texture).enhance(1.2 if oak else 1.25);texture.putalpha(sprite.getchannel('A'))
    return texture,tuple(boughs),tuple(foliage)


def paint_growth(layer,sprite,x,y,progress,effect,seed,intensity=1.,cache=None,glyph_spans=None):
    if progress<=0:return
    key=('tree-growth-v4',sprite_key(sprite),effect,seed,tuple(glyph_spans or ()))
    if cache is None:parts=geometry(sprite,effect,seed,glyph_spans)
    else:
        if key not in cache:cache[key]=geometry(sprite,effect,seed,glyph_spans)
        parts=cache[key]
    texture,boughs,foliage=parts;fade=entrance_opacity(progress)
    rear=Image.new('RGBA',layer.size);front=rear.copy();draws=[ImageDraw.Draw(rear),ImageDraw.Draw(front)]
    camera=max(sprite.width*2,sprite.height*8)
    def project(point):
        f=camera/(camera-point[2]);return (x+sprite.width/2+(point[0]-sprite.width/2)*f,y+sprite.height/2+(point[1]-sprite.height/2)*f)
    for branch in boughs:
        age=max(0.,min(1.,(progress-branch.birth)/max(.01,min(branch.duration,1-branch.birth))))
        end=age*(len(branch.points)-1)
        for n in range(1,min(len(branch.points),math.ceil(end)+1)):
            a,b=branch.points[n-1],branch.points[n]
            if n>end:
                t=end-n+1;b=tuple(a[j]+(b[j]-a[j])*t for j in range(3))
            pa,pb=project(a),project(b);draw=draws[1 if a[2]+b[2]>=0 else 0]
            width=max(1,round(branch.width*(1-.63*n/len(branch.points))))
            draw.line((*pa,*pb),fill=(35,27,21,round(250*fade)),width=width+2)
            draw.line((*pa,*pb),fill=(116,90,60,round(255*fade)),width=width)
            draw.line((pa[0]-1,pa[1]-1,pb[0]-1,pb[1]-1),fill=(178,154,108,round(180*fade)),width=1)
    for leaf in foliage:
        age=ease((progress-leaf.birth)/max(.01,min(.2,1-leaf.birth)))
        if age<=0:continue
        photo=sized_asset(leaf.index,max(2,round(leaf.size*(.15+.85*age)))).rotate(leaf.angle+(1-age)*35,Image.Resampling.BICUBIC,expand=True)
        photo.putalpha(photo.getchannel('A').point(lambda a:round(a*fade*age)))
        px,py=project(leaf.point);target=front if leaf.point[2]>=0 else rear
        target.alpha_composite(photo,(round(px-photo.width/2),round(py-photo.height/2)))
    occlusion=Image.new('L',layer.size,255);occlusion.paste(ImageChops.invert(sprite.getchannel('A')),(round(x),round(y)))
    rear.putalpha(ImageChops.multiply(rear.getchannel('A'),occlusion));layer.alpha_composite(rear)
    yy,xx=np.indices((sprite.height,sprite.width));born=.04+(1-yy/max(1,sprite.height))*.31+xx/max(1,sprite.width)*.12
    reveal=np.clip((progress-born)/.52,0,1);reveal=reveal*reveal*(3-2*reveal)*fade
    body=texture.copy();body.putalpha(Image.fromarray((np.asarray(body.getchannel('A'))*reveal).astype('uint8')))
    rim_color=(0,0,0,255) if effect.id=='autumn-maple-lettering' else WOOD_RIM
    alpha=body.getchannel('A');rim=Image.new('RGBA',body.size,rim_color)
    rim.putalpha(alpha.filter(ImageFilter.MaxFilter(RIM_SIZE)))
    light=Image.new('RGBA',body.size,WOOD_LIGHT);light.putalpha(ImageChops.subtract(alpha,ImageChops.offset(alpha,2,2)).point(lambda a:a*.7))
    layer.alpha_composite(rim,(round(x),round(y)));layer.alpha_composite(body,(round(x),round(y)))
    layer.alpha_composite(light,(round(x),round(y)))
    layer.alpha_composite(front)
