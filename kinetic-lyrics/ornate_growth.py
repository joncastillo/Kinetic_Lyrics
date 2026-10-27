"""Intricate, shaded filigree, lace, brocade and coral built from glyph pixels."""
from dataclasses import dataclass
import math
import random
import numpy as np
from PIL import Image,ImageDraw,ImageChops
from scipy.ndimage import distance_transform_edt,gaussian_filter
from particle_cache import sprite_key
from particle_choreography import entrance_opacity

EFFECT_IDS=frozenset(('gold-filigree-lettering','pearl-lace-lettering',
                     'jeweled-brocade-lettering','luminous-coral-lettering','clockwork-lettering','folded-paper-lettering','obsidian-lattice-lettering'))
SCALE=2


@dataclass(frozen=True)
class Strand:
    points: tuple
    birth: float
    duration: float
    width: float
    color: tuple
    clipped: bool=True
    depth: float=1.
    spin: float=0.
    center: tuple=(0.,0.)


@dataclass(frozen=True)
class Jewel:
    point: tuple
    radius: float
    birth: float
    color: tuple
    pearl: bool=False
    clipped: bool=True


def ease(value):
    value=np.clip(value,0,1)
    return value*value*(3-2*value)


def spiral(cx,cy,radius,angle,turns=1.55,count=45):
    return tuple((cx+math.cos(angle+t*math.tau*turns)*radius*(1-.91*t),
                  cy+math.sin(angle+t*math.tau*turns)*radius*(1-.91*t))
                 for t in np.linspace(0,1,count))


def oval(cx,cy,rx,ry,angle,count=35):
    ca,sa=math.cos(angle),math.sin(angle)
    return tuple((cx+math.cos(t)*rx*ca-math.sin(t)*ry*sa,
                  cy+math.cos(t)*rx*sa+math.sin(t)*ry*ca) for t in np.linspace(0,math.tau,count))


