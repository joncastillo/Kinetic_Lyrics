"""Ice and steam: a thawing block, frozen shatter, evaporation."""

import math

import numpy as np

from effects.materials.fx import (
    Particles,
    bevel,
    bloom,
    blur,
    environment,
    fresnel,
    lambert,
    mix,
    normals,
    rgb,
    shadow,
    sm,
    smooth,
    specular,
    sun,
    warp,
)
from effects.materials.recipes.registry import recipe
from effects.materials.recipes.common import (
    arrival,
    block_erosion,
    front_band,
    front_particles,
    plume,
    rim_cover,
)


ICE_FREEZE = 0.2  # the block freezes into being over the first frames


@recipe('ice-block-thaw', 'entrance', pad=0.75)
def ice_thaw(F, canvas, t, intensity):
    """A block of ice freezes into being; fissures race through it and trace the letters, then it thaws from
    the left, letter by letter, dripping into a puddle, until only the ice letters are left, gleaming wet."""
    u = F.u
    erode = block_erosion(F, 'ice', (0.14, 0.16, 0.14, 0.12, 0.08), (0.3, 0.06), 0.006, span=(0.5, 0.82), power=0.6)
    freeze = sm(t, 0, ICE_FREEZE)
    remaining = erode - max(t, ICE_FREEZE)
    cov = smooth(remaining, 0, 0.015) * sm(t, 0, 0.04)
    depth = np.clip(remaining, 0, 0.25) / 0.25
    wet = 1 - sm(t, 0.9, 1) * 0.4
    height = u * (0.18 * np.sqrt(depth) + 0.006 * F.fbm(0.05, 3, 50) * wet)
    n = normals(height)
    light = sun()
    _, _, edge, _ = F.cells(0.22, 51)
    cracks = (1 - smooth(edge / u, 0, 0.012)) * (F.noise(0.15, 52) > -0.2)
    bubbles = smooth(F.noise(0.012, 53), 0.82, 0.95)
    inner = mix(rgb(140, 200, 230), rgb(226, 246, 255), np.clip(1 - depth, 0, 1) * 0.7 + 0.3 * bubbles)
    color = inner * (0.55 + 0.45 * lambert(n, light))[..., None]
    color = color + environment(n, sky=(0.75, 0.88, 1)) * fresnel(n, 0.08)[..., None] * 1.4
    color = color + specular(n, light, 120)[..., None] * 1.5 + cracks[..., None] * 0.35
    # A light sweeps along the finished letters as the last of the block goes.
    sweep_x = -0.3 + 1.7 * sm(t, 0.8, 0.98)
    band = np.exp(-(((F.xn - sweep_x) / 0.12) ** 2)) * sm(t, 0.8, 0.84) * (1 - sm(t, 0.96, 1))
    color = color + (band * 0.5)[..., None]
    alpha = cov * np.clip(
        0.55 + 0.35 * (1 - n[..., 2]) * 4 + 0.3 * cracks + 0.25 * bubbles + 0.15 * (1 - depth), 0, 0.95
    )
    # Meltwater pools under the word and dries off once the thaw is done.
    pool_t = sm(t, 0.4, 0.78) * (1 - sm(t, 0.84, 0.98))
    if pool_t > 0:
        y0 = F.box[3] + u * 0.1
        half_w = (F.box[2] - F.box[0]) / 2 * (0.5 + 0.6 * pool_t) + u * 0.15
        rx = (F.px - F.cx) / max(1.0, half_w)
        ry = (F.py - y0) / (u * (0.03 + 0.06 * pool_t))
        pool = smooth(1 - (rx**2 + ry**2), 0, 0.2) * (F.py > y0 - u * 0.03)
        puddle = rgb(120, 170, 210) * 0.8 + rgb(230, 245, 255) * (np.exp(-(((rx + 0.25) / 0.3) ** 2) - ((ry + 0.3) / 0.5) ** 2))[..., None]
        canvas.over(np.clip(puddle, 0, 1), pool * 0.55 * pool_t)
    canvas.over(rgb(20, 60, 90), shadow(cov, F, 0.04, 0.07, 0.05, 0.25))
    canvas.over(np.clip(color, 0, 1), alpha)
    # Fissures run through the block from the left and trace the letters before the melt frees them.
    fissure = np.exp(-(((F.sdf - u * 0.03) / (u * 0.012)) ** 2)) * (F.sdf > 0) * (cov > 0.5)
    fissure = fissure * (0.6 + 0.4 * F.noise(0.02, 55))
    reveal = smooth(t - 0.2 - np.clip(F.xn, 0, 1) * 0.18, 0, 0.06)
    canvas.over(np.ones(3), np.clip(fissure * reveal, 0, 1) * 0.9)
    canvas.add(bloom(rgb(200, 235, 255) * (fissure * reveal)[..., None], F, 0.03, 0.9), 0.2)
    rim_cover(F, canvas, cov, sm(t, 0.78, 1) * 0.8, colour=(0.04, 0.14, 0.24))
    if freeze < 1:  # the block freezes into being, growing out from its heart
        scale = 0.55 + 0.45 * freeze
        canvas.c = warp(F, canvas.c, (F.px - F.cx) * (1 - 1 / scale), (F.py - F.cy) * (1 - 1 / scale))
    if ICE_FREEZE - 0.02 < t < 0.97:
        origins, rng, (ys, xs) = front_particles(F, erode, 320, 54)
        if origins is not None:
            drops = Particles(
                F,
                origins,
                erode[ys, xs] + rng.uniform(0, 0.05, len(xs)),
                np.stack((rng.uniform(-0.05, 0.05, len(xs)), rng.uniform(0, 0.3, len(xs))), 1),
                accel=(0, 7.0),
                drag=0.3,
                life=rng.uniform(0.07, 0.14, len(xs)),
                size=rng.choice((1, 2, 2), len(xs)),
                color=rgb(225, 245, 255),
                alpha=0.9,
            )
            drops.render(canvas, t)

    if t < 0.95:  # cold mist rolls off the melting face
        plume(F, canvas, t, front_band(erode, t, 0.06, F.sdf > 0), rgb(220, 240, 250), 0.35, 0.35, 0.2, 704)


