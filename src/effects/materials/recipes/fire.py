"""Heat and light: molten, branded, burning, electric and glowing lettering."""

import math

import numpy as np
from scipy.ndimage import gaussian_filter

from effects.materials.fx import (
    Particles,
    bevel,
    blackbody,
    bloom,
    blur,
    coverage,
    lambert,
    flames,
    mix,
    normals,
    paint_fire,
    paint_smoke,
    ragged,
    rgb,
    shadow,
    shift,
    sm,
    smooth,
    smoke,
    specular,
    sun,
    warp,
)
from effects.materials.recipes.registry import recipe
from effects.materials.recipes.common import (
    front_band,
    grain,
    letters,
    lit,
    plume,
    rim_cover,
    sample,
    spark_burst,
)


@recipe('lava-flow-fill', 'entrance', pad=0.7)
def lava(F, canvas, t, intensity):
    """Molten rock pours down into each letter in turn, drips running ahead of the fill, then crusts over
    into cracked basalt whose seams keep glowing."""
    index, count = letters(F)
    drip = smooth(F.noise(0.03, 96)[int(F.cy)][None, :], 0.55, 0.8)  # some columns run ahead as drips
    depth = np.clip(F.yn, 0, 1.1)
    filled = -0.02 + 0.3 * index / max(1, count) + 0.3 * depth * (1 - 0.45 * drip) + 0.03 * F.fbm(0.3, 3, 90)
    age = t - filled
    swell = F.u * 0.02 * np.exp(-(((age - 0.04) / 0.035) ** 2))  # the fill line bulges, then settles
    cov = coverage(F.sdf - swell + F.u * 0.012 * F.fbm(0.04, 2, 91)) * smooth(age, -0.01, 0.01)
    _, _, edge, _ = F.cells(0.3, 92)
    crust = smooth(age, 0.04, 0.3)
    crack = (1 - smooth(edge / F.u, 0.012, 0.024 + 0.03 * (1 - crust))) * smooth(-F.sdf, F.u * 0.025, F.u * 0.05)
    heat = np.clip(1 - crust * 0.92, 0, 1) * (1 - crack) + crack * (0.55 + 0.45 * (1 - crust * 0.55))
    heat = heat * (0.9 + 0.1 * np.sin(F.fbm(0.08, 2, 93) * 6 + t * 20))
    heat = heat * (1 - 0.3 * crack * smooth(t - 0.74 - 0.16 * index / max(1, count), 0, 0.1))
    plate = 0.02 * smooth(edge / F.u, 0, 0.02)
    height = F.u * (0.06 * np.sqrt(np.clip(-F.sdf / (F.u * 0.06), 0, 1)) + plate * crust + 0.01 * F.fbm(0.03, 2, 94))
    n = normals(height)
    rock = lit(rgb(118, 110, 104) * grain(F, 0.2, 95)[..., None], n, sun()) + specular(n, sun(), 30)[..., None] * 0.15
    hot = blackbody(0.3 + 0.62 * heat) * 1.35  # saturated orange-yellow melt, never blown out to white
    body = mix(rock, hot, smooth(heat, 0.15, 0.7))
    front = smooth(0.05 - np.abs(age), 0, 0.05) * cov  # the advancing lip runs yellow-hot
    body = mix(body, blackbody(0.92) * 1.3, front * 0.8)
    body = mix(body, rgb(40, 30, 28), front * smooth(F.sdf, -F.u * 0.03, -F.u * 0.01) * 0.6)  # dark crust lip
    canvas.over(np.zeros(3), shadow(cov, F, 0.05, 0.08, 0.05, 0.5))
    canvas.over(np.clip(body, 0, 1), cov)
    canvas.add(bloom(hot * (cov * smooth(heat, 0.2, 0.9))[..., None], F, 0.05, 0.6))
    canvas.add(bloom(blackbody(0.85) * front[..., None], F, 0.08, 1.2), 0.3)

    if t < 0.97:  # the fresh flow burns, smokes and throws embers until its crust closes
        burning = cov * smooth(heat, 0.45, 0.9)
        paint_fire(F, canvas, flames(F, burning * (1 - sm(t, 0.75, 0.95)), t, 0.3, 709), 0.8)
        plume(F, canvas, t, cov * smooth(heat, 0.2, 0.7) * 0.6, rgb(88, 74, 70), 0.4, 0.9, 0.2, 710)
        canvas.distort(
            F, np.clip(shift(blur(burning[..., None], F.u * 0.06)[..., 0], -round(F.u * 0.12), 0) * 2.5, 0, 1), t
        )
        rng = np.random.default_rng(F.seed + 711)
        lift = F.ink_points(160, 712)
        Particles(
            F,
            lift,
            rng.uniform(0.05, 0.8, 160),
            np.stack((rng.normal(0, 0.3, 160), -rng.uniform(0.5, 1.3, 160)), 1),
            accel=(0, -1.0),
            drag=1.2,
            life=rng.uniform(0.08, 0.18, 160),
            size=rng.choice((1, 2), 160),
            glow=True,
            cooling=True,
            flicker=0.6,
            swirl=0.05,
        ).render(canvas, t)
    rim_cover(F, canvas, cov, sm(t, 0.5, 1), colour=(0.08, 0.05, 0.04))


NEON = (rgb(255, 70, 160), rgb(30, 180, 255), rgb(170, 255, 80), rgb(255, 170, 60))
NEON_HALO = (rgb(150, 60, 255), rgb(40, 80, 255), rgb(30, 200, 170), rgb(255, 60, 40))  # two-tone glow


