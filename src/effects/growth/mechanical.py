"""Clockwork, folded paper and dark faceted geometry using ornate growth paths."""
import math,random
import numpy as np
from PIL import Image,ImageDraw
from scipy.spatial import Delaunay

EFFECT_IDS=frozenset(('clockwork-lettering','folded-paper-lettering','obsidian-lattice-lettering'))


def geometry(sprite,effect,seed,intensity=1.):
    from effects.growth.ornate import Strand, Jewel, oval
    rng=random.Random(seed);mask=np.asarray(sprite.getchannel('A'));ink=mask>120;h,w=mask.shape
    yy,xx=np.indices(mask.shape);birth=xx/max(1,w)*.28+yy/max(1,h)*.14
    paths=[];jewels=[];texture=Image.new('RGBA',sprite.size,(24,24,32,255));draw=ImageDraw.Draw(texture)
    if effect.id=='clockwork-lettering':
        sheen=.5+.5*np.cos(xx*.18+yy*.24)
        rgb=np.stack((87+73*sheen,63+54*sheen,36+32*sheen),axis=-1).astype('uint8')
        texture=Image.fromarray(np.dstack((rgb,mask)));draw=ImageDraw.Draw(texture)
        step=max(10,round(h*.15))
        for cy in range(step//2,h,step):
            for cx in range(step//2,w,step):
                if not ink[cy,cx]:continue
                r=step*rng.uniform(.44,.58);born=float(birth[cy,cx]);teeth=rng.choice((10,12,14))
                gear=[]
                for n in range(teeth*4):
                    angle=n/(teeth*4)*math.tau;radius=r*(1 if n%4 in (1,2) else .82)
                    gear.append((cx+math.cos(angle)*radius,cy+math.sin(angle)*radius))
                gear.append(gear[0]);color=(225,181,92) if (cx//step+cy//step)%2 else (184,202,207)
                spin=(-1 if (cx//step+cy//step)%2 else 1)*math.pi*.8
                paths.append(Strand(tuple(gear),born,.36,1.1,color,True,1.,spin,(cx,cy)))
                paths.append(Strand(oval(cx,cy,r*.62,r*.62,0),born+.04,.33,.8,color,True,1.,spin,(cx,cy)))
                for n in range(5):
                    angle=n/5*math.tau
                    paths.append(Strand(((cx,cy),(cx+math.cos(angle)*r*.65,cy+math.sin(angle)*r*.65)),born+.10,.27,.7,color,True,1.,spin,(cx,cy)))
                jewels.append(Jewel((cx,cy),1.5,born+.31,(245,224,160),True))
                for k in range(4):
                    angle=rng.random()*math.tau;distance=r*.42
                    jewels.append(Jewel((cx+math.cos(angle)*distance,cy+math.sin(angle)*distance),.6,born+.37,(38,34,27),True))
        ys,xs=np.nonzero(ink)
        for number in range(min(7,max(1,w//55))):
            target=(number+.5)*w/min(7,max(1,w//55));i=int(np.argmin((xs-target)**2+(ys-h*.2)**2))
            root=(float(xs[i]),float(ys[i]));cx=root[0];cy=root[1]-h*.18;r=max(7,min(17,h*.11));born=.12+number*.045
            paths.append(Strand((root,(cx,cy)),born,.3,1.1,(150,118,67),False,-1))
            gear=[]
            for n in range(48):
                angle=n/48*math.tau;radius=r*(1 if n%4 in (1,2) else .79);gear.append((cx+math.cos(angle)*radius,cy+math.sin(angle)*radius))
            gear.append(gear[0]);spin=(-1 if number%2 else 1)*math.pi
            paths.append(Strand(tuple(gear),born+.05,.5,1.5,(231,189,103),False,1.,spin,(cx,cy)))
            paths.append(Strand(oval(cx,cy,r*.67,r*.67,0),born+.08,.45,.9,(202,216,222),False,1.,spin,(cx,cy)))
            for n in range(5):
                angle=n/5*math.tau;paths.append(Strand(((cx,cy),(cx+math.cos(angle)*r*.64,cy+math.sin(angle)*r*.64)),born+.12,.4,.8,(224,199,140),False,1.,spin,(cx,cy)))
            jewels.append(Jewel((cx,cy),2.,born+.43,(249,219,145),True,False))
    else:
        step=max(12,round(h*.19));points=[]
        for y in range(-step,h+2*step,step):
            for x in range(-step,w+2*step,step):points.append((x+rng.uniform(-step*.3,step*.3),y+rng.uniform(-step*.3,step*.3)))
        points=np.asarray(points);triangles=Delaunay(points).simplices
        dark=effect.id=='obsidian-lattice-lettering'
        palette=((12,15,25),(28,28,48),(48,42,69),(63,57,83),(27,37,50)) if dark else ((240,227,200),(184,205,211),(217,139,118),(237,197,141),(126,158,173))
        for n,indices in enumerate(triangles):
            vertices=tuple(tuple(points[i]) for i in indices);center=np.mean(points[indices],axis=0)
            color=palette[n%len(palette)];draw.polygon(vertices,fill=(*color,255))
            born=max(.02,min(.6,center[0]/max(1,w)*.34+center[1]/max(1,h)*.12))
            wire=(122,116,161) if dark else tuple(min(255,c+30) for c in color)
            paths.append(Strand(vertices+(vertices[0],),born,.34,.65,wire))
            a,b=vertices[0],vertices[1]
            paths.append(Strand(((a[0]+1,a[1]+1),(b[0]+1,b[1]+1)),born+.05,.28,1.4,tuple(round(c*.52) for c in color)))
            if n%4==0:jewels.append(Jewel(vertices[0],.85,born+.32,(181,151,230) if dark else (255,246,222),True))
        ys,xs=np.nonzero(ink)
        for n in range(min(14,len(xs))):
            i=round(n*max(0,len(xs)-1)/max(1,min(14,len(xs))-1));root=(float(xs[i]),float(ys[i]))
            angle=math.atan2(root[1]-h/2,root[0]-w/2);length=min(35,h*.28)
            end=(root[0]+math.cos(angle)*length,root[1]+math.sin(angle)*length)
            side=(end[0]+math.cos(angle+1.3)*length*.55,end[1]+math.sin(angle+1.3)*length*.55)
            color=(107,99,151) if dark else (240,218,179)
            paths.append(Strand((root,end,side,root),.17+n*.025,.5,.9,color,False,-1))
            if dark:
                tip=(side[0]+length*.22,side[1]-length*.18)
                paths.append(Strand((end,tip,side),.25+n*.025,.45,.65,(63,82,107),False,-1))
    texture.putalpha(sprite.getchannel('A'))
    return texture,birth,tuple(paths),tuple(jewels)
