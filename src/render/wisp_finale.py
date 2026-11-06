"""How a will-o'-wisp ends: instead of slowly reeling its tail in, the ribbon flares and bursts into sparks.

When the wisp's run is over, the strand it had drawn at that moment breaks up into glowing sparks in its own
colours. Sparks along the strand puff out sideways and drift upwards like embers; a denser burst flies out from
the head with a bright expanding ring; every spark shrinks and fades as it slows. The ribbon itself flashes
brighter for a moment and is gone within half a second. Every spark's path is a pure function of the time since
the run ended, so a frame can be rendered on its own.
"""
import math
import random

from PIL import Image, ImageDraw, ImageFilter

BURST_TIME = 1.6     # seconds the sparks live
RIBBON_FADE = .45    # seconds the ribbon takes to vanish once it bursts
RING_TIME = .55


def ribbon_strength(age):
    """The ribbon's opacity after the run ended `age` seconds ago: a brief flare, then gone."""
    if age <= 0:
        return 1.
    if age >= RIBBON_FADE:
        return 0.
    u = age/RIBBON_FADE
    return (1+.6*math.sin(math.pi*min(1., u*2.5)))*(1-u)**1.5


def sparks(points, seed, unit):
    """Deterministic sparks for a strand given as [(x, y, (r, g, b)), ...]: start, velocity, size, colour."""
    rng = random.Random(seed)
    result = []
    if not points:
        return result
    step = max(1, len(points)//70)
    for k in range(0, len(points), step):
        x, y, color = points[k]
        if k+1 < len(points):
            nx, ny = points[k+1][1]-y, -(points[k+1][0]-x)
        else:
            nx, ny = rng.uniform(-1, 1), rng.uniform(-1, 1)
        length = math.hypot(nx, ny) or 1.
        side = rng.choice((-1, 1))
        speed = unit*rng.uniform(1.5, 4.5)
        result.append((x, y, side*nx/length*speed+rng.uniform(-1, 1)*unit, side*ny/length*speed-unit*rng.uniform(1, 3),
                       rng.uniform(.6, 1.3)*unit*.32, color, rng.uniform(.75, 1.)))
    hx, hy, hc = points[-1]
    for _ in range(36):  # the head's burst: faster, all round
        a = rng.uniform(0, math.tau)
        speed = unit*rng.uniform(4, 10)
        result.append((hx, hy, math.cos(a)*speed, math.sin(a)*speed-unit*2, rng.uniform(.8, 1.6)*unit*.36,
                       rng.choice((hc, (255, 255, 255))), 1.))
    return result


def paint_finale(layer, points, age, seed, unit, offset=(0, 0)):
    """Draw the burst `age` seconds after the run ended. `points` is the strand at that moment in layer
    coordinates (before `offset`, which is subtracted, e.g. the camera's position); `unit` sets the scale."""
    if age < 0 or age >= BURST_TIME or not points:
        return
    ox, oy = offset
    u = age/BURST_TIME
    spark_layer = Image.new('RGBA', layer.size)
    draw = ImageDraw.Draw(spark_layer)
    drag = (1-math.exp(-2.6*age))/2.6  # velocities decay: distance = v*(1-e^-kt)/k
    for x, y, vx, vy, size, color, bright in sparks(points, seed, unit):
        px = x-ox+vx*drag
        py = y-oy+vy*drag+unit*1.2*age*age  # a little gravity once they have slowed
        r = size*(1-u)**.7
        if r < .35:
            continue
        alpha = round(255*bright*(1-u)**1.2)
        draw.ellipse((px-r, py-r, px+r, py+r), fill=(*color, alpha))
    if age < RING_TIME:
        hx, hy, hc = points[-1]
        v = age/RING_TIME
        radius = unit*(1.5+9*(1-(1-v)**3))
        draw.ellipse((hx-ox-radius, hy-oy-radius, hx-ox+radius, hy-oy+radius), outline=(255, 255, 255, round(220*(1-v))),
                     width=max(1, round(unit*.35*(1-v))+1))
    box = spark_layer.getbbox()
    if not box:
        return
    glow = spark_layer.filter(ImageFilter.GaussianBlur(max(1., unit*.6)))
    layer.alpha_composite(glow)
    layer.alpha_composite(spark_layer)
