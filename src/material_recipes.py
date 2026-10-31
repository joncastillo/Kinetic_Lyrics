"""The material entrances and exits. Each recipe paints one frame of its effect from progress t alone.

Entrances run t = 0 (nothing) to 1 (the finished word, which is also the held image); exits run
t = 0 (the word as it was) to 1 (gone). Shared simulation pieces live in material_fx.py.
"""
import math

import numpy as np
from scipy.ndimage import gaussian_filter

from material_fx import (Particles, bevel, blackbody, bloom, blur, coverage, environment, flames, fresnel, lambert, mix,
                         normals, paint_fire, paint_smoke, ragged, rgb, rim, shadow, shift, sm, smooth, smoke, specular, sun,
                         warp)

RECIPES = {}


def recipe(effect_id, phase, pad=.6, work_height=None):
    """Register a painter; the effect's name and description live in its JSON recipe and descriptions.json."""
    def register(function):
        RECIPES[effect_id] = dict(phase=phase, pad=pad, paint=function, work_height=work_height)
        return function
    return register


def rim_cover(F, canvas, cov, alpha=1., width=.026, colour=(.07, .05, .04)):
    """A bold outline just outside whatever shape `cov` covers, ragged edges and all."""
    from scipy.ndimage import maximum_filter
    size = max(3, int(round(F.u*width))*2+1)
    grown = maximum_filter(np.asarray(cov, dtype=float), size=size)
    canvas.over(np.asarray(colour), np.clip(grown-cov, 0, 1)*alpha)


# ---------------------------------------------------------------- secondary layers shared by many recipes

def front_band(erode, t, width=.05, mask=None):
    """Where a front (erosion, burn, fill...) is passing right now: 1 on the front, 0 away from it."""
    band = smooth(width-np.abs(erode-t), 0, width)
    return band if mask is None else band*mask


def plume(F, canvas, t, source, colour, opacity=.6, rise=.6, drift=.3, seed=0):
    """A dust, steam or smoke plume rising from `source`."""
    if np.any(source > .01):
        paint_smoke(F, canvas, smoke(F, source, t, rise, seed, drift=drift), colour, opacity)


def spark_burst(F, canvas, t, origins, born, seed, up=2.2, spread=1.6, gravity=8., life=(.05, .13), cooling=True,
           colour=(1, .85, .6)):
    """Motion-blurred sparks thrown from points, cooling from white to red under gravity."""
    if not len(origins):
        return
    rng = np.random.default_rng(F.seed+seed)
    n = len(origins)
    velocity = np.stack((rng.normal(0, spread, n), -rng.uniform(up*.3, up, n)), 1)
    Particles(F, origins, born, velocity, accel=(0, gravity), drag=.8, life=rng.uniform(*life, n),
              size=rng.choice((1, 1, 2), n), shape='streak', cooling=cooling, color=colour, trail=.02).render(canvas, t)


def sample(mask, count, seed, F):
    """Random pixel positions where `mask` is set."""
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return np.zeros((0, 2))
    pick = np.random.default_rng(F.seed+seed).integers(0, len(xs), count)
    return np.stack((xs[pick], ys[pick]), 1).astype(float)


# ---------------------------------------------------------------- shared pieces

def self_shadow(F, height, light, steps=8, reach=.18):
    """Height-field cast shadows: a pixel is shaded if terrain toward the sun rises above its sightline."""
    flat = math.hypot(light[0], light[1])
    if flat < 1e-3:
        return np.zeros_like(height)
    dx, dy = light[0]/flat, light[1]/flat
    rise = light[2]/flat
    shade = np.zeros_like(height)
    step = max(1., reach*F.u/steps)
    for k in range(1, steps+1):
        ox, oy = round(dx*step*k), round(dy*step*k)
        ahead = shift(height, -oy, -ox)
        shade = np.maximum(shade, ahead-height-rise*step*k)
    return smooth(shade, 0, F.u*.03)


def strata_color(F, palette, frequency, warp, seed=0, tilt=.12):
    """Sedimentary bands: colour by a warped depth coordinate, interpolated through a palette."""
    layer = F.Y*frequency+warp*F.fbm(.9, 3, seed)+tilt*F.X+F.fbm(.12, 2, seed+5)*.25
    pal = np.asarray(palette, dtype=float)/255
    position = (layer % len(pal))
    low = np.floor(position).astype(int) % len(pal)
    high = (low+1) % len(pal)
    blend = smooth(position-np.floor(position), .35, .65)
    return mix(pal[low], pal[high], blend), layer


def grain(F, amount, seed=0, scale=.012):
    return 1+amount*F.noise(scale, seed+400)


def rounded_box(F, left, top, right, bottom, radius):
    """Signed distance (px) to a rounded rectangle around the ink box, margins in units."""
    x0, y0, x1, y1 = F.box
    x0, x1 = x0-left*F.u, x1+right*F.u
    y0, y1 = y0-top*F.u, y1+bottom*F.u
    r = radius*F.u
    qx = np.abs(F.px-(x0+x1)/2)-((x1-x0)/2-r)
    qy = np.abs(F.py-(y0+y1)/2)-((y1-y0)/2-r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))+np.minimum(np.maximum(qx, qy), 0)-r


def letter_depth(F):
    """Depth into the letters in units (0 at the outline)."""
    return np.clip(-F.sdf/F.u, 0, None)


def lit(albedo, n, light, brightness=1., tint=1., ambient=.32, shade=None, sky=rgb(120, 140, 175)):
    diffuse = lambert(n, light)
    if shade is not None:
        diffuse = diffuse*(1-shade*.85)
    fill = ambient*(.55+.45*n[..., 2])
    return albedo*(diffuse[..., None]*brightness*np.asarray(tint)+fill[..., None]*sky*1.6)


# ---------------------------------------------------------------- entrances: erosion

SANDSTONE = ((236, 204, 160), (219, 160, 104), (190, 108, 66), (231, 176, 138), (160, 86, 58), (240, 214, 176),
             (205, 132, 84))


def metal(n, tint, light=None, power=80, env_gain=1.):
    light = sun() if light is None else light
    env = environment(n)*env_gain
    return env*np.asarray(tint)+specular(n, light, power)[..., None]*1.2


def block_erosion(F, key, margins, wind, noise, hard_bands=0., chips=None):
    """Erosion time per pixel for a block around the word; letters (rough outline) survive to the end."""
    def build():
        block = rounded_box(F, *margins)+F.fbm(.3, 4, 1)*F.u*.08
        rough = F.sdf+F.u*noise*F.fbm(.05, 3, 7)
        outside = np.clip(rough/F.u, 0, None)
        skin = np.clip(-block/F.u, 0, None)
        fraction = (skin/(skin+outside+1e-3))**.85
        if hard_bands:
            fraction = fraction*(1+hard_bands*np.sin(F.Y*19+F.fbm(.6, 3, 2)*2.2))
        erode = .05+.83*fraction-wind[0]*(1-np.clip(F.xn, 0, 1))-wind[1]*(1-np.clip(F.yn, 0, 1))
        erode = erode+.07*F.fbm(.08, 3, 3)
        if chips:
            ids, _, edge, _ = F.cells(chips, 21)
            flat = np.bincount(ids.ravel(), erode.ravel())/np.maximum(1, np.bincount(ids.ravel()))
            erode = flat[ids]+.01*np.clip(edge/F.u, 0, 1)
        erode = np.where(block > 0, -1, np.minimum(erode, .95))
        return np.where(rough <= 0, 1.+np.clip(-rough/F.u, 0, None)*2.5, erode)
    return F.memo(('erosion', key), build)


def front_particles(F, erode, count, seed):
    front = np.nonzero((erode > .03) & (erode < .94) & (F.sdf > 0))
    rng = np.random.default_rng(F.seed+seed)
    if not len(front[0]):
        return None, rng, (np.zeros(0, int),)*2
    pick = rng.integers(0, len(front[0]), count)
    ys, xs = front[0][pick], front[1][pick]
    return np.stack((xs, ys), 1), rng, (ys, xs)


MARBLE_VEIN = rgb(118, 112, 120)


@recipe('marble-chisel-reveal', 'entrance', pad=.75)
def marble_chisel(F, canvas, t, intensity):
    erode = block_erosion(F, 'marble', (.28, .3, .28, .18, .04), (.05, .0), .008, chips=.07)

    def build():
        veins = np.abs(np.sin(F.X*3+F.Y*5+F.fbm(.5, 5, 30)*5))
        vein = 1-smooth(veins, 0, .09)
        base = mix(rgb(236, 233, 227), rgb(214, 208, 200), .5+.5*F.fbm(.4, 3, 31))
        return mix(base, MARBLE_VEIN, vein*.75)*grain(F, .025)[..., None]
    albedo = F.memo('marble-albedo', build)
    remaining = erode-t
    cov = smooth(remaining, 0, .01)*sm(t, 0, .05)
    rough_face = 1-sm(t, .75, .97)
    _, _, edge, _ = F.cells(.07, 21)
    facets = np.clip(edge/F.u, 0, .03)/.03
    depth = np.clip(remaining, 0, .2)/.2
    height = F.u*(.14*np.sqrt(depth)+.02*facets*rough_face)
    n = normals(height)
    light = sun()
    polish = sm(t, .82, 1)
    body = lit(albedo, n, light, shade=self_shadow(F, height, light))
    body += specular(n, light, 40)[..., None]*(.15+.5*polish)
    canvas.over(np.zeros(3), shadow(cov, F, .06, .08, .05, .5))
    canvas.over(body, cov)
    if t < .97:
        origins, rng, (ys, xs) = front_particles(F, erode, 260, 41)
        if origins is not None:
            count = len(xs)
            side = np.sign(F.px[ys, xs]-F.cx+1e-3)
            chips = Particles(F, origins, erode[ys, xs],
                              np.stack((side*rng.uniform(.4, 2.2, count), -rng.uniform(.8, 2.4, count)), 1),
                              accel=(0, 9.), drag=.4, life=rng.uniform(.08, .16, count),
                              size=rng.uniform(1.5, max(2, F.u*.035), count), color=albedo[ys, xs], shape='chip', spin=60)
            chips.render(canvas, t)
            dust = Particles(F, origins, erode[ys, xs],
                             np.stack((side*rng.uniform(.1, .6, count), -rng.uniform(.1, .5, count)), 1),
                             accel=(.2, .6), drag=3, life=.2, size=1, color=rgb(240, 236, 228), alpha=.5, swirl=.05)
            dust.render(canvas, t)

    if t < .95:  # each strike bursts into marble dust and white sparks off the chisel
        plume(F, canvas, t, front_band(erode, t, .03, F.sdf > 0), rgb(236, 232, 226), .55, .4, .1, 701)
        strike = sample(np.abs(erode-t) < .004, 40, 702+int(t*60), F)
        spark_burst(F, canvas, t, strike, t-.01, 703+int(t*60), 2.5, 2., 9., (.02, .05), False, (1., 1., .95))
    rim_cover(F, canvas, cov, sm(t, .75, 1), colour=(.2, .2, .22))


@recipe('ice-block-thaw', 'entrance', pad=.75)
def ice_thaw(F, canvas, t, intensity):
    erode = block_erosion(F, 'ice', (.26, .3, .26, .2, .12), (0., .12), .006)
    remaining = erode-t
    cov = smooth(remaining, 0, .015)*sm(t, 0, .06)
    depth = np.clip(remaining, 0, .25)/.25
    wet = 1-sm(t, .9, 1)*.4
    height = F.u*(.18*np.sqrt(depth)+.006*F.fbm(.05, 3, 50)*wet)
    n = normals(height)
    light = sun()
    _, _, edge, _ = F.cells(.22, 51)
    cracks = (1-smooth(edge/F.u, 0, .012))*(F.noise(.15, 52) > -.2)
    bubbles = smooth(F.noise(.012, 53), .82, .95)
    inner = mix(rgb(150, 205, 230), rgb(230, 247, 255), np.clip(1-depth, 0, 1)*.7+.3*bubbles)
    color = inner*(.55+.45*lambert(n, light))[..., None]
    color = color+environment(n, sky=(.75, .88, 1))*fresnel(n, .08)[..., None]*1.4
    color = color+specular(n, light, 120)[..., None]*1.5+cracks[..., None]*.35
    alpha = cov*np.clip(.55+.35*(1-n[..., 2])*4+.3*cracks+.25*bubbles+.15*(1-depth), 0, .95)
    canvas.over(rgb(20, 60, 90), shadow(cov, F, .04, .07, .05, .25))
    canvas.over(np.clip(color, 0, 1), alpha)
    if t < .97:
        origins, rng, (ys, xs) = front_particles(F, erode, 300, 54)
        if origins is not None:
            drops = Particles(F, origins, erode[ys, xs]+rng.uniform(0, .05, len(xs)),
                              np.stack((rng.uniform(-.05, .05, len(xs)), rng.uniform(0, .3, len(xs))), 1),
                              accel=(0, 7.), drag=.3, life=rng.uniform(.05, .1, len(xs)),
                              size=rng.choice((1, 2), len(xs)), color=rgb(225, 245, 255), alpha=.85)
            drops.render(canvas, t)

    if t < .95:  # cold mist rolls off the melting face
        plume(F, canvas, t, front_band(erode, t, .06, F.sdf > 0), rgb(220, 240, 250), .35, .35, .2, 704)
    rim_cover(F, canvas, cov, sm(t, .75, 1)*.8, colour=(.04, .14, .24))


# ---------------------------------------------------------------- entrances: pours

