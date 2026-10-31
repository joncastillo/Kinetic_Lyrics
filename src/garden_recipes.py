"""Low, lush growth sitting on top of a word: succulents and cacti, and a tuft of meadow grass.

Both keep the letters in their own colours and plant along the word's top edge, so the garden follows the
lettering's real contour and bridges the gaps between letters. They stay low over the word rather than towering
like the trees, and pop up from left to right as the word forms.
"""
import math

import numpy as np

from material_fx import coverage, mix, rgb, shadow, sm
from material_recipes import recipe, supersampled

# Mostly fresh light greens, then sage and blue-green, with pink- and red-blushed rosettes and ruby sedum among them.
ROSETTE_BODIES = [(rgb(176, 218, 146), .28), (rgb(156, 206, 128), .22), (rgb(198, 228, 168), .18), (rgb(140, 190, 152), .1),
                  (rgb(168, 204, 182), .08), (rgb(238, 182, 192), .08), (rgb(214, 104, 118), .03), (rgb(180, 62, 78), .03)]
BLUSH = (rgb(242, 128, 150), rgb(214, 66, 86))
GRASS = (rgb(58, 128, 44), rgb(96, 168, 58), rgb(150, 198, 84), rgb(188, 214, 112))


def top_edge(F, xs):
    """The height of the lettering's top at each x, bridging the gaps between letters with the word's top line."""
    def build():
        inside = F.ink > .5
        top = np.where(inside.any(axis=0), inside.argmax(axis=0), F.box[1]).astype(float)
        top = np.minimum(top, F.box[1]+F.u*.18)  # dips such as an L's foot are bridged, keeping one band on top
        kernel = np.ones(max(1, round(F.u*.12)))/max(1, round(F.u*.12))
        return np.convolve(np.pad(top, len(kernel), mode='edge'), kernel, mode='same')[len(kernel):-len(kernel)]
    edge = F.memo('garden-top-edge', build)
    return edge[np.clip(np.round(xs).astype(int), 0, len(edge)-1)]


def letters(F, canvas, t):
    """The word in its own colours, firming up as the garden starts to grow."""
    cov = coverage(F.sdf)*sm(t, 0., .3)
    canvas.over(np.zeros(3), shadow(cov, F, .03, .05, .03, .35))
    canvas.over(F.source, cov)


def plants(F, kind, build):
    return F.memo(('garden', kind), build)