def geometry(sprite,effect,seed,intensity=1.):
    from mechanical_growth import EFFECT_IDS as mechanical_ids
    if effect.id in mechanical_ids:
        from mechanical_growth import geometry as mechanical_geometry
        return mechanical_geometry(sprite,effect,seed,intensity)
    mask=np.asarray(sprite.getchannel('A'));ink=mask>120;h,w=mask.shape
    yy,xx=np.indices(mask.shape);ys,xs=np.nonzero(ink)
    if not len(xs):return None
    rng=random.Random(seed);noise_rng=np.random.default_rng(seed)
    depth=distance_transform_edt(ink)
    noise=gaussian_filter(noise_rng.random(mask.shape),max(1,h*.025))
    noise=(noise-noise.min())/max(.001,np.ptp(noise))
    phase=xx*.43+yy*.67
    if effect.id=='gold-filigree-lettering':
        sheen=.5+.5*np.sin(phase*.24+noise*2)
        rgb=np.stack((98+109*sheen,61+89*sheen,25+40*sheen),axis=-1)
        edge=depth<1.7;rgb[edge]=(251,218,137)
        colors=((218,166,67),(246,207,119),(190,127,44))
    elif effect.id=='pearl-lace-lettering':
        fabric=.5+.5*np.cos(xx*1.7)*np.cos(yy*1.9)
        rgb=np.stack((135+70*fabric,132+66*fabric,127+65*fabric),axis=-1)
        rgb[depth<1.5]=(247,237,212)
        colors=((240,230,205),(215,214,207),(255,247,226))
    elif effect.id=='jeweled-brocade-lettering':
        rib=.5+.5*np.sin(xx*1.5+yy*.75)
        rgb=np.stack((62+46*rib,23+20*rib,49+44*rib),axis=-1)
        rgb[depth<1.4]=(237,184,84)
        colors=((234,179,73),(251,218,139),(167,117,48))
    else:
        light=.5+.5*np.sin(yy*.16+noise*4)
        rgb=np.stack((37+30*light,87+79*light,101+77*light),axis=-1)
        rgb[depth<1.5]=(126,236,213)
        colors=((69,192,177),(242,157,151),(116,217,228))
    texture=Image.fromarray(np.dstack((np.clip(rgb,0,255).astype('uint8'),mask)))
    birth=(xx/max(1,w))*.32+(yy/max(1,h))*.10+noise*.08
    strands=[];jewels=[]
    spacing=max(5.,min(13.,h*.073))/math.sqrt(max(.3,intensity))
    occupied=set()
    for raw in rng.sample(range(len(xs)),len(xs)):
        px,py=float(xs[raw]),float(ys[raw]);cell=(round(px/spacing),round(py/spacing))
        if cell in occupied or depth[int(py),int(px)]<2:continue
        occupied.add(cell)
        angle=rng.uniform(-math.pi,math.pi);born=float(birth[int(py),int(px)])
        radius=max(4,min(16,h*.10))*(.7+rng.random()*.6)
        color=colors[len(occupied)%len(colors)]
        if effect.id=='gold-filigree-lettering':
            points=spiral(px,py,radius,angle,1.35+rng.random()*.4)
            strands.append(Strand(points,born,.32,1.25,color))
            mirror=tuple((2*px-x,y) for x,y in points)
            strands.append(Strand(mirror,min(.65,born+.07),.30,.85,colors[1]))
            jewels.append(Jewel(points[-1],1.35,min(.82,born+.30),(255,227,161),True))
        elif effect.id=='pearl-lace-lettering':
            for turn in range(3):
                theta=angle+turn*math.tau/3
                strands.append(Strand(oval(px,py,radius,radius*.29,theta),born+turn*.035,.32,.85,color,True,(-1 if turn%2 else 1)))
            points=oval(px,py,radius*.34,radius*.34,0,23)
            strands.append(Strand(points,born+.12,.24,.7,colors[2]))
            jewels.append(Jewel((px,py),1.5,born+.34,(255,244,224),True))
        elif effect.id=='jeweled-brocade-lettering':
            petals=tuple((px+math.cos(t)*radius*(.63+.22*math.cos(t*4)),
                          py+math.sin(t)*radius*(.63+.22*math.cos(t*4))) for t in np.linspace(0,math.tau,45))
            strands.append(Strand(petals,born,.35,1.1,color))
            strands.append(Strand(oval(px,py,radius*.36,radius*.65,angle),born+.05,.30,.75,colors[1]))
            if len(occupied)%2==0:
                gem_colors=((167,32,67),(24,165,112),(62,114,217),(156,87,199))
                jewels.append(Jewel((px,py),min(5.4,max(2.4,depth[int(py),int(px)]*.6)),born+.36,gem_colors[len(occupied)%4]))
        else:
            for branch in range(3):
                direction=angle+(branch-1)*.54
                length=radius*(1.1+branch*.2)
                points=tuple((px+math.cos(direction+t*.3)*length*t,
                              py+math.sin(direction+t*.3)*length*t) for t in np.linspace(0,1,22))
                strands.append(Strand(points,born+branch*.035,.38,1.4,color))
                for node in (.45,.72,.94):
                    at=points[round(node*(len(points)-1))]
                    for side in (-1,1):
                        tip=(at[0]+math.cos(direction+side*.9)*length*.28,
                             at[1]+math.sin(direction+side*.9)*length*.28)
                        strands.append(Strand((at,tip),born+node*.31,.23,.65,colors[2]))
                        jewels.append(Jewel(tip,.9,born+node*.31+.17,(198,255,217),True))
        if len(occupied)>=max(90,min(260,round(w*h/110*max(.3,intensity)))):break
    edge_y,edge_x=np.nonzero((depth>0)&(depth<1.7))
    edge_cells=set()
    for ex,ey in zip(edge_x,edge_y):
        cell=(int(ex//5),int(ey//5))
        if cell in edge_cells:continue
        edge_cells.add(cell)
        if effect.id!='luminous-coral-lettering':
            jewels.append(Jewel((float(ex),float(ey)),.7 if effect.id!='pearl-lace-lettering' else 1.,
                                .22+float(ex)/max(1,w)*.42,colors[1],True))
    flourishes=max(4,min(12,w//40))
    for n in range(flourishes):
        i=round(n*max(0,len(xs)-1)/max(1,flourishes-1))
        root=(float(xs[i]),float(ys[i]));angle=math.atan2(root[1]-h/2,root[0]-w/2)
        radius=min(h*.34,40)*(.7+rng.random()*.4)
        if effect.id in ('gold-filigree-lettering','jeweled-brocade-lettering'):
            center=(root[0]+math.cos(angle)*radius,root[1]+math.sin(angle)*radius)
            points=(root,)+spiral(*center,radius,angle+math.pi,1.3,55)
            strands.append(Strand(points,.13+n*.025,.62,1.3,colors[1],False,-1))
            jewels.append(Jewel(points[-1],2.1,.80,colors[0],True,False))
        elif effect.id=='pearl-lace-lettering':
            center=(root[0]+math.cos(angle)*radius*.5,root[1]+math.sin(angle)*radius*.5)
            points=(root,)+oval(*center,radius*.8,radius*.27,angle,45)
            strands.append(Strand(points,.12+n*.03,.56,.8,colors[0],False,-1))
            for index in (12,25,37):jewels.append(Jewel(points[index],1.5,.63+index*.004,colors[2],True,False))
        else:
            def branch(start,direction,length,born,generation):
                points=tuple((start[0]+math.cos(direction+.18*t)*length*t,start[1]+math.sin(direction+.18*t)*length*t) for t in np.linspace(0,1,18))
                strands.append(Strand(points,born,.25,max(.6,2.-generation*.45),colors[generation%3],False,-1))
                if generation<3:
                    for fraction,side in ((.55,-1),(.83,1)):
                        branch(points[round(fraction*17)],direction+side*.63,length*.52,born+fraction*.22,generation+1)
                else:jewels.append(Jewel(points[-1],1.6,min(.95,born+.23),(217,255,210),True,False))
            branch(root,angle,radius,.08+n*.018,0)
    return texture,birth,tuple(strands),tuple(jewels)


def _partial(points,amount):
    end=max(0,min(len(points)-1,amount*(len(points)-1)))
    whole=int(end);chosen=list(points[:whole+1])
    if whole<len(points)-1:
        a,b=points[whole],points[whole+1];fraction=end-whole
        chosen.append((a[0]+(b[0]-a[0])*fraction,a[1]+(b[1]-a[1])*fraction))
    return chosen


def _strand(draw,strand,age,fade,offset):
    points=_partial(strand.points,age)
    if strand.spin:
        angle=strand.spin*(1-age);ca,sa=math.cos(angle),math.sin(angle);cx,cy=strand.center
        points=[(cx+(px-cx)*ca-(py-cy)*sa,cy+(px-cx)*sa+(py-cy)*ca) for px,py in points]
    if len(points)<2:return
    points=[(round((x+offset[0])*SCALE),round((y+offset[1])*SCALE)) for x,y in points]
    width=max(1,round(strand.width*SCALE))
    alpha=round(255*fade);c=strand.color
    shadow=[(x+SCALE,y+SCALE) for x,y in points]
    draw.line(shadow,fill=(18,17,22,round(alpha*.70)),width=width+SCALE,joint='curve')
    draw.line(points,fill=(*tuple(round(v*.56) for v in c),alpha),width=width+1,joint='curve')
    draw.line(points,fill=(*c,alpha),width=width,joint='curve')
    highlight=[(x,y-1) for x,y in points]
    draw.line(highlight,fill=(*tuple(min(255,round(v*.48+137)) for v in c),round(alpha*.9)),width=1,joint='curve')
    if age<.98:
        cx,cy=points[-1];r=1.5*SCALE
        draw.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(255,244,203,round(alpha*.55)))


def _jewel(draw,jewel,age,fade,offset):
    if age<=0:return
    x=(jewel.point[0]+offset[0])*SCALE;y=(jewel.point[1]+offset[1])*SCALE
    radius=jewel.radius*SCALE*(.2+.8*float(ease(age)));alpha=round(255*fade*float(ease(min(1,age*3))))
    if radius<.5:return
    draw.ellipse((x-radius-1,y-radius-1,x+radius+1,y+radius+1),fill=(64,44,30,alpha))
    c=jewel.color
    if jewel.pearl:
        draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=(*tuple(round(v*.55) for v in c),alpha))
        draw.ellipse((x-radius,y-radius,x+radius*.65,y+radius*.65),fill=(*c,alpha))
    else:
        vertices=[(x+math.cos(t)*radius,y+math.sin(t)*radius) for t in np.linspace(-math.pi/2,math.tau-math.pi/2,7)[:-1]]
        draw.polygon(vertices,fill=(*tuple(round(v*.42) for v in c),alpha))
        for n in range(6):
            ca=tuple(min(255,round(v*(.65 if n>2 else 1.15)+(22 if n<3 else 0))) for v in c)
            draw.polygon(((x,y),vertices[n],vertices[(n+1)%6]),fill=(*ca,alpha))
        inset=[(x+(vx-x)*.48,y+(vy-y)*.48) for vx,vy in vertices]
        draw.polygon(inset,fill=(*c,alpha))
    glint=max(1,radius*.25)
    draw.ellipse((x-radius*.45-glint,y-radius*.45-glint,x-radius*.45+glint,y-radius*.45+glint),fill=(255,255,235,alpha))


def paint_growth(layer,sprite,x,y,progress,effect,seed,intensity=1.,cache=None):
    progress=max(0.,min(1.,progress))
    if progress<=0:return
    key=('ornate-geometry-v1',sprite_key(sprite),effect,seed,intensity)
    if cache is None:parts=geometry(sprite,effect,seed,intensity)
    else:
        if key not in cache:cache[key]=geometry(sprite,effect,seed,intensity)
        parts=cache[key]
    if parts is None:return
    texture,birth,strands,jewels=parts
    fade=entrance_opacity(progress)
    padding=round(sprite.height*.6);size=(sprite.width+2*padding,sprite.height+2*padding)
    internal=Image.new('RGBA',(size[0]*SCALE,size[1]*SCALE));rear=internal.copy();front=internal.copy()
    draws={True:ImageDraw.Draw(internal),'rear':ImageDraw.Draw(rear),'front':ImageDraw.Draw(front)}
    for strand in strands:
        age=max(0.,min(1.,(progress-strand.birth)/max(.01,min(strand.duration,1-strand.birth))))
        if age>0:_strand(draws[True if strand.clipped else 'rear' if strand.depth<0 else 'front'],strand,age,fade,(padding,padding))
    for jewel in jewels:
        age=max(0.,min(1.,(progress-jewel.birth)/max(.01,min(.16,1-jewel.birth))))
        _jewel(draws[True if jewel.clipped else 'front'],jewel,age,fade,(padding,padding))
    internal=internal.resize(size,Image.Resampling.LANCZOS)
    rear=rear.resize(size,Image.Resampling.LANCZOS);front=front.resize(size,Image.Resampling.LANCZOS)
    mask=Image.new('L',size);mask.paste(sprite.getchannel('A'),(padding,padding))
    internal.putalpha(ImageChops.multiply(internal.getchannel('A'),mask))
    rear.putalpha(ImageChops.multiply(rear.getchannel('A'),ImageChops.invert(mask)))
    body=texture.copy();reveal=ease((progress-birth)/.46)*fade
    body.putalpha(Image.fromarray((np.asarray(texture.getchannel('A'))*reveal*(.38 if effect.id=='pearl-lace-lettering' else 1.)).astype('uint8')))
    held=Image.new('RGBA',size);held.alpha_composite(rear);held.alpha_composite(body,(padding,padding));held.alpha_composite(internal);held.alpha_composite(front)
    layer.alpha_composite(held,(round(x)-padding,round(y)-padding))