@recipe('lava-flow-fill', 'entrance', pad=.7)
def lava(F, canvas, t, intensity):
    filled = .04+.62*np.clip(F.xn+.25*F.fbm(.3, 3, 90), 0, 1.2)/1.2+.08*np.clip(1-F.yn, 0, 1)
    age = t-filled
    cov = coverage(F.sdf+F.u*.012*F.fbm(.04, 2, 91))*smooth(age, -.01, .01)
    _, _, edge, _ = F.cells(.11, 92)
    crust = smooth(age, .03, .22)
    crack = 1-smooth(edge/F.u, 0, .006+.03*(1-crust))
    heat = np.clip(1-crust*.92, 0, 1)*(1-crack)+crack*(.35+.65*(1-crust*.6))
    heat = heat*(.9+.1*np.sin(F.fbm(.08, 2, 93)*6+t*20))
    plate = .02*smooth(edge/F.u, 0, .02)
    height = F.u*(.06*np.sqrt(np.clip(-F.sdf/(F.u*.06), 0, 1))+plate*crust+.01*F.fbm(.03, 2, 94))
    n = normals(height)
    rock = lit(rgb(52, 44, 42)*grain(F, .2, 95)[..., None], n, sun())+specular(n, sun(), 30)[..., None]*.15
    hot = blackbody(heat*1.05)*1.5
    body = mix(rock, hot, smooth(heat, .15, .7))
    canvas.over(np.zeros(3), shadow(cov, F, .05, .08, .05, .5))
    canvas.over(np.clip(body, 0, 1), cov)
    canvas.add(bloom(hot*(cov*smooth(heat, .2, .9))[..., None], F, .05, .6))

    if t < .97:  # the fresh flow burns, smokes and throws embers until its crust closes
        burning = cov*smooth(heat, .45, .9)
        paint_fire(F, canvas, flames(F, burning*(1-sm(t, .75, .95)), t, .3, 709), .8)
        plume(F, canvas, t, cov*smooth(heat, .2, .7)*.8, rgb(70, 60, 58), .55, .9, .2, 710)
        canvas.distort(F, np.clip(shift(blur(burning[..., None], F.u*.06)[..., 0], -round(F.u*.12), 0)*2.5, 0, 1), t)
        rng = np.random.default_rng(F.seed+711)
        lift = F.ink_points(160, 712)
        Particles(F, lift, rng.uniform(.05, .8, 160), np.stack((rng.normal(0, .3, 160), -rng.uniform(.5, 1.3, 160)), 1),
                  accel=(0, -1.), drag=1.2, life=rng.uniform(.08, .18, 160), size=rng.choice((1, 2), 160), glow=True,
                  cooling=True, flicker=.6, swirl=.05).render(canvas, t)
    rim_cover(F, canvas, cov, sm(t, .5, 1), colour=(.08, .05, .04))


# ---------------------------------------------------------------- silk

SILK_SHADOW, SILK_BASE, SILK_LIGHT = rgb(140, 78, 84), rgb(228, 196, 150), rgb(255, 247, 228)
MUCHA_INK = rgb(66, 42, 36)


def fold(u):
    """Cloth fold profile: broad rounded crowns, tighter valleys."""
    return np.sin(u)+.35*np.sin(2*u+1.)


def silk_pins(F, spacing=.42):
    """Folds hang from pins along the top of the word, so every letter drapes like pinned fabric."""
    def build():
        x0, y0, x1, y1 = F.box
        count = max(2, round((x1-x0)/(F.u*spacing)))
        xs = np.linspace(x0+F.u*.1, x1-F.u*.1, count)
        nearest = np.argmin(np.abs(F.px[..., None]-xs), -1)
        dx = F.px-xs[nearest]
        dy = F.py-(y0-F.u*.18)
        theta = np.arctan2(dx, np.maximum(dy, 1.))
        r = np.hypot(dx, dy)/F.u
        hang = fold(theta*7+.8*F.fbm(.25, 3, 120)+nearest*1.7)*np.clip(r, 0, 1.4)**.6
        sag = .35*fold(r*9-np.abs(dx)/F.u*3)
        return hang+sag*.4
    return F.memo('silk-pins', build)


def silk_letter_spans(F):
    """Separate ink columns into glyph slots, including detached dots over i and j."""
    def build():
        columns = np.flatnonzero(np.any(F.ink > .35, axis=0))
        if not len(columns):
            return [(F.box[0], F.box[2])]
        cuts = np.flatnonzero(np.diff(columns) > 1)+1
        groups = [part for part in np.split(columns, cuts) if len(part)]
        return [(int(part[0]), int(part[-1]+1)) for part in groups]
    return F.memo('silk-letter-spans', build)


def satin(F, height, cov, light=None, palette=(SILK_SHADOW, SILK_BASE, SILK_LIGHT), sheen=1., side=None,
          reverse=(rgb(96, 50, 66), rgb(196, 132, 136), rgb(250, 222, 214))):
    """Satin: wrapped diffuse, a broad soft sheen plus a tighter glint, shot colour in the shadows."""
    light = sun(-2.2, .85) if light is None else light
    n = normals(gaussian_filter(height, 1.2))
    wrap = np.clip((n@light+.4)/1.4, 0, 1)
    broad = specular(n, light, 10)
    glint = specular(n, light, 70)
    shadow_c, base_c, light_c = palette
    if side is not None:
        shadow_c, base_c, light_c = (mix(r, p, side) for r, p in zip(reverse, palette))
    color = mix(shadow_c, base_c, wrap**1.3)
    color = mix(color, light_c, np.clip(broad*.55+glint*.6, 0, 1)*sheen)
    return np.clip(color, 0, 1), n


def mucha_lines(F, canvas, sdf, folds, alpha, width=.022):
    """Art Nouveau ink: a confident contour plus thin strokes in the deepest creases."""
    edge = smooth(-np.abs(sdf+F.u*width*.5)+F.u*width*.5, 0, .9)
    crease = smooth(-folds, 1.05, 1.25)*np.clip(-sdf/(F.u*.04), 0, 1)
    canvas.over(MUCHA_INK, np.clip(edge+crease*.55, 0, 1)*alpha)


def silk_strokes(F, lo, hi):
    """The letter's stroke centrelines between columns lo and hi, as one route a ribbon can follow:
    [(x, y, half stroke width, drawn)], where `drawn` is False on the hops between separate strokes."""
    def build():
        from scipy.ndimage import distance_transform_edt
        from skimage.morphology import skeletonize
        mask = F.ink > .5
        mask[:, :max(0, int(lo))] = False
        mask[:, int(hi):] = False
        if not mask.any():
            return []
        width = distance_transform_edt(mask)
        skeleton = skeletonize(mask)
        pixels = set(zip(*np.nonzero(skeleton)))

        def around(p):
            return [(p[0]+dy, p[1]+dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy or dx) and (p[0]+dy, p[1]+dx) in pixels]
        degree = {p: len(around(p)) for p in pixels}
        used, chains = set(), []

        def walk(a, b):
            chain = [a, b]
            used.add(frozenset((a, b)))
            while degree[chain[-1]] == 2:
                step = [q for q in around(chain[-1]) if frozenset((chain[-1], q)) not in used]
                if not step:
                    break
                used.add(frozenset((chain[-1], step[0])))
                chain.append(step[0])
            return chain
        for p in sorted(pixels, key=lambda p: (degree[p] == 2, p[1], p[0])):
            for q in around(p):
                if frozenset((p, q)) not in used:
                    chains.append(walk(p, q))
        # Drop the short spurs a skeleton grows into corners.
        spur = max(3., float(np.median([width[p] for p in pixels]))*1.5)
        kept = [c for c in chains if len(c) >= spur or (degree[c[0]] != 1 and degree[c[-1]] != 1)] or chains
        # Small separate marks (the dot of an i, a full stop) keep their own stroke, even a single pixel's.
        from scipy.ndimage import label
        parts, count = label(mask, structure=np.ones((3, 3)))
        covered = {parts[c[0]] for c in kept}
        for part in range(1, count+1):
            if part in covered:
                continue
            own = max((c for c in chains if parts[c[0]] == part), key=len, default=[])
            ys, xs = np.nonzero(parts == part)
            y, x = int(round(ys.mean())), int(round(xs.mean()))
            if len(own) >= width[y, x]*1.5:
                kept.append(own)
                continue
            # A round mark's skeleton is a point: give it a short stroke across its middle instead.
            reach = max(1, int(width[y, x]*.7))
            kept.append([(y, x+dx) for dx in range(-reach, reach+1) if mask[y, x+dx]] or [(y, x)])
        chains = kept
        # Join the strokes into one route: start at the top-left, then always the nearest loose end.
        route, chains = [], [list(c) for c in chains]
        chains.sort(key=lambda c: min(c[0][1]+c[0][0]*.5, c[-1][1]+c[-1][0]*.5))
        current = chains.pop(0)
        if current[-1][1]+current[-1][0]*.5 < current[0][1]+current[0][0]*.5:
            current.reverse()
        while True:
            route.extend((x, y, width[y, x], k > 0 or not route) for k, (y, x) in enumerate(current))
            if not chains:
                break
            last = current[-1]
            k, flip = min(((k, flip) for k in range(len(chains)) for flip in (False, True)),
                          key=lambda kf: math.dist(last, chains[kf[0]][-1 if kf[1] else 0]))
            current = chains.pop(k)[::-1] if flip else chains.pop(k)
            hop = math.dist(last, current[0]) > 2.5
            route.append((current[0][1], current[0][0], width[current[0]], not hop))
        # Ease the pixel staircase into smooth strokes.
        xy = np.array([(x, y) for x, y, _, _ in route], dtype=float)
        smoothed = xy.copy()
        for k in range(len(route)):
            if route[k][3] and 0 < k < len(route)-1 and route[k-1][3] and route[k+1][3]:
                smoothed[k] = xy[max(0, k-2):k+3].mean(axis=0)
        return [(float(x), float(y), float(w), drawn) for (x, y), (_, _, w, drawn) in zip(smoothed, route)]
    return F.memo(('silk-strokes', int(lo), int(hi)), build)


@recipe('mucha-silk-lettering', 'entrance', pad=2.6)
def mucha_silk(F, canvas, t, intensity):
    """Wind-driven translucent satin sheets twist and gather into fabric letters."""
    from silk_fabric import paint_silk
    paint_silk(F, canvas, t)


@recipe('mucha-silk-unfurl', 'exit', pad=1.1)


def mucha_unfurl(F, canvas, t, intensity):
    x0, x1 = F.box[0], F.box[2]
    passed = (F.px-(x0-F.u*1.1))/(x1-x0+F.u*2.2)
    keep = 1-smooth(.55+t*SCARF_SPEED-.25-passed, 0, .4)
    canvas.over(F.source, F.ink*(1-sm(t, 0, .15))*keep)
    sheer_letters(F, canvas, sm(t, 0, .15)*keep, t)
    paint_scarves(F, canvas, t, leaving=True, fade=sm(t, 0, .12)*(1-sm(t, .8, 1)))


@recipe('silk-veil-unveil', 'exit', pad=1.5)
def silk_unveil(F, canvas, t, intensity):
    # Reverse the same per-letter fabric surface: the glyphs open back into their own
    # wind-borne ribbons. The original ink hands off to the coloured silk at the start.
    mucha_silk(F, canvas, 1-t, intensity)
    canvas.over(F.source, F.ink*(1-sm(t, 0, .18)))


# ---------------------------------------------------------------- liquids that morph

def blob_sdf(F, t, radius=.45):
    """A wobbling puddle at the word's centre."""
    angle = np.arctan2(F.Y, F.X)
    r = np.hypot(F.X*.55, F.Y)
    wobble = .06*np.sin(angle*5+t*25)+.04*np.sin(angle*3-t*17)
    return (r-radius*(1+wobble))*F.u


# ---------------------------------------------------------------- growth fronts

def letters(F):
    """Per-pixel letter index from gaps in the ink's column coverage, plus the letter count."""
    def build():
        from scipy.ndimage import label
        columns = F.ink.max(axis=0) > .3
        labels, count = label(columns)
        index = np.maximum.accumulate(labels)
        index = np.where(index == 0, 1, index)
        return np.broadcast_to(index[None, :]-1, F.ink.shape).astype(float), max(1, count)
    return F.memo('letters', build)


def arrival(F, key, per_unit=1., noise=.15, seed=0):
    """0..1 time for a front spreading through the glyph from seeds scattered along the word."""
    def build():
        x0, _, x1, _ = F.box
        seeds = F.ink_spread(max(2, round((x1-x0)/F.u*per_unit)), seed)
        d = F.distance_from(seeds, ('arrival', key))+noise*F.fbm(.12, 3, seed+500)
        inside = F.ink > .3
        low, high = d[inside].min(), d[inside].max()
        return np.clip((d-low)/max(1e-3, high-low), 0, 1.2)
    return F.memo(('arrival', key), build)


@recipe('neon-tube-ignite', 'entrance', pad=.7)
def neon(F, canvas, t, intensity):
    index, count = letters(F)
    tube_d = np.abs(F.sdf+F.u*.05)
    radius = F.u*.024
    tube = coverage(tube_d-radius)
    across = np.clip(tube_d/radius, 0, 1)
    cyl = np.sqrt(1-across**2)
    rng = np.random.default_rng(F.seed+190)
    starts = .12+.55*np.arange(count)/max(1, count)+rng.uniform(-.04, .04, count)
    frame = math.floor(t*48)
    hashes = (np.sin((frame+np.arange(count)*7.3)*12.9898)*43758.5453) % 1
    lit_letter = np.clip((t-starts)/.14, 0, 1)
    on = np.where(lit_letter >= 1, 1., np.where(lit_letter > 0, (hashes > .45)*(.4+.6*lit_letter), 0.))
    on = on*sm(t, .1, .12) if t < .12 else on
    glow_on = on[index.astype(int)]
    hue = mix(rgb(255, 70, 160), rgb(80, 220, 255), (index/max(1, count-1) > .5)*0+.0)
    glass_off = rgb(120, 130, 140)*(.4+.6*cyl)[..., None]+specular(np.stack((F.X*0, F.Y*0+(-across), cyl), -1), sun(), 20)[..., None]*.4
    core = mix(hue, np.ones(3), cyl**3*.85)
    canvas.over(np.zeros(3), shadow(tube, F, .03, .05, .03, .3)*(1-glow_on))
    canvas.over(mix(glass_off, core, glow_on), tube*sm(t, 0, .06))
    backing = coverage(F.sdf)*(1-tube)*sm(t, 0, .1)
    canvas.over(rgb(18, 14, 26), backing*.55)
    canvas.add(bloom(hue*(tube*glow_on)[..., None], F, .05, 1.1))
    canvas.add(hue*(gaussian_filter(coverage(F.sdf), F.u*.03)*glow_on*.2)[..., None])

    rim_cover(F, canvas, tube*sm(t, 0, .06), 1., .02, (.05, .05, .07))
    if t < .9:  # each tube sparks at its electrodes as it strikes
        for k in range(count):
            if 0 < t-starts[k] < .14:
                tips = sample((index == k)*tube > .6, 18, 721+k, F)
                spark_burst(F, canvas, t, tips, t-.008, 722+k*13+int(t*90), 1.8, 1.8, 9., (.02, .05), False, (1., .8, .95))


