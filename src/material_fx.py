"""Shared simulation kit for material lettering: words carved, poured, grown, burnt or blown out of real stuff.

Every frame is a pure function of (glyph, seed, progress). A recipe in material_recipes.py builds one frame
from the cached fields here: a signed distance to the glyph, value noise, Voronoi cells, height-field
shading per material, and analytic particles whose positions are solved in closed form rather than stepped.
Work happens at a capped resolution and is scaled back up, so large stage sprites stay affordable.
"""
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, gaussian_filter
from scipy.spatial import cKDTree

from particle_cache import sprite_key

WORK_HEIGHT = 150  # ink height the simulation runs at; larger sprites are scaled down, then back up


def smooth(value, low=0., high=1.):
    value = np.clip((np.asarray(value, dtype=float)-low)/np.maximum(1e-6, np.subtract(high, low)), 0, 1)
    return value*value*(3-2*value)


def sm(value, low=0., high=1.):
    """Scalar smoothstep."""
    value = max(0., min(1., (value-low)/max(1e-6, high-low)))
    return value*value*(3-2*value)


def mix(a, b, w):
    """Blend a to b; a per-pixel weight map also blends RGB images."""
    a, b, w = (np.asarray(v, dtype=float) for v in (a, b, w))
    colour = 3 in (a.shape[-1:]+b.shape[-1:])
    if w.ndim >= 2 and w.shape[-1] != 1 and (colour or max(a.ndim, b.ndim) == w.ndim+1):
        w = w[..., None]
    return a*(1-w)+b*w


def rgb(*value):
    return np.array(value, dtype=float)/255


