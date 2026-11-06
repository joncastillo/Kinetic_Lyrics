"""Low, lush growth sitting on top of a word: succulents and cacti, and a tuft of meadow grass.

Both keep the letters in their own colours and plant along the word's top edge, so the garden follows the
lettering's real contour and bridges the gaps between letters. They stay low over the word rather than towering
like the trees, and pop up from left to right as the word forms.
"""
import math

import numpy as np

from effects.materials.fx import coverage, mix, rgb, shadow, sm, smooth, warp
from effects.materials.recipes import recipe, supersampled
from effects.materials.recipes.common import letters as letter_index

# Mostly fresh light greens, then sage and blue-green, with pink- and red-blushed rosettes and ruby sedum among them.
# Saturated jade and sea-green rosettes, every one tipped in blush pink or red.
ROSETTE_BODIES = [(rgb(64, 178, 132), .35), (rgb(96, 196, 150), .3), (rgb(44, 150, 120), .2), (rgb(132, 204, 168), .15)]
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


def landing(k, count):
    """When letter k starts to fall, and when it lands in the soil."""
    begin = .02+.3*k/max(1, count)
    return begin, begin+.15


def dropped_letters(F, canvas, t):
    """Each letter drops from above into the soil bed in a relay, squashes on landing and springs back."""
    index, count = letter_index(F)
    base = float(F.box[3])
    offset, squash, shown = np.zeros(count), np.ones(count), np.zeros(count)
    keys = ((0, 1.), (.18, .66), (.34, .68), (.6, 1.1), (.82, .97), (1, 1.))  # a deep squash held two frames
    for k in range(count):
        begin, land = landing(k, count)
        if t <= begin:
            continue
        shown[k] = 1
        e = min(1., (t-begin)/(land-begin))
        offset[k] = -F.u*1.05*(1-e*e)  # falls, accelerating
        q = (t-land)/.2
        for (q0, v0), (q1, v1) in zip(keys, keys[1:]):
            if 0 < q <= q1:
                squash[k] = v0+(v1-v0)*sm(q, q0, q1)
                break
    idx = np.clip(index.astype(int), 0, count-1)
    dy = (F.py-base)*(1-1/squash[idx])+offset[idx]
    zero = np.zeros_like(dy)
    cov = warp(F, coverage(F.sdf), zero, dy)*shown[idx]
    colour = warp(F, F.source, zero, dy)
    canvas.over(np.zeros(3), shadow(cov, F, .03, .05, .03, .35))
    canvas.over(colour, cov)
    return count


def soil(F, d, f, t, count):
    """A terracotta window-box planter under the word that spreads out from the middle, its soil, and crumbs
    thrown up where each letter lands. The front of the box is drawn by planter_front, over the letters' feet."""
    u = F.u
    x0, _, x1, base = F.box
    cx = (x0+x1)/2
    half = ((x1-x0)/2+u*.3)*sm(t, 0, .16)
    if half <= 1:
        return
    top = base-u*.02
    d.rectangle(((cx-half)*f, (top-u*.05)*f, (cx+half)*f, (top+u*.1)*f), fill=(70, 46, 30, 255))  # the soil inside
    index, _ = letter_index(F)
    for k in range(count):
        a = (t-landing(k, count)[1])/.2
        if not 0 < a < 1:
            continue
        cols = np.nonzero(index[0] == k)[0]
        mid = cols.mean() if len(cols) else cx
        for j, (vx, vy) in enumerate(()):  # (no loose crumbs: they read as debris)
            x = mid+vx*u*.5*a
            y = base-u*.04-u*.6*vy*a+u*.9*a*a
            r = u*(.1 if j % 2 else .08)
            shape = [((x+r*math.cos(n*1.6+j))*f, (y+r*.8*math.sin(n*1.6+j))*f) for n in range(4)]
            d.polygon(shape, fill=(92, 62, 40, 255), outline=(170, 126, 84, 255), width=max(1, f))


# (body, shadow, rim, rim light) per word: terracotta, glazed teal, cream, slate
PLANTERS = (((176, 84, 52, 255), (132, 58, 36, 255), (214, 116, 74, 255), (244, 170, 120, 255)),
            ((38, 128, 132, 255), (20, 84, 90, 255), (60, 166, 168, 255), (150, 222, 218, 255)),
            ((226, 210, 184, 255), (168, 148, 120, 255), (240, 228, 206, 255), (255, 250, 238, 255)),
            ((84, 96, 112, 255), (52, 60, 72, 255), (112, 126, 144, 255), (176, 190, 206, 255)))