@recipe('freeze-shatter', 'exit', pad=1.1)
def freeze_shatter(F, canvas, t, intensity):
    """Frost feathers across the letters, bright cracks race through the ice from one point, and the word
    bursts into tumbling shards and glitter."""
    u = F.u

    def build():
        ids, _, edge, centres = F.cells(0.45, 380, jitter=0.9)
        frost = arrival(F, 'freeze', 1.0, 0.25)
        fracture = arrival(F, 'fracture', 0.4, 0.2, seed=9)
        return ids, edge, centres, frost, fracture

    ids, edge, centres, frost, fracture = F.memo('freeze', build)
    frozen = smooth(t - 0.02 - frost * 0.38, 0, 0.06)
    feathers = smooth(np.abs(np.sin(F.X * 40 + F.Y * 25 + F.fbm(0.05, 3, 381) * 8)), 0.8, 1)
    n = normals(bevel(F.sdf, u * 0.05) + u * 0.006 * F.fbm(0.02, 2, 382))
    ice = (
        mix(rgb(160, 210, 240), rgb(240, 252, 255), feathers * 0.7 + 0.15) * (0.65 + 0.4 * lambert(n, sun()))[..., None]
    )
    ice = ice + specular(n, sun(), 120)[..., None]
    body = mix(F.source, ice, frozen)
    burst = 0.56
    intact = t < burst
    # Dark cracks with a bright halo race out from an impact point over four frames before the burst.
    cracked = smooth(t - 0.3 - fracture * 0.14, 0, 0.06) * (t < burst)
    crack = (1 - smooth(edge, u * 0.012, u * 0.026)) * cracked
    halo = (1 - smooth(edge, u * 0.026, u * 0.06)) * cracked
    canvas.over(np.clip(body, 0, 1), F.ink * intact)
    canvas.over(np.ones(3), halo * F.ink * 0.8)
    canvas.over(rgb(20, 50, 90), crack * F.ink)
    web = smooth(t, 0.4, 0.43) * (t < burst)  # the fracture web, held at full strength up to the split
    if web > 0.02:
        canvas.over(rgb(40, 84, 130), F.ink * web * 0.45)  # the ice darkens so the cracks pop
        crack_web = long_cracks(F, 3.4) * F.ink
        canvas.over(rgb(10, 26, 50), np.clip(crack_web * 1.4, 0, 1) * web)  # a dark hairline either side
        core = np.clip(crack_web * 2.2 - 1.2, 0, 1) * web  # and a thin bright core
        canvas.over(np.ones(3), core)
        canvas.add(bloom(rgb(210, 240, 255) * core[..., None], F, 0.03, 0.6), 0.3)
    if 0.28 < t < burst:  # long dark cracks run out from an impact point in each letter
        lines = long_cracks(F) * F.ink
        canvas.over(rgb(14, 34, 64), lines * smooth(t - 0.28, 0, 0.12))
        fork = lines * smooth(t - 0.44, 0, 0.04)  # just before the break the cracks flare white
        canvas.add(np.ones(3) * fork[..., None] * 0.9 + bloom(rgb(200, 235, 255) * fork[..., None], F, 0.05, 1.2), 0.5)
    if 0.45 < t < burst:  # the frozen word shudders for a few frames
        jolt = u * 0.07 * math.sin(t * 150)  # big enough to see in a still
        pulse = 1 + 0.04 * math.exp(-(((t - 0.54) / 0.025) ** 2))  # the ice swells a hair as it gives
        k = 1 - 1 / pulse
        canvas.c = warp(F, canvas.c, jolt + (F.px - F.cx) * k, (F.py - F.cy) * k)
    canvas.add(bloom(rgb(200, 235, 255) * (halo * F.ink)[..., None], F, 0.04, 0.6), 0.2)  # glow beside the cracks, not on them
    if t >= burst:
        flash = np.exp(-(((t - burst) / 0.035) ** 2))
        canvas.add(rgb(210, 240, 255) * (F.ink * flash * 0.9)[..., None], 0.6)
        canvas.add(bloom(rgb(200, 235, 255) * (F.ink * flash)[..., None], F, 0.12, 1.2), 0.3)
        # The frozen letters break into big pieces along the cracks, released outward from the impact point.
        rim = 1 - smooth(edge, 0, u * 0.02)
        facet = (1 - smooth(edge, u * 0.02, u * 0.04)) * smooth(edge, u * 0.008, u * 0.02)
        piece_rgb = np.clip(mix(np.clip(body, 0, 1), rgb(14, 44, 90), rim * 0.95), 0, 1)  # dark ice edges
        piece_rgb = mix(piece_rgb, np.ones(3), facet * 0.8)  # a sharp bright facet inside each edge
        pieces = ice_pieces(F, ids, centres, fracture)
        big = sorted((pc[4].sum() for pc in pieces), reverse=True)[min(3, len(pieces) - 1)] if pieces else 0
        for y0, y1, x0, x1, alpha, delay, vx, vy, spin in pieces:
            # Frozen time: the pieces part by a hair and hang still for a couple of frames, then fly.
            parted = sm(t - burst, 0, 0.03)
            a = max(0.0, t - burst - 0.07) - delay * (t - burst > 0.07)
            if a <= 0:
                norm = max(1.0, math.hypot(vx, vy))
                dx, dy = round(vx / norm * u * 0.05 * parted), round(vy / norm * u * 0.05 * parted)
                fade, shade = 1.0, 1.0
            else:
                kick = 0.14 * (1 - np.exp(-a / 0.05))  # a sharp outward burst, then gravity takes over
                norm = max(1.0, math.hypot(vx, vy))
                dx = round(vx * kick + vx / norm * u * 0.05)
                dy = round(vy * kick + vy / norm * u * 0.05 + 0.5 * u * 24 * a * a)  # falls about a word height
                fade = 1 - sm(a, 0.22, 0.34)
                shade = 1.0 + 0.15 * np.cos(spin * a)  # the face turns to and from the light as it tumbles
            crop, mask = piece_rgb[y0:y1, x0:x1] * shade, alpha * fade
            turn = np.degrees(spin * 0.06 * max(a, 0.0)) * (1 if spin > 14 else -1)  # each piece spins as it tumbles
            if abs(turn) > 1:
                from scipy.ndimage import rotate

                h, w = mask.shape
                mask = rotate(mask, turn, reshape=True, order=1)
                crop = np.stack([rotate(crop[..., c], turn, reshape=True, order=1) for c in range(3)], -1)
                dy -= (mask.shape[0] - h) // 2
                dx -= (mask.shape[1] - w) // 2
            paste(canvas, crop, mask, y0 + dy, x0 + dx)
            if alpha.sum() >= big and 0.74 < t < 0.9:  # the biggest chunks glint together as they melt away
                glint = math.exp(-(((t - 0.81) / 0.03) ** 2))
                gy, gx = y0 + dy + mask.shape[0] // 2, x0 + dx + mask.shape[1] // 2
                star = np.exp(-(((F.px - gx) / (u * 0.02)) ** 2) - ((F.py - gy) / (u * 0.2)) ** 2)
                star = np.maximum(star, np.exp(-(((F.px - gx) / (u * 0.2)) ** 2) - ((F.py - gy) / (u * 0.02)) ** 2))
                star = np.maximum(star, np.exp(-(np.hypot(F.px - gx, F.py - gy) / (u * 0.04)) ** 2))
                canvas.add(np.ones(3) * (star * glint)[..., None], 0.6)
        rng2 = np.random.default_rng(F.seed + 384)
        glitter = Particles(
            F,
            F.ink_points(400, 385),
            burst,
            np.stack((rng2.normal(0, 2, 400), rng2.normal(-0.5, 1.5, 400)), 1),
            accel=(0, 4),
            drag=2,
            life=0.35,
            size=1,
            color=rgb(230, 250, 255),
            glow=True,
        )
        glitter.render(canvas, t)

    if t < burst:  # freezing air: a cold mist creeps off the frost front
        plume(F, canvas, t, frozen * F.ink * 0.5, rgb(225, 240, 250), 0.3, 0.3, 0.2, 742)