@recipe('branding-iron-scorch', 'entrance', pad=1.)


def brand(F, canvas, t, intensity):
    u = F.u

    def build():
        edge = ragged(F, .03, 200)  # the burnt outline is torn and irregular, never the clean glyph
        depth = np.clip(-edge/(u*.09), 0, 1)
        creep = .3+.42*depth**.8+.1*F.fbm(.05, 3, 201)  # charcoal creeps in from the edges
        _, _, cells, _ = F.cells(.05, 202, jitter=.9)
        crack = (1-smooth(cells, 0, u*.007))*(depth > .15)
        singe = np.exp(-np.clip(edge, 0, None)/(u*(.035+.025*(.5+.5*F.fbm(.08, 2, 203)))))*(edge > 0)
        grain = F.fbm(.015, 3, 204)
        sparks = edge_points(F, edge, 240, 205)
        risers = F.ink_points(300, 206)
        return edge, depth, creep, crack, singe, grain, sparks, risers
    edge, depth, creep, crack, singe, grain, spark_at, riser_at = F.memo('brand', build)
    press = sm(t, 0, .05)
    cov = coverage(edge)*press
    iron = press*(1-sm(t, .04, .42))*(.55+.45*(1-depth))  # the iron's white heat, cooling inside out
    scorch = sm(t, .05, .3)
    charred = smooth(t-creep, 0, .05)
    front = np.exp(-((t-creep)/.035)**2)
    embers = crack*charred*np.exp(-np.clip(t-creep, 0, None)/.18)*(1-sm(t, .85, 1))
    temp = np.clip(iron+front*.55+embers*.5, 0, 1.1)

    # The singed board around the letters browns, then darkens.
    canvas.over(rgb(92, 48, 18), singe*scorch*.6*press)
    canvas.over(rgb(24, 16, 12), singe**2*sm(t, .3, .9)*.65)

    height = -.6*bevel(edge, u*.05)+u*.006*grain-u*.012*crack*charred
    n = normals(height)
    wood = mix(rgb(176, 112, 60), rgb(120, 64, 28), scorch)
    wood = mix(wood, rgb(70, 34, 16), smooth(1-depth, .3, 1)*scorch)
    coal = mix(rgb(12, 10, 10), rgb(40, 36, 35), .5+.5*grain)
    body = lit(mix(wood, coal, charred), n, sun(), ambient=.35)+(specular(n, sun(), 16)*.22*charred)[..., None]
    body = mix(body, blackbody(temp)*1.3, smooth(temp, .08, .5))
    canvas.over(np.zeros(3), shadow(cov, F, .03, .05, .03, .4))
    canvas.over(np.clip(body, 0, 1), cov)
    ash = smooth(edge, -u*.014, -u*.004)*(1-smooth(edge, -u*.002, 0))*charred
    canvas.over(rgb(170, 164, 156)*(.8+.3*grain[..., None]), ash*cov*.85)
    canvas.add(bloom(blackbody(temp)*(temp*cov)[..., None], F, .05, .7))

    if t < .98:
        burning = (1-sm(t, .45, .72))*sm(t, .03, .1)
        fuel = cov*((.35+.65*(1-depth))*burning+front*.55*(1-sm(t, .78, .95)))
        source = cov*((1-depth)*sm(t, .04, .12)*(1-sm(t, .6, .95))*.8+front*.45)
        paint_smoke(F, canvas, smoke(F, source, t, .95, 210), (.26, .24, .23), .7)
        canvas.distort(F, np.clip(shift(blur(fuel[..., None], u*.06)[..., 0], -round(u*.15), 0)*3, 0, 1), t)
        paint_fire(F, canvas, flames(F, fuel, t, .55, 211), 1.15)
        rng = np.random.default_rng(F.seed+212)
        n_ = len(spark_at)
        out = np.stack((rng.normal(0, 1.6, n_), -rng.uniform(.8, 3., n_)), 1)
        Particles(F, spark_at, rng.uniform(.03, .14, n_), out, accel=(0, 7.), drag=.8, life=rng.uniform(.05, .13, n_),
                  size=rng.choice((1, 1, 2), n_), shape='streak', cooling=True, trail=.02).render(canvas, t)
        m_ = len(riser_at)
        Particles(F, riser_at, rng.uniform(.08, .75, m_), np.stack((rng.normal(0, .25, m_), -rng.uniform(.4, 1.2, m_)), 1),
                  accel=(.2, -1.4), drag=1.2, life=rng.uniform(.1, .24, m_), size=rng.choice((1, 2), m_), glow=True,
                  cooling=True, flicker=.6, swirl=.05).render(canvas, t)


@recipe('moss-overgrowth', 'entrance', pad=.6)
def moss(F, canvas, t, intensity):
    born = arrival(F, 'moss', 1.1, .3)
    clumps = F.fbm(.035, 3, 210)
    fine = F.noise(.008, 211)
    q = smooth(t-.05-born*.7+.08*clumps, 0, .18)
    fuzz = F.u*(.02*fine+.015*clumps)
    cov = coverage(F.sdf+fuzz+F.u*.05*(1-q))*smooth(q, 0, .3)
    height = F.u*(.05*np.sqrt(q)*(.6+.4*clumps)+.012*fine)+bevel(F.sdf, F.u*.05)
    n = normals(height)
    tips = smooth(clumps+.4*fine, .1, .9)
    albedo = mix(rgb(34, 66, 22), rgb(150, 190, 60), tips)*mix(np.ones(3), rgb(200, 210, 120), (1-q)*.5)
    body = lit(albedo, n, sun(), shade=self_shadow(F, height, sun(), 5, .06))
    body = body+rgb(220, 255, 160)*(smooth(fine, .7, 1)*q*.15)[..., None]
    canvas.over(np.zeros(3), shadow(cov, F, .04, .06, .04, .4))
    canvas.over(np.clip(body, 0, 1), cov)

    rim_cover(F, canvas, cov, sm(t, .6, 1), colour=(.06, .1, .03))
    dew = smooth(F.noise(.012, 723), .86, .95)*cov*sm(t, .7, .95)  # morning dew beads on the moss
    canvas.add(np.ones(3)*(dew*specular(normals(F.u*.02*dew), sun(), 30)*1.5)[..., None], .3)


def bolt(rng, start, end, jag, steps=14):
    """A jagged lightning path between two points."""
    points = []
    for k in range(steps+1):
        f = k/steps
        x = start[0]+(end[0]-start[0])*f
        y = start[1]+(end[1]-start[1])*f
        wobble = jag*math.sin(f*math.pi)
        points.append((x+rng.normal(0, wobble), y+rng.normal(0, wobble*.3)))
    return points


@recipe('bioluminescent-bloom', 'entrance', pad=.7)
def biolum(F, canvas, t, intensity):
    ids, d1, edge, _ = F.cells(.045, 240, jitter=.9)
    born = arrival(F, 'biolum', 1.4, .25)
    q = smooth(t-.06-born*.6, 0, .15)
    phase = (ids*.618) % 1
    pulse = .65+.35*np.sin(t*24+phase*math.tau)*(1-sm(t, .85, 1))
    spots = np.exp(-(d1/(F.u*.018))**2)*q*pulse
    body_cov = coverage(F.sdf)*smooth(q, 0, .5)
    canvas.over(rgb(6, 30, 40), body_cov*.75)
    membrane = (1-smooth(edge, 0, F.u*.006))*body_cov
    canvas.over(rgb(30, 110, 120), membrane*.6)
    light = mix(rgb(40, 255, 220), rgb(120, 160, 255), phase)
    canvas.add(light*(spots*coverage(F.sdf))[..., None]*1.2)
    canvas.add(bloom(light*(spots*coverage(F.sdf))[..., None], F, .04, .9))
    if t < .97:
        rng = np.random.default_rng(F.seed+241)
        origins = F.ink_points(180, 242)
        spores = Particles(F, origins, rng.uniform(.05, .85, 180), np.stack((rng.normal(0, .15, 180), -rng.uniform(.1, .4, 180)), 1),
                           accel=(0, -.4), drag=1., life=rng.uniform(.1, .2, 180), size=rng.choice((1, 2), 180),
                           color=rgb(120, 255, 230), alpha=.9, swirl=.06, glow=True)
        spores.render(canvas, t)

    rim_cover(F, canvas, body_cov, sm(t, .6, 1)*.8, colour=(.0, .06, .08))


@recipe('stained-glass-leading', 'entrance', pad=1.1)


def stained_glass(F, canvas, t, intensity):
    u = F.u

    def build():
        ids, _, edge, centres = F.cells(.15, 260, jitter=.85)
        inside = np.unique(ids[F.ink > .5])
        rng = np.random.default_rng(F.seed+261)
        colour = np.array(TIFFANY)[rng.integers(0, len(TIFFANY), ids.max()+1)]
        second = np.array(TIFFANY)[rng.integers(0, len(TIFFANY), ids.max()+1)]
        land = np.full(ids.max()+1, 9.)
        order = np.clip((centres[inside, 0]-F.box[0])/max(1, F.box[2]-F.box[0]), 0, 1)
        land[inside] = .05+.25*order+rng.uniform(0, .06, len(inside))
        solder = arrival(F, 'solder', 1.2, .05)
        mottle = .5+.5*F.fbm(.06, 3, 262, (1.6, .6))  # opalescent glass: two colours swirled together
        pane = mix(colour[ids], second[ids], smooth(mottle, .35, .75)*.55)
        return ids, edge, centres, inside, land, solder, pane, rng.uniform(0, math.tau, ids.max()+1)
    ids, edge, centres, inside, land, solder, pane, spin = F.memo('tiffany', build)
    glass = coverage(F.sdf)
    landed = smooth(t-land[ids], 0, .02)
    seam = np.maximum(1-smooth(edge, u*.008, u*.016), smooth(F.sdf, -u*.03, -u*.018))*glass
    # 1. Shards fly in, tumbling, and snap into their places with a flash.
    flying = inside[(land[inside]-t > 0) & (land[inside]-t < .18)]
    if len(flying):
        q = (land[flying]-t)/.18
        out = centres[flying]-np.array((F.cx, F.cy+u*.6))
        out = out/np.maximum(1, np.linalg.norm(out, axis=1, keepdims=True))
        shards = Particles(F, centres[flying]+out*u*1.5*q[:, None]**1.3, 0., (0, 0), size=u*.08*(1+q*.5),
                           color=np.clip(pane[np.clip(centres[flying][:, 1].astype(int), 0, F.H-1),
                                               np.clip(centres[flying][:, 0].astype(int), 0, F.W-1)]*1.3, 0, 1),
                           shape='shard', alpha=1-q*.3, life=1., fade_in=0)
        shards.angle0 = spin[flying]+q*9
        shards.render(canvas, .001)
    snap = np.exp(-((t-land[ids])/.012)**2)*glass
    # 3. The lamp flickers on behind the glass, then glows steady and warm.
    lamp = sm(t, .58, .62)*(.35+.65*(math.sin(t*140)**2 if t < .7 else 1.))*sm(t, .58, .8)
    warm = (.35+1.05*lamp)*(.85+.3*np.exp(-((F.xn-.5)**2+(F.yn-.55)**2)/.35))
    body = pane*warm[..., None]+rgb(255, 220, 160)*(lamp*.12)
    canvas.over(rgb(30, 18, 6), shadow(glass*landed, F, .03, .05, .04, .4))
    canvas.over(np.clip(body, 0, 1), glass*landed*(1-seam))
    canvas.add(np.ones(3)*(snap*(1-seam))[..., None]*.7, .2)
    if lamp > 0:
        canvas.add(bloom(pane*(glass*landed*(1-seam)*lamp*.6)[..., None], F, .08, .7), .3)
    # 2. A glowing solder bead runs along the copper-foil seams, spitting sparks and smoke.
    soldered_at = .3+.28*solder
    done = smooth(t-soldered_at, 0, .02)
    bead_n = normals(bevel(-np.abs(np.minimum(edge, -F.sdf+u*.024))+u*.016, u*.012)+u*.004*F.noise(.01, 263))
    metal_seam = metal(bead_n, rgb(170, 160, 150), power=50)*.8
    canvas.over(np.clip(metal_seam, 0, 1), seam*done)
    molten = np.exp(-np.clip(t-soldered_at, 0, None)/.03)*done*seam
    canvas.add(blackbody(.6+.4*molten)*molten[..., None]*1.3+bloom(rgb(255, 200, 120)*molten[..., None], F, .03, .6), .4)
    if .3 < t < .6:
        tips = sample((np.abs(t-soldered_at) < .006) & (seam > .5), 30, 264+int(t*90), F)
        spark_burst(F, canvas, t, tips, t-.006, 265+int(t*90), 1.6, 1.8, 9., (.02, .06))
        plume(F, canvas, t, molten*.8, rgb(170, 170, 176), .35, .5, .1, 266)
    rim_cover(F, canvas, glass*landed, sm(t, .3, .7), colour=(.12, .1, .08))


# ---------------------------------------------------------------- exits

def transform(F, canvas, t, until, material):
    """The word's own colours give way to a material over the first part of an exit."""
    w = sm(t, 0, until)
    return mix(F.source, material, w), w


def stone_body(F, albedo, light=None, depth=.05):
    n = normals(bevel(F.sdf, F.u*depth)+F.u*.006*F.fbm(.03, 2, 300))
    return lit(albedo, n, light if light is not None else sun()), n


