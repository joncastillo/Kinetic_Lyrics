"""Stone and metal: lettering that crumbles to dust, rusts apart or is eaten by acid."""

import math

import numpy as np

from effects.materials.fx import (
    Particles,
    bevel,
    bloom,
    coverage,
    mix,
    normals,
    rgb,
    shadow,
    shift,
    sm,
    smooth,
    specular,
    sun,
    warp,
)
from effects.materials.recipes.registry import recipe
from effects.materials.recipes.frost import paste
from effects.materials.recipes.common import (
    arrival,
    front_band,
    lit,
    plume,
    sample,
)


def stone_body(F, albedo, light=None, depth=0.05):
    n = normals(bevel(F.sdf, F.u * depth) + F.u * 0.006 * F.fbm(0.03, 2, 300))
    return lit(albedo, n, light if light is not None else sun()), n


def cell_debris(F, canvas, t, ids, centres, fall, colour, size, seed, gravity=10.0, spread=1.2, shape='chip',
                life=0.35, lift=(0.2, 1.5)):
    """Chunks that broke off at `fall` (per cell) tumble away under gravity."""
    inside = np.unique(ids[F.ink > 0.5])
    going = inside[(fall[inside] < t) & (t - fall[inside] < life)]
    if not len(going):
        return
    rng = np.random.default_rng(F.seed + seed)
    vx = rng.normal(0, spread, len(going))
    vy = -rng.uniform(*lift, len(going))
    cx = np.clip(centres[going, 0], 0, F.W - 1).astype(int)
    cy = np.clip(centres[going, 1], 0, F.H - 1).astype(int)
    chunks = Particles(
        F,
        centres[going],
        fall[going],
        np.stack((vx, vy), 1),
        accel=(0, gravity),
        drag=0.3,
        life=life,
        size=size * rng.uniform(0.7, 1.2, len(going)),
        color=colour[cy, cx],
        shape=shape,
        spin=25,
        fade_in=0,
    )
    chunks.render(canvas, t)