def planter_front(F, d, f, t):
    """The front of the terracotta box: a lit rim band over the letters' feet, a tapering body, and a shadow line."""
    u = F.u
    x0, _, x1, base = F.box
    cx = (x0+x1)/2
    half = ((x1-x0)/2+u*.3)*sm(t, 0, .16)
    if half <= 1:
        return
    top = base-u*.03
    rim_h, depth = u*.16, u*.62
    body, shade, rim, light = PLANTERS[F.seed % len(PLANTERS)]
    d.polygon([((cx-half*.86+u*.05)*f, (top+depth)*f), ((cx+half*.86+u*.05)*f, (top+depth)*f),
               ((cx+half*.84+u*.08)*f, (top+depth+u*.06)*f), ((cx-half*.84+u*.08)*f, (top+depth+u*.06)*f)], fill=(20, 14, 12, 120))
    d.polygon([((cx-half*.94)*f, (top+rim_h)*f), ((cx+half*.94)*f, (top+rim_h)*f),
               ((cx+half*.86)*f, (top+depth)*f), ((cx-half*.86)*f, (top+depth)*f)], fill=body)
    d.polygon([((cx-half*.86)*f, (top+depth*.82)*f), ((cx+half*.86)*f, (top+depth*.82)*f),
               ((cx+half*.86)*f, (top+depth)*f), ((cx-half*.86)*f, (top+depth)*f)], fill=shade)
    d.rectangle(((cx-half)*f, top*f, (cx+half)*f, (top+rim_h)*f), fill=rim)
    d.line([((cx-half)*f, (top+u*.012)*f), ((cx+half)*f, (top+u*.012)*f)], fill=light, width=max(1, round(u*.02*f)))
    d.line([((cx-half)*f, (top+rim_h)*f), ((cx+half)*f, (top+rim_h)*f)], fill=shade, width=max(1, round(u*.012*f)))
    # strings of bead-leaved succulent spill over the rim and trail down the front
    rng = np.random.default_rng(F.seed+78)
    for j in range(max(2, int((x1-x0)/u*1.2))):
        sx = cx-half*.85+half*1.7*rng.uniform(0, 1)
        grow = sm(t, .6+.04*j, .85+.03*j)
        if grow <= 0:
            continue
        full = u*rng.uniform(.5, .75)
        drop = (1+.18*math.sin(math.pi*min(1., grow/.7))*(grow > .3)) if grow < 1 else 1.  # falls past, springs back
        length = full*min(1., grow*1.4)*drop
        sway = math.sin(t*8+j)*u*.03*(1-sm(t, .9, 1.))
        d.line([(sx*f, top*f), ((sx+sway)*f, (top+length)*f)], fill=(52, 104, 56, 255), width=max(1, round(u*.035*f)))
        n = max(2, int(length/(u*.1)))
        for m in range(n):
            s_ = (m+.5)/n
            bx = sx+sway*s_
            by = top+u*.04+length*s_
            r = u*.08*(1-.25*s_)  # plump pearl beads
            d.ellipse(((bx-r)*f, (by-r)*f, (bx+r)*f, (by+r)*f), fill=(110, 182, 112, 255), outline=(40, 92, 52, 255))
            d.ellipse(((bx-r*.5)*f, (by-r*.6)*f, (bx-r*.05)*f, (by-r*.15)*f), fill=(200, 240, 196, 255))


def plants(F, kind, build):
    return F.memo(('garden', kind), build)