def cell_debris(F, canvas, t, ids, centres, fall, colour, size, seed, gravity=10., spread=1.2, shape='chip'):
    """Chunks that broke off at `fall` (per cell) tumble away under gravity."""
    inside = np.unique(ids[F.ink > .5])
    going = inside[(fall[inside] < t) & (t-fall[inside] < .35)]
    if not len(going):
        return
    rng = np.random.default_rng(F.seed+seed)
    vx = rng.normal(0, spread, len(going))
    vy = -rng.uniform(.2, 1.5, len(going))
    cx = np.clip(centres[going, 0], 0, F.W-1).astype(int)
    cy = np.clip(centres[going, 1], 0, F.H-1).astype(int)
    chunks = Particles(F, centres[going], fall[going], np.stack((vx, vy), 1), accel=(0, gravity), drag=.3,
                       life=.35, size=size*rng.uniform(.7, 1.2, len(going)), color=colour[cy, cx], shape=shape, spin=25,
                       fade_in=0)
    chunks.render(canvas, t)


@recipe('sandstone-crumble', 'exit', pad=.9)
def sandstone_crumble(F, canvas, t, intensity):
    def build():
        color, _ = strata_color(F, SANDSTONE, 4.2, .35)
        color = mix(color, color.mean((0, 1)), .25)*grain(F, .08)[..., None]
        erode = .2+.4*np.clip(F.xn, 0, 1)+2.5*np.clip(-F.sdf/F.u, 0, .1)+.08*F.fbm(.05, 3, 301)+.04*F.fbm(.2, 2, 302)
        return color, erode
    color, erode = F.memo('sand-crumble', build)
    rock, _ = stone_body(F, color)
    body, w = transform(F, canvas, t, .2, rock)
    cov = F.ink*smooth(erode-t, 0, .012)
    canvas.over(np.zeros(3), shadow(cov, F, .05, .07, .05, .4*w))
    canvas.over(np.clip(body, 0, 1), cov)
    origins = F.ink_points(3000, 303)
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    rng = np.random.default_rng(F.seed+304)
    grains = Particles(F, origins, erode[ys, xs], np.stack((rng.uniform(.8, 2.6, len(xs)), rng.uniform(-.6, .1, len(xs))), 1),
                       accel=(1.6, .5), drag=2.2, life=rng.uniform(.12, .3, len(xs)), size=rng.choice((1, 1, 2), len(xs)),
                       color=color[ys, xs], swirl=.05)
    grains.render(canvas, t)
    fresh = smooth(.05-np.abs(erode-t), 0, .05)*F.ink
    haze = shift(gaussian_filter(fresh, F.u*.07), 0, round(F.u*.15))
    canvas.over(rgb(222, 178, 128), np.clip(haze*1.4, 0, .35))

    if t < .95:
        plume(F, canvas, t, front_band(erode, t, .05)*F.ink, rgb(214, 170, 120), .45, .4, 1.6, 730)


@recipe('paper-burn', 'exit', pad=.9)
def paper_burn(F, canvas, t, intensity):
    def build():
        ys, xs = F.inside_px
        lows = [(xs[i], ys[i]) for i in np.argsort(-ys-np.random.default_rng(F.seed).uniform(0, F.u*.6, len(ys)))[:1]]
        lows.append((xs[np.argmin(xs)], ys[np.argmin(xs)]))
        d = F.distance_from(lows, 'burn')+.12*F.fbm(.08, 4, 310)
        inside = F.ink > .3
        d = (d-d[inside].min())/max(1e-3, np.ptp(d[inside]))
        return .08+.8*d
    burn = F.memo('paper-burn', build)
    r = burn-t
    scorch = smooth(.12-r, 0, .12)
    paper = mix(F.source, rgb(120, 70, 30), scorch*.8)
    char = smooth(-r, 0, .025)
    body = mix(paper, rgb(26, 20, 18), char)
    present = F.ink*smooth(r+.06+.03*F.fbm(.03, 2, 311), 0, .01)
    canvas.over(np.clip(body, 0, 1), present)
    rim = np.exp(-(r/.008)**2)*F.ink
    ember = blackbody(rim*.85+.1)*rim[..., None]*1.6
    canvas.add(ember+bloom(ember, F, .04, .7))
    sparks_on = smooth(F.noise(.01, 312), .5, .9)*np.exp(-((r+.03)/.015)**2)*F.ink
    canvas.add(blackbody(sparks_on*.7)*sparks_on[..., None])
    origins = F.ink_points(500, 313)
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    rng = np.random.default_rng(F.seed+314)
    ash = Particles(F, origins, burn[ys, xs]+.04, np.stack((rng.normal(.2, .3, len(xs)), -rng.uniform(.4, 1.2, len(xs))), 1),
                    accel=(.6, -1.8), drag=1.6, life=rng.uniform(.15, .3, len(xs)), size=F.u*rng.uniform(.015, .035, len(xs)),
                    color=mix(rgb(40, 36, 34), rgb(110, 100, 94), rng.uniform(0, 1, (len(xs), 1))), shape='flake', spin=14,
                    swirl=.08)
    ash.render(canvas, t)
    smoke = Particles(F, origins[:200], burn[ys[:200], xs[:200]], np.stack((rng.normal(0, .1, 200), -rng.uniform(.3, .7, 200)), 1),
                      accel=(.3, -.8), drag=1.2, life=.3, size=4, color=rgb(150, 145, 140), alpha=.18, swirl=.1)
    smoke.render(canvas, t)

    if t < .97:  # the burning edge carries real flame and smoke
        edge_fire = np.exp(-((r+.012)/.02)**2)*F.ink
        plume(F, canvas, t, edge_fire*.9, rgb(60, 55, 52), .6, .9, .3, 731)
        paint_fire(F, canvas, flames(F, edge_fire, t, .3, 732), .9)
        spark_burst(F, canvas, t, sample(edge_fire > .6, 40, 733+int(t*70), F), t-.01, 734+int(t*70), 1.5, 1., 2., (.03, .07))


@recipe('dust-disintegrate', 'exit', pad=1.)
def disintegrate(F, canvas, t, intensity):
    gone = .08+.72*np.clip(F.xn*.7+(1-F.yn)*.3, 0, 1)+.14*F.fbm(.05, 3, 340)
    r = gone-t
    darken = smooth(.08-r, 0, .08)
    body = mix(F.source, F.source*.35+rgb(40, 36, 34)*.4, darken)
    canvas.over(np.clip(body, 0, 1), F.ink*smooth(r, 0, .008))
    origins = F.ink_points(5000, 341)
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    rng = np.random.default_rng(F.seed+342)
    dust = Particles(F, origins, gone[ys, xs], np.stack((rng.uniform(.4, 1.8, len(xs)), -rng.uniform(.1, 1., len(xs))), 1),
                     accel=(1.2, -.6), drag=1.4, life=rng.uniform(.15, .35, len(xs)), size=rng.choice((1, 1, 1, 2), len(xs)),
                     color=F.source[ys, xs]*.6+rgb(60, 54, 50)*.4, swirl=.12)
    dust.render(canvas, t)

    if t < .95:  # the crumbling leaves a faint cloud in the word's own colours
        plume(F, canvas, t, front_band(gone, t, .06)*F.ink, np.clip(F.source.mean((0, 1))*.7+.15, 0, 1), .35, .4, 1.4, 738)


RUST = (rgb(92, 40, 22), rgb(170, 78, 34), rgb(206, 120, 60))


@recipe('rust-corrode-crumble', 'exit', pad=1.)
def rust(F, canvas, t, intensity):
    def build():
        ids, _, edge, centres = F.cells(.07, 350, jitter=.9)
        spread = arrival(F, 'rust', 1.2, .3)
        cell_rust = np.bincount(ids.ravel(), spread.ravel())/np.maximum(1, np.bincount(ids.ravel()))
        fall = .45+cell_rust*.4+np.random.default_rng(F.seed+351).uniform(-.05, .08, ids.max()+1)
        return ids, edge, centres, spread, fall
    ids, edge, centres, spread, fall = F.memo('rust', build)
    rusted = smooth(t-.05-spread*.4+.1*F.fbm(.04, 3, 352), 0, .08)
    texture = .5+.5*F.fbm(.03, 4, 353)
    iron, n = stone_body(F, rgb(120, 124, 130))
    iron = iron+specular(n, sun(), 40)[..., None]*.3
    oxide = lit(mix(RUST[0], mix(RUST[1], RUST[2], texture), texture), n, sun())
    body = mix(transform(F, canvas, t, .12, iron)[0], oxide, rusted)
    remaining = (t < fall[ids])
    cov = F.ink*remaining
    canvas.over(np.zeros(3), shadow(cov, F, .04, .06, .04, .35*sm(t, 0, .12)))
    canvas.over(np.clip(body, 0, 1), cov)
    canvas.over(RUST[0]*.6, (1-smooth(edge, 0, F.u*.008))*cov*rusted*.5)
    cell_debris(F, canvas, t, ids, centres, fall, oxide, F.u*.035, 354, spread=.4, shape='flake')

    if t < .95:
        falling = (np.abs(fall[ids]-t) < .03)*F.ink
        plume(F, canvas, t, falling, rgb(150, 80, 40), .4, -.3, .2, 739)


@recipe('acid-dissolve', 'exit', pad=.9)
def acid(F, canvas, t, intensity):
    eaten = sm(t, .1, .95)*F.u*.14*(1.3-F.yn*.6)+F.u*.03*F.fbm(.05, 3, 360)*sm(t, .1, .4)
    sdf = F.sdf+eaten
    cov = F.ink*coverage(sdf, 1.2)
    rim = np.exp(-((sdf+F.u*.01)/(F.u*.02))**2)*F.ink*sm(t, .05, .2)
    body = mix(F.source, rgb(150, 220, 60), np.clip(rim*.9+smooth(-sdf, 0, F.u*.05)*0, 0, 1))
    canvas.over(np.clip(body, 0, 1), cov)
    _, d1, _, _ = F.cells(.035, 361, jitter=.9)
    pop = .5+.5*np.sin(t*40+F.noise(.03, 362)*9)
    bubbles = np.exp(-((d1-F.u*.014*pop)/(F.u*.004))**2)*rim
    canvas.over(rgb(220, 255, 140), np.clip(bubbles, 0, 1)*(1-sm(t, .9, 1)))
    canvas.add(bloom(rgb(120, 255, 60)*(rim*.4)[..., None], F, .03, .5))
    rng = np.random.default_rng(F.seed+363)
    origins = F.ink_points(400, 364)
    fumes = Particles(F, origins, rng.uniform(.1, .9, 400), np.stack((rng.normal(0, .1, 400), -rng.uniform(.3, .8, 400)), 1),
                      accel=(.2, -1.), drag=1.2, life=.25, size=3, color=rgb(170, 230, 90), alpha=.2, swirl=.1)
    fumes.render(canvas, t)

    if t < .95:  # caustic fumes curl off the dissolving edge
        plume(F, canvas, t, rim*.9, rgb(170, 230, 90), .45, .7, .25, 740)


@recipe('petrify-crumble', 'exit', pad=1.)
def petrify(F, canvas, t, intensity):
    def build():
        ids, _, edge, centres = F.cells(.12, 370, jitter=.9)
        rng = np.random.default_rng(F.seed+371)
        cy = np.clip(centres[:, 1], 0, F.H-1)
        fall = .5+.35*np.clip((F.box[3]-cy)/max(1, F.box[3]-F.box[1]), 0, 1)*0+.35*rng.uniform(0, 1, len(centres))
        albedo = mix(rgb(120, 118, 112), rgb(178, 174, 166), .5+.5*F.fbm(.08, 3, 372))*grain(F, .1)[..., None]
        return ids, edge, centres, fall, albedo
    ids, edge, centres, fall, albedo = F.memo('petrify', build)
    stone, n = stone_body(F, albedo)
    body, w = transform(F, canvas, t, .25, stone)
    crack = (1-smooth(edge, 0, F.u*.01))*sm(t, .25, .45)
    shake = math.sin(t*90)*F.u*.006*sm(t, .4, .5)*(1-sm(t, .55, .6))
    remaining = t < fall[ids]
    cov = F.ink*remaining
    if shake:
        cov = shift(cov, 0, round(shake))
    canvas.over(np.zeros(3), shadow(cov, F, .05, .07, .05, .45*w))
    canvas.over(np.clip(body*(1-.7*crack)[..., None], 0, 1), cov)
    cell_debris(F, canvas, t, ids, centres, fall, stone, F.u*.06, 373, gravity=14, spread=.6)
    origins = F.ink_points(800, 374)
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    rng = np.random.default_rng(F.seed+375)
    dust = Particles(F, origins, fall[ids[ys, xs]], np.stack((rng.normal(0, .5, len(xs)), rng.uniform(-.4, .3, len(xs))), 1),
                     accel=(0, .4), drag=2.5, life=.25, size=1, color=albedo[ys, xs], alpha=.5, swirl=.06)
    dust.render(canvas, t)

    if t < .95:
        breaking = (np.abs(fall[ids]-t) < .03)*F.ink
        plume(F, canvas, t, breaking, rgb(170, 166, 158), .55, .25, .3, 741)