@recipe('dust-disintegrate', 'exit', pad=1.0)
def disintegrate(F, canvas, t, intensity):
    """The letters dry to a dusty tone, then a gust lifts them away from the left in long sweeping
    streamers of dust that keep the word's own colours."""
    u = F.u
    gone = 0.2 + 0.64 * np.clip(F.xn * 0.8 + (1 - F.yn) * 0.2, 0, 1) + 0.08 * F.fbm(0.05, 3, 340)
    r = gone - t
    # 1. The word dries out: a dusty, grainy tone spreads from the left and the first letter cracks.
    dry = smooth(t - 0.02 - 0.3 * np.clip(F.xn, 0, 1), 0, 0.12)
    dusty = mix(F.source, F.source * 0.5 + rgb(104, 90, 76) * 0.5, dry)
    speckle = smooth(F.noise(0.01, 343), 0.3, 0.9) * dry * 0.45
    _, _, edge, _ = F.cells(0.09, 344, jitter=0.9)
    crack = (1 - smooth(edge, 0, u * 0.012)) * smooth(0.12 - r, 0, 0.1) * dry
    body = dusty * (1 - speckle)[..., None]
    body = mix(body, rgb(40, 34, 30), crack * 0.8)
    sink = 0.2 * sm(t, 0.24, 0.5)  # the letters' feet pour away and the bottoms thin before the gust
    poured = smooth(1.02 - sink + 0.06 * F.fbm(0.04, 2, 349) - F.yn, 0, 0.03)
    canvas.over(np.clip(body, 0, 1), F.ink * smooth(r, 0, 0.008) * poured)
    lip = front_band(gone, t, 0.02) * F.ink
    canvas.over(np.clip(F.source * 1.15, 0, 1), lip * 0.5)
    origins = F.ink_points(4000, 341)  # a thinner cloud, so it reads as sand rather than smoke
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    rng = np.random.default_rng(F.seed + 342)
    dark = (rng.random(len(xs)) < 0.35)[:, None]  # a share of darker grains
    colour = np.where(dark, F.source[ys, xs] * 0.35 + rgb(40, 34, 30) * 0.3, mix(F.source[ys, xs], rgb(196, 168, 128), 0.35))  # sandy, not white
    dust = Particles(
        F,
        origins[:3000],
        gone[ys[:3000], xs[:3000]],
        np.stack((rng.uniform(0.8, 3.0, 3000), -rng.uniform(1.6, 4.0, 3000)), 1),  # rising and fanning up-right
        accel=(1.4, -2.2),
        drag=1.0,
        life=rng.uniform(0.3, 0.55, 3000),
        size=rng.choice((1, 1, 1, 2), 3000),
        color=colour[:3000],
        swirl=0.12,
    )
    dust.render(canvas, t)
    streaks = Particles(  # a share of the dust draws out into long wind streaks
        F,
        origins[3000:],
        gone[ys[3000:], xs[3000:]],
        np.stack((rng.uniform(1.4, 3.0, 1000), -rng.uniform(1.0, 2.2, 1000)), 1),
        accel=(1.8, -1.8),
        drag=0.9,
        life=rng.uniform(0.2, 0.4, 1000),
        size=1,
        color=np.clip(colour[3000:] * 0.6, 0, 1),
        shape='streak',
        trail=0.05,
    )
    streaks.render(canvas, t)
    # Before the gust, the dried letters start to run like an hourglass: sand trickles from their bottom edges.
    def build_feet():  # grains gathered into two or three narrow streams per letter, not a fringe
        foot = sample((F.ink > 0.5) & (shift(F.ink, -2, 0) < 0.3), 40, 346, F)
        r = np.random.default_rng(F.seed + 347)
        spouts = foot[r.choice(len(foot), min(len(foot), max(4, round((F.box[2] - F.box[0]) / F.u * 2.5))), replace=False)]
        pts = np.repeat(spouts, 70, 0)
        return pts + np.stack((r.normal(0, F.u * 0.014, len(pts)), np.zeros(len(pts))), 1)

    feet = F.memo('dust-feet-streams', build_feet)
    fx, fy = feet[:, 0].astype(int), feet[:, 1].astype(int)
    srng = np.random.default_rng(F.seed + 348)
    Particles(
        F,
        feet,
        np.minimum(gone[fy, fx] - 0.02, 0.12 + srng.uniform(0, 0.25, len(fx))),
        np.stack((srng.normal(0, 0.12, len(fx)), srng.uniform(0.1, 0.4, len(fx))), 1),  # a widening cone
        accel=(0, 16.0),  # the grains speed up as they fall
        drag=0.2,
        life=srng.uniform(0.2, 0.3, len(fx)),  # streams about 0.6 of a letter tall
        size=srng.choice((2, 2, 3), len(fx)),
        color=np.clip(F.source[fy, fx] * 0.95 + 0.08, 0, 1),
    ).render(canvas, t)
    # The gust also sweeps up the sand that fell: grains from below each letter join the plume as that letter goes.
    below = np.repeat(feet, 2, 0) + np.stack((srng.normal(0, F.u * 0.05, 2 * len(feet)), srng.uniform(F.u * 0.1, F.u * 0.45, 2 * len(feet))), 1)
    bx = below[:, 0].astype(int).clip(0, F.W - 1)
    Particles(
        F,
        below,
        gone[F.box[3] - 1, bx] if F.box[3] - 1 < F.H else gone[-1, bx],
        np.stack((srng.uniform(0.8, 3.0, len(bx)), -srng.uniform(1.6, 4.0, len(bx))), 1),
        accel=(1.4, -2.2),
        drag=1.0,
        life=srng.uniform(0.25, 0.45, len(bx)),
        size=srng.choice((1, 2), len(bx)),
        color=np.clip(np.repeat(F.source[fy, fx], 2, 0) * 0.9 + 0.05, 0, 1),
    ).render(canvas, t)

    if t < 0.95:  # the crumbling leaves a faint cloud in the word's own colours
        plume(
            F,
            canvas,
            t,
            front_band(gone, t, 0.06) * F.ink,
            np.clip(F.source.mean((0, 1)) * 0.5, 0, 1),
            0.35,
            0.5,
            1.6,
            738,
        )
    # The gust: before the dust lifts, the letters lean into the wind and shiver, tops first.
    lean = u * 0.13 * sm(t, 0.1, 0.24) + u * 0.012 * math.sin(t * 130) * sm(t, 0.1, 0.2) * (1 - sm(t, 0.3, 0.45))
    if lean > 0.3:
        canvas.c = warp(F, canvas.c, lean * np.clip(1 - F.yn, 0, 1.2), F.Y * 0)


RUST = (rgb(92, 40, 22), rgb(176, 78, 30), rgb(222, 128, 56))