def rosettes(F):
    def build():
        rng = np.random.default_rng(F.seed+900)
        x0, _, x1, _ = F.box
        index, letter_count = letter_index(F)

        def after_landing(x):  # a plant comes up once the letter under it has landed
            k = int(index[0, int(np.clip(round(x), 0, F.W-1))])
            return landing(k, letter_count)[1]+.02

        cactus_count = 0  # rosettes only: the cacti read as clip-art
        cactus_xs = np.linspace(x0+F.u*.35, x1-F.u*.35, cactus_count)
        cactus_xs += rng.uniform(-.12, .12, cactus_count)*F.u
        cactus_tops = top_edge(F, cactus_xs)
        cacti = [dict(kind='cactus', shape=('column','barrel','paddle')[k%3], x=x, y=top-F.u*1.1,
                      base=top+F.u*.04, height=F.u*rng.uniform(*((.72,1.) if k%3==0 else (.4,.58) if k%3==1 else (.55,.78))), width=F.u*rng.uniform(.14,.21),
                      body=rgb(70,145,105) if k%3==0 else rgb(95,158,112) if k%3==1 else rgb(91,156,125),
                      start=after_landing(x)+rng.uniform(0,.06), r=F.u*.2)
                 for k,(x,top) in enumerate(zip(cactus_xs,cactus_tops))]
        # rosettes sit along the planter's rim in the gaps between letters and at the ends, never on the letter tops
        columns = F.ink.max(axis=0) > .3
        edges = np.flatnonzero(np.diff(columns.astype(int)))
        gaps = [(edges[i]+edges[i+1])/2 for i in range(1, len(edges)-1, 2)]
        xs = [x0-F.u*.15]+gaps[::max(1, len(gaps)//6)]+[x1+F.u*.15]
        xs = [x for x in xs if all(abs(x-c['x'])>c['width']+F.u*.1 for c in cacti)]
        tops = top_edge(F, xs)
        weights = np.array([w for _, w in ROSETTE_BODIES])
        bodies = rng.choice(len(ROSETTE_BODIES), len(xs), p=weights/weights.sum())
        result = []
        for k, (x, top) in enumerate(zip(xs, tops)):
            radius = F.u*.5*rng.uniform(.75, 1.15)  # sizes vary, so the row never looks stamped
            kind = 'rosette'
            # Plants sit on the letters' top edge, mostly above it, so the lettering stays readable.
            low = True  # on the rim
            end = k in (0, len(xs)-1)  # the ends of the box get the biggest rosettes, in full view
            radius *= 1.35 if end else 1.
            result.append(dict(x=x+rng.uniform(-.03, .03)*F.u, y=(F.box[3]-radius*(.55 if end else .75)) if low else top-radius*rng.uniform(.35, .7), r=radius, kind=kind,
                               body=ROSETTE_BODIES[bodies[k]][0], blush=BLUSH[int(rng.integers(0, 2))],
                               blushed=True, spin=rng.uniform(0, math.tau), depth=rng.uniform(0, 1),
                               start=after_landing(x)+rng.uniform(0, .06), leaves=int(rng.integers(9, 12))))
        # A few tiny blooms on fine stems, for cuteness.
        for _ in range(0):
            x = rng.uniform(x0, x1)
            result.append(dict(x=x, y=top_edge(F, np.array([x]))[0]-F.u*rng.uniform(.12, .2), r=F.u*.05, kind='bloom',
                               body=rgb(250, 190, 204) if rng.random() < .6 else rgb(255, 236, 160), depth=.0,
                               start=.7+rng.uniform(0, .12), stem=F.u*rng.uniform(.1, .2)))
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
    from effects.materials.fx import Canvas
    word = Canvas(F)
    letter_count = dropped_letters(F, word, t)
    garden = rosettes(F)

    def draw(d, f):  # behind the letters: the soil and the rosettes, which peek out between and beside them
        soil(F, d, f, t, letter_count)
        for p in garden:
            grown = sm(t, p['start'], p['start']+.24)
            if grown <= 0:
                continue
            bounce = 1+.15*math.sin(math.pi*min(1., grown/.85))*(grown > .4)  # overshoots by about 15 per cent, then settles
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
                    a = p['spin']+ring*.4+k*math.tau/count+(1-grown)*1.6  # the rosette twists open
                    leaves.append((math.sin(a), a))
                for depth, a in sorted(leaves):  # back leaves first, front leaves over them
                    length = r*scale*sm(grown, (2-ring)*.18, (2-ring)*.18+.6)  # the heart opens first, then the outer leaves
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
    canvas.over(np.zeros(3), shadow(leaf_a, F, .02, .05, .03, .4))
    canvas.over(np.clip(leaf_rgb, 0, 1), leaf_a)
    a = np.clip(word.c[..., 3:4], 0, 1)
    canvas.c = word.c+canvas.c*(1-a)  # the letters over the garden
    front_rgb, front_a = supersampled(F, lambda d, f: planter_front(F, d, f, t), factor=2)  # the box's front over their feet
    canvas.over(np.zeros(3), shadow(front_a, F, .02, .04, .03, .35))
    canvas.over(np.clip(front_rgb, 0, 1), front_a)


def blades(F):
    """Blades along the letters' top edges, each with its column's height jitter."""
    def build():
        rng = np.random.default_rng(F.seed+950)
        x0, _, x1, _ = F.box
        inside = F.ink > .5
        cols = np.nonzero(inside.any(axis=0))[0]
        result = []
        for x in rng.choice(cols, size=min(len(cols), int(np.clip(round((x1-x0)/F.u*26), 16, 200))), replace=False):
            top = float(inside[:, x].argmax())
            result.append(dict(x=float(x), base=top+F.u*.05, height=F.u*rng.uniform(.14, .3), width=F.u*rng.uniform(.02, .032),
                               tone=GRASS[int(rng.integers(1, len(GRASS)))], lean=rng.uniform(-.2, .2), phase=rng.uniform(0, math.tau)))
        return result
    return plants(F, 'blades', build)


@recipe('meadow-grass-lettering', 'entrance', pad=.9)
def meadow_grass(F, canvas, t, intensity):
    """The letters grow as patches of turf from the ground up, behind a ragged front of blade tips, in a wave
    from left to right; then a gust combs across the word as a travelling silver-green sheen,
    bending the blade tips along the letter tops before they spring back."""
    from effects.growth.crafted import rim
    grow = np.clip((t-.02-.36*np.clip(F.xn, 0, 1))/.3, 0, 1)  # the turf comes up in a wave from left to right
    jitter = F.noise(.02, 961, (.15, 3.))  # every column its own blade height
    up = np.clip((F.box[3]-F.py)/max(1, F.box[3]-F.box[1]), 0, 1)
    front = grow*1.2-up+.14*jitter
    cov = coverage(F.sdf)*smooth(front, 0, .03)
    streak = .78+.22*F.noise(.006, 962, (.12, 4.))  # vertical blade streaks
    turfs = ((rgb(52, 142, 58), rgb(196, 234, 112)), (rgb(30, 128, 104), rgb(150, 226, 186)), (rgb(134, 104, 36), rgb(255, 242, 186)), (rgb(36, 112, 120), rgb(150, 214, 200)))
    deep, light = (np.array(c) for c in turfs[F.seed % len(turfs)])  # spring lime, sea-green, golden, blue-green
    body = mix(deep, light, (np.clip(up, 0, 1)**.9*.85)[..., None])*streak[..., None]
    wave = sm(t, .52, .92)*1.5-.25
    gust = np.exp(-((F.xn-wave)/.13)**2)*(0 < wave < 1.25)
    body = np.clip(body+gust[..., None]*np.array((.5, .5, .42))*streak[..., None], 0, 1)
    tips = np.exp(-((front-.03)/.04)**2)*coverage(F.sdf)*(grow > 0)*(grow < 1)
    canvas.over(np.zeros(3), shadow(cov, F, .03, .05, .03, .4))
    colour, alpha = rim(F, cov, .018, np.array(rgb(22, 50, 20)), .9)
    canvas.over(colour, alpha)
    canvas.over(body, cov)
    canvas.add(np.array((.75, 1., .45))*tips[..., None]*.6)
    meadow = blades(F)
    x0, x1 = F.box[0], F.box[2]

    def draw(d, f):
        for b in meadow:
            g = sm(grow[0, int(b['x'])], .75, 1.)
            if g <= 0:
                continue
            here = (b['x']-x0)/max(1, x1-x0)
            bend = math.exp(-((here-wave)/.12)**2)*(0 < wave < 1.25)*1.6  # the gust lays the tips right over
            height = b['height']*g
            sway = (b['lean']+bend)*height
            pl, pr = [], []
            for n in range(6):
                s_ = n/5
                x = b['x']+sway*s_*s_
                y = b['base']-height*s_
                w = b['width']*(1-s_)**.8
                pl.append(((x-w)*f, y*f))
                pr.append(((x+w)*f, y*f))
            tone = mix(b['tone'], rgb(214, 232, 170), bend*.6)
            d.polygon(pl+pr[::-1], fill=as_fill(tone))

    grass_rgb, grass_a = supersampled(F, draw)
    canvas.over(np.clip(grass_rgb, 0, 1), grass_a)