@recipe('freeze-shatter', 'exit', pad=1.1)
def freeze_shatter(F, canvas, t, intensity):
    def build():
        ids, _, edge, centres = F.cells(.1, 380, jitter=.9)
        frost = arrival(F, 'freeze', 1., .25)
        return ids, edge, centres, frost
    ids, edge, centres, frost = F.memo('freeze', build)
    frozen = smooth(t-.02-frost*.4, 0, .06)
    feathers = smooth(np.abs(np.sin(F.X*40+F.Y*25+F.fbm(.05, 3, 381)*8)), .85, 1)
    n = normals(bevel(F.sdf, F.u*.05)+F.u*.006*F.fbm(.02, 2, 382))
    ice = mix(rgb(170, 215, 240), rgb(240, 252, 255), feathers*.6+.2)*(.65+.4*lambert(n, sun()))[..., None]
    ice = ice+specular(n, sun(), 120)[..., None]
    body = mix(F.source, ice, frozen)
    burst = .55
    intact = t < burst
    canvas.over(np.clip(body+(1-smooth(edge, 0, F.u*.008))[..., None]*.4*sm(t, .4, .55), 0, 1), F.ink*intact)
    if t >= burst:
        flash = np.exp(-((t-burst)/.03)**2)
        canvas.add(rgb(200, 240, 255)*(F.ink*flash*.5)[..., None])
        inside = np.unique(ids[F.ink > .5])
        rng = np.random.default_rng(F.seed+383)
        out = centres[inside]-np.array((F.cx, F.cy))
        out = out/np.maximum(1, np.linalg.norm(out, axis=1, keepdims=True))
        speed = rng.uniform(1.5, 4, len(inside))[:, None]
        shards = Particles(F, centres[inside], burst, out*speed+np.array((0, -.5)), accel=(0, 8), drag=.8, life=.45,
                           size=F.u*rng.uniform(.04, .08, len(inside)), color=rgb(215, 240, 252), shape='shard', spin=30,
                           fade_in=0)
        shards.render(canvas, t)
        rng2 = np.random.default_rng(F.seed+384)
        glitter = Particles(F, F.ink_points(600, 385), burst, np.stack((rng2.normal(0, 2, 600), rng2.normal(-.5, 1.5, 600)), 1),
                            accel=(0, 4), drag=2, life=.35, size=1, color=rgb(230, 250, 255), glow=True)
        glitter.render(canvas, t)

    if t < burst:  # freezing air: a cold mist creeps off the frost front
        plume(F, canvas, t, frozen*F.ink*.5, rgb(225, 240, 250), .3, .3, .2, 742)


@recipe('ice-sublimate', 'exit', pad=1.)
def sublimate(F, canvas, t, intensity):
    thin = sm(t, .15, .95)*F.u*.12+F.u*.02*F.fbm(.04, 3, 390)*sm(t, .1, .3)
    sdf = F.sdf+thin
    cov = F.ink*coverage(sdf, 1.)*(1-sm(t, .9, 1))
    n = normals(bevel(sdf, F.u*.05))
    ice = mix(rgb(180, 220, 240), rgb(245, 252, 255), .5+.5*F.fbm(.05, 2, 391))*(.6+.45*lambert(n, sun()))[..., None]
    ice = ice+specular(n, sun(), 160)[..., None]*1.2
    body, w = transform(F, canvas, t, .2, ice)
    canvas.over(np.clip(body, 0, 1), cov*(1-.25*w))
    rng = np.random.default_rng(F.seed+392)
    origins = F.ink_points(700, 393)
    vapour = Particles(F, origins, rng.uniform(.12, .85, 700), np.stack((rng.normal(0, .15, 700), -rng.uniform(.2, .6, 700)), 1),
                       accel=(0, -.8), drag=1.4, life=rng.uniform(.15, .3, 700), size=rng.uniform(2, 4, 700),
                       color=rgb(235, 245, 255), alpha=.22, swirl=.12)
    vapour.render(canvas, t)
    glints = Particles(F, origins[:120], rng.uniform(.1, .8, 120), (0, -.2), drag=1, life=.05, size=1,
                       color=np.ones(3), glow=True)
    glints.render(canvas, t)

    if t < .95:
        plume(F, canvas, t, cov*sm(t, .1, .4)*.8, rgb(236, 244, 252), .4, .8, .15, 743)


@recipe('ink-in-water', 'exit', pad=1.3)


def ink_water(F, canvas, t, intensity):
    u = F.u
    q = sm(t, 0, 1)
    premult = F.source*F.ink[..., None]
    # 2. Billow: the ink pours out of the letters as layered clouds, each sinking and curling at its own
    #    pace; dense cores keep the ink's own colour, thin wisps turn translucent (never grey).
    out = sm(t, .06, .65)
    total_a = np.zeros(F.ink.shape)
    total_c = np.zeros(F.source.shape)
    for layer, (weight, speed, swirl) in enumerate(((.6, .7, .25), (.42, 1.05, .4), (.3, 1.5, .6))):
        drift = q**1.25*(1+.3*layer)
        sink = u*speed*drift*(.65+.35*(.5+.5*F.fbm(.25, 2, 400+layer)))
        curl = u*swirl*drift*F.flow(.18, t, (0., .8), 401+layer)
        sigma = .6+u*(.015+.07*drift)*(1+.6*layer)
        a = blur(warp(F, F.ink, curl, sink)[..., None], sigma)[..., 0]
        c = blur(warp(F, premult, curl, sink), sigma)
        filaments = .5+.75*(.5+.5*F.flow(.07, t, (.1, 1.4), 405+layer, (1., 2.5)))
        total_a += a*weight*filaments*out
        total_c += c*(weight*filaments*out)[..., None]
    fade = 1-sm(t, .55, 1)
    density = np.clip(total_a*1.4, 0, 1)*fade
    shade = total_c/np.maximum(total_a[..., None], 1e-4)
    shade = shade*(1-.22*np.clip(total_a*1.6-.4, 0, 1))[..., None]  # denser ink reads deeper, as real ink does
    canvas.over(np.clip(shade, 0, 1), density)
    # The letters stay crisp and fully coloured at first, then erode as their ink leaves them.
    erode = F.u*.1*sm(t, .12, .7)*(1.2-F.yn*.5)+F.u*.03*F.fbm(.04, 3, 406)*sm(t, .1, .3)
    core = coverage(F.sdf+erode, 1.)*F.ink*(1-sm(t, .55, .75))
    canvas.over(F.source, core)
    # 1. First bleed: thin tendrils droop from the bottom edges, curling as they sink.
    bottoms = ((F.ink > .5) & (shift(F.ink, -2, 0) < .3)).astype(float)
    feed = bottoms*smooth(F.noise(.03, 407), .1, .6)
    reach = sm(t, .02, .5)
    tendril = np.zeros(F.ink.shape)
    steps = 14
    for k in range(1, steps+1):
        tendril = np.maximum(tendril, shift(feed, round(k*u*.05*reach), 0)*(1-k/(steps+1)))
    tendril = warp(F, tendril, F.flow(.08, t, (0., 1.), 408)*u*.08*reach, 0)
    nearby = blur(premult, u*.12)/np.maximum(blur(F.ink[..., None], u*.12), 1e-4)  # each letter's own ink colour
    tendril_colour = warp(F, nearby, 0, u*.15*reach)
    canvas.over(np.clip(tendril_colour, 0, 1), np.clip(blur(tendril[..., None], .8)[..., 0]*1.5, 0, 1)*sm(t, .01, .08)*fade)
    # 3. Fine specks of ink sink and drift through the water.
    origins = F.ink_points(500, 409)
    rng = np.random.default_rng(F.seed+410)
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    Particles(F, origins, rng.uniform(.04, .7, len(xs)), np.stack((rng.normal(0, .15, len(xs)), rng.uniform(.15, .6, len(xs))), 1),
              accel=(0, .3), drag=1.2, life=rng.uniform(.2, .4, len(xs)), size=rng.choice((1, 1, 2), len(xs)),
              color=F.source[ys, xs]*.8, alpha=.85, swirl=.12).render(canvas, t)


@recipe('steam-evaporate', 'exit', pad=1.1)
def steam(F, canvas, t, intensity):
    shimmer = F.u*.03*sm(t, 0, .4)*np.sin(F.py/F.u*22+t*60)
    alpha = warp(F, F.ink, shimmer, 0)
    colour = warp(F, F.source, shimmer, 0)
    hot = sm(t, .05, .5)
    body = mix(colour, rgb(255, 250, 240), hot*.5)
    cov = alpha*(1-sm(t, .3, .85))*(1-hot*.3*(.5+.5*F.fbm(.04, 2, 410)))
    canvas.over(np.clip(body, 0, 1), cov)
    rng = np.random.default_rng(F.seed+411)
    origins = F.ink_points(900, 412)
    puffs = Particles(F, origins, rng.uniform(.1, .8, 900), np.stack((rng.normal(0, .2, 900), -rng.uniform(.6, 1.4, 900)), 1),
                      accel=(0, -1.5), drag=1.6, life=rng.uniform(.18, .3, 900), size=rng.uniform(2.5, 4, 900),
                      color=rgb(245, 246, 248), alpha=.18, swirl=.15)
    puffs.render(canvas, t)

    if t < .95:
        plume(F, canvas, t, alpha*hot*.9, rgb(244, 245, 247), .55, 1., .2, 744)


@recipe('lightning-vaporize', 'exit', pad=1.1)
def vaporize(F, canvas, t, intensity):
    from PIL import Image, ImageDraw
    index, count = letters(F)
    rng = np.random.default_rng(F.seed+420)
    strikes = sorted(rng.uniform(.05, .45, count+1))
    targets = F.ink_spread(count+1, 421)
    hit = np.full(F.ink.shape, 9.)
    for when, (tx, ty) in zip(strikes, targets):
        hit = np.minimum(hit, when+F.distance_from([(tx, ty)], ('strike', tx, ty))*.12)
    charge = smooth(t-hit, 0, .05)
    gone = hit+.18+.1*F.fbm(.05, 2, 422)
    cov = F.ink*smooth(gone-t, 0, .01)
    plasma = mix(rgb(150, 180, 255), np.ones(3), charge*(.6+.4*math.sin(t*200)**2))
    body = mix(F.source, plasma, charge)
    canvas.over(np.clip(body, 0, 1), cov)
    canvas.add(bloom(plasma*(cov*charge)[..., None], F, .05, .8))
    glow = Image.new('L', (F.W, F.H))
    draw = ImageDraw.Draw(glow)
    for k, (when, (tx, ty)) in enumerate(zip(strikes, targets)):
        if -.005 < t-when < .06:
            path_rng = np.random.default_rng(F.seed*5+k*17+math.floor(t*60))
            path = bolt(path_rng, (tx+path_rng.normal(0, F.u*.6), 0), (tx, ty), F.u*.18)
            draw.line(path, fill=255, width=max(1, round(F.u*.012)))
    arcs = np.asarray(glow, dtype=float)/255
    if arcs.any():
        canvas.add(bloom(rgb(140, 170, 255)*arcs[..., None], F, .04, 1.4))
        canvas.over(np.ones(3), arcs)
    origins = F.ink_points(1500, 423)
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    sparks = Particles(F, origins, gone[ys, xs], np.stack((rng.normal(0, 1.5, len(xs)), rng.normal(-.8, 1.2, len(xs))), 1),
                       accel=(0, 3), drag=1.5, life=rng.uniform(.06, .16, len(xs)), size=1,
                       color=rgb(170, 200, 255), glow=True)
    sparks.render(canvas, t)

    if t < .95:
        plume(F, canvas, t, front_band(gone, t, .05)*F.ink, rgb(170, 180, 210), .4, .6, .2, 745)


@recipe('neon-burnout', 'exit', pad=.9)
def neon_burnout(F, canvas, t, intensity):
    index, count = letters(F)
    tube_d = np.abs(F.sdf+F.u*.05)
    radius = F.u*.024
    tube = coverage(tube_d-radius)
    cyl = np.sqrt(1-np.clip(tube_d/radius, 0, 1)**2)
    rng = np.random.default_rng(F.seed+470)
    deaths = .3+.5*rng.permutation(count)/max(1, count)+rng.uniform(-.03, .03, count)
    frame = math.floor(t*48)
    hashes = (np.sin((frame+np.arange(count)*7.3)*12.9898)*43758.5453) % 1
    dying = np.clip((t-deaths+.15)/.15, 0, 1)
    on = np.where(dying <= 0, 1., np.where(dying < 1, (hashes > .3+.6*dying)*1., 0.))
    glow_on = on[index.astype(int)]*sm(t, 0, .1)+(1-sm(t, 0, .1))*0
    hue = rgb(255, 70, 160)
    core = mix(hue, np.ones(3), cyl**3*.85)
    dead = rgb(90, 94, 100)*(.4+.6*cyl)[..., None]
    word = mix(F.source, core, sm(t, 0, .1))
    lit_tube = tube*sm(t, 0, .1)
    canvas.over(F.source, F.ink*(1-sm(t, 0, .1)))
    canvas.over(np.clip(mix(dead, word, glow_on), 0, 1), lit_tube*(1-sm(t, .85, 1)))
    canvas.add(bloom(hue*(lit_tube*glow_on)[..., None], F, .05, 1.1))
    sparking = (dying > 0) & (dying < 1)
    for k in np.nonzero(sparking)[0]:
        pts = F.ink_points(40, 471+k)
        pts = pts[index[pts[:, 1].astype(int), pts[:, 0].astype(int)] == k]
        if len(pts):
            srng = np.random.default_rng(F.seed+frame*3+k)
            sparks = Particles(F, pts, t-srng.uniform(0, .03, len(pts)), np.stack((srng.normal(0, 1.5, len(pts)), srng.normal(-.5, 1., len(pts))), 1),
                               accel=(0, 10), drag=1, life=.03, size=1, color=rgb(255, 220, 160), glow=True)
            sparks.render(canvas, t)

    if t < .95:
        for k in np.nonzero(sparking)[0]:
            plume(F, canvas, t, (index == k)*tube*.6, rgb(150, 150, 160), .35, .5, .1, 748+k)


@recipe('thermite-burn', 'exit', pad=1.2)
def thermite(F, canvas, t, intensity):
    burn_line = -.1+1.25*sm(t, .05, .95)
    r = F.yn-burn_line+.04*F.fbm(.04, 2, 480)
    cov = F.ink*smooth(r, 0, .02)
    heat = np.exp(-np.clip(r, 0, None)/.05)*F.ink
    body = mix(F.source, blackbody(.6+.6*heat), smooth(heat, .1, .6))
    canvas.over(np.clip(body, 0, 1), cov)
    canvas.add(bloom(blackbody(heat*1.1)*(heat*cov)[..., None], F, .05, 1.))
    canvas.add(np.ones(3)*(np.exp(-(r/.01)**2)*F.ink)[..., None])
    front = np.nonzero((np.abs(r) < .02) & (F.ink > .5))
    if len(front[0]) and t < .97:
        rng = np.random.default_rng(F.seed+481+math.floor(t*150))
        pick = rng.integers(0, len(front[0]), 160)
        origins = np.stack((front[1][pick], front[0][pick]), 1)
        sparks = Particles(F, origins, t-rng.uniform(0, .05, 160), np.stack((rng.normal(0, .8, 160), rng.uniform(-1, .5, 160)), 1),
                           accel=(0, 14), drag=.5, life=.05, size=rng.choice((1, 2), 160), color=rgb(255, 230, 170), glow=True)
        sparks.render(canvas, t)

    if t < .97:  # thermite burns with a roaring white flame, choking smoke and a shimmer above
        burning = np.exp(-(r/.03)**2)*F.ink
        paint_fire(F, canvas, flames(F, burning, t, .45, 749), 1.2)
        plume(F, canvas, t, burning*.9, rgb(200, 196, 190), .55, 1., .25, 750)
        canvas.distort(F, np.clip(shift(blur(burning[..., None], F.u*.06)[..., 0], -round(F.u*.15), 0)*3, 0, 1), t)


