"""Organic branching vines grow around words, sprouting photographic foliage."""
from dataclasses import dataclass,replace
import math
import random
from PIL import Image,ImageDraw,ImageChops
from effects.growth.botanical_materials import botanical_sprite, FLOWERS
from effects.particles.cache import sprite_key
from effects.particles.choreography import entrance_opacity


def ease(value):
    value=max(0.,min(1.,value));return value*value*(3-2*value)


def bezier(a,b,c,d,count=55):
    return tuple(((1-t)**3*a[0]+3*(1-t)**2*t*b[0]+3*(1-t)*t*t*c[0]+t**3*d[0],
                  (1-t)**3*a[1]+3*(1-t)**2*t*b[1]+3*(1-t)*t*t*c[1]+t**3*d[1])
                 for t in (i/(count-1) for i in range(count)))

@dataclass(frozen=True)
class Vine:
    points: tuple
    birth: float
    duration: float
    width: float
    depths: tuple = ()

@dataclass(frozen=True)
class Sprout:
    point: tuple
    angle: float
    birth: float
    size: float
    kind: str
    values: tuple
    duration: float
    depth: float = 0.


def vine_geometry(sprite,seed=0,intensity=1.):
    rng=random.Random(seed);w,h=sprite.size
    bounds=sprite.getchannel('A').getbbox() or (0,0,w,h)
    left,top,right,bottom=bounds;span=max(1,right-left);height=max(12,bottom-top)
    jitter=lambda scale:(rng.random()-.5)*scale
    import numpy as np
    yy,xx=np.nonzero(np.asarray(sprite.getchannel('A'))>160)
    def root_at(fraction):
        if not len(xx):return (left+span*fraction,bottom)
        target=left+span*fraction
        chosen=int(np.argmin((xx-target)**2+3*(yy-bottom)**2))
        return float(xx[chosen]),float(yy[chosen])
    root_left,root_right=root_at(.08),root_at(.92)
    paths=[]
    main=bezier(root_left,
                (left+span*.2,bottom+height*(.55+jitter(.25))),
                (left+span*.7,bottom+height*(.03+jitter(.25))),
                (right+height*.1,bottom+height*.28))
    paths.append(Vine(main,0.,.66,max(1.8,height*.035)))
    for fraction,side in ((.28,-1),(.72,1)):
        anchor=main[round(fraction*(len(main)-1))]
        end=(left+span*(.28 if side<0 else .80)+jitter(span*.10),top-height*(.28+rng.random()*.22))
        outside=left-height*(.35+rng.random()*.2) if side<0 else right+height*(.35+rng.random()*.2)
        curve=bezier(anchor,(outside,bottom+height*.12),(outside,top-height*.55),end)
        birth=fraction*.66
        paths.append(Vine(curve,birth,.80-birth,max(1.2,height*.026)))
    paths.append(Vine(bezier(root_right,(right+height*.45,bottom+height*.1),
                             (right+height*.4,top-height*.55),
                             (left+span*.68,top-height*.20)),.04,.73,max(1.4,height*.026)))
    for parent in tuple(paths):
        for fraction in (.34,.67):
            index=round(fraction*(len(parent.points)-1));anchor=parent.points[index]
            before=parent.points[max(0,index-1)];after=parent.points[min(len(parent.points)-1,index+1)]
            angle=math.atan2(after[1]-before[1],after[0]-before[0]);normal=angle+math.pi/2
            direction=(anchor[0]-(left+right)/2,anchor[1]-(top+bottom)/2)
            if math.cos(normal)*direction[0]+math.sin(normal)*direction[1]<0:normal+=math.pi
            length=height*(.42+rng.random()*.43);bend=normal+jitter(.65)
            end=(anchor[0]+math.cos(bend)*length,anchor[1]+math.sin(bend)*length)
            curve=bezier(anchor,(anchor[0]+math.cos(normal)*length*.4,anchor[1]+math.sin(normal)*length*.4),
                         (end[0]+math.cos(angle)*length*.25,end[1]+math.sin(angle)*length*.25),end,35)
            birth=parent.birth+parent.duration*fraction
            paths.append(Vine(curve,birth,max(.16,.88-birth),max(1.,height*.018)))
    from scipy.ndimage import binary_fill_holes,label,find_objects
    mask=np.asarray(sprite.getchannel('A'))>160
    holes=binary_fill_holes(mask)&~mask
    hole_labels,count=label(holes)
    glyph_labels,_=label(mask)
    glyph_boxes=find_objects(glyph_labels)
    weave_start=len(paths)
    for hole_id in range(1,min(count,8)+1):
        hy,hx=np.nonzero(hole_labels==hole_id)
        if len(hx)<4:continue
        cx,cy=float(hx.mean()),float(hy.mean())
        root_index=int(np.argmin((xx-(cx-height*.18))**2+(yy-cy)**2))
        root=(float(xx[root_index]),float(yy[root_index]))
        owner=int(glyph_labels[int(root[1]),int(root[0])])
        box=glyph_boxes[owner-1] if owner else None
        edge=box[1].stop if box else cx+height*.2
        next_pixels=np.nonzero(mask & (np.indices(mask.shape)[1]>edge+1))
        if len(next_pixels[1]):
            chosen=int(np.argmin((next_pixels[1]-(edge+height*.35))**2+(next_pixels[0]-bottom)**2))
            target=(float(next_pixels[1][chosen]),float(next_pixels[0][chosen]))
        else:target=(edge+height*.28,bottom+height*.12)
        first=bezier(root,(cx-height*.22,cy-height*.22),(cx+height*.16,cy-height*.17),(cx,cy),25)
        second=bezier((cx,cy),(cx+height*.12,cy+height*.55),
                      (target[0]+height*.16,target[1]-height*.25),target,40)
        paths.append(Vine(first+second[1:],.03+hole_id*.018,.78,max(1.2,height*.024)))
    depth_paths=[]
    for number,path in enumerate(paths):
        depths=tuple(-math.sin(i/(len(path.points)-1)*math.tau*(2 if number>=weave_start else 1))*height*(.22 if number>=weave_start else .11)
                     for i in range(len(path.points)))
        depth_paths.append(replace(path,depths=depths))
    paths=depth_paths
    sprouts=[]
    for number,path in enumerate(paths):
        for leaf_number,fraction in enumerate((.20,.37,.55,.73,.87)):
            index=round(fraction*(len(path.points)-1));point=path.points[index]
            a=path.points[max(0,index-1)];b=path.points[min(len(path.points)-1,index+1)]
            tangent=math.atan2(b[1]-a[1],b[0]-a[0]);side=-1 if (leaf_number+number)%2 else 1
            angle=tangent+side*(.65+rng.random()*.45)
            values=tuple(rng.random() for _ in range(6));size=height*(.16+values[3]*.28)/3
            sprouts.append(Sprout(point,angle,path.birth+path.duration*fraction-.012,size,'leaf',values,.22,path.depths[index]))
        for fraction in ((.62,.95) if number<3 else (.97,)):
            index=round(fraction*(len(path.points)-1));point=path.points[index]
            values=tuple(rng.random() for _ in range(6));kind=FLOWERS[min(2,int(values[0]*3))]
            size=height*(.24+values[3]*.33)/3
            if number==1 and fraction>.9:size=height*.82/3
            birth=path.birth+path.duration*fraction-.02-(.12 if number==1 and fraction>.9 else 0.)
            sprouts.append(Sprout(point,(values[4]-.5)*.5,birth,size,kind,values,.32,path.depths[index]))
    return tuple(paths),tuple(sprouts)


