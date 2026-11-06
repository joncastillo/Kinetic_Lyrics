"""Weathered oak and autumn maple trunks with shaded branching depth."""
from dataclasses import dataclass,replace
import math,random
import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageFilter
from effects.growth.assets import asset, glyph_ranges, turned_asset
from core.imaging import Strokes
from effects.particles.cache import sprite_key
from core.easing import smoothstep as ease  # shared curves, under this module's own names

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


OAK_TONE,MAPLE_TONE=(200,152,96,255),(248,234,208,255)  # warm tan oak; maple letters are cream
WOOD_RIM,WOOD_LIGHT=(28,20,14,255),(236,214,170,255)
RIM_SIZE=7


def geometry(sprite,effect,seed,glyph_spans=None):
    rng=random.Random(seed);w,h=sprite.size;mask=np.asarray(sprite.getchannel('A'))>120
    oak=effect.id=='old-oak-lettering';boughs=[];foliage=[]
    def branch(start,angle,length,birth,level):
        points=[]
        for t in np.linspace(0,1,26):
            bend=angle+math.sin(t*4+level)*(.32 if oak else .16)  # oak limbs twist and knot
            points.append((start[0]+math.cos(bend)*length*t,start[1]+math.sin(bend)*length*t,start[2]+math.sin(t*math.pi*1.5)*h*.12))
        span=max(.14,.40-level*.065);boughs.append(Bough(tuple(points),birth,span,max(1.,h*((.11-.025*level) if oak else (.06-.014*level)))))  # stout limbs that scale with the word
        if level<3:
            for fraction,side in ((.56,-1),(.86,1)):
                branch(points[round(fraction*25)],angle+side*(.52+rng.random()*.25),length*(.58+rng.random()*.10),birth+span*fraction,level+1)
        for fraction in (.65,.94):
            point=points[round(fraction*25)]
            if level>0:
                size=round(h*rng.uniform(.2,.32)*min(1.,.6+.1*w/h) if oak else h*rng.uniform(.18,.3));index=(0 if rng.random()<.6 else 1) if oak else rng.choice((2,3,4,5))  # short words get a smaller crown; more autumn clusters
                if oak and point[1]>-size*.35:continue  # the oak's leaves stay above the word, never over the letters
                foliage.append(Foliage(point,birth+span*fraction,size,rng.uniform(-150,150),index))
                if oak and rng.random()<.15:foliage.append(Foliage(point,birth+span*fraction+.04,10,rng.uniform(-30,30),10))
    ranges=glyph_ranges(sprite,glyph_spans)
    if oak:  # one broad, gnarled oak grows out of the middle letter and spreads its limbs over the whole word
        middle=ranges[len(ranges)//2] if ranges else (0,w)
        left,right=middle
        yy,xx=np.nonzero(mask[:,left:right])
        if len(xx):
            xx=xx+left;chosen=int(np.argmin((xx-(left+right)/2)**2+(yy-h*.2)**2))
            root=(float(xx[chosen]),float(yy[chosen]),0.)
            foliage.append(Foliage(root,.12,round(min(58,h*.2)),0.,8))
            for side,outer in ((-1,1),(1,1),(-1,0),(1,0)):  # four limbs aimed at the word's ends and above its middle, so the crown spans the word but stays low
                end=(left+right)/2+side*w*(.36 if outer else .14);dx=end-root[0];dy=-h*(.55 if outer else .75)
                branch(root,math.atan2(dy,dx)+rng.uniform(-.06,.06),math.hypot(dx,dy)*.8,.03+(.04 if outer else 0),0)
    else:
        for number,(left,right) in enumerate(ranges):
            yy,xx=np.nonzero(mask[:,left:right])
            if not len(xx):continue
            xx=xx+left;chosen=int(np.argmin((xx-(left+right)/2)**2+(yy-h*.2)**2))
            root=(float(xx[chosen]),float(yy[chosen]),0.)
            foliage.append(Foliage(root,.12,round(min(58,h*.32)),0.,9))
            branch(root,-math.pi/2+rng.uniform(-.30,.30),h*(.3+.12*((number*2)%3)),.03+(number%3)*.035,0)  # heights alternate, so each letter's tree reads
    final=max([b.birth+b.duration for b in boughs]+[leaf.birth+.2 for leaf in foliage]+[1.])
    scale=.95/final
    boughs=[replace(b,birth=b.birth*scale,duration=b.duration*scale) for b in boughs]
    foliage=[replace(leaf,birth=leaf.birth*scale) for leaf in foliage]
    bark=asset(6 if oak else 7);tile=bark.resize((max(20,round(h*.85)),h),Image.Resampling.LANCZOS)
    texture=Image.new('RGBA',sprite.size)
    for x in range(0,w,tile.width):texture.alpha_composite(tile,(x,0))
    texture=ImageEnhance.Contrast(texture).enhance(.55 if oak else .65)
    texture=Image.blend(texture,Image.new('RGBA',texture.size,OAK_TONE if oak else MAPLE_TONE),.4 if oak else .85)
    texture=ImageEnhance.Brightness(texture).enhance(1.35 if oak else 1.1);texture.putalpha(sprite.getchannel('A'))
    return texture,tuple(boughs),tuple(foliage)


def paint_growth(layer,sprite,x,y,progress,effect,seed,intensity=1.,cache=None,glyph_spans=None):
    if progress<=0:return
    key=('tree-growth-v16',sprite_key(sprite),effect,seed,tuple(glyph_spans or ()))
    if cache is None:parts=geometry(sprite,effect,seed,glyph_spans)
    else:
        if key not in cache:cache[key]=geometry(sprite,effect,seed,glyph_spans)
        parts=cache[key]
    texture,boughs,foliage=parts;fade=ease(progress/.1)  # opaque from the first frames, never a long fade
    rear=Image.new('RGBA',layer.size);front=rear.copy();draws=[Strokes(),Strokes()]
    camera=max(sprite.width*2,sprite.height*8)
    def project(point):
        f=camera/(camera-point[2]);return (x+sprite.width/2+(point[0]-sprite.width/2)*f,y+sprite.height/2+(point[1]-sprite.height/2)*f)
    oak=effect.id=='old-oak-lettering'
    for branch in boughs:
        age=max(0.,min(1.,(progress-branch.birth)/max(.01,min(branch.duration,1-branch.birth))))
        end=age*(len(branch.points)-1)
        for n in range(1,min(len(branch.points),math.ceil(end)+1)):
            a,b=branch.points[n-1],branch.points[n]
            if n>end:
                t=end-n+1;b=tuple(a[j]+(b[j]-a[j])*t for j in range(3))
            pa,pb=project(a),project(b);draw=draws[1 if a[2]+b[2]>=0 and oak else 0]  # maple's stems grow from behind the letters, so the word stays clean
            width=max(1,round(branch.width*(1-.63*n/len(branch.points))))
            draw.line((*pa,*pb),fill=(35,27,21,round(250*fade)),width=width+(2 if oak else 3),order=0)  # maple: a heavier dark edge, so the stems read on paper
            draw.line((*pa,*pb),fill=(116,90,60,round(255*fade)),width=width,order=1)
            draw.line((pa[0]-1,pa[1]-1,pb[0]-1,pb[1]-1),fill=(178,154,108,round(180*fade)),width=1,order=2)
    draws[0].paint(rear);draws[1].paint(front)
    q=(progress-.84)/.16;sway=sprite.height*.06*math.sin(math.tau*q)*(1-q) if 0<q<1 else 0.
    for leaf in foliage:
        age=ease((progress-leaf.birth)/max(.01,min(.2,1-leaf.birth)))
        if age<=0:continue
        pop=1+.42*math.sin(math.pi*min(1.,age*1.15))*(age<1)  # each clump pops past its size and settles
        photo=turned_asset(leaf.index,max(2,round(leaf.size*(.15+.85*age)*pop)),round(leaf.angle+(1-age)*35)%360).copy()
        photo.putalpha(photo.getchannel('A').point(lambda a:round(a*fade*age)))
        px,py=project(leaf.point);target=front if leaf.point[2]>=0 else rear
        px+=sway*min(1.,max(0.,-leaf.point[1])/sprite.height)  # the crown rustles once as it locks
        target.alpha_composite(photo,(round(px-photo.width/2),round(py-photo.height/2)))
    occlusion=Image.new('L',layer.size,255);occlusion.paste(ImageChops.invert(sprite.getchannel('A')),(round(x),round(y)))
    rear.putalpha(ImageChops.multiply(rear.getchannel('A'),occlusion));layer.alpha_composite(rear)
    yy,xx=np.indices((sprite.height,sprite.width));across=xx/max(1,sprite.width)
    if effect.id=='old-oak-lettering':  # the word grows up and out from the oak's trunk in the middle
        born=(1-yy/max(1,sprite.height))*.08+np.abs(across-.5)*.3  # finished by about .25
    else:  # maple's letters colour in from the top down like turning leaves, left to right
        born=yy/max(1,sprite.height)*.14+across*.24
    grown=progress-born
    reveal=np.clip(grown/.025,0,1)*fade  # a hard growth front, never a soft wipe
    body=texture.copy();body.putalpha(Image.fromarray((np.asarray(body.getchannel('A'))*reveal).astype('uint8')))
    rim_color=(168,36,20,255) if effect.id=='autumn-maple-lettering' else WOOD_RIM  # maple: a red outline
    alpha=body.getchannel('A');rim=Image.new('RGBA',body.size,rim_color)
    hard=alpha.point(lambda v:255 if v>110 else 0)  # a hard outline, never a soft halo
    rim.putalpha(hard.filter(ImageFilter.MaxFilter(RIM_SIZE)))
    drop=Image.new('RGBA',body.size,(30,16,10,150));drop.putalpha(ImageChops.offset(hard.filter(ImageFilter.MaxFilter(RIM_SIZE)),2,3).point(lambda v:v*150//255))
    word=Image.new('RGBA',body.size);word.alpha_composite(drop)
    light=Image.new('RGBA',body.size,WOOD_LIGHT);light.putalpha(ImageChops.subtract(alpha,ImageChops.offset(alpha,2,2)).point(lambda a:a*.7))
    word.alpha_composite(rim);word.alpha_composite(body);word.alpha_composite(light)
    sap=Image.new('RGBA',body.size,(255,236,170,255))  # a bright sapwood line rides the growth front
    sap.putalpha(Image.fromarray((np.asarray(sprite.getchannel('A'))*np.clip(1-np.abs(grown-.03)/.03,0,1)*(progress<1)).astype('uint8')))
    word.alpha_composite(sap)
    # each letter lifts as the growth front reaches it and settles back, so the letters move as well as the tree
    for left,right in glyph_ranges(sprite,glyph_spans):
        c=(left+right)/2/max(1,sprite.width)
        reach=(abs(c-.5)*.3 if effect.id=='old-oak-lettering' else c*.24)+.06
        q=(progress-reach)/.2
        lift=-sprite.height*.15*math.sin(math.pi*min(1.,q))*(1-.4*min(1.,q)) if 0<q<1 else 0
        layer.alpha_composite(word.crop((left,0,right,sprite.height)),(round(x)+left,round(y+lift)))
    layer.alpha_composite(front)