@recipe('snow-blown-away', 'exit', pad=1.1)
def snow_blown(F, canvas, t, intensity):
    gone = .35+.5*np.clip(F.xn*.8+(1-F.yn)*.2, 0, 1)+.1*F.fbm(.05, 3, 500)
    fluffy = F.u*.025*(.5+.5*F.fbm(.03, 3, 501))
    sdf = F.sdf-fluffy*sm(t, .05, .3)
    cov = coverage(sdf, 1.2)*smooth(gone-t, 0, .01)
    n = normals(bevel(sdf, F.u*.05)+F.u*.008*F.fbm(.02, 2, 502))
    snow = mix(rgb(200, 215, 235), rgb(255, 255, 255), lambert(n, sun()))
    sparkle = smooth(F.noise(.005, 503), .9, 1)*.6
    body = mix(F.source, snow+sparkle[..., None], sm(t, 0, .3))
    canvas.over(np.clip(body, 0, 1), cov)
    origins = F.ink_points(3500, 504)
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    rng = np.random.default_rng(F.seed+505)
    flakes = Particles(F, origins, gone[ys, xs], np.stack((rng.uniform(1.5, 3.5, len(xs)), -rng.uniform(.2, 1.2, len(xs))), 1),
                       accel=(2, .6), drag=1.8, life=rng.uniform(.15, .3, len(xs)), size=rng.choice((1, 1, 2), len(xs)),
                       color=rgb(250, 252, 255), swirl=.1)
    flakes.render(canvas, t)

    if t < .95:
        plume(F, canvas, t, front_band(gone, t, .06)*F.ink, rgb(246, 250, 255), .5, .35, 1.8, 751)


# ---------------------------------------------------------------- ornamental growth above the word

def supersampled(F, draw_fn, factor=2):
    """Draw with PIL at `factor` times the working resolution and return an antialiased float RGBA."""
    from PIL import Image, ImageDraw
    big = Image.new('RGBA', (F.W*factor, F.H*factor))
    draw_fn(ImageDraw.Draw(big), factor)
    small = big.resize((F.W, F.H), Image.LANCZOS)
    rgba = np.asarray(small, dtype=float)/255
    return rgba[..., :3], rgba[..., 3]


def telescope(q, segments):
    """Bamboo grows one internode at a time: each segment extends quickly, then the next begins."""
    q = max(0., min(1., q))*segments
    whole = math.floor(q)
    return min(1., (whole+sm(q-whole, 0, 1))/segments)


BAMBOO_CULM = (rgb(58, 116, 46), rgb(132, 168, 64), rgb(196, 204, 120))


def bamboo_culms(F):
    """Culm layout: position, height, width, lean, sway phase and internode count, back to front."""
    def build():
        rng = np.random.default_rng(F.seed+600)
        x0, y0, x1, y1 = F.box
        count = int(np.clip(round((x1-x0)/F.u*1.7), 4, 11))
        xs = np.linspace(x0+F.u*.05, x1-F.u*.05, count)+rng.uniform(-.08, .08, count)*F.u
        culms = []
        for k, cx in enumerate(xs):
            depth = rng.uniform(0, 1)
            lean = rng.uniform(.04, .24)*(1 if (k+rng.integers(0, 2)) % 2 else -1)  # a clump fans out, never quite vertical
            culms.append(dict(x=cx, base=y1+F.u*.04, top=max(3., y0-F.u*rng.uniform(1., 1.6)),
                              width=F.u*(.03+.03*(1-depth)), lean=lean, phase=rng.uniform(0, math.tau),
                              segments=int(rng.integers(7, 11)), depth=depth, start=.02+.3*k/count+rng.uniform(0, .05),
                              tint=rng.uniform(0, 1)))
        return sorted(culms, key=lambda c: -c['depth'])
    return F.memo('bamboo-culms', build)


@recipe('bamboo-lettering', 'entrance', pad=1.8)
def bamboo(F, canvas, t, intensity):
    light = sun(-2.3, .7)
    settle = 1-sm(t, .65, 1)
    fibres = F.noise(.02, 610, (.25, 8.))
    culms = bamboo_culms(F)
    leaves = []
    body_rgb = np.zeros((F.H, F.W, 3))
    body_a = np.zeros((F.H, F.W))
    for c in culms:
        grown = telescope(sm(t, c['start'], c['start']+.6), c['segments'])
        if grown <= 0:
            continue
        span = c['base']-c['top']
        tip = c['base']-span*grown
        reach = abs(c['lean'])*span+F.u*.08+c['width']
        r0, r1 = max(0, int(tip)-2), min(F.H, int(c['base'])+2)
        c0, c1 = max(0, int(c['x']-reach)-2), min(F.W, int(c['x']+reach)+3)
        if r1 <= r0 or c1 <= c0:
            continue
        window = (slice(r0, r1), slice(c0, c1))  # shade each culm only inside its own bounding box
        py, px = F.py[window], F.px[window]
        rise = np.clip((c['base']-py)/span, 0, 1)
        sway = F.u*.05*math.sin(t*7+c['phase'])*settle*rise**2
        centre = c['x']+c['lean']*(c['base']-py)+sway
        width = c['width']*(1-.45*rise**2)
        across = (px-centre)/np.maximum(width, .5)
        inside = (np.abs(across) < 1) & (py >= tip) & (py <= c['base'])
        if not inside.any():
            continue
        cyl = np.sqrt(np.clip(1-across**2, 0, 1))
        internode = span/c['segments']
        d = ((c['base']-py)/internode) % 1
        node = np.exp(-(d/.035)**2)+np.exp(-((1-d)/.035)**2)
        n = np.stack((across*.9, -node*.6*np.sign(.5-d), cyl+.15), -1)
        n = n/np.linalg.norm(n, axis=-1, keepdims=True)
        colour = mix(BAMBOO_CULM[0], BAMBOO_CULM[1], .35+.45*c['tint']+.25*rise)
        colour = colour*(1+.08*fibres[window])[..., None]
        colour = mix(colour, rgb(226, 232, 200), np.exp(-((d-.06)/.05)**2)*.35)
        colour = mix(colour, rgb(40, 70, 30), np.exp(-((d-.985)/.02)**2)*.6)
        shaded = colour*(.35+.85*lambert(n, light))[..., None]+specular(n, light, 40)[..., None]*.45
        shaded = shaded*(1-.35*c['depth'])+rgb(150, 170, 150)*.35*c['depth']*.4
        alpha = inside*smooth(1-np.abs(across), 0, .12)*smooth(py-tip, 0, 2.)
        body_rgb[window] = mix(body_rgb[window], shaded, alpha)
        body_a[window] = alpha+body_a[window]*(1-alpha)
        for s in range(2, c['segments']+1):  # a side spray at every joint the culm has grown past
            ny = c['base']-internode*s
            if ny < tip-1 or ny > F.box[3]-F.u*.3:
                continue
            born = c['start']+.6*(s/c['segments'])+.03
            nx = c['x']+c['lean']*(c['base']-ny)+F.u*.05*math.sin(t*7+c['phase'])*settle*((c['base']-ny)/span)**2
            crown = s == c['segments']
            for side in ((-1, 1) if crown else (-1 if (s+int(c['phase']*3)) % 2 else 1,)):
                leaves.append((nx, ny, side, born, s, c, crown))
    canvas.over(np.zeros(3), shadow(body_a, F, .05, .06, .05, .35)*sm(t, 0, .1))
    canvas.over(np.clip(body_rgb, 0, 1), body_a)

    # Leaf sprays unfurl from the upper nodes; drawn supersampled, shading split along the midrib.
    sprays = []
    for nx, ny, side, born, s, c, crown in leaves:
        q = sm(t, born, born+.22)
        if q <= 0:
            continue
        local = np.random.default_rng(F.seed*31+int(c['x'])*7+s*3+side)
        count_leaves = int(local.integers(6, 10) if crown else local.integers(3, 7))
        twig = (nx+side*F.u*.12*q, ny-F.u*.04*q)
        for j in range(count_leaves):
            droop = math.radians(local.uniform(15, 70))
            spread = droop if side > 0 else math.pi-droop
            angle = -math.pi/2*(1-q)+spread*q  # rolled upright, then opening into a drooping fan
            angle += local.uniform(-.35, .35)*q+.04*math.sin(t*9+j)*settle
            length = F.u*local.uniform(.26, .46)*q**.6
            sprays.append((twig, angle, length, F.u*local.uniform(.045, .06)*q, (nx, ny), local.uniform(0, 1), c['depth'],
                           ny > F.box[1]+F.u*.1))
    # Sprays beside the letters sit behind them so the word stays readable; the canopy above is in front.
    paint_sprays(F, canvas, [p for p in sprays if p[-1]])
    # Letters carved from culm: telescoping growth with node rings at a fixed pitch.
    index, count = letters(F)
    pitch = .3
    height = bevel(F.sdf, F.u*.06)
    ring_d = ((F.box[3]-F.py)/(F.u*pitch)) % 1
    ring = np.exp(-(ring_d/.05)**2)+np.exp(-((1-ring_d)/.05)**2)
    height = height+F.u*.012*ring*np.clip(-F.sdf/(F.u*.02), 0, 1)
    n = normals(height)
    # The letters are older, darker culm than the fresh stalks around them, so they stand out from the grove.
    colour = mix(rgb(7, 28, 13), rgb(19, 47, 22), .45+.3*F.fbm(.25, 2, 611))*(1+.06*fibres)[..., None]
    colour = mix(colour, rgb(36, 66, 30), np.exp(-((ring_d-.07)/.05)**2)*.22)
    letter = lit(colour, n, light, ambient=.24)+specular(n, light, 36)[..., None]*.08
    reveal = np.zeros_like(F.yn)
    for k in range(count):
        level = telescope(sm(t, .12+.4*k/max(1, count), .62+.4*k/max(1, count)), 4)
        reveal = np.where(index == k, smooth(F.yn-(1-level*1.02), -.02, .0), reveal)
    cov = coverage(F.sdf)*reveal
    canvas.over(np.zeros(3), shadow(cov, F, .04, .06, .04, .45))
    canvas.over(np.clip(letter, 0, 1), cov)
    paint_sprays(F, canvas, [p for p in sprays if not p[-1]])


def paint_sprays(F, canvas, sprays):
    """Bamboo leaf sprays, drawn supersampled with the shading split along each midrib."""
    if sprays:
        def draw(d, f):
            for twig, angle, length, width, node, tone, depth, _ in sprays:
                d.line([(node[0]*f, node[1]*f), (twig[0]*f, twig[1]*f)], fill=(92, 112, 52, 255), width=max(1, round(f*F.u*.012)))
                ca, sa = math.cos(angle), math.sin(angle)
                bend = .18*length
                spine, left, right = [], [], []
                for k in range(13):
                    s = k/12
                    along = s*length
                    sag = bend*s*s
                    px, py = twig[0]+ca*along, twig[1]+sa*along+sag
                    w = width*(s**.45)*(1-s)**.9*2.2
                    spine.append((px*f, py*f))
                    left.append(((px-sa*w)*f, (py+ca*w)*f))
                    right.append(((px+sa*w)*f, (py-ca*w)*f))
                top_c = mix(rgb(52, 112, 40), rgb(110, 160, 56), tone)*(1-.3*depth)
                under = mix(rgb(120, 168, 70), rgb(176, 200, 98), tone)*(1-.3*depth)
                d.polygon(spine+left[::-1], fill=tuple(int(v*255) for v in top_c)+(255,))
                d.polygon(spine+right[::-1], fill=tuple(int(v*255) for v in under)+(255,))
                d.line(spine, fill=tuple(int(min(255, v*255*1.25)) for v in under)+(255,), width=max(1, f))
                d.line(right, fill=(206, 222, 120, 160), width=max(1, f//2))
        leaf_rgb, leaf_a = supersampled(F, draw)
        canvas.darken(shadow(leaf_a, F, .04, .07, .03, .35))
        veins = .92+.08*np.sin(F.px*1.7+F.py*1.1)
        canvas.over(np.clip(leaf_rgb*veins[..., None], 0, 1), leaf_a)


def cross_geometry(F):
    """Signed distances of a trefoil-tipped Latin cross above the word, plus its key points."""
    def build():
        x0, y0, x1, y1 = F.box
        u = F.u
        cx, foot, top = (x0+x1)/2, y0-u*.08, max(F.u*.12, y0-u*.95)
        bar = top+(foot-top)*.3
        half, arm = u*.052, (foot-top)*.32

        def box(px, py, hx, hy):
            qx, qy = np.abs(F.px-px)-hx, np.abs(F.py-py)-hy
            return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))+np.minimum(np.maximum(qx, qy), 0)

        def disc(px, py, r):
            return np.hypot(F.px-px, F.py-py)-r

        sdf = np.minimum(box(cx, (top+foot)/2, half, (foot-top)/2), box(cx, bar, arm, half))
        lobe = half*1.25
        for ex, ey, dx, dy in ((cx, top, 0, -1), (cx-arm, bar, -1, 0), (cx+arm, bar, 1, 0)):
            sdf = np.minimum(sdf, disc(ex+dx*lobe*.35, ey+dy*lobe*.35, lobe))
            sdf = np.minimum(sdf, disc(ex+dy*lobe*.95-dx*lobe*.35, ey+dx*lobe*.95-dy*lobe*.35, lobe*.78))
            sdf = np.minimum(sdf, disc(ex-dy*lobe*.95-dx*lobe*.35, ey-dx*lobe*.95-dy*lobe*.35, lobe*.78))
        sdf = np.minimum(sdf, box(cx, foot-half*.6, half*1.9, half*.6))
        reach = np.maximum(np.abs(F.px-cx)/max(1, arm), np.abs(F.py-bar)/max(1, foot-bar))
        return sdf, dict(cx=cx, bar=bar, top=top, foot=foot, half=half, arm=arm), reach
    return F.memo('cross', build)