def _opacity(image,amount):
    if amount>=.999:return image
    result=image.copy();result.putalpha(result.getchannel('A').point(lambda a:round(a*max(0.,amount))));return result


def _centered(image,size):
    result=Image.new('RGBA',(size,size));result.alpha_composite(image,((size-image.width)//2,(size-image.height)//2));return result


def _flower(sprout,age):
    size=max(2,round(sprout.size*(.18+.82*ease(age))))
    full=botanical_sprite(sprout.kind,size,sprout.values)
    bud_kind='poppy' if sprout.kind=='poppy' else 'chrysanthemum'
    closed=botanical_sprite(bud_kind+'-bud',max(2,round(size*.72)),sprout.values)
    opening=botanical_sprite(bud_kind+'-opening',max(2,round(size*.9)),sprout.values)
    span=max(size,full.width,full.height,closed.width,closed.height,opening.width,opening.height)+2
    if age<.46:return Image.blend(_centered(closed,span),_centered(opening,span),ease(age/.46))
    return Image.blend(_centered(opening,span),_centered(full,span),ease((age-.46)/.54))


def paint_growth(layer,sprite,x,y,progress,effect,seed,intensity=1.,cache=None):
    progress=max(0.,min(1.,progress));key=('organic-vines-depth-v1',sprite_key(sprite),seed,intensity)
    if cache is None:geometry=vine_geometry(sprite,seed,intensity)
    else:
        if key not in cache:cache[key]=vine_geometry(sprite,seed,intensity)
        geometry=cache[key]
    if progress<=0:
        layer.alpha_composite(_opacity(sprite,.08),(round(x),round(y)))
        return
    behind=Image.new('RGBA',layer.size);front=Image.new('RGBA',layer.size)
    back_draw,front_draw=ImageDraw.Draw(behind),ImageDraw.Draw(front)
    fade=entrance_opacity(progress)
    camera=max(sprite.width*2,sprite.height*8)
    def project(point,depth):
        factor=camera/(camera-depth)
        return (x+sprite.width/2+(point[0]-sprite.width/2)*factor,
                y+sprite.height/2+(point[1]-sprite.height/2)*factor,factor)
    for path in geometry[0]:
        grown=max(0.,min(1.,(progress-path.birth)/path.duration))
        if grown<=0:continue
        end=grown*(len(path.points)-1)
        for index in range(1,min(len(path.points),math.ceil(end)+1)):
            a,b=path.points[index-1],path.points[index]
            za,zb=path.depths[index-1],path.depths[index]
            if index>end:
                fraction=end-(index-1);b=(a[0]+(b[0]-a[0])*fraction,a[1]+(b[1]-a[1])*fraction)
                zb=za+(zb-za)*fraction
            pa,pb=project(a,za),project(b,zb);depth=(za+zb)/2
            draw=back_draw if depth<0 else front_draw
            width=max(1,round(path.width*(1-.72*index/len(path.points))*pb[2]))
            segment=(round(pa[0]),round(pa[1]),round(pb[0]),round(pb[1]))
            light=.75+.25*(depth/max(1,sprite.height*.22)+1)/2
            draw.line((segment[0]+1,segment[1]+2,segment[2]+1,segment[3]+2),fill=(11,28,16,round(100*fade)),width=width+2)
            draw.line(segment,fill=(29,65,34,round(235*fade)),width=width+1)
            draw.line(segment,fill=(round(73*light),round(132*light),round(65*light),round(240*fade)),width=width)
            if width>1:draw.line((segment[0]-1,segment[1]-1,segment[2]-1,segment[3]-1),fill=(151,182,112,round(150*fade)),width=1)
    for sprout in geometry[1]:
        age=max(0.,min(1.,(progress-sprout.birth)/sprout.duration))
        if age<=0:continue
        amount=ease(age);point=project(sprout.point,sprout.depth);factor=point[2]
        if sprout.kind=='leaf':
            size=sprout.size*(.18+.82*amount)*factor;photo=botanical_sprite('leaf',size,sprout.values)
            photo=photo.resize((max(1,round(photo.width*(.08+.92*amount))),max(1,photo.height)),Image.Resampling.LANCZOS)
            rotation=-math.degrees(sprout.angle)-45+(1-amount)*32
            piece=photo.rotate(rotation,Image.Resampling.BICUBIC,expand=True);offset=size*.35
        else:
            piece=_flower(sprout,age).rotate(-math.degrees(sprout.angle),Image.Resampling.BICUBIC,expand=True)
            if abs(factor-1)>.005:piece=piece.resize((max(1,round(piece.width*factor)),max(1,round(piece.height*factor))),Image.Resampling.LANCZOS)
            offset=sprout.size*.16*amount*factor
        cx=point[0]+math.cos(sprout.angle)*offset;cy=point[1]+math.sin(sprout.angle)*offset
        target=behind if sprout.depth<0 else front;draw=back_draw if sprout.depth<0 else front_draw
        draw.line((round(point[0]),round(point[1]),round(cx),round(cy)),fill=(80,129,65,round(200*fade*amount)),width=1)
        piece=_opacity(piece,fade*ease(min(1.,age/.35)))
        target.alpha_composite(piece,(round(cx-piece.width/2),round(cy-piece.height/2)))
    occlusion=Image.new('L',layer.size,255)
    occlusion.paste(ImageChops.invert(sprite.getchannel('A')),(round(x),round(y)))
    behind.putalpha(ImageChops.multiply(behind.getchannel('A'),occlusion))
    layer.alpha_composite(behind)
    layer.alpha_composite(_opacity(sprite,.08*(1-ease(progress))),(round(x),round(y)))
    from effects.growth.leaf_fill import paint_leaf_fill
    paint_leaf_fill(layer,sprite,x,y,progress,seed,cache)
    from effects.particles.petals import _petals
    glyph_key=('organic-glyph-pieces-v4',sprite_key(sprite),effect,seed,intensity)
    if cache is None:pieces=_petals(sprite,effect,seed,intensity)
    else:
        if glyph_key not in cache:cache[glyph_key]=_petals(sprite,effect,seed,intensity)
        pieces=cache[glyph_key]
    for particle in pieces:
        birth=.025+.23*particle.x/max(1,sprite.width)
        age=max(0.,min(1.,(progress-birth)/.52))
        if age<=0:continue
        growth=ease(age);size=.12+.88*growth
        photo=particle.image.resize((max(1,round(particle.image.width*size)),max(1,round(particle.image.height*size))),Image.Resampling.LANCZOS)
        photo=photo.rotate((particle.random[4]-.5)*90,Image.Resampling.BICUBIC,expand=True)
        photo=_opacity(photo,entrance_opacity(age))
        layer.alpha_composite(photo,(round(x+particle.x-photo.width/2),round(y+particle.y-photo.height/2)))
    layer.alpha_composite(front)


def grown_sprite(sprite,effect,seed,intensity=1.,cache=None):
    key=('organic-grown-leaf-fill-v1',sprite_key(sprite),effect,seed,intensity)
    if cache is not None and key in cache:return cache[key]
    padding=round(sprite.height*1.65)
    image=Image.new('RGBA',(sprite.width+2*padding,sprite.height+2*padding))
    paint_growth(image,sprite,padding,padding,1.,effect,seed,intensity,cache)
    result=image,padding
    if cache is not None:cache[key]=result
    return result