def rosettes(F):
    def build():
        rng = np.random.default_rng(F.seed+900)
        x0, _, x1, _ = F.box
        cactus_count = int(np.clip(round((x1-x0)/F.u*.65), 1, 5))
        cactus_xs = np.linspace(x0+F.u*.35, x1-F.u*.35, cactus_count)
        cactus_xs += rng.uniform(-.12, .12, cactus_count)*F.u
        cactus_tops = top_edge(F, cactus_xs)
        cacti = [dict(kind='cactus', shape=('column','barrel','paddle')[k%3], x=x, y=top-F.u*1.1,
                      base=top+F.u*.04, height=F.u*rng.uniform(*((.72,1.) if k%3==0 else (.4,.58) if k%3==1 else (.55,.78))), width=F.u*rng.uniform(.14,.21),
                      body=rgb(70,145,105) if k%3==0 else rgb(95,158,112) if k%3==1 else rgb(91,156,125),
                      start=.13+.53*(x-x0)/max(1,x1-x0)+rng.uniform(0,.06), r=F.u*.2)
                 for k,(x,top) in enumerate(zip(cactus_xs,cactus_tops))]
        count = int(np.clip(round((x1-x0)/F.u*4.8), 7, 48))
        xs = np.sort(rng.uniform(x0-F.u*.1, x1+F.u*.1, count))
        xs = [x for x in xs if all(abs(x-c['x'])>c['width']+F.u*.1 for c in cacti)]
        tops = top_edge(F, xs)
        weights = np.array([w for _, w in ROSETTE_BODIES])
        bodies = rng.choice(len(ROSETTE_BODIES), len(xs), p=weights/weights.sum())
        result = []
        for k, (x, top) in enumerate(zip(xs, tops)):
            radius = F.u*rng.uniform(.22, .38)*(1.2 if rng.random() < .18 else 1)
            kind = 'sedum' if rng.random() < .1 else 'rosette'
            # Plants sit on the letters' top edge, mostly above it, so the lettering stays readable.
            result.append(dict(x=x+rng.uniform(-.04, .04)*F.u, y=top-radius*rng.uniform(.35, .7), r=radius, kind=kind,
                               body=ROSETTE_BODIES[bodies[k]][0], blush=BLUSH[int(rng.integers(0, 2))],
                               blushed=rng.random() < .3, spin=rng.uniform(0, math.tau), depth=rng.uniform(0, 1),
                               start=.12+.55*(x-x0)/max(1, x1-x0)+rng.uniform(0, .08), leaves=int(rng.integers(8, 11))))
        # A few tiny blooms on fine stems, for cuteness.
        for _ in range(max(2, count//8)):
            x = rng.uniform(x0, x1)
            result.append(dict(x=x, y=top_edge(F, np.array([x]))[0]-F.u*rng.uniform(.12, .2), r=F.u*.05, kind='bloom',
                               body=rgb(250, 190, 204) if rng.random() < .6 else rgb(255, 236, 160), depth=.0,
                               start=.55+rng.uniform(0, .3), stem=F.u*rng.uniform(.1, .2)))
        return cacti+sorted(result, key=lambda p: (p['y']+p['r']*.3, -p['depth']))
    return plants(F, 'rosettes', build)


def as_fill(colour, shade=1., alpha=255):
    return tuple(int(np.clip(v*shade, 0, 1)*255) for v in colour)+(alpha,)


def draw_cactus(d, f, p, grown):
    """Three readable cactus silhouettes with soft ribs and fine sunlit spines."""
    cx, base = p['x'], p['base']
    h, w = p['height']*grown, p['width']*grown
    if h <= 0 or w <= 0:return
    dark, light = mix(p['body'], rgb(36, 91, 72), .35), mix(p['body'], rgb(194, 218, 150), .42)
    if p['shape']=='column':
        stem=w*.68
        for side, rise in ((-1,.36),(1,.52)):
            elbow=(cx+side*w*.95, base-h*rise)
            tip=(elbow[0], base-h*(rise+.25))
            d.line([(cx*f,(base-h*rise*.7)*f),(elbow[0]*f,elbow[1]*f),(tip[0]*f,tip[1]*f)],
                   fill=as_fill(dark),width=max(2,round(stem*f*.58)),joint='curve')
            d.ellipse(((tip[0]-stem*.29)*f,(tip[1]-stem*.29)*f,(tip[0]+stem*.29)*f,(tip[1]+stem*.29)*f),fill=as_fill(dark))
        d.rounded_rectangle(((cx-stem*.5)*f,(base-h)*f,(cx+stem*.5)*f,base*f),radius=stem*f*.5,fill=as_fill(p['body']))
        d.line([(cx-stem*.18)*f,(base-h*.91)*f,(cx-stem*.18)*f,(base-h*.08)*f],fill=as_fill(light,.95,190),width=max(1,round(stem*f*.14)))
        d.line([(cx+stem*.24)*f,(base-h*.88)*f,(cx+stem*.24)*f,(base-h*.1)*f],fill=as_fill(dark,.85,185),width=max(1,round(stem*f*.1)))
        edge=stem*.5
    elif p['shape']=='barrel':
        d.ellipse(((cx-w)*f,(base-h)*f,(cx+w)*f,base*f),fill=as_fill(dark))
        d.ellipse(((cx-w*.89)*f,(base-h*.98)*f,(cx+w*.7)*f,(base-h*.04)*f),fill=as_fill(p['body']))
        for offset in (-.58,-.18,.25,.6):
            x=cx+w*offset
            d.line([(x*f,(base-h*.94)*f),(x*f,(base-h*.07)*f)],fill=as_fill(light if offset<0 else dark,.95,170),width=max(1,round(f*w*.1)))
        edge=w*.78
    else:
        d.line([(cx*f,base*f),(cx*f,(base-h*.55)*f)],fill=as_fill(dark),width=max(2,round(w*f*.55)))
        for ox,oy,s in ((-.65,.58,.7),(.55,.68,.65),(0,.23,1.)):
            x,y=cx+w*ox,base-h*oy
            d.ellipse(((x-w*s*.65)*f,(y-h*s*.32)*f,(x+w*s*.65)*f,(y+h*s*.32)*f),fill=as_fill(dark))
            d.ellipse(((x-w*s*.58)*f,(y-h*s*.29)*f,(x+w*s*.43)*f,(y+h*s*.28)*f),fill=as_fill(p['body']))
            d.ellipse(((x-w*s*.35)*f,(y-h*s*.2)*f,(x-w*s*.2)*f,(y-h*s*.1)*f),fill=as_fill(light,1.,190))
        edge=w*.65
    if grown>.65:
        spine=as_fill(rgb(235,225,169),1.,220)
        for k in range(4):
            y=base-h*(.18+.2*k)
            for side in (-1,1):
                x=cx+side*edge
                d.line([(x*f,y*f),((x+side*w*.28)*f,(y-h*.035)*f)],fill=spine,width=max(1,round(f*.7)))


@recipe('succulent-garden-lettering', 'entrance', pad=1.2, work_height=210)
def succulent_garden(F, canvas, t, intensity):
    letters(F, canvas, t)
    garden = rosettes(F)

    def draw(d, f):
        for p in garden:
            grown = sm(t, p['start'], p['start']+.3)
            if grown <= 0:
                continue
            bounce = 1+.12*math.sin(min(1., grown)*math.pi)*(1-grown)  # a little springy pop as it appears
            r = p['r']*grown*bounce
            cx, cy = p['x'], p['y']
            if p['kind']=='cactus':
                draw_cactus(d,f,p,grown)
                continue
            if p['kind'] == 'bloom':
                d.line([(cx*f, (cy+p['stem'])*f), (cx*f, cy*f)], fill=(110, 150, 80, 255), width=max(1, round(f*F.u*.012)))
                for k in range(5):
                    a = k*math.tau/5
                    px, py = cx+math.cos(a)*r*.7, cy+math.sin(a)*r*.6
                    d.ellipse(((px-r*.5)*f, (py-r*.5)*f, (px+r*.5)*f, (py+r*.5)*f), fill=as_fill(p['body']))
                d.ellipse(((cx-r*.3)*f, (cy-r*.3)*f, (cx+r*.3)*f, (cy+r*.3)*f), fill=(255, 214, 90, 255))
                continue
            if p['kind'] == 'sedum':  # a cluster of plump jelly-bean leaves, green blushing to ruby
                rng = np.random.default_rng(int(p['x']*31+p['y']*7))
                for k in range(9):
                    a = rng.uniform(0, math.tau)
                    dist = r*rng.uniform(.1, .75)
                    bx, by = cx+math.cos(a)*dist, cy+math.sin(a)*dist*.55
                    br = r*rng.uniform(.22, .32)
                    tone = rgb(204, 52, 70) if rng.random() < .3 else mix(rgb(150, 206, 108), rgb(196, 230, 150), rng.uniform(0, 1))  # fresh green beans, some ruby
                    d.ellipse(((bx-br)*f, (by-br*1.25)*f, (bx+br)*f, (by+br*1.25)*f), fill=as_fill(tone, .85))
                    d.ellipse(((bx-br*.45)*f, (by-br*1.)*f, (bx+br*.25)*f, (by-br*.2)*f), fill=as_fill(tone, 1.25, 200))
                continue
            # An echeveria seen a little from above: rings of pointed leaves, outer ones longer and darker.
            for ring, (scale, count, shade) in enumerate(((1., p['leaves'], .8), (.72, p['leaves']-2, .95), (.46, 6, 1.08))):
                leaves = []
                for k in range(count):
                    a = p['spin']+ring*.4+k*math.tau/count
                    leaves.append((math.sin(a), a))
                for depth, a in sorted(leaves):  # back leaves first, front leaves over them
                    length = r*scale
                    ca, sa = math.cos(a), math.sin(a)*.62
                    nx, ny = -math.sin(a), math.cos(a)*.62  # across the leaf, flattened by the viewing angle
                    near = .82+.22*(depth+1)/2
                    # A plump spoon-shaped leaf: narrow at the base, wide and rounded, ending in a soft point.
                    outline = []
                    for along, half in ((.08, .1), (.3, .32), (.55, .42), (.75, .38), (.9, .22)):
                        outline.append((cx+ca*length*along+nx*length*half*.55, cy+sa*length*along+ny*length*half*.55))
                    tip = (cx+ca*length, cy+sa*length-r*.06*scale)
                    other = [(cx+ca*length*along-nx*length*half*.55, cy+sa*length*along-ny*length*half*.55)
                             for along, half in ((.9, .22), (.75, .38), (.55, .42), (.3, .32), (.08, .1))]
                    shape = outline+[tip]+other
                    d.polygon([(x*f, y*f) for x, y in shape], fill=as_fill(p['body'], shade*near))
                    # A paler, waxy highlight down the middle of the leaf.
                    d.polygon([(x*f, y*f) for x, y in (outline[1], outline[3], tip, other[1])][:3]+[((cx+ca*length*.3)*f, (cy+sa*length*.3)*f)],
                              fill=as_fill(mix(p['body'], rgb(236, 246, 226), .35), shade*near, 110))
                    if p['blushed']:  # pink or red tips
                        d.polygon([(x*f, y*f) for x, y in (outline[4], tip, other[0])], fill=as_fill(p['blush'], near))
            core = r*.14
            d.ellipse(((cx-core)*f, (cy-core*.8)*f, (cx+core)*f, (cy+core*.8)*f), fill=as_fill(mix(p['body'], rgb(240, 250, 220), .5)))

    leaf_rgb, leaf_a = supersampled(F, draw, factor=3)
    canvas.darken(shadow(leaf_a, F, .02, .05, .03, .4))
    canvas.over(np.clip(leaf_rgb, 0, 1), leaf_a)


def blades(F):
    def build():
        rng = np.random.default_rng(F.seed+950)
        x0, _, x1, _ = F.box
        count = int(np.clip(round((x1-x0)/F.u*34), 20, 260))
        xs = rng.uniform(x0-F.u*.08, x1+F.u*.08, count)
        tops = top_edge(F, xs)
        result = []
        for x, top in zip(xs, tops):
            depth = rng.uniform(0, 1)
            result.append(dict(x=x, base=top+F.u*rng.uniform(.02, .08), height=F.u*rng.uniform(.18, .48)*(1.3 if rng.random() < .12 else 1),
                               lean=rng.uniform(-.35, .35), width=F.u*rng.uniform(.018, .034), depth=depth,
                               tone=GRASS[int(rng.integers(0, len(GRASS)))], phase=rng.uniform(0, math.tau),
                               start=.1+.55*(x-x0)/max(1, x1-x0)+rng.uniform(0, .12), seed=rng.random() < .07))
        return sorted(result, key=lambda b: -b['depth'])
    return plants(F, 'blades', build)


@recipe('meadow-grass-lettering', 'entrance', pad=.9)
def meadow_grass(F, canvas, t, intensity):
    letters(F, canvas, t)
    meadow = blades(F)
    settle = 1-sm(t, .7, 1.)

    def draw(d, f):
        for b in meadow:
            grown = sm(t, b['start'], b['start']+.35)
            if grown <= 0:
                continue
            height = b['height']*grown
            sway = (b['lean']+.12*math.sin(t*9+b['phase'])*settle)*height
            points_l, points_r = [], []
            for k in range(7):
                s = k/6
                x = b['x']+sway*s*s
                y = b['base']-height*s
                w = b['width']*(1-s)**.8
                points_l.append(((x-w)*f, y*f))
                points_r.append(((x+w)*f, y*f))
            shade = 1-.35*b['depth']
            d.polygon(points_l+points_r[::-1], fill=as_fill(b['tone'], shade))
            d.line([((b['x']+sway*.25)*f, (b['base']-height*.5)*f), ((b['x']+sway)*f, (b['base']-height)*f)],
                   fill=as_fill(b['tone'], shade*1.25, 120), width=max(1, f//2))
            if b['seed'] and grown > .8:  # an occasional seed head
                x, y = b['x']+sway, b['base']-height
                d.ellipse(((x-b['width']*1.4)*f, (y-b['width']*3)*f, (x+b['width']*1.4)*f, (y+b['width'])*f),
                          fill=as_fill(rgb(214, 200, 120), shade))

    grass_rgb, grass_a = supersampled(F, draw)
    canvas.darken(shadow(grass_a, F, .02, .04, .03, .3))
    canvas.over(np.clip(grass_rgb, 0, 1), grass_a)