@recipe('steam-evaporate', 'exit', pad=1.1)
def steam(F, canvas, t, intensity):
    """Condensation beads up on the letters, then the heat takes them one by one: each letter peels upward in
    separate curling tongues of steam that turn slate grey as they rise and thin away."""
    from effects.materials.recipes.common import letters

    u = F.u
    index, count = letters(F)
    hot = sm(t, 0.08, 0.35)
    start = 0.36 + 0.26 * index / max(1, count)  # the letters go in relay, left to right
    lift = np.clip((t - start) / 0.42, 0, 1) ** 1.2
    band = 0.5 + 0.5 * np.sin(F.px / u * 14 + F.fbm(0.1, 2, 411) * 3)  # separate tongues across each letter
    stretch = (0.25 + 0.95 * (1 - np.clip(F.yn, 0, 1))) * (0.35 + 0.9 * band)
    dx = u * 0.03 * hot * np.sin(F.py / u * 20 + t * 60) + u * 0.14 * lift * np.sin(F.py / u * 5 + band * 6)
    dy = -u * 1.2 * lift * stretch
    alpha = warp(F, F.ink, dx, dy)
    colour = warp(F, F.source, dx, dy)
    risen = warp(F, lift, dx, dy)
    soft = u * 0.05 * float(lift.max())
    if soft > 0.6:
        alpha = blur(alpha[..., None], soft)[..., 0] * (1 + 0.5 * risen)
    alpha = np.clip(alpha, 0, 1)
    body = mix(colour, rgb(150, 166, 188), np.clip(risen * 1.2, 0, 1) * 0.85)  # turns to slate steam as it rises
    cov = alpha * (1 - smooth(risen, 0.45, 1.0))
    canvas.over(np.clip(body, 0, 1), cov)
    # Condensation: droplets bead up on the plain word before the heat takes it.
    beads = smooth(F.noise(0.016, 417), 0.78, 0.9) * F.ink * sm(t, 0.12, 0.3) * (1 - smooth(lift, 0, 0.3))
    canvas.over(np.clip(F.source * 0.55, 0, 1), beads * 0.8)
    glint = smooth(F.noise(0.016, 417), 0.88, 0.93) * beads
    canvas.over(np.ones(3), glint)
    rng = np.random.default_rng(F.seed + 415)
    origins = F.ink_points(700, 416)
    xs = origins[:, 0].astype(int).clip(0, F.W - 1)
    Particles(
        F,
        origins,
        start[0, xs] + rng.uniform(0.02, 0.35, 700),
        np.stack((rng.normal(0, 0.2, 700), -rng.uniform(0.6, 1.4, 700)), 1),
        accel=(0, -1.5),
        drag=1.6,
        life=rng.uniform(0.18, 0.3, 700),
        size=rng.uniform(2.5, 4, 700),
        color=rgb(120, 138, 160),
        alpha=0.22,
        swirl=0.15,
    ).render(canvas, t)
    if t < 0.95:
        plume(F, canvas, t, F.ink * lift * 0.7, rgb(128, 146, 170), 0.7, 1.1, 0.2, 744)