@recipe('neon-tube-ignite', 'entrance', pad=0.7)
def neon(F, canvas, t, intensity):
    """Dead glass tubes trace the letters, then strike alight one by one, each stuttering and spitting at its
    electrodes before it holds, in a hue that changes from word to word."""
    index, count = letters(F)
    tube_d = np.abs(F.sdf + F.u * 0.05)
    radius = F.u * 0.026
    tube = coverage(tube_d - radius)
    across = np.clip(tube_d / radius, 0, 1)
    cyl = np.sqrt(1 - across**2)
    rng = np.random.default_rng(F.seed + 190)
    starts = 0.26 + 0.48 * np.arange(count) / max(1, count) + rng.uniform(-0.03, 0.03, count)
    # First the dead glass is bent on: a tracing tip runs round each letter from the top, letter after letter.
    draws = 0.02 + 0.2 * np.arange(count) / max(1, count)
    sweep = neon_sweep(F, index, count)
    traced = np.clip((t - draws) / 0.16, 0, 1)[index.astype(int)] * 1.03
    drawn = smooth(traced - sweep, 0, 0.03)
    head = np.exp(-(((traced - sweep) / 0.04) ** 2)) * (traced < 1.02) * (traced > 0)
    frame = math.floor(t * 48)
    hashes = (np.sin((frame + np.arange(count) * 7.3) * 12.9898) * 43758.5453) % 1
    lit_letter = np.clip((t - starts) / 0.14, 0, 1)
    stutter = 0.3 + 0.7 * (hashes > 0.45) * (0.4 + 0.6 * lit_letter)
    on = np.where(lit_letter >= 1, 1.0, np.where(lit_letter > 0, stutter, 0.0))
    mid = count // 2
    if count > 2 and 0.2 < t - starts[mid] < 0.3:  # one tube drops out for a couple of frames
        on[mid] = 0.15
    late = max(0, count // 3)
    if count > 1 and 0.68 < t < 0.75:  # one more tube stutters late, so the relay does not end too early
        on[late] = 0.2
    glow_on = on[index.astype(int)]
    strike = np.exp(-(((t - starts - 0.03) / 0.05) ** 2))[index.astype(int)]
    hue = NEON[F.seed % len(NEON)]
    glass_off = (
        rgb(120, 130, 140) * (0.4 + 0.6 * cyl)[..., None]
        + specular(np.stack((F.X * 0, F.Y * 0 + (-across), cyl), -1), sun(), 20)[..., None] * 0.4
    )
    core = mix(hue, np.ones(3), cyl**3 * 0.85)
    surge = math.exp(-(((t - 0.47) / 0.05) ** 2))  # every letter overbrights together for a few frames
    present = tube * drawn
    canvas.over(np.zeros(3), shadow(tube * drawn, F, 0.03, 0.05, 0.03, 0.3) * (1 - glow_on))
    canvas.over(rgb(36, 40, 48), coverage(tube_d - radius * 1.7) * drawn * 0.85)  # dark glass casing
    canvas.over(mix(glass_off, core, glow_on), present)
    backing = coverage(F.sdf) * (1 - tube) * smooth(traced, 0.9, 1.03)
    canvas.over(mix(rgb(18, 14, 26), hue * 0.95, glow_on), backing * (0.85 + 0.15 * glow_on))  # lit gas fill
    if surge > 0.02:
        canvas.over(np.ones(3), coverage(F.sdf) * surge * 0.9)  # near-white
        canvas.add(bloom(hue * (coverage(F.sdf) * surge)[..., None], F, 0.2, 2.6), 0.5)
    halo = NEON_HALO[F.seed % len(NEON_HALO)]
    canvas.add(bloom(hue * (tube * glow_on * (1 + 1.5 * strike))[..., None], F, 0.06, 1.2))
    canvas.add(bloom(halo * (tube * glow_on)[..., None], F, 0.16, 1.4))  # a wide halo in a second hue
    canvas.add(hue * (gaussian_filter(coverage(F.sdf), F.u * 0.03) * glow_on * 0.25)[..., None])
    canvas.over(np.ones(3), coverage(F.sdf) * strike * 0.8)  # the strike flash, brighter than the hold
    canvas.add(bloom(hue * (coverage(F.sdf) * strike)[..., None], F, 0.16, 2.2), 0.4)

    rim_cover(F, canvas, present, 1.0, 0.02, (0.05, 0.05, 0.07))
    pen = head * coverage(tube_d - radius * 2.6)
    canvas.add(np.ones(3) * pen[..., None] + bloom(hue * pen[..., None], F, 0.1, 2.4), 0.6)  # the tracing tip
    if t < 0.9:  # each tube sparks at its electrodes as it strikes
        for k in range(count):
            if 0 < t - starts[k] < 0.14:
                tips = sample((index == k) * tube > 0.6, 18, 721 + k, F)
                spark_burst(
                    F,
                    canvas,
                    t,
                    tips,
                    t - 0.008,
                    722 + k * 13 + int(t * 90),
                    1.8,
                    1.8,
                    9.0,
                    (0.02, 0.05),
                    False,
                    np.clip(hue * 0.6 + 0.4, 0, 1),
                )


def neon_sweep(F, index, count):
    """Per pixel, how far round its letter (0..1, clockwise from the top) the tube is, for the draw-on."""

    def build():
        ys, xs = np.nonzero(F.ink > 0.5)
        k = index[ys, xs].astype(int)
        cx = np.bincount(k, xs, count) / np.maximum(1, np.bincount(k, minlength=count))
        cy = np.bincount(k, ys, count) / np.maximum(1, np.bincount(k, minlength=count))
        ids = index.astype(int)
        angle = np.arctan2(F.px - cx[ids], -(F.py - cy[ids]))  # 0 at the top, growing clockwise
        return (angle / (2 * np.pi)) % 1

    return F.memo('neon-sweep', build)


BRAND_PRESS = 0.04


@recipe('branding-iron-scorch', 'entrance', pad=1.0)
def brand(F, canvas, t, intensity):
    """A white-hot iron presses down onto the board, flames and smoke boil off, and the letters are left as
    charred wood with embers still glowing in the cracks."""
    u = F.u

    def build():
        edge = ragged(F, 0.03, 200)  # the burnt outline is torn and irregular, never the clean glyph
        depth = np.clip(-edge / (u * 0.09), 0, 1)
        creep = 0.32 + 0.4 * depth**0.8 + 0.1 * F.fbm(0.05, 3, 201)  # charcoal creeps in from the edges
        _, _, cells, _ = F.cells(0.05, 202, jitter=0.9)
        crack = (1 - smooth(cells, 0, u * 0.008)) * (depth > 0.12)
        singe = np.exp(-np.clip(edge, 0, None) / (u * (0.035 + 0.025 * (0.5 + 0.5 * F.fbm(0.08, 2, 203))))) * (edge > 0)
        grain = F.fbm(0.015, 3, 204)
        sparks = edge_points(F, edge, 240, 205)
        risers = F.ink_points(300, 206)
        return edge, depth, creep, crack, singe, grain, sparks, risers

    edge, depth, creep, crack, singe, grain, spark_at, riser_at = F.memo('brand', build)
    # The iron comes down on the whole word at once (a hair later per letter), then lifts.
    index, count = letters(F)
    since = t - (BRAND_PRESS + 0.05 * index / max(1, count))
    press = smooth(since, 0, 0.03)
    cov = coverage(edge) * press
    flash_heat = 1 - smooth(since, 0.06, 0.22)
    core_edge = 0.15 + 0.85 * sm(t, 0.26, 0.7)  # the hot core shrinks from the outline inward over .3-.7
    core = smooth(depth, core_edge, core_edge + 0.15) * (1 - sm(t, 0.68, 0.8)) * smooth(since, 0.02, 0.08)
    iron = np.maximum(flash_heat, core * 0.85)
    scorch = smooth(since, 0.04, 0.26)
    charred = smooth(t - creep, 0, 0.05)
    front = np.exp(-(((t - creep) / 0.035) ** 2))
    embers = crack * charred * 0.7 * np.exp(-np.clip(t - creep, 0, None) / 0.12)  # die out to a flat char
    rim_glow = smooth(edge, -u * 0.06, -u * 0.012) * (1 - smooth(edge, -u * 0.004, 0)) * charred * 1.4
    temp = np.clip(iron + front * 0.55 + embers * 0.5 + rim_glow * 0.4, 0, 1.1)

    # The singed board around the letters browns, then darkens.
    canvas.over(rgb(92, 48, 18), singe * scorch * 0.6 * press)
    canvas.over(rgb(24, 16, 12), singe**2 * sm(t, 0.3, 0.9) * 0.65)

    height = -0.6 * bevel(edge, u * 0.05) + u * 0.006 * grain - u * 0.012 * crack * charred
    n = normals(height)
    wood = mix(rgb(176, 112, 60), rgb(120, 64, 28), scorch)
    wood = mix(wood, rgb(70, 34, 16), smooth(1 - depth, 0.3, 1) * scorch)
    coal = mix(rgb(30, 22, 20), rgb(58, 46, 42), 0.5 + 0.2 * grain)  # clean dark char, little grain
    body = lit(mix(wood, coal, charred), n, sun(), ambient=0.4) + (specular(n, sun(), 16) * 0.25 * charred)[..., None]
    body = mix(body, blackbody(temp) * 1.3, smooth(temp, 0.08, 0.5))
    finish = sm(t, 0.62, 0.82)  # the last third settles to a clean, solid char
    flat = rgb(132, 66, 30) * (0.85 + 0.3 * lambert(n, sun()))[..., None]
    body = mix(body, flat, finish)
    canvas.over(np.zeros(3), shadow(cov, F, 0.03, 0.05, 0.03, 0.4))
    canvas.over(np.clip(body, 0, 1), cov)
    ember_rim = smooth(edge, -u * 0.05, -u * 0.016) * (1 - smooth(edge, -u * 0.004, 0)) * finish
    canvas.over(mix(rgb(255, 150, 50), rgb(255, 128, 48), sm(t, 0.82, 1)), ember_rim * cov)
    ash = smooth(edge, -u * 0.016, -u * 0.004) * (1 - smooth(edge, -u * 0.002, 0)) * charred * (1 - finish)
    canvas.over(rgb(184, 178, 170) * (0.8 + 0.3 * grain[..., None]), ash * cov * 0.9)
    canvas.add(bloom(blackbody(temp) * (temp * cov * (1 - 0.7 * finish))[..., None], F, 0.05, 0.7))
    flash = np.exp(-(((t - 0.2) / 0.045) ** 2)) * cov  # the press: a white flash on contact, three or four frames
    canvas.over(np.ones(3), flash * 0.85)
    canvas.add(bloom(blackbody(1.0) * flash[..., None], F, 0.035, 1.0), 0.5)  # a crisp slam

    if t < 0.98:
        burning = (1 - smooth(since, 0.3, 0.55)) * smooth(since, 0.02, 0.1)
        fuel = cov * ((0.3 + 0.5 * (1 - depth)) * burning + front * 0.45 * (1 - sm(t, 0.78, 0.95)))
        source = cov * ((1 - depth) * smooth(since, 0.04, 0.12) * (1 - smooth(since, 0.45, 0.8)) * 0.6 + front * 0.35)
        paint_smoke(F, canvas, smoke(F, source, t, 0.9, 210), (0.3, 0.28, 0.27), 0.55)
        canvas.distort(F, np.clip(shift(blur(fuel[..., None], u * 0.06)[..., 0], -round(u * 0.12), 0) * 3, 0, 1), t)
        paint_fire(F, canvas, flames(F, fuel, t, 0.34, 211), 0.9)
        rng = np.random.default_rng(F.seed + 212)
        n_ = len(spark_at)
        out = np.stack((rng.normal(0, 1.6, n_), -rng.uniform(0.8, 3.0, n_)), 1)
        Particles(
            F,
            spark_at,
            BRAND_PRESS + 0.02 + rng.uniform(0, 0.12, n_),  # sparks spit as the iron lands
            out,
            accel=(0, 7.0),
            drag=0.8,
            life=rng.uniform(0.05, 0.13, n_),
            size=rng.choice((1, 1, 2), n_),
            shape='streak',
            cooling=True,
            trail=0.02,
        ).render(canvas, t)
        m_ = len(riser_at)
        Particles(
            F,
            riser_at,
            rng.uniform(0.15, 0.75, m_),
            np.stack((rng.normal(0, 0.25, m_), -rng.uniform(0.4, 1.2, m_)), 1),
            accel=(0.2, -1.4),
            drag=1.2,
            life=rng.uniform(0.1, 0.24, m_),
            size=rng.choice((1, 2), m_),
            glow=True,
            cooling=True,
            flicker=0.6,
            swirl=0.05,
        ).render(canvas, t)
    # The iron slams the word down: in large, squashed under on contact, then springs back to size.
    if t < 0.2:
        k = sm(t, 0.1, 0.2) ** 2  # hangs large, then slams, landing exactly on the squash
        sx, sy = 1.3 - 0.2 * k, 1.3 - 0.46 * k
    else:  # the stamp: squashed flat and wide on contact, a small stretch back, then to size
        k = sm(t, 0.2, 0.36)
        wave = np.cos(k * np.pi * 1.5) * (1 - k)
        sx, sy = 1 + 0.1 * wave, 1 - 0.16 * wave
    if abs(sx - 1) > 1e-3 or abs(sy - 1) > 1e-3:
        canvas.c = warp(F, canvas.c, (F.px - F.cx) * (1 - 1 / sx), (F.py - F.box[3]) * (1 - 1 / sy))


@recipe('moss-overgrowth', 'entrance', pad=0.6)
def moss(F, canvas, t, intensity):
    """Moss climbs the letters from the baseline, some runs racing ahead as tendrils, thickens into a velvet
    pile with a crisp pale edge, then dew beads and tiny flowers open across it."""
    runs = smooth(F.noise(0.025, 212)[int(F.cy)][None, :], 0.45, 0.8)  # columns that race ahead as tendrils
    born = 0.78 * np.clip(1 - F.yn, 0, 1) * (1 - 0.55 * runs) + 0.12 * F.fbm(0.05, 2, 213) + 0.05
    clumps = F.fbm(0.12, 3, 210)
    fine = F.noise(0.01, 211)
    q = smooth(t + 0.02 - born * 0.7, 0, 0.22)
    fuzz = F.u * (0.03 * fine + 0.025 * clumps)
    # Young moss overgrows the letter edges in lumpy fronds, then pulls back to the outline as it settles.
    extra = F.u * 0.1 * smooth(q, 0, 0.5) * (0.6 + 0.4 * clumps) * (1 - sm(t, 0.66, 0.86))
    cov = coverage(F.sdf + fuzz + F.u * 0.06 * (1 - q) - extra) * smooth(q, 0, 0.3)
    height = F.u * (0.07 * np.sqrt(q) * (0.6 + 0.4 * clumps) + 0.015 * fine) + bevel(F.sdf, F.u * 0.05)
    n = normals(height)
    tips = smooth(clumps + 0.4 * fine, 0.1, 0.9)
    band = np.floor(np.clip(tips, 0, 0.999) * 3) / 2  # three flat tones, graphic rather than photographic
    albedo = mix(rgb(70, 132, 40), rgb(206, 238, 92), band) * mix(np.ones(3), rgb(210, 220, 120), (1 - q) * 0.5)
    # Flat graphic shading: the tone bands with only a soft top light, no photographic grain.
    body = albedo * (0.9 + 0.2 * np.clip(-n[..., 1] * 3 + 0.5, 0, 1))[..., None]
    canvas.over(np.zeros(3), shadow(cov, F, 0.04, 0.06, 0.04, 0.4))
    canvas.over(np.clip(body, 0, 1), cov)
    # The creeping front is a paler, younger green.
    young = smooth(0.1 - np.abs(q - 0.5), 0, 0.1) * cov
    canvas.over(rgb(196, 230, 110), young * 0.35)

    rim_cover(F, canvas, cov, sm(t, 0.6, 1), colour=(0.06, 0.1, 0.03))
    edge = smooth(F.sdf, -F.u * 0.03, -F.u * 0.012) * (1 - smooth(F.sdf, -F.u * 0.008, 0)) * cov
    canvas.over(rgb(206, 240, 130), edge * sm(t, 0.62, 0.9) * 0.85)  # a crisp pale edge on the finished word
    dew = smooth(F.noise(0.012, 723), 0.86, 0.95) * cov * sm(t, 0.7, 0.95)  # morning dew beads on the moss
    canvas.add(np.ones(3) * (dew * specular(normals(F.u * 0.02 * dew), sun(), 30) * 1.5)[..., None], 0.3)
    bloom_t = sm(t, 0.74, 0.96)
    if bloom_t > 0:  # tiny flowers open across the moss
        _, d1, _, _ = F.cells(0.13, 724, jitter=1.0)
        petal_r = F.u * 0.08 * bloom_t
        flower = smooth(petal_r - d1, 0, F.u * 0.006) * smooth(F.noise(0.05, 725), 0.3, 0.6) * (F.ink > 0.5)
        centre = smooth(petal_r * 0.4 - d1, 0, F.u * 0.006) * flower
        canvas.over(rgb(255, 150, 196), flower)
        canvas.over(rgb(236, 170, 60), centre)


def bolt(rng, start, end, jag, steps=14):
    """A jagged lightning path between two points."""
    points = []
    for k in range(steps + 1):
        f = k / steps
        x = start[0] + (end[0] - start[0]) * f
        y = start[1] + (end[1] - start[1]) * f
        wobble = jag * math.sin(f * math.pi)
        points.append((x + rng.normal(0, wobble), y + rng.normal(0, wobble * 0.3)))
    return points


@recipe('paper-burn', 'exit', pad=0.9)
def paper_burn(F, canvas, t, intensity):
    """The paper browns ahead of a bright ember edge that eats the letters from one corner, curling ash flakes
    and smoke lifting off the burn."""

    def build():
        ys, xs = F.inside_px
        lows = [
            (xs[i], ys[i]) for i in np.argsort(-ys - np.random.default_rng(F.seed).uniform(0, F.u * 0.6, len(ys)))[:1]
        ]
        lows.append((xs[np.argmin(xs)], ys[np.argmin(xs)]))
        d = F.distance_from(lows, 'burn') + 0.12 * F.fbm(0.08, 4, 310)
        inside = F.ink > 0.3
        d = (d - d[inside].min()) / max(1e-3, np.ptp(d[inside]))
        return 0.1 + 0.78 * d

    burn = F.memo('paper-burn', build)
    r = burn - t
    scorch = smooth(0.32 - r, 0, 0.3)
    paper = mix(F.source, rgb(104, 56, 20), scorch * 0.9)
    char = smooth(-r, 0, 0.03)
    body = mix(paper, rgb(26, 20, 18), char)
    present = F.ink * smooth(r + 0.06 + 0.03 * F.fbm(0.03, 2, 311), 0, 0.01)
    canvas.over(np.clip(body, 0, 1), present)
    rim = np.exp(-((r / 0.04) ** 2)) * F.ink
    ember = blackbody(rim * 0.85 + 0.1) * rim[..., None] * 2.0
    canvas.add(ember + bloom(ember, F, 0.06, 1.0))
    sparks_on = smooth(F.noise(0.01, 312), 0.5, 0.9) * np.exp(-(((r + 0.03) / 0.015) ** 2)) * F.ink
    canvas.add(blackbody(sparks_on * 0.7) * sparks_on[..., None])
    origins = F.ink_points(500, 313)
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    rng = np.random.default_rng(F.seed + 314)
    ash = Particles(
        F,
        origins,
        burn[ys, xs] + 0.04,
        np.stack((rng.normal(0.2, 0.3, len(xs)), -rng.uniform(0.4, 1.2, len(xs))), 1),
        accel=(0.6, -1.8),
        drag=1.6,
        life=rng.uniform(0.15, 0.32, len(xs)),
        size=F.u * rng.uniform(0.06, 0.12, len(xs)),
        color=mix(rgb(40, 36, 34), rgb(120, 110, 104), rng.uniform(0, 1, (len(xs), 1))),
        shape='flake',
        spin=14,
        swirl=0.08,
    )
    ash.render(canvas, t)
    smoke_p = Particles(
        F,
        origins[:200],
        burn[ys[:200], xs[:200]],
        np.stack((rng.normal(0, 0.1, 200), -rng.uniform(0.3, 0.7, 200)), 1),
        accel=(0.3, -0.8),
        drag=1.2,
        life=0.3,
        size=4,
        color=rgb(150, 145, 140),
        alpha=0.18,
        swirl=0.1,
    )
    smoke_p.render(canvas, t)

    if t < 0.97:  # the burning edge carries real flame and smoke
        edge_fire = np.exp(-(((r + 0.012) / 0.02) ** 2)) * F.ink
        plume(F, canvas, t, edge_fire * 0.9, rgb(70, 64, 60), 0.55, 0.9, 0.3, 731)
        paint_fire(F, canvas, flames(F, edge_fire, t, 0.3, 732), 0.9)
        spark_burst(
            F,
            canvas,
            t,
            sample(edge_fire > 0.6, 40, 733 + int(t * 70), F),
            t - 0.01,
            734 + int(t * 70),
            1.5,
            1.0,
            2.0,
            (0.03, 0.07),
        )


@recipe('lightning-vaporize', 'exit', pad=1.1)
def vaporize(F, canvas, t, intensity):
    """Bolts strike the letters one after another; each struck letter flashes, crawls with arcs as plasma, and
    boils away into sparks and vapour."""
    from PIL import Image, ImageDraw

    u = F.u
    index, count = letters(F)
    rng = np.random.default_rng(F.seed + 420)
    strikes = sorted(rng.uniform(0.22, 0.44, count + 1))
    targets = F.ink_spread(count + 1, 421)
    hit = np.full(F.ink.shape, 9.0)
    for when, (tx, ty) in zip(strikes, targets):
        hit = np.minimum(hit, when + F.distance_from([(tx, ty)], ('strike', tx, ty)) * 0.2)  # a slower ring
    charge = smooth(t - hit, 0, 0.04)
    gone = hit + 0.14 + 0.015 * F.fbm(0.05, 2, 422)  # a hard ring of vapour expands from each strike
    cov = F.ink * smooth(gone - t, 0, 0.006)
    flash = sum(math.exp(-(((t - when) / 0.018) ** 2)) for when in strikes)
    # Before the first strike the air crackles: a faint violet charge gathers on the letters.
    static = sm(t, 0.04, strikes[0]) * (1 - charge) * (0.5 + 0.5 * F.flow(0.06, t, (0.0, -1.5), 424))
    plasma = mix(F.source, rgb(112, 64, 230), 0.55 + 0.15 * math.sin(t * 200) ** 2)  # deep violet, holds on paper
    body = mix(F.source, rgb(150, 140, 255), static * 0.35)
    body = mix(body, plasma, charge)
    body = mix(body, rgb(225, 215, 255), min(1.0, flash) * 0.5)
    dark_rim = smooth(F.sdf, -u * 0.06, -u * 0.02) * charge  # a violet-black edge keeps the glow readable on paper
    body = mix(body, rgb(40, 20, 90), dark_rim * 0.9)
    canvas.over(np.clip(body, 0, 1), cov)
    edge = np.exp(-(((t - gone) / 0.012) ** 2)) * F.ink  # the vapour front eats outward from each strike, white-hot
    canvas.over(rgb(240, 236, 255), np.clip(edge * 1.3, 0, 1))
    canvas.add(bloom(rgb(170, 140, 255) * edge[..., None], F, 0.06, 1.2), 0.4)
    canvas.add(bloom(rgb(150, 110, 255) * (cov * charge)[..., None], F, 0.05, 0.45))
    canvas.add(bloom(rgb(190, 200, 255) * (F.ink * min(1.0, flash) * 0.8)[..., None], F, 0.12, 1.0), 0.3)
    glow = Image.new('L', (F.W, F.H))
    draw = ImageDraw.Draw(glow)
    for k, (when, (tx, ty)) in enumerate(zip(strikes, targets)):
        since = t - when
        if -0.005 < since < 0.08:
            path_rng = np.random.default_rng(F.seed * 5 + k * 17 + math.floor(t * 45))
            top = (tx + path_rng.normal(0, u * 0.6), 0)
            width = max(4, round(u * 0.12 * (1 - since / 0.08)))  # a trunk as thick as a letter stroke
            path = bolt(path_rng, top, (tx, ty), u * 0.2)
            draw.line(path, fill=255, width=width)
            for _ in range(4):  # branches off the main bolt
                k0 = path_rng.integers(3, len(path) - 3)
                end = (path[k0][0] + path_rng.normal(0, u * 0.5), path[k0][1] + path_rng.uniform(u * 0.2, u * 0.6))
                draw.line(bolt(path_rng, path[k0], end, u * 0.1, 7), fill=180, width=max(1, width // 2))
    # Arcs crawl over charged letters that have not yet boiled away.
    live = ((charge > 0.5) | (static > 0.6)) & (cov > 0.5)
    if live.any():
        ys, xs = np.nonzero(live)
        arc_rng = np.random.default_rng(F.seed * 9 + math.floor(t * 20))
        for _ in range(min(8, 1 + len(xs) // 300)):
            a, b = arc_rng.integers(0, len(xs), 2)
            if abs(xs[a] - xs[b]) < u * 0.6:
                draw.line(bolt(arc_rng, (xs[a], ys[a]), (xs[b], ys[b]), u * 0.05, 8), fill=220, width=1)
    arcs = np.asarray(glow, dtype=float) / 255
    if arcs.any():
        canvas.add(bloom(rgb(140, 170, 255) * arcs[..., None], F, 0.06, 2.2), 0.5)
        canvas.over(np.ones(3), arcs)
    origins = F.ink_points(300, 423)  # a few clean sparks, no speckle
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    sparks = Particles(
        F,
        origins,
        gone[ys, xs],
        radial(origins, targets, rng),
        accel=(0, 3),
        drag=1.5,
        life=rng.uniform(0.06, 0.18, len(xs)),
        size=rng.choice((1, 2), len(xs)),
        color=rgb(170, 200, 255),
        glow=True,
    )
    sparks.render(canvas, t)

    if t < 0.95:
        plume(F, canvas, t, front_band(gone, t, 0.05) * F.ink * 0.35, rgb(170, 180, 210), 0.4, 0.6, 0.2, 745)


def radial(origins, targets, rng):
    """Spark velocities thrown outward from the nearest strike point."""
    pts = np.asarray(targets, dtype=float)
    d = origins[:, None, :] - pts[None, :, :]
    near = d[np.arange(len(origins)), np.argmin((d**2).sum(-1), 1)]
    near = near / np.maximum(1.0, np.linalg.norm(near, axis=1, keepdims=True))
    return near * rng.uniform(1.0, 2.6, (len(origins), 1)) + rng.normal(0, 0.3, (len(origins), 2))


@recipe('neon-burnout', 'exit', pad=0.9)
def neon_burnout(F, canvas, t, intensity):
    """The word becomes a lit neon sign that surges and buzzes, then its tubes die one by one with a stutter
    and a spit of sparks, and the dead glass drops off the wall."""
    u = F.u
    index, count = letters(F)
    tube_d = np.abs(F.sdf + u * 0.05)
    radius = u * 0.026
    tube = coverage(tube_d - radius)
    cyl = np.sqrt(1 - np.clip(tube_d / radius, 0, 1) ** 2)
    rng = np.random.default_rng(F.seed + 470)
    deaths = 0.34 + 0.42 * rng.permutation(count) / max(1, count) + rng.uniform(-0.03, 0.03, count)
    frame = math.floor(t * 48)
    hashes = (np.sin((frame + np.arange(count) * 7.3) * 12.9898) * 43758.5453) % 1
    dying = np.clip((t - deaths + 0.14) / 0.14, 0, 1)
    stutter = 0.25 + 0.75 * (hashes > 0.3 + 0.6 * dying)
    on = np.where(dying <= 0, 1.0, np.where(dying < 1, stutter, 0.0))
    surge = sm(t, 0.08, 0.16) * (1 - sm(t, 0.3, 0.4)) * (0.6 + 0.4 * math.sin(t * 130) ** 2)
    glow_on = on[index.astype(int)] * sm(t, 0, 0.1)
    hue = NEON[F.seed % len(NEON)]
    core = mix(hue, np.ones(3), cyl**3 * (0.85 + 0.15 * surge))
    dead = rgb(90, 94, 100) * (0.4 + 0.6 * cyl)[..., None]
    word = mix(F.source, core, sm(t, 0, 0.1))
    lit_tube = tube * sm(t, 0, 0.1)
    canvas.over(F.source, F.ink * (1 - sm(t, 0, 0.1)))
    # Dead tubes let go of the wall and drop, letter by letter.
    for k in range(count):
        fell = t - deaths[k]
        mask = (index == k) * lit_tube
        if fell <= 0:
            continue
        drop = round(u * 22 * fell**2)
        fade = 1 - sm(fell, 0.08, 0.26)
        alive = on[k]
        glass = mix(dead, word, alive)
        layer = mask * (alive + (1 - alive) * fade)
        if drop and alive < 1:
            layer = shift(layer, drop, 0)
            glass = shift(glass, drop, 0) if alive < 1 else glass
        canvas.over(np.clip(glass, 0, 1), layer)
    canvas.over(np.clip(word, 0, 1), lit_tube * (t < deaths[index.astype(int)]))
    # Each tube flares bright for a frame just before it dies.
    pop = np.exp(-(((t - (deaths - 0.05)) / 0.04) ** 2))[index.astype(int)]
    canvas.add(np.ones(3) * (lit_tube * pop * 0.8)[..., None], 0.3)
    canvas.add(bloom(hue * (lit_tube * glow_on * (1 + 0.9 * surge + 1.5 * pop))[..., None], F, 0.05, 1.1))
    canvas.add(hue * (gaussian_filter(coverage(F.sdf), u * 0.03) * glow_on * 0.2 * (1 + surge))[..., None])
    sparking = (dying > 0) & (dying < 1)
    for k in np.nonzero(sparking)[0]:
        pts = F.ink_points(40, 471 + k)
        pts = pts[index[pts[:, 1].astype(int), pts[:, 0].astype(int)] == k]
        if len(pts):
            srng = np.random.default_rng(F.seed + frame * 3 + k)
            sparks = Particles(
                F,
                pts,
                t - srng.uniform(0, 0.03, len(pts)),
                np.stack((srng.normal(0, 1.5, len(pts)), srng.normal(-0.5, 1.0, len(pts))), 1),
                accel=(0, 10),
                drag=1,
                life=0.03,
                size=1,
                color=rgb(255, 220, 160),
                glow=True,
            )
            sparks.render(canvas, t)

    if t < 0.95:
        for k in np.nonzero(sparking)[0]:
            plume(F, canvas, t, (index == k) * tube * 0.6, rgb(150, 150, 160), 0.35, 0.5, 0.1, 748 + k)
    # The afterimage: once the last tube is dead, the word burns on the eye in the complementary colour.
    since_last = t - float(deaths.max())
    after = smooth(since_last, -0.02, 0.12) * (1 - smooth(since_last, 0.14, 0.26))  # a soft glow that swells and fades
    if after > 0.02:
        comp = 1.0 - hue
        comp = np.clip(comp / max(0.3, float(comp.max())), 0, 1)  # the saturated complementary colour
        ghost = gaussian_filter(coverage(F.sdf - F.u * 0.04), F.u * 0.05)  # enlarged, with blurred edges
        ghost = shift(ghost, -round(F.u * 0.12 * smooth(since_last, 0, 0.22)), 0)  # drifting up as it fades
        canvas.add(comp * (np.clip(ghost * 1.2, 0, 1) * after * 0.75)[..., None], 0.55)


@recipe('thermite-burn', 'exit', pad=1.2)
def thermite(F, canvas, t, intensity):
    """The top edge of the word heats to a dull red, then a blinding thermite line burns down through the
    letters, spraying sparks, dripping molten metal and dropping dark slag."""
    u = F.u
    burn_line = -0.3 + 1.66 * min(1.0, max(0.0, (t - 0.1) / 0.82)) ** 1.8
    tilt = 0.24 * (np.clip(F.xn, 0, 1) - 0.5)  # the cut leans, so the left letters go first
    r = F.yn - burn_line + tilt + 0.09 * F.fbm(0.05, 3, 480) + 0.03 * F.noise(0.015, 484)  # a ragged edge
    cov = F.ink * smooth(r, 0, 0.02)
    preheat = np.exp(-np.clip(F.yn, 0, None) / 0.12) * sm(t, 0, 0.1) * (1 - sm(t, 0.15, 0.3)) * F.ink
    heat = np.clip(np.exp(-np.clip(r, 0, None) / 0.06) * F.ink + preheat * 0.5, 0, 1) * (1 - sm(t, 0.86, 0.95))
    body = mix(F.source, blackbody(0.45 + 0.6 * heat), smooth(heat, 0.08, 0.6))
    canvas.over(np.clip(body, 0, 1), cov)
    canvas.add(bloom(blackbody(heat * 1.1) * (heat * cov)[..., None], F, 0.05, 1.0))
    core = np.exp(-((r / 0.014) ** 2)) * F.ink * (1 - sm(t, 0.9, 0.97))
    canvas.add(np.ones(3) * core[..., None] * 1.6 + bloom(np.ones(3) * core[..., None], F, 0.05, 1.2), 0.5)
    front = np.nonzero((np.abs(r) < 0.02) & (F.ink > 0.5))
    if len(front[0]) and 0.08 < t < 0.92:
        rng = np.random.default_rng(F.seed + 481 + math.floor(t * 150))
        pick = rng.integers(0, len(front[0]), 300)
        origins = np.stack((front[1][pick], front[0][pick]), 1)
        sparks = Particles(
            F,
            origins,
            t - rng.uniform(0, 0.06, 300),
            np.stack((rng.normal(0, 2.2, 300), rng.uniform(-3.2, 0.8, 300)), 1),
            accel=(0, 14),
            drag=0.5,
            life=0.09,
            size=rng.choice((1, 1, 2), 300),
            shape='streak',
            cooling=True,
            trail=0.015,
        )
        sparks.render(canvas, t)
    # Slag and molten drips: the line sheds dark flakes and glowing drops as it passes.
    origins = F.ink_points(700, 482)
    xs, ys = origins[:, 0].astype(int), origins[:, 1].astype(int)
    reach = np.clip((F.yn[ys, xs] + tilt[ys, xs] + 0.3) / 1.66, 0, 1)
    when = 0.1 + 0.82 * reach ** (1 / 1.8)  # when the line reaches each origin
    rng2 = np.random.default_rng(F.seed + 483)
    slag = Particles(
        F,
        origins[:450],
        when[:450],
        np.stack((rng2.normal(0, 0.4, 450), rng2.uniform(-0.3, 0.4, 450)), 1),
        accel=(0, 9),
        drag=0.6,
        life=rng2.uniform(0.12, 0.2, 450),
        size=u * rng2.uniform(0.015, 0.035, 450),
        color=mix(rgb(36, 32, 30), rgb(80, 72, 68), rng2.uniform(0, 1, (450, 1))),
        shape='flake',
        spin=20,
        fade_in=0,
    )
    slag.render(canvas, t)
    drips = Particles(
        F,
        origins[450:],
        when[450:],
        np.stack((rng2.normal(0, 0.1, 250), rng2.uniform(0.6, 1.6, 250)), 1),
        accel=(0, 6),
        drag=1.0,
        life=rng2.uniform(0.1, 0.2, 250),
        size=rng2.choice((1, 2, 2), 250),
        shape='streak',
        cooling=True,
        trail=0.03,
    )
    drips.render(canvas, t)

    if t < 0.93:  # thermite burns with a roaring white flame, choking smoke and a shimmer above
        burning = np.exp(-((r / 0.03) ** 2)) * F.ink
        paint_fire(F, canvas, flames(F, burning, t, 0.45, 749), 1.2)
        plume(F, canvas, t, burning * 0.9, rgb(200, 196, 190), 0.55, 1.0, 0.25, 750)
        canvas.distort(
            F, np.clip(shift(blur(burning[..., None], u * 0.06)[..., 0], -round(u * 0.15), 0) * 3, 0, 1), t
        )


def _inverse_sm(value):
    """Progress at which a smoothstep reaches `value` (0..1), by bisection; works on arrays."""
    value = np.clip(np.asarray(value, dtype=float), 0, 1)
    lo, hi = np.zeros_like(value), np.ones_like(value)
    for _ in range(18):
        mid = (lo + hi) / 2
        below = mid * mid * (3 - 2 * mid) < value
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    return (lo + hi) / 2


def edge_points(F, sdf, count, seed, band=0.02):
    """Random pixels on a (ragged) outline, for sparks and embers thrown off an edge."""
    ys, xs = np.nonzero(np.abs(sdf) < F.u * band)
    if not len(xs):
        return np.zeros((0, 2))
    pick = np.random.default_rng(F.seed + seed).integers(0, len(xs), count)
    return np.stack((xs[pick], ys[pick]), 1).astype(float)