class Field:
    """Glyph geometry and noise at working resolution; cached per sprite and seed."""

    def __init__(self, sprite, seed, pad):
        alpha = np.asarray(sprite.getchannel('A'), dtype=float)/255
        rows = np.nonzero(alpha.max(axis=1) > .3)[0]
        ink_h = (rows[-1]-rows[0]+1) if len(rows) else sprite.height
        self.scale = min(1., WORK_HEIGHT/max(1, ink_h))
        if self.scale < 1:
            size = (max(2, round(sprite.width*self.scale)), max(2, round(sprite.height*self.scale)))
            sprite = sprite.resize(size, Image.LANCZOS)
            alpha = np.asarray(sprite.getchannel('A'), dtype=float)/255
        self.sprite_size = sprite.size
        self.P = P = max(8, round(max(ink_h*self.scale, 12)*pad))
        self.ink = np.pad(alpha, P)
        source = np.asarray(sprite.convert('RGBA'), dtype=float)[..., :3]/255
        self.source = np.pad(source, ((P, P), (P, P), (0, 0)), mode='edge')
        self.H, self.W = self.ink.shape
        self.seed = seed
        inside = self.ink > .5
        sdf = distance_transform_edt(~inside)-distance_transform_edt(inside)
        self.sdf = gaussian_filter(sdf, .8).astype('float32')
        ys, xs = np.nonzero(inside)
        if not len(xs):
            ys, xs = np.array([self.H//2]), np.array([self.W//2])
        self.box = (xs.min(), ys.min(), xs.max()+1, ys.max()+1)
        self.u = max(6., (self.box[3]-self.box[1]))  # px per unit: the ink height
        self.cx, self.cy = (self.box[0]+self.box[2])/2, (self.box[1]+self.box[3])/2
        yy, xx = np.indices(self.ink.shape, dtype='float32')
        self.px, self.py = xx, yy
        self.X, self.Y = (xx-self.cx)/self.u, (yy-self.cy)/self.u
        self.xn = (xx-self.box[0])/max(1, self.box[2]-self.box[0])
        self.yn = (yy-self.box[1])/max(1, self.box[3]-self.box[1])
        self.inside_px = (ys, xs)
        self._memo = {}

    def memo(self, key, build):
        if key not in self._memo:
            self._memo[key] = build()
        return self._memo[key]

    def _value_noise(self, H, W, scale, seed, stretch):
        cell_x = max(1., scale*self.u*stretch[0])
        cell_y = max(1., scale*self.u*stretch[1])
        gw, gh = int(W/cell_x)+4, int(H/cell_y)+4
        rng = np.random.default_rng((self.seed*7919+seed*104729+int(scale*1000)) % 2**32)
        grid = rng.uniform(-1, 1, (gh, gw)).astype('float32')
        big = Image.fromarray(grid, 'F').resize((round(gw*cell_x), round(gh*cell_y)), Image.BICUBIC)
        out = np.asarray(big)[:H, :W]
        if out.shape != (H, W):
            out = np.pad(out, ((0, H-out.shape[0]), (0, W-out.shape[1])), mode='edge')
        return np.clip(out/.55, -1, 1)

    def noise(self, scale, seed=0, stretch=(1., 1.)):
        """Smooth value noise in [-1, 1]; scale in units, stretch elongates features along x / y."""
        return self.memo(('noise', scale, seed, stretch),
                         lambda: self._value_noise(self.H, self.W, scale, seed, stretch))

    def flow(self, scale, t, velocity, seed=0, stretch=(1., 1.)):
        """Noise that streams with `velocity` (units per unit of progress): a window sliding over a field
        twice the canvas size, so flames lick upward and smoke billows without any frame history."""
        big = self.memo(('flow', scale, seed, stretch),
                        lambda: self._value_noise(self.H*2, self.W*2, scale, seed+7000, stretch))
        ox = int(round(-velocity[0]*t*self.u)) % self.W
        oy = int(round(-velocity[1]*t*self.u)) % self.H
        return big[oy:oy+self.H, ox:ox+self.W]

    def fbm(self, scale, octaves=4, seed=0, stretch=(1., 1.), gain=.5):
        def build():
            total, amp, norm = 0., 1., 0.
            for octave in range(octaves):
                total = total+amp*self.noise(scale/2**octave, seed*31+octave, stretch)
                norm += amp
                amp *= gain
            return total/norm
        return self.memo(('fbm', scale, octaves, seed, stretch, gain), build)

    def cells(self, size, seed=0, jitter=1.):
        """Voronoi cells of `size` units: (id, distance to centre, distance to nearest edge, centres)."""
        def build():
            rng = np.random.default_rng((self.seed*31337+seed*977+int(size*1000)) % 2**32)
            step = max(3., size*self.u)
            gx, gy = np.meshgrid(np.arange(-step, self.W+step, step), np.arange(-step, self.H+step, step))
            points = np.stack((gx.ravel(), gy.ravel()), 1)+rng.uniform(-.5, .5, (gx.size, 2))*step*jitter
            dist, index = cKDTree(points).query(np.stack((self.px.ravel(), self.py.ravel()), 1), k=2)
            ids = index[:, 0].reshape(self.H, self.W).astype('int32')
            d1 = dist[:, 0].reshape(self.H, self.W).astype('float32')
            edge = ((dist[:, 1]-dist[:, 0])*.5).reshape(self.H, self.W).astype('float32')
            return ids, d1, edge, points
        return self.memo(('cells', size, seed, jitter), build)

    def distance_from(self, points, key):
        """Distance in units from a set of seed points (pixel coords)."""
        def build():
            seeds = np.zeros(self.ink.shape, bool)
            for px, py in points:
                seeds[min(self.H-1, max(0, int(py))), min(self.W-1, max(0, int(px)))] = True
            return (distance_transform_edt(~seeds)/self.u).astype('float32')
        return self.memo(('dist', key), build)

    def ink_points(self, count, seed=0):
        """Deterministic sample of pixel positions inside the glyph."""
        ys, xs = self.inside_px
        rng = np.random.default_rng(self.seed*13+seed)
        pick = rng.integers(0, len(xs), count)
        return np.stack((xs[pick], ys[pick]), 1).astype(float)

    def ink_spread(self, count, seed=0):
        """Seeds spread evenly across the glyph (one per letter-sized slot), for growth fronts."""
        ys, xs = self.inside_px
        order = np.argsort(xs+np.random.default_rng(self.seed+seed).uniform(0, self.u*.4, len(xs)))
        chunks = np.array_split(order, max(1, count))
        rng = np.random.default_rng(self.seed*3+seed)
        return [(xs[c[rng.integers(len(c))]], ys[c[rng.integers(len(c))]]) for c in chunks if len(c)]


# ---------------------------------------------------------------- shading

def normals(height, strength=1.):
    gy, gx = np.gradient(height*strength)
    n = np.stack((-gx, -gy, np.ones_like(height)), -1)
    return n/np.linalg.norm(n, axis=-1, keepdims=True)


def sun(azimuth=-2.3, elevation=.75):
    """Light direction (x right, y down, z toward viewer); default from the upper left."""
    c = math.cos(elevation)
    return np.array((math.cos(azimuth)*c, math.sin(azimuth)*c, math.sin(elevation)))


def lambert(n, light):
    return np.clip(n@light, 0, 1)


def specular(n, light, power):
    half = light+np.array((0, 0, 1.))
    half = half/np.linalg.norm(half)
    return np.clip(n@half, 0, 1)**power


def fresnel(n, base=.04):
    return base+(1-base)*(1-np.clip(n[..., 2], 0, 1))**5


def environment(n, horizon=(1., .93, .82), sky=(.55, .68, .86), ground=(.10, .08, .07), seed_band=0.):
    """Studio environment seen in a mirror: bright softbox above, dark floor, a hot horizon line."""
    r = 2*n[..., 2:3]*n-np.array((0, 0, 1.))
    up = -r[..., 1]
    side = r[..., 0]
    sky_c = np.array(sky)
    color = np.where((up > 0)[..., None], mix(np.array(horizon), sky_c, smooth(up, 0, .7)),
                     mix(np.array(horizon)*.6, np.array(ground), smooth(-up, 0, .35)))
    softbox = smooth(up, .45, .62)*smooth(-np.abs(side+.25), -.45, -.2)
    band = np.exp(-((up-.05-seed_band)/.05)**2)
    return color+softbox[..., None]*1.6+band[..., None]*.8


def blackbody(temp):
    """0 = cold dark red, .5 = orange, 1 = white-yellow; returns linear-ish RGB, can exceed 1 for bloom."""
    t = np.clip(np.asarray(temp, dtype=float), 0, 1.2)
    r = smooth(t, 0, .35)*1.15
    g = smooth(t, .25, .75)*.95
    b = smooth(t, .65, 1.05)*.85
    return np.stack((r, g, b), -1)*(.3+.9*t[..., None])


def bevel(sdf, width, sharp=False):
    """Height (px) of a bevelled solid: flat top, rounded or chamfered shoulders."""
    d = np.clip(-sdf/max(.5, width), 0, 1)
    return (d if sharp else np.sqrt(d*(2-d)))*width


def coverage(sdf, soft=.7):
    return np.clip(.5-sdf/max(.3, soft), 0, 1)


def shift(a, dy, dx):
    """Translate an image by whole pixels, filling with zeros instead of wrapping around."""
    out = np.zeros_like(a)
    H, W = a.shape[:2]
    dy, dx = int(dy), int(dx)
    if abs(dy) >= H or abs(dx) >= W:
        return out
    out[max(0, dy):H+min(0, dy), max(0, dx):W+min(0, dx)] = a[max(0, -dy):H-max(0, dy), max(0, -dx):W-max(0, dx)]
    return out


def shadow(cov, F, dx=.05, dy=.08, blur=.04, strength=.55):
    """Soft contact shadow of a covered region, offset away from the light."""
    s = gaussian_filter(cov, max(.6, blur*F.u))
    s = shift(s, round(dy*F.u), round(dx*F.u))
    return s*strength


def bloom(emissive, F, radius=.08, gain=1.):
    """Wide glow around bright emissive light; returns RGB to add."""
    return (blur(emissive, radius*F.u)*.7+blur(emissive, radius*3*F.u)*.5)*gain


def blur(image, sigma):
    """Gaussian blur of an (H, W, C) image; wide blurs run at reduced resolution, which they cannot show."""
    step = max(1, int(sigma/3))
    if step == 1:
        return np.stack([gaussian_filter(image[..., c], max(.5, sigma)) for c in range(image.shape[-1])], -1)
    H, W = image.shape[:2]
    small = image[::step, ::step]
    small = np.stack([gaussian_filter(small[..., c], sigma/step) for c in range(image.shape[-1])], -1)
    out = np.stack([np.asarray(Image.fromarray(small[..., c].astype('float32'), 'F').resize((W, H), Image.BILINEAR))
                    for c in range(image.shape[-1])], -1)
    return out


def warp(F, image, dx, dy):
    """Sample an image (H,W) or (H,W,C) at (x-dx, y-dy) with bilinear filtering."""
    from scipy.ndimage import map_coordinates
    coords = (F.py-dy, F.px-dx)
    if image.ndim == 2:
        return map_coordinates(image, coords, order=1, mode='constant')
    return np.stack([map_coordinates(image[..., c], coords, order=1, mode='nearest') for c in range(image.shape[2])], -1)


def ragged(F, amount=.025, seed=0):
    """The glyph's signed distance with a torn, irregular edge (burnt, eroded or broken)."""
    return F.sdf+F.u*(amount*F.fbm(.045, 3, seed+900)+amount*.3*F.noise(.02, seed+901))


def flames(F, fuel, t, reach=.32, seed=0, steps=9):
    """Flame density rising from `fuel` (0..1): fuel carried upward with falloff, then torn into
    flickering tongues by streaming turbulence. Feed the result to paint_fire."""
    fuel = blur(np.asarray(fuel, dtype=float)[..., None], F.u*.02)[..., 0]
    step = max(1., reach*F.u/steps)
    rise = fuel.copy()
    for k in range(1, steps+1):
        rise = np.maximum(rise, shift(fuel, -round(k*step), 0)*(1-k/(steps+1))**1.2)
    sway = F.flow(.12, t, (0., -2.5), seed+2)*F.u*.06+F.flow(.045, t, (0., -5.), seed+3)*F.u*.02
    rise = warp(F, rise, sway, 0)
    tongues = .65*F.flow(.08, t, (0., -4.5), seed, (.7, 1.6))+.35*F.flow(.035, t, (.3, -7.), seed+1, (.7, 1.6))
    return np.clip((rise*(.45+.8*(tongues*.5+.5))-.2)/.75, 0, 1)


def paint_fire(F, canvas, density, gain=1.):
    """Flames as light: a white-yellow core, orange body and red tips, with a soft glow around them."""
    hot = blackbody(.3+.8*density)*smooth(density, 0, .45)[..., None]*gain
    canvas.add(hot, .9)
    canvas.add(bloom(hot*.5, F, .05, .8), .3)


def smoke(F, source, t, rise=.8, seed=0, steps=10, drift=.25):
    """Rising smoke from `source` (0..1): carried upward and sideways, spreading and billowing as it goes."""
    # Puffs leave from patches of the source, not its whole shape, and spread as they climb, so the
    # smoke never echoes the letters above them.
    patches = smooth(F.flow(.1, t, (0., -1.), seed+3), -.2, .6)
    source = blur((np.asarray(source, dtype=float)*patches)[..., None], F.u*.03)[..., 0]
    step = rise*F.u/steps
    acc = np.zeros(F.sdf.shape)
    for k in range(steps+1):
        layer = shift(source, -round(k*step), round(k*step*drift))*(1-.6*k/steps)
        acc += blur(layer[..., None], F.u*(.02+.09*k/steps))[..., 0] if k % 3 == 0 else layer
    acc = blur(acc[..., None]/(steps*.6), F.u*.05)[..., 0]
    billow = .5+.5*F.flow(.14, t, (drift*.8, -1.6), seed)
    fine = .5+.5*F.flow(.05, t, (drift, -2.4), seed+1)
    curl = F.flow(.2, t, (0., -1.), seed+2)*F.u*.22
    return np.clip(warp(F, acc*(.3+1.*billow)*(.7+.5*fine), curl, 0)*1.9, 0, 1)


def paint_smoke(F, canvas, density, colour=(.32, .3, .3), opacity=.75):
    """Smoke lit from above: lighter billow tops, darker undersides."""
    gy = np.gradient(gaussian_filter(density, 2.), axis=0)
    light = np.clip(.75-gy*F.u*.6, .45, 1.2)
    canvas.over(np.clip(np.asarray(colour)*light[..., None], 0, 1), np.clip(density*opacity, 0, .92))


def rim(F, canvas, sdf, alpha=1., width=.028, colour=(.07, .05, .04)):
    """A bold dark outline outside the letter edge: legible on any background, graphic like an inked plate."""
    w = F.u*width
    band = smooth(sdf, -1., 0.)*(1-smooth(sdf, w*.7, w))
    canvas.over(np.asarray(colour), band*alpha)


# ---------------------------------------------------------------- canvas

class Canvas:
    """Premultiplied RGBA float image the recipe paints into, back to front."""

    def __init__(self, F):
        self.F = F
        self.c = np.zeros((F.H, F.W, 4))

    def over(self, color, alpha):
        alpha = np.clip(np.asarray(alpha, dtype=float), 0, 1)
        color = np.broadcast_to(np.asarray(color, dtype=float), self.c[..., :3].shape)
        self.c[..., :3] = color*alpha[..., None]+self.c[..., :3]*(1-alpha[..., None])
        self.c[..., 3] = alpha+self.c[..., 3]*(1-alpha)

    def distort(self, F, strength, t, seed=0):
        """Heat haze: shimmer everything painted so far where `strength` (0..1) is high."""
        if not np.any(strength > .01):
            return
        dx = F.flow(.05, t, (0., -3.), seed+40)*F.u*.014*strength
        dy = F.flow(.05, t, (.2, -3.), seed+41)*F.u*.01*strength
        self.c = warp(F, self.c, dx, dy)

    def darken(self, value):
        """Shade what is already painted, such as a leaf's shadow falling on a letter."""
        self.c[..., :3] *= 1-np.clip(value, 0, 1)[..., None]

    def add(self, color, coverage_gain=.6):
        """Additive light (glow); also makes the glow itself visible over transparent areas."""
        color = np.clip(color, 0, None)
        self.c[..., :3] += color
        self.c[..., 3] = np.clip(self.c[..., 3]+np.max(color, -1)*coverage_gain, 0, 1)

    def image(self):
        a = np.clip(self.c[..., 3:4], 0, 1)
        color = np.where(a > 1e-4, self.c[..., :3]/np.maximum(a, 1e-4), 0)
        out = np.concatenate((np.clip(color, 0, 1), a), -1)
        return Image.fromarray((out*255+.5).astype('uint8'), 'RGBA')


# ---------------------------------------------------------------- particles

class Particles:
    """Closed-form particles: position(age) = p0 + vt*age + (v0-vt)(1-e^(-k age))/k + swirl."""

    def __init__(self, F, origins, born, velocity, accel=(0., 0.), drag=1., life=.3, size=1., color=(1, 1, 1),
                 alpha=1., swirl=0., seed=0, glow=False, shape='dot', spin=0., fade_in=.02, cooling=False,
                 flicker=0., trail=.025):
        n = len(origins)
        self.F, self.n = F, n
        self.p0 = np.asarray(origins, dtype=float).reshape(n, 2)
        self.born = np.broadcast_to(np.asarray(born, dtype=float), (n,))
        self.v0 = np.broadcast_to(np.asarray(velocity, dtype=float), (n, 2))*F.u
        self.acc = np.broadcast_to(np.asarray(accel, dtype=float), (n, 2))*F.u
        self.k = np.broadcast_to(np.asarray(drag, dtype=float), (n,))
        self.life = np.broadcast_to(np.asarray(life, dtype=float), (n,))
        self.size = np.broadcast_to(np.asarray(size, dtype=float), (n,))
        self.color = np.broadcast_to(np.asarray(color, dtype=float), (n, 3))
        self.alpha = np.broadcast_to(np.asarray(alpha, dtype=float), (n,))
        rng = np.random.default_rng(F.seed*101+seed)
        self.phase = rng.uniform(0, math.tau, (n, 2))
        self.swirl = swirl*F.u
        self.glow, self.shape, self.spin, self.fade_in = glow, shape, spin, fade_in
        self.cooling, self.flicker, self.trail = cooling, flicker, trail
        self.angle0 = rng.uniform(0, math.tau, n)

    def at(self, age):
        k = self.k[:, None]
        vt = self.acc/k
        a = age[:, None]
        pos = self.p0+vt*a+(self.v0-vt)*(1-np.exp(-k*a))/k
        if self.swirl:
            pos = pos+self.swirl*np.sin(a*np.array((7., 5.))+self.phase)*np.minimum(1, a*4)
        return pos

    def render(self, canvas, t, time_scale=1.):
        age = (t-self.born)*time_scale
        live = (age > 0) & (age < self.life*time_scale)
        if not live.any():
            return
        idx = np.nonzero(live)[0]
        age = age[idx]
        life = self.life[idx]*time_scale
        rel = age/life
        fade = np.minimum(1, rel/max(1e-3, self.fade_in))*(1-smooth(rel, .55, 1))*self.alpha[idx]
        sub = self._subset(idx)
        color = self.color[idx]
        if self.cooling:  # white-hot at birth, through yellow and orange to a dull red as it dies
            color = blackbody(1.05-.85*rel)
        if self.flicker:
            fade = fade*(1-self.flicker+self.flicker*(.5+.5*np.sin(age*90+self.phase[idx, 0]*7)))
        if self.shape == 'streak':
            now = sub.at(age)
            before = sub.at(np.maximum(0, age-self.trail*time_scale))
            _streaks(canvas, before, now, self.size[idx], color, fade)
        elif self.shape == 'dot':
            for blur in (0., .012, .024):  # three motion-blur samples
                pos = sub.at(np.maximum(0, age-blur*time_scale))
                _splat(canvas, pos, self.size[idx], color, fade*(.55 if blur else 1.), self.glow)
        else:
            _shapes(canvas, sub.at(age), self.size[idx], color, fade,
                    self.angle0[idx]+self.spin*age, self.shape)

    def _subset(self, idx):
        sub = object.__new__(Particles)
        sub.F, sub.p0, sub.v0, sub.acc = self.F, self.p0[idx], self.v0[idx], self.acc[idx]
        sub.k, sub.phase, sub.swirl = self.k[idx], self.phase[idx], self.swirl
        return sub


def _splat(canvas, pos, size, color, alpha, glow):
    H, W = canvas.c.shape[:2]
    for radius in np.unique(np.clip(np.round(size), 1, 4)):
        pick = np.clip(np.round(size), 1, 4) == radius
        p, c, a = pos[pick], color[pick], alpha[pick]
        r = int(radius)
        for oy in range(-r+1, r):
            for ox in range(-r+1, r):
                fall = max(0., 1-(ox*ox+oy*oy)/(r*r)) if r > 1 else 1.
                x = np.round(p[:, 0]+ox).astype(int)
                y = np.round(p[:, 1]+oy).astype(int)
                ok = (x >= 0) & (x < W) & (y >= 0) & (y < H)
                w = (a*fall)[ok]
                if glow:
                    np.add.at(canvas.c[..., :3], (y[ok], x[ok]), c[ok]*w[:, None])
                    np.add.at(canvas.c[..., 3], (y[ok], x[ok]), w*.5)
                else:
                    cur = canvas.c[y[ok], x[ok]]
                    cur[:, :3] = c[ok]*w[:, None]+cur[:, :3]*(1-w[:, None])
                    cur[:, 3] = w+cur[:, 3]*(1-w)
                    canvas.c[y[ok], x[ok]] = cur
    np.clip(canvas.c[..., 3], 0, 1, out=canvas.c[..., 3])


def _streaks(canvas, start, end, size, color, alpha):
    """Motion-blurred sparks: bright lines from where each spark was a moment ago, with a soft glow."""
    H, W = canvas.c.shape[:2]
    layer = Image.new('RGB', (W, H))
    draw = ImageDraw.Draw(layer)
    for a, b, s, c, k in zip(start, end, size, color, alpha):
        if k <= .01:
            continue
        draw.line((a[0], a[1], b[0], b[1]), fill=tuple(int(min(255, v*255*k)) for v in c), width=max(1, int(round(s))))
    light = np.asarray(layer, dtype=float)/255
    if light.any():
        canvas.add(light+np.stack([gaussian_filter(light[..., c], 1.6) for c in range(3)], -1)*1.4, .7)


def _shapes(canvas, pos, size, color, alpha, angle, shape):
    """Chips, flakes and shards drawn as small shaded polygons."""
    H, W = canvas.c.shape[:2]
    layer = Image.new('RGBA', (W, H))
    draw = ImageDraw.Draw(layer)
    corners = {'chip': (0, 1.9, 2.8, 4.2, 5.3), 'flake': (0, .4, 3.1, 3.5), 'shard': (0, 2.5, 3.6)}[shape]
    radii = {'chip': (1, .8, 1.1, .7, .9), 'flake': (1.2, .5, 1.2, .5), 'shard': (1.4, .6, .9)}[shape]
    for (px, py), s, c, a, ang in zip(pos, size, color, alpha, angle):
        if a <= .01 or not (-20 < px < W+20 and -20 < py < H+20):
            continue
        squash = .35+.65*abs(math.cos(ang*1.7))  # tumbling in depth
        points = [(px+math.cos(ang+k)*s*r, py+math.sin(ang+k)*s*r*squash) for k, r in zip(corners, radii)]
        lit = .75+.35*math.cos(ang*1.7)
        fill = tuple(int(min(255, v*255*lit)) for v in c)+(int(255*min(1, a)),)
        draw.polygon(points, fill=fill)
    rgba = np.asarray(layer, dtype=float)/255
    canvas.over(rgba[..., :3], rgba[..., 3])


# ---------------------------------------------------------------- entry points

def field(sprite, seed, pad, cache):
    key = ('material-field-v1', sprite_key(sprite), seed, pad)
    if cache is not None and key in cache:
        return cache[key]
    result = Field(sprite, seed, pad)
    if cache is not None:
        cache[key] = result
    return result


def paint(layer, sprite, x, y, phase, t, effect, seed, intensity=1., cache=None):
    """Paint `effect` at progress t (entrance: 0 nothing .. 1 formed; exit: 0 intact .. 1 gone)."""
    from material_recipes import RECIPES
    recipe = RECIPES[effect.id]
    F = field(sprite, seed % 9973, recipe.get('pad', .6), cache)
    canvas = Canvas(F)
    t = max(0., min(1., t))
    recipe['paint'](F, canvas, t, intensity)
    # Every entrance starts from nothing and every exit ends with nothing, whatever is still in flight.
    canvas.c *= sm(t, 0, .05) if phase == 'entrance' else 1-sm(t, .88, 1)
    # Glows and rays fade out before the working canvas ends, so they never stop at a hard rectangle.
    border = np.minimum(np.minimum(F.px, F.W-1-F.px), np.minimum(F.py, F.H-1-F.py))
    canvas.c *= smooth(border, 0, max(3., F.P*.35))[..., None]
    image = canvas.image()
    if F.scale < 1:
        image = image.resize((round(image.width/F.scale), round(image.height/F.scale)), Image.BICUBIC)
    left = round(x-F.P/F.scale)
    top = round(y-F.P/F.scale)
    crop = (max(0, -left), max(0, -top), min(image.width, layer.width-left), min(image.height, layer.height-top))
    if crop[2] <= crop[0] or crop[3] <= crop[1]:
        return
    layer.alpha_composite(image.crop(crop), (left+crop[0], top+crop[1]))


def held(sprite, effect, seed, intensity=1., cache=None):
    """The finished entrance as a padded image, matching grown_sprite's (image, padding) contract."""
    key = ('material-held-v1', sprite_key(sprite), effect.id, seed, intensity)
    if cache is not None and key in cache:
        return cache[key]
    from material_recipes import RECIPES
    F = field(sprite, seed % 9973, RECIPES[effect.id].get('pad', .6), cache)
    padding = max(round(sprite.height*.7), math.ceil(F.P/F.scale)+2)  # room for anything grown above the word
    image = Image.new('RGBA', (sprite.width+2*padding, sprite.height+2*padding))
    paint(image, sprite, padding, padding, 'entrance', 1., effect, seed, intensity, cache)
    if cache is not None:
        cache[key] = (image, padding)
    return image, padding