def long_cracks(F, thick=1.0):
    """Three to five long jagged cracks per letter, from one impact point each, as a 0..1 mask."""

    def build():
        from PIL import Image, ImageDraw

        from effects.materials.recipes.common import letters

        index, count = letters(F)
        rng = np.random.default_rng(F.seed + 386)
        f = 2
        img = Image.new('L', (F.W * f, F.H * f))
        draw = ImageDraw.Draw(img)
        width = max(2, round(F.u * 0.028 * thick * f))
        for k in range(count):
            ys, xs = np.nonzero((index == k) & (F.ink > 0.5))
            if not len(xs):
                continue
            i = rng.integers(len(xs))
            cx, cy = float(xs[i]), float(ys[i])
            for _ in range(rng.integers(3, 6)):
                angle = rng.uniform(0, 2 * np.pi)
                length = F.u * rng.uniform(0.4, 0.8)
                points = [(cx * f, cy * f)]
                for step in range(1, 7):
                    a = angle + rng.normal(0, 0.35)
                    d = length * step / 6
                    points.append(((cx + np.cos(a) * d) * f, (cy + np.sin(a) * d) * f))
                draw.line(points, fill=255, width=width)
        small = img.resize((F.W, F.H), Image.LANCZOS)
        return np.asarray(small, dtype=float) / 255

    return F.memo(('freeze-long-cracks', thick), build)