@recipe('rust-corrode-crumble', 'exit', pad=1.0)
def rust(F, canvas, t, intensity):
    """Iron letters bloom with orange rust that spreads from scattered spots, weep rusty stains below, and
    then flake apart along the bloom's path."""
    u = F.u

    def build():
        ids, _, edge, centres = F.cells(0.07, 350, jitter=0.9)
        spread = arrival(F, 'rust', 0.7, 0.3)  # a pit or two per letter, blooming outward
        cell_rust = np.bincount(ids.ravel(), spread.ravel()) / np.maximum(1, np.bincount(ids.ravel()))
        fall = 0.52 + cell_rust * 0.3 + np.random.default_rng(F.seed + 351).uniform(-0.03, 0.04, ids.max() + 1)
        bottoms = ((F.ink > 0.5) & (shift(F.ink, -2, 0) < 0.3)).astype(float)
        feed = bottoms * smooth(F.noise(0.025, 356), 0.2, 0.7)
        return ids, edge, centres, spread, fall, feed

    ids, edge, centres, spread, fall, feed = F.memo('rust', build)

    def build_slabs():
        sids, _, sedge, _ = F.cells(0.3, 360, jitter=0.9)  # slabs about a quarter of the letter height
        n = sids.max() + 1
        rng = np.random.default_rng(F.seed + 361)
        inside = np.unique(sids[F.ink > 0.5])
        order = np.zeros(n)  # release order, top slabs first
        tops = np.array([np.nonzero(sids == k)[0].min() for k in inside])
        order[inside[np.argsort(tops, kind='stable')]] = np.linspace(0, 1, len(inside))  # top slabs go first
        sfall = 0.46 + 0.36 * order + rng.uniform(-0.02, 0.02, n)  # release spread over .46 to .82
        pieces = []
        for k in inside:
            ys, xs = np.nonzero((sids == k) & (F.ink > 0.02))
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            gap = smooth(sedge[y0:y1, x0:x1], u * 0.008, u * 0.02)  # a clean gap between broken slabs
            alpha = F.ink[y0:y1, x0:x1] * (sids[y0:y1, x0:x1] == k) * gap
            pieces.append((k, y0, y1, x0, x1, alpha, rng.normal(0, u * 1.6), rng.uniform(6, 14)))
        return sids, sedge, sfall, pieces

    sids, sedge, sfall, slabs = F.memo('rust-slabs', build_slabs)
    rusted = smooth(t - 0.22 - spread * 0.3 + 0.12 * F.fbm(0.04, 3, 352), 0, 0.05)  # ragged bloom edge
    texture = 0.5 + 0.5 * F.fbm(0.03, 4, 353)
    pits = smooth(F.noise(0.01, 357), 0.55, 0.9)
    iron, n = stone_body(F, rgb(150, 156, 164))
    iron = iron + specular(n, sun(), 40)[..., None] * 0.35
    oxide = lit(mix(RUST[0], mix(RUST[1], RUST[2], texture), texture * (1 - 0.5 * pits)), n, sun(), ambient=0.4)
    core = smooth(0.25 - spread, 0, 0.25) * rusted  # dark, deeply pitted cores where the rust began
    pitting = F.noise(0.1, 359)
    seeds = smooth(pitting, 0.6, 0.68) * sm(t, 0.15, 0.24)  # near-black pits show on their own first
    halo = smooth(pitting, 0.4, 0.6) * sm(t, 0.22, 0.36) * (1 - seeds)  # then grow orange halos
    oxide = mix(oxide, RUST[0] * 0.7, core * 0.7)
    oxide = mix(oxide, rgb(200, 92, 28), 0.35)  # a saturated orange-ochre rust
    body = mix(F.source, oxide, rusted)  # straight from the plain word into rust
    body = mix(body, RUST[2], halo * (1 - rusted) * 0.8)
    body = mix(body, rgb(40, 18, 10), seeds * 0.9)
    # Rust weeps from the bottom edges in streaks that lengthen as the corrosion spreads.
    reach = sm(t, 0.12, 0.7)
    weep = np.zeros(F.ink.shape)
    for k in range(1, 13):
        weep = np.maximum(weep, shift(feed * rusted, round(k * u * 0.04 * reach), 0) * (1 - k / 13))
    canvas.over(RUST[1] * 0.85, np.clip(weep, 0, 1) * 0.6 * (1 - F.ink))
    remaining = t < sfall[sids]
    cov = F.ink * remaining
    canvas.over(np.zeros(3), shadow(cov, F, 0.04, 0.06, 0.04, 0.35 * sm(t, 0, 0.12)))
    canvas.over(np.clip(body, 0, 1), cov)
    canvas.over(RUST[0] * 0.6, (1 - smooth(edge, 0, u * 0.01)) * cov * rusted * 0.6)
    # Broken slabs sag, then drop and tumble, still falling in the last frames.
    slab_rgb = np.clip(mix(np.clip(body, 0, 1), RUST[0] * 0.45, 1 - smooth(sedge, 0, u * 0.014)), 0, 1)
    for k, y0, y1, x0, x1, alpha, vx, spin in slabs:
        a = t - sfall[k]
        if a < 0:
            continue
        dy = round(u * 0.04 * sm(a, 0, 0.06) + 0.5 * u * 20 * max(0.0, a - 0.04) ** 2)
        fade = (1 - sm(a, 0.24, 0.4)) * (1 - sm(t, 0.92, 0.99))
        shade = 0.9 + 0.15 * np.cos(spin * a)
        floor = F.box[3] + u * 0.14 - y1 + (y1 - F.box[1]) * 0.7  # a loose heap that keeps the chunks apart
        if dy > floor:
            dy = round(floor - u * 0.08 * abs(np.sin((a - 0.2) * 14)) * np.exp(-(a - 0.2) * 6))
        paste(canvas, slab_rgb[y0:y1, x0:x1] * shade, alpha * fade, y0 + dy, x0 + round(vx * min(a, 0.3)))
    if t < 0.95:
        falling = (np.abs(sfall[sids] - t) < 0.03) * F.ink
        plume(F, canvas, t, falling, rgb(150, 80, 40), 0.4, -0.3, 0.2, 739)


