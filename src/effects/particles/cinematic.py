"""Depth-sorted glyph particles with analytic trails and independent exit paths."""
from dataclasses import replace
import math
from PIL import Image, ImageDraw, ImageFilter
from effects.particles.cache import sprite_key
from effects.particles.choreography import entrance_opacity

STYLES = {
    'prismatic-helix': 'prism', 'prismatic-singularity': 'prism',
    'liquid-chrome-assembly': 'chrome', 'liquid-chrome-collapse': 'chrome',
    'ember-forge': 'ember', 'ember-ash-drift': 'ember',
}
PALETTES = {
    'prism': ((102,229,255),(178,142,255),(255,170,219)),
    'chrome': ((205,235,248),(100,155,185),(246,251,255)),
    'ember': ((255,204,93),(255,113,40),(224,65,24)),
}


def smooth(q):
    q=max(0.,min(1.,q))
    return q*q*(3-2*q)


def pose(style,phase,q,fragment,size,spread):
    """Shared exact rest position, distinct arrival and departure paths."""
    width,height=size;cx,cy=fragment.center;r=fragment.random
    u,v=cx-width/2,cy-height/2;h=height*spread;a=r[1]*math.tau;q=smooth(q)
    if style=='prism':
        if phase=='entrance':
            angle=cx/max(1,width)*math.tau*1.5+q*math.tau*1.2+(r[0]>.5)*math.pi
            dx=math.cos(angle)*h*q*.8;dy=math.sin(angle)*h*q*.9;z=math.cos(angle)*q*.45
        else:
            collapse=smooth(q/.8);angle=a+q*math.tau*1.4
            dx=-u*collapse+math.cos(angle)*h*q*(1-q)*1.1
            dy=-v*collapse+math.sin(angle)*h*q*(1-q)*.7;z=-q*.7
        return dx,dy,z,q*(r[4]-.5)*5,q*(r[5]-.5)*8,q*(r[6]-.5)*4
    if style=='chrome':
        if phase=='entrance':
            dx=math.sin(a+q*math.tau)*h*q;dy=math.cos(a*2+q*math.tau*1.4)*h*q*.7
            z=math.sin(a+q*5)*q*.4
        else:
            pull=smooth(q/.65);dx=-u*pull*.8+math.sin(a+q*5)*h*q*.18
            dy=-v*pull*.6+h*q*q*1.3;z=-q*.25
        return dx,dy,z,q*(r[4]-.5)*4,q*(r[5]-.5)*5,q*(r[6]-.5)*3
    if phase=='entrance':
        dx=math.sin(a+q*5)*h*q*.5;dy=h*q*(.5+r[2])
    else:
        dx=h*q*(.35+math.sin(a+q*6)*.4)
        dy=-h*(q*.45+q*q*.8)+math.sin(a+q*4)*h*q*.14
    return dx,dy,math.sin(a+q*3)*q*.2,q*(r[4]-.5)*3,q*(r[5]-.5)*4,q*(r[6]-.5)*5


def colored(image,color,opacity):
    result=Image.new('RGBA',image.size,(*color,0))
    result.putalpha(image.getchannel('A').point(lambda a:round(a*max(0.,min(1.,opacity)))))
    return result