def ice_pieces(F, ids, centres, fracture):
    """Each crack cell of the word as a piece: its crop, release delay and launch velocity (px per unit t)."""

    def build():
        inside = np.unique(ids[F.ink > 0.5])
        rng = np.random.default_rng(F.seed + 383)
        at = np.clip(centres[inside].round().astype(int), 0, (F.W - 1, F.H - 1))
        first = inside[np.argmin(fracture[at[:, 1], at[:, 0]])]
        impact = centres[first]
        reach = np.linalg.norm(centres[inside] - impact, axis=1)
        reach = reach / max(1.0, reach.max())
        pieces = []
        for k, r in zip(inside, reach):
            ys, xs = np.nonzero((ids == k) & (F.ink > 0.02))
            if not len(xs):
                continue
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            alpha = F.ink[y0:y1, x0:x1] * (ids[y0:y1, x0:x1] == k)
            out = centres[k] - impact
            out = out / max(1.0, np.linalg.norm(out))
            speed = F.u * rng.uniform(4.0, 7.0) * (1.3 - 0.6 * r)
            vx = out[0] * speed + rng.normal(0, F.u * 0.3)
            vy = out[1] * speed - F.u * rng.uniform(1.5, 3.0)  # a small kick upward before it drops
            pieces.append((y0, y1, x0, x1, alpha, 0.08 * r, vx, vy, rng.uniform(8, 20)))
        return pieces

    return F.memo('freeze-pieces', build)


def paste(canvas, rgb_crop, alpha, y, x):
    """Composite a crop over the canvas at (y, x), clipped to the frame."""
    H, W = canvas.c.shape[:2]
    h, w = alpha.shape
    ya, yb, xa, xb = max(0, y), min(H, y + h), max(0, x), min(W, x + w)
    if ya >= yb or xa >= xb:
        return
    al = np.clip(alpha[ya - y:yb - y, xa - x:xb - x], 0, 1)[..., None]
    region = canvas.c[ya:yb, xa:xb]
    region[..., :3] = rgb_crop[ya - y:yb - y, xa - x:xb - x] * al + region[..., :3] * (1 - al)
    region[..., 3:] = al + region[..., 3:] * (1 - al)