def cross_surfaces(F):
    """Everything about the cross and its letters that does not change from frame to frame."""
    def build():
        sdf, g, reach = cross_geometry(F)
        u, half = F.u, g['half']
        dx, dy = F.px-g['cx'], F.py-g['bar']
        phi = np.arctan2(dy, dx)
        groove = np.exp(-((sdf+half*.5)/(half*.12))**2)
        n = normals(bevel(sdf, half*.95)-half*.18*groove)
        gold = np.clip(metal(n, rgb(255, 196, 92), power=90)*(1-.25*groove)[..., None], 0, 1)
        gem_r = np.hypot(dx, dy)/(half*1.05)
        gem_n = np.stack((dx/(half*1.05)*.8, dy/(half*1.05)*.8, np.sqrt(np.clip(1-gem_r**2, 0, 1))+.2), -1)
        gem_n = gem_n/np.linalg.norm(gem_n, axis=-1, keepdims=True)
        ruby = mix(rgb(110, 0, 20), rgb(230, 30, 60), lambert(gem_n, -sun()*np.array((1, 1, -1))))
        ruby = np.clip(ruby+specular(gem_n, sun(), 120)[..., None]*1.5, 0, 1)
        star = (np.exp(-np.abs(dx)/(u*.004))*np.exp(-np.abs(dy)/(u*.12))+np.exp(-np.abs(dy)/(u*.004))*np.exp(-np.abs(dx)/(u*.12)))
        ln = normals(bevel(F.sdf, u*.05))
        enamel = mix(rgb(236, 226, 204), rgb(255, 250, 238), lambert(ln, sun()))+specular(ln, sun(), 60)[..., None]*.35
        rim = smooth(-F.sdf, 0, 1.)*(1-smooth(-F.sdf, u*.03, u*.04))
        letter = mix(enamel, metal(ln, rgb(255, 196, 92), power=70), rim)
        warm = (rgb(255, 210, 130)*(np.clip(-ln[..., 1], 0, 1)*.25)[..., None])*(1-rim)[..., None]
        origin = np.hypot(F.px-g['cx'], (F.py-F.box[1])*1.6)/max(1., F.box[2]-F.box[0])
        return dict(sdf=sdf, g=g, reach=reach, dx=dx, dy=dy, r=np.hypot(dx, dy)/u, c16=np.cos(phi*16), s16=np.sin(phi*16),
                    gold=gold, gem=smooth(1-gem_r, 0, .15), ruby=ruby, star=star, letter=np.clip(letter, 0, 1), warm=warm,
                    gild=.42+.42*np.clip(origin*1.6, 0, 1), cover=coverage(sdf), letter_cover=coverage(F.sdf))
    return F.memo('cross-surfaces', build)


@recipe('catholic-cross-lettering', 'entrance', pad=1.2)
def cross_radiance(F, canvas, t, intensity):
    S = cross_surfaces(F)
    g, r = S['g'], S['r']
    u = F.u

    # Radiance: alternating long and short rays turning slowly, a halo, and a fine aureole ring.
    burst = sm(t, .04, .3)
    calm = .45+.55*(1-sm(t, .4, .95))
    spin = t*.9
    wave = S['c16']*math.cos(spin)-S['s16']*math.sin(spin)  # cos(16 phi + spin) from cached terms
    long_rays = (.5+.5*wave)**10
    short_rays = (.5-.5*wave)**14
    length = (.2+.45*burst)*(.75+.25*calm)*(1-.35*sm(t, .9, 1))
    rays = (long_rays*np.exp(-r/length)+.6*short_rays*np.exp(-r/(length*.6)))*smooth(r, .0, .06)
    halo = np.exp(-(r/(.16+.12*burst))**2)
    ring = np.exp(-((r-.3*burst)/.012)**2)*sm(t, .2, .45)*(1-sm(t, .9, 1)*.5)
    glow = (rays*.75+halo*.55+ring*.35)*burst*calm
    canvas.add(rgb(255, 214, 140)*glow[..., None]*.9+bloom(rgb(255, 200, 120)*(halo*burst*calm)[..., None], F, .1, .4), .5)
    if t < .35:
        flare = sm(t, .02, .1)*(1-sm(t, .2, .35))
        streak = np.exp(-(S['dy']/(u*.008))**2)*np.exp(-np.abs(S['dx'])/(u*.9))*flare
        canvas.add(rgb(255, 236, 200)*(streak+np.exp(-(r/.03)**2)*flare*2)[..., None])

    # The cross is first drawn in light from the crossing outwards, then cools into engraved gold.
    cov = S['cover']*smooth(sm(t, .1, .42)*1.15-S['reach'], 0, .05)
    solid = smooth(t-.38-.22*np.clip(S['reach'], 0, 1), 0, .12)
    canvas.over(rgb(40, 20, 0), shadow(cov, F, .03, .05, .03, .35*solid))
    canvas.over(mix(rgb(255, 246, 220), S['gold'], solid), cov)
    canvas.add(bloom(rgb(255, 220, 150)*(cov*(1-solid))[..., None], F, .04, 1.1))
    canvas.over(S['ruby'], S['gem']*sm(t, .5, .62))
    sparkle = sm(t, .6, .7)*(1-sm(t, .78, .9))
    if sparkle > 0:
        canvas.add(np.ones(3)*(S['star']*sparkle)[..., None])

    # Letters: ivory enamel within gold rims, gilded outward from the foot of the cross.
    lcov = S['letter_cover']*smooth(t-S['gild'], 0, .1)
    canvas.over(rgb(40, 20, 0), shadow(lcov, F, .03, .06, .04, .45))
    canvas.over(np.clip(S['letter']+S['warm']*sm(t, .5, 1), 0, 1), lcov)
    canvas.add(rgb(255, 230, 170)*(np.exp(-((t-S['gild']-.05)/.03)**2)*S['letter_cover'])[..., None]*.8)

    if .1 < t < .95:
        rng = np.random.default_rng(F.seed+640)
        n_ = 160
        angle = rng.uniform(0, math.tau, n_)
        speed = rng.uniform(.3, 1.1, n_)
        motes = Particles(F, np.tile((g['cx'], g['bar']), (n_, 1)), rng.uniform(.1, .7, n_),
                          np.stack((np.cos(angle)*speed, np.sin(angle)*speed*.7-.2), 1), accel=(0, -.3), drag=2.,
                          life=rng.uniform(.15, .3, n_), size=rng.choice((1, 1, 2), n_), color=rgb(255, 226, 160), glow=True,
                          swirl=.03)
        motes.render(canvas, t)
def edge_points(F, sdf, count, seed, band=.02):
    """Random pixels on a (ragged) outline, for sparks and embers thrown off an edge."""
    ys, xs = np.nonzero(np.abs(sdf) < F.u*band)
    if not len(xs):
        return np.zeros((0, 2))
    pick = np.random.default_rng(F.seed+seed).integers(0, len(xs), count)
    return np.stack((xs[pick], ys[pick]), 1).astype(float)
SCARF_SPEED = 1.9  # how far (in word-crossings) a scarf's leading edge travels over the whole effect
CHIFFON = ((rgb(236, 176, 172), rgb(196, 120, 130)), (rgb(242, 220, 168), rgb(206, 166, 104)),
           (rgb(196, 214, 176), rgb(140, 168, 128)), (rgb(214, 196, 232), rgb(160, 130, 190)))


def chiffon_scarves(F):
    """Scarf layout: each follows a graceful wave across the word; the body trails its leading edge."""
    def build():
        rng = np.random.default_rng(F.seed+130)
        count = 3
        return [dict(amplitude=rng.uniform(.3, .55)*(1 if k % 2 else -1), frequency=rng.uniform(.7, 1.1),
                     phase=rng.uniform(0, math.tau), offset=(k-1)*.2+rng.uniform(-.05, .05), width=rng.uniform(.42, .58),
                     lag=rng.uniform(.8, 1.), delay=k*.06, twist=rng.uniform(1.2, 1.9), palette=CHIFFON[(k+F.seed) % 4])
                for k in range(count)]
    return F.memo('chiffon', build)