def paint_cinematic(layer,sprite,x,y,phase,amount,effect,seed,intensity,cache):
    from effects.particles.motion import build_fragments, tumble, _alpha
    style=STYLES[effect.id]
    recipe=replace(effect,family='cinematic')
    key=('cinematic-v1',sprite_key(sprite),recipe,seed,intensity)
    if cache is None:fragments=build_fragments(sprite,recipe,seed,intensity)
    else:
        if key not in cache:cache[key]=build_fragments(sprite,recipe,seed,intensity)
        fragments=cache[key]
    padding=math.ceil(sprite.height*effect.spread*2.5+20)
    origin_x=max(0,round(x)-padding);origin_y=max(0,round(y)-padding)
    right=min(layer.width,round(x)+sprite.width+padding);bottom=min(layer.height,round(y)+sprite.height+padding)
    if right<=origin_x or bottom<=origin_y:return
    offset_x=x-origin_x;offset_y=y-origin_y
    surface=Image.new('RGBA',(right-origin_x,bottom-origin_y))
    glow=Image.new('RGBA',surface.size);gd=ImageDraw.Draw(glow);items=[]
    palette=PALETTES[style]
    fade_in=entrance_opacity(1-amount) if phase=='entrance' else 1.
    fade_out=1-smooth((amount-.75)/.25) if phase=='exit' else 1.
    for fragment in fragments:
        r=fragment.random;horizontal=fragment.center[0]/max(1,sprite.width)
        delay=effect.stagger*(horizontal if style=='ember' else r[0])
        q=max(0.,min(1.,(amount-delay)/(1-delay)))
        dx,dy,z,ax,ay,az=pose(style,phase,q,fragment,sprite.size,effect.spread)
        depth=1/(1-z)
        center=(offset_x+sprite.width/2+(fragment.center[0]-sprite.width/2+dx)*depth,
                offset_y+sprite.height/2+(fragment.center[1]-sprite.height/2+dy)*depth)
        tint=palette[min(2,int(r[3]*3))];alpha=fade_in*fade_out;piece=fragment.image
        if style in ('chrome','ember'):
            blend=smooth(q/.45);piece=_alpha(piece,1-blend)
            radius=max(1.,min(6.,math.sqrt(fragment.image.width*fragment.image.height)*.21))
            drop=Image.new('RGBA',(max(5,round(radius*3)),max(5,round(radius*3))))
            dd=ImageDraw.Draw(drop);c=drop.width/2
            if style=='chrome':
                dd.ellipse((c-radius,c-radius,c+radius,c+radius),fill=(*tint,round(255*blend)))
                dd.arc((c-radius,c-radius,c+radius,c+radius),190,295,fill=(255,255,255,round(255*blend)),width=2)
                dd.ellipse((c-radius*.45,c-radius*.55,c,c-radius*.1),fill=(255,255,255,round(255*blend)))
            else:
                hot=1-smooth((q-.45)/.55) if phase=='exit' else 1.
                tint=tuple(round(c*hot+55*(1-hot)) for c in tint)
                dd.ellipse((c-radius*.6,c-radius*.3,c+radius*.6,c+radius*.3),fill=(*tint,round(255*blend)))
            pw=max(piece.width,drop.width);ph=max(piece.height,drop.height)
            merged=Image.new('RGBA',(pw,ph))
            merged.alpha_composite(piece,((pw-piece.width)//2,(ph-piece.height)//2))
            merged.alpha_composite(drop,((pw-drop.width)//2,(ph-drop.height)//2));piece=merged
        else:
            piece=Image.alpha_composite(piece,colored(piece,tint,smooth(q)*.6))
            if style=='prism':piece.alpha_composite(colored(fragment.edge,tint,smooth(q)))
        piece=tumble(piece,ax,ay,az,depth)
        if piece is None:continue
        piece=_alpha(piece,alpha);items.append((z,piece,center))
        strength=math.sin(math.pi*amount)*alpha
        if strength>.005:
            points=[]
            for step in range(6):
                previous=max(0.,q-step*.018) if phase=='exit' else min(1.,q+step*.018)
                tx,ty,tz,*_=pose(style,phase,previous,fragment,sprite.size,effect.spread);td=1/(1-tz)
                points.append((offset_x+sprite.width/2+(fragment.center[0]-sprite.width/2+tx)*td,
                               offset_y+sprite.height/2+(fragment.center[1]-sprite.height/2+ty)*td))
            gd.line(points,fill=(*tint,round(125*strength)),width=1)
            if style in ('prism','ember'):
                cx,cy=center;radius=1.5 if style=='prism' else 2.
                gd.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill=(*tint,round(180*strength)))
    surface.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3)));surface.alpha_composite(glow)
    for _,piece,center in sorted(items,key=lambda item:item[0]):
        surface.alpha_composite(piece,(round(center[0]-piece.width/2),round(center[1]-piece.height/2)))
    layer.alpha_composite(surface,(origin_x,origin_y))