ACID = rgb(168, 236, 60)


@recipe('acid-dissolve', 'exit', pad=0.9)
def acid(F, canvas, t, intensity):
    """Beads of acid land along the top of the word and sizzle, then run down through the letters, each eating a
    widening channel with a dark etched rim and a sour stain beside it, until only lace is left; the beads drip
    on below the word."""
    u = F.u

    def build():
        rng = np.random.default_rng(F.seed + 362)
        x0, y0, x1, y1 = F.box
        n = max(5, round((x1 - x0) / u * 4))
        xs = np.sort(x0 + (x1 - x0) * (np.arange(n) + rng.uniform(0.2, 0.8, n)) / n)
        t0 = 0.18 + 0.3 * rng.random(n)  # when each bead starts to run
        speed = (y1 - y0 + u * 0.6) / rng.uniform(0.2, 0.32, n)  # px per unit of progress
        width = rng.uniform(0.3, 0.55, n) * (x1 - x0) / n  # final half width of each channel
        return xs, t0, speed, width

    xs, t0, speed, width = F.memo('acid-runs', build)
    top = F.box[1] - u * 0.04
    eaten = np.zeros(F.ink.shape)
    rim = np.zeros(F.ink.shape)
    stain = np.zeros(F.ink.shape)
    beads = []
    for x, start, v, w_end in zip(xs, t0, speed, width):
        a = t - start
        if a < -0.1:
            continue
        if a <= 0:  # the bead lands on the top of the word and swells there before it runs
            beads.append((x, top, sm(a, -0.1, -0.06), 0.55 + 0.45 * sm(a, -0.1, 0)))
            continue
        front = top + v * a
        w = u * 0.03 + w_end * sm(a, 0.08, 0.6)  # the channel widens behind the bead
        wobble = u * 0.012 * np.sin(F.py / u * 18 + x)
        d = np.abs(F.px - x - wobble) - w
        behind = smooth(front - F.py, 0, u * 0.05)
        eaten = np.maximum(eaten, smooth(-d, 0, u * 0.02) * behind)
        rim = np.maximum(rim, np.exp(-((d / (u * 0.022)) ** 2)) * behind)
        stain = np.maximum(stain, smooth(u * 0.14 - d, 0, u * 0.12) * behind)
        beads.append((x, front, 1 - sm(front - F.box[3], u * 0.3, u * 0.7), 1.0))
    eaten = np.maximum(eaten, 1 - coverage(F.sdf + u * 0.09 * sm(t, 0.62, 0.92), 1.0))  # the lace thins away
    cov = F.ink * (1 - eaten)
    body = mix(F.source, rgb(38, 50, 30), stain * 0.7)  # a dark green-black stain beside the channels
    canvas.over(np.clip(body, 0, 1), cov)
    canvas.over(rgb(52, 32, 12), np.clip(rim * 2.4, 0, 1) * cov)  # the dark etched rim
    canvas.over(rgb(190, 214, 70), np.clip(rim - 0.55, 0, 1) * 2 * cov)
    for x, y, alpha, swell in beads:
        if alpha <= 0.01:
            continue
        r = u * 0.05 * swell
        dist = np.hypot(F.px - x, (F.py - y) * 0.8)
        drop = coverage(dist - r) * alpha
        canvas.over(rgb(52, 60, 16), coverage(dist - r * 1.3) * alpha * 0.9)
        canvas.over(rgb(110, 196, 60), drop * 0.85)
        canvas.add(bloom(ACID * (drop * 0.6)[..., None], F, 0.04, 0.8), 0.3)
    # The weakened letters slump: from about .45 the strokes stretch down and run as drips.
    slump = u * 0.7 * sm(t, 0.45, 0.78) * np.clip(F.yn + 0.2, 0, 1.6) * (0.7 + 0.3 * F.fbm(0.08, 2, 373))
    if slump.max() > 0.5:
        canvas.c = warp(F, canvas.c, F.X * 0, slump)
    if t < 0.95:  # caustic fumes curl off the etched edges
        plume(F, canvas, t, rim * cov * 0.9, rgb(160, 190, 90), 0.45, 0.7, 0.25, 740)