def paint_scarves(F, canvas, t, leaving=False, fade=1.):
    """Sheer scarves drawn as twisting ribbons: translucent where the cloth faces us, denser where it turns
    edge-on (more layers in view), a sheen along the turn, and soft folds running along the length."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = F.box
    f = 2
    layers = []
    for s in chiffon_scarves(F):
        head = (t-s['delay'])*SCARF_SPEED if not leaving else .55+(t-s['delay'])*SCARF_SPEED
        if head <= 0:
            continue
        colour_img = Image.new('RGB', (F.W*f, F.H*f))
        alpha_img = Image.new('L', (F.W*f, F.H*f))
        cd, ad = ImageDraw.Draw(colour_img), ImageDraw.Draw(alpha_img)
        sections = []
        for i in range(141):
            along = i/140
            tau = head-s['lag']*along
            if tau < -.05:
                break
            x = x0-F.u*1.1+(x1-x0+F.u*2.2)*tau
            y = F.cy+F.u*(s['offset']+s['amplitude']*math.sin(tau*math.tau*s['frequency']+s['phase']))
            y += F.u*.08*math.sin(tau*17+t*6)  # a small flutter riding on the big wave
            sections.append((x, y, along))
        if len(sections) < 3:
            continue
        for i in range(len(sections)-1):
            (xa, ya, ua), (xb, yb, ub) = sections[i], sections[i+1]
            dx, dy = xb-xa, yb-ya
            norm = math.hypot(dx, dy) or 1.
            nx, ny = -dy/norm, dx/norm
            twist = math.cos((ua*s['twist']+t*.9+s['phase'])*math.pi)
            taper = math.sin(math.pi*min(1., ua*1.02))**.5*(1-.3*ua)
            half = F.u*s['width']*taper*(.12+.88*abs(twist))
            face = s['palette'][0] if twist > 0 else s['palette'][1]
            sheen = math.exp(-((abs(twist)-.35)/.18)**2)
            opacity = min(.94, .52/(abs(twist)+.3))*(1-ua**3)
            for k in range(6):  # strips across the width carry the soft lengthwise folds
                va, vb = -1+k/3, -1+(k+1)/3
                fold = .84+.16*math.sin((k+.5)*2.1+ua*3+t*2)
                shade = tuple(int(min(255, c*255*fold*(1+.35*sheen))) for c in face)
                quad = [((xa+nx*half*va)*f, (ya+ny*half*va)*f), ((xa+nx*half*vb)*f, (ya+ny*half*vb)*f),
                        ((xb+nx*half*vb)*f, (yb+ny*half*vb)*f), ((xb+nx*half*va)*f, (yb+ny*half*va)*f)]
                density = int(255*opacity*(.85+.15*fold))
                cd.polygon(quad, fill=shade, outline=shade)  # outlines close hairline gaps between strips
                ad.polygon(quad, fill=density, outline=density)
        colour = blur(np.asarray(colour_img.resize((F.W, F.H), Image.LANCZOS), dtype=float)/255, .8)
        alpha = gaussian_filter(np.asarray(alpha_img.resize((F.W, F.H), Image.LANCZOS), dtype=float)/255, .8)
        layers.append((colour, alpha))
    for colour, alpha in layers:
        canvas.over(np.clip(colour, 0, 1), alpha*fade)


def sheer_letters(F, canvas, reveal, t):
    """Sculpted satin letters that loosen into scarves during the paired exit."""
    pins = silk_pins(F)
    creases = fold(F.X*16-F.Y*5+pins*.7)
    folds = pins*.85+creases*.35
    depth = np.clip(-F.sdf/(F.u*.065), 0, 1)
    height = F.u*(.065*folds+.09*np.sqrt(depth))
    cov = coverage(F.sdf)*reveal
    face = .65+.35*smooth(np.sin(F.X*11+F.Y*3+pins), -.4, .4)
    colour, n = satin(F, height, cov, sheen=1.3, side=face)
    canvas.over(rgb(73, 36, 48), shadow(cov, F, .045, .07, .05, .3))
    canvas.over(colour, cov*.94)
    # The last fold travels just outside the letter before turning into its edge.
    turning = np.clip(4*reveal*(1-reveal), 0, 1)
    lip = np.exp(-((F.sdf-F.u*(.075*(1-reveal)-.012))/(F.u*.038))**2)*turning
    canvas.over(rgb(105, 52, 65), lip*.75)
    canvas.over(np.clip(colour*1.2, 0, 1), lip*.65)
    hem = smooth(-F.sdf, 0, 1.)*(1-smooth(-F.sdf, F.u*.014, F.u*.028))
    canvas.over(np.clip(metal(n, rgb(228, 176, 91)), 0, 1), hem*reveal*.8)
    mucha_lines(F, canvas, F.sdf, folds, reveal*.55, width=.012)
CATHEDRAL_GLASS = ((rgb(24, 58, 170), 34), (rgb(36, 84, 196), 14), (rgb(170, 16, 36), 18), (rgb(232, 158, 22), 12),
                   (rgb(22, 122, 66), 10), (rgb(104, 34, 140), 7), (rgb(222, 214, 180), 5))


def cathedral_window(F):
    """Each letter as a cathedral window: a jewelled border band of square panes, diamond quarries inside,
    lead came between every pane, and hand-made glass with streaks, seeds and uneven thickness."""
    def build():
        u = F.u
        depth = np.clip(-F.sdf/u, 0, None)
        border = .065
        cell = .2*u
        a = (F.px+F.py)/(cell*math.sqrt(2))
        b = (F.px-F.py)/(cell*math.sqrt(2))
        ia, ib = np.floor(a), np.floor(b)
        quarry_edge = np.minimum(np.minimum(a-ia, 1-(a-ia)), np.minimum(b-ib, 1-(b-ib)))*cell*math.sqrt(2)
        square = .085*u
        sq_x, sq_y = np.floor(F.px/square), np.floor(F.py/square)
        square_edge = np.minimum(np.minimum(F.px % square, square-F.px % square), np.minimum(F.py % square, square-F.py % square))
        in_border = depth < border
        ids = np.where(in_border, (sq_x*7919+sq_y*104729).astype(np.int64) % 100003+200000,
                       (ia*7919+ib*104729).astype(np.int64) % 100003)
        weights = np.array([w for _, w in CATHEDRAL_GLASS], dtype=float)
        palette = np.array([c for c, _ in CATHEDRAL_GLASS])
        rng = np.random.default_rng(F.seed+800)
        table_size = 300004
        choice = rng.choice(len(palette), table_size, p=weights/weights.sum())
        border_choice = rng.choice((2, 3, 0), table_size, p=(.45, .3, .25))  # ruby, gold and cobalt jewels
        pane_index = np.where(in_border, border_choice[ids % table_size], choice[ids % table_size])
        colour = palette[pane_index]
        streaks = F.fbm(.05, 3, 801, (.35, 3.))
        seeds = smooth(F.noise(.008, 802), .75, .95)
        thickness = .78+.18*streaks+.1*F.fbm(.2, 2, 803)
        glass = colour*thickness[..., None]*(1-.25*seeds)[..., None]
        w = u*.01
        lead = np.maximum.reduce([
            np.where(in_border, 1-smooth(square_edge, w*.6, w), 1-smooth(quarry_edge, w*.6, w)),
            1-smooth(np.abs(depth-border)*u, w*.6, w),
            smooth(F.sdf, -u*.026, -u*.016)]) * coverage(F.sdf)
        lead_height = bevel(-np.abs(np.where(in_border, square_edge, quarry_edge))+w, w*.8)+bevel(F.sdf, u*.02)
        cy = np.bincount(ids.ravel() % table_size, F.yn.ravel(), table_size)/np.maximum(1, np.bincount(ids.ravel() % table_size, None, table_size))
        jitter = rng.uniform(-.06, .06, table_size)
        kindle = .36+.38*np.clip(1-cy[ids % table_size], 0, 1)+jitter[ids % table_size]
        return glass, lead, lead_height, kindle
    return F.memo('cathedral', build)


@recipe('cathedral-stained-glass', 'entrance', pad=1.)


def cathedral_glass(F, canvas, t, intensity):
    u = F.u
    glass, lead, lead_height, kindle = cathedral_window(F)
    inside = coverage(F.sdf)
    index, count = letters(F)
    # 1. In the dark, the lead came is laid letter by letter, a silver glint running along it.
    laid_at = .03+.3*(index+np.clip(F.yn, 0, 1)*.6)/max(1, count)
    laid = smooth(t-laid_at, 0, .04)
    glint = np.exp(-((t-laid_at-.03)/.012)**2)*lead
    # 2. Dawn rises behind the window; each pane kindles in turn, warm first, then its true colour.
    lit = smooth(t-kindle, 0, .1)
    sun_x = -.2+1.4*sm(t, .3, 1)
    flare = np.exp(-((F.xn-sun_x)/.35)**2-((F.yn-.2)/.6)**2)
    backlight = lit*(.75+.55*flare*(1-.5*sm(t, .85, 1)))
    dark = glass*.16
    grisaille = 1-.45*gaussian_filter(lead, u*.02)  # painted shading deepens each pane towards its lead
    light = glass*((.6+1.*backlight)*grisaille)[..., None]+rgb(255, 236, 190)*(flare*lit*.22)[..., None]
    pane = mix(dark, light, lit)
    pane = mix(pane, rgb(255, 210, 140), np.exp(-((t-kindle-.02)/.03)**2)*.5)
    canvas.over(np.zeros(3), shadow(inside, F, .03, .05, .04, .45*sm(t, .1, .4)))
    canvas.over(np.clip(pane, 0, 1), inside*sm(t, .02, .2)*(1-lead))
    canvas.add(bloom(glass*(inside*(1-lead)*backlight*.8)[..., None], F, .05, .8), .25)
    n = normals(lead_height)
    came = lit_came(n)
    canvas.over(np.clip(came, 0, 1), lead*laid)
    canvas.add(rgb(240, 244, 255)*glint[..., None]*1.4, .3)
    # 3. Coloured light streams out of the glass as god rays, dust motes drifting through it.
    rays_on = sm(t, .45, .7)*(1-.6*sm(t, .82, 1))
    if rays_on > 0:
        source = glass*(inside*(1-lead)*backlight)[..., None]
        rays = np.zeros_like(source)
        for k in range(1, 21):
            rays += shift(source, round(k*u*.055), round(k*u*.025))*(1-k/21)**1.2
        beams = .6+.4*(.5+.5*F.flow(.12, t, (.15, .4), 804, (.3, 2.)))
        canvas.add(blur(rays, u*.03)*beams[..., None]*.3*rays_on, .45)
        rng = np.random.default_rng(F.seed+805)
        motes = F.ink_points(220, 806)+np.stack((rng.uniform(0, u*.3, 220), rng.uniform(0, u*.6, 220)), 1)
        Particles(F, motes, rng.uniform(.4, .9, 220), np.stack((rng.normal(.05, .06, 220), rng.normal(.04, .05, 220)), 1),
                  drag=.5, life=rng.uniform(.25, .5, 220), size=1, color=rgb(255, 236, 190), glow=True, flicker=.4,
                  alpha=.7*rays_on).render(canvas, t)


def lit_came(n):
    """Lead came: dark grey metal with a soft sheen along its bevelled ridge."""
    return lit(rgb(64, 66, 72), n, sun(), ambient=.25)+specular(n, sun(), 30)[..., None]*.45
GRAPHITE = (46, 50, 58)


def sketch_plan(F):
    """Every stroke of an architectural sketch of the word as 3D blocks, in drawing order: construction
    lines, perspective boxes, front contours, extruded back contours and corner edges, then hatching.
    Each stroke is (points, weight, darkness, start, end, kind); times are fractions of the entrance."""
    def build():
        from skimage.measure import approximate_polygon, find_contours
        rng = np.random.default_rng(F.seed+900)
        u = F.u
        x0, y0, x1, y1 = F.box
        depth = np.array((u*.13, -u*.1))  # the extrusion runs back, up and to the right
        vanish = np.array((x1+u*3.5, y0-u*2.2))
        strokes = []

        def wobbly(a, b, overshoot=.12, jitter=.006):
            a, b = np.array(a, float), np.array(b, float)
            d = b-a
            a, b = a-d*rng.uniform(0, overshoot), b+d*rng.uniform(0, overshoot)
            n = max(2, int(np.linalg.norm(b-a)/(u*.08)))
            line = np.linspace(a, b, n)
            normal = np.array((-d[1], d[0]))/max(1e-6, np.linalg.norm(d))
            return line+normal*(rng.normal(0, u*jitter, n).cumsum()*.35)[:, None]

        # 1. construction: guide lines across the word, rays toward the vanishing point
        cap = y0
        for y in (y1, cap, y0+(y1-y0)*.45):
            strokes.append(['guide', wobbly((x0-u*.5, y), (x1+u*.5, y), .05)])
        index, count = letters(F)
        boxes = []
        for k in range(count):
            cols = np.nonzero((index[0] == k) & (F.ink.max(axis=0) > .3))[0]
            rows = np.nonzero(F.ink[:, cols].max(axis=1) > .3)[0] if len(cols) else []
            if len(cols) and len(rows):
                boxes.append((cols[0], rows[0], cols[-1], rows[-1]))
        for bx0, by0, bx1, by1 in boxes[::max(1, len(boxes)//3)]:
            strokes.append(['ray', wobbly((bx1, by0), vanish, 0, .003)])
        # 2. a perspective box around each letter
        for bx0, by0, bx1, by1 in boxes:
            front = [(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)]
            back = [tuple(np.array(p)+depth) for p in front]
            for a, b in zip(front, front[1:]+front[:1]):
                strokes.append(['box', wobbly(a, b)])
            for a, b in zip(back[:2], back[1:3]):
                strokes.append(['box', wobbly(a, b)])
            for a, b in ((front[0], back[0]), (front[1], back[1]), (front[2], back[2])):
                strokes.append(['box', wobbly(a, b)])
        # 3. front contours, then their extruded back and the corner edges joining them
        contours = [c[:, ::-1] for c in find_contours(F.ink, .5) if len(c) > 8]
        contours.sort(key=lambda c: c[:, 0].min())
        corners = []
        for contour in contours:
            jitter = rng.normal(0, u*.003, contour.shape)
            strokes.append(['contour', contour+jitter])
            strokes.append(['contour2', contour+rng.normal(0, u*.004, contour.shape)+u*.004])
            simple = approximate_polygon(contour, tolerance=u*.035)
            corners.extend(simple[:-1])
        for contour in contours:
            strokes.append(['back', contour+depth])
        for p in corners:
            strokes.append(['edge', wobbly(p, p+depth, .02, .002)])
        weights = {'guide': (.5, .35), 'ray': (.4, .25), 'box': (.6, .45), 'contour': (1.3, 1.), 'contour2': (.7, .55),
                   'back': (.8, .6), 'edge': (.8, .7)}
        windows = {'guide': (0., .16), 'ray': (.06, .2), 'box': (.12, .4), 'contour': (.32, .62), 'contour2': (.4, .66),
                   'back': (.5, .72), 'edge': (.56, .76)}
        plan = []
        for kind in ('guide', 'ray', 'box', 'contour', 'contour2', 'back', 'edge'):
            group = [s for s in strokes if s[0] == kind]
            start, end = windows[kind]
            span = (end-start)/max(1, len(group))
            for number, (_, points) in enumerate(group):
                begin = start+number*span
                plan.append((np.asarray(points, float), *weights[kind], begin, begin+span*1.6, kind))
        # 4. the extruded sides: the swept volume behind each letter, minus its front face
        swept = np.zeros_like(F.ink)
        for k in range(1, 13):
            swept = np.maximum(swept, shift(F.ink, round(depth[1]*k/12), round(depth[0]*k/12)))
        sides = np.clip(swept-F.ink, 0, 1)
        ground = np.clip(shift(gaussian_filter(F.ink, u*.02), round(u*.06), round(u*.12))-F.ink-sides, 0, 1)
        return plan, sides, ground
    return F.memo('sketch', build)


def hatching(F, angle, spacing, seed):
    """Parallel pencil hatching (0..1) at an angle, with slightly irregular pressure."""
    u = F.u
    coordinate = (F.px*math.cos(angle)+F.py*math.sin(angle))/(u*spacing)
    line = 1-smooth(np.abs((coordinate % 1)-.5)*2, .55, .85)
    return line*(.75+.25*F.noise(.04, seed))


@recipe('architectural-sketch', 'entrance', pad=1.)


def architectural_sketch(F, canvas, t, intensity):
    from PIL import Image, ImageDraw
    plan, sides, ground = sketch_plan(F)
    u = F.u
    sweep = np.clip(F.xn, 0, 1)
    shaded = smooth(t-.66-.2*sweep, 0, .08)
    # Shading after the line work: paper-toned faces, cross-hatched sides, a hatched cast shadow.
    face = mix(rgb(244, 238, 224), rgb(226, 218, 200), .5+.5*F.fbm(.05, 2, 901))*(1-.06*F.noise(.006, 902))[..., None]
    side_tone = np.clip(hatching(F, .9, .045, 903)+hatching(F, -.5, .06, 904)*.7, 0, 1)
    canvas.over(rgb(250, 246, 236), ground*shaded*.25)
    canvas.over(np.array(GRAPHITE)/255, ground*hatching(F, .9, .06, 905)*shaded*.55)
    canvas.over(rgb(236, 230, 214), sides*shaded*.85)
    canvas.over(np.array(GRAPHITE)/255, sides*side_tone*shaded*.9)
    canvas.over(face, coverage(F.sdf)*smooth(t-.6-.2*sweep, 0, .1))
    # The line work, drawn supersampled, stroke by stroke; construction lines fade back once shaded.
    f = 2
    lines = Image.new('L', (F.W*f, F.H*f))
    halo = Image.new('L', (F.W*f, F.H*f))
    ld, hd = ImageDraw.Draw(lines), ImageDraw.Draw(halo)
    tip = None
    for points, weight, darkness, begin, end, kind in plan:
        q = (t-begin)/(end-begin)
        if q <= 0:
            continue
        shown = points[:max(2, int(len(points)*min(1., q)))]
        if q < 1:
            tip = shown[-1]
        construction = kind in ('guide', 'ray', 'box')
        alpha = darkness*(1-.55*sm(t, .7, 1)*construction)
        width = max(1, round(weight*f*max(1., u/90)))
        path = [tuple(p*f) for p in shown]
        ld.line(path, fill=round(255*alpha), width=width)
        hd.line(path, fill=round(160*alpha), width=width+3*f)
    halo_a = np.asarray(halo.resize((F.W, F.H), Image.LANCZOS), dtype=float)/255
    line_a = np.asarray(lines.resize((F.W, F.H), Image.LANCZOS), dtype=float)/255
    canvas.over(rgb(250, 248, 240), gaussian_filter(halo_a, 1.)*.35)  # a pale halo keeps lines legible on dark scenes
    canvas.over(np.array(GRAPHITE)/255, np.clip(line_a*1.2, 0, 1))
    if tip is not None and t < .8:
        glint = np.exp(-((F.px-tip[0])**2+(F.py-tip[1])**2)/(u*.012)**2)
        canvas.add(np.ones(3)*glint[..., None]*.8, .5)
TIFFANY = (rgb(214, 150, 40), rgb(232, 196, 96), rgb(120, 140, 50), rgb(40, 130, 120), rgb(150, 30, 30), rgb(236, 226, 196),
           rgb(90, 60, 140))


import garden_recipes  # noqa: E402,F401  (registers the succulent garden and meadow grass recipes)
