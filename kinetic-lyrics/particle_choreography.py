"""Material-specific advection, drag and terminal breakup for glyph particles."""

import math
from PIL import Image, ImageDraw


def dynamics(family, q, values, height):
    """Return additional drift, size and angular motion, all neutral at rest."""
    phase = values[3] * math.tau
    curl = math.sin(q * 5 + phase) - math.sin(phase)
    dx = dy = 0.0
    scale = spin = 1.0
    if family == "dust":
        dx = height * (0.25 * q + 0.18 * curl * q)
        dy = -height * (0.35 * q + 0.2 * q * q)
        scale = 1 - 0.55 * q * q
        spin = 0.25
    elif family == "sparks":
        dy = height * 0.7 * q * q
        scale = 1 - 0.6 * max(0.0, (q - 0.45) / 0.55)
        spin = 0.15
    elif family == "ribbons":
        dx = height * 0.18 * math.sin(q * 8 + phase) * q
        dy = height * 0.22 * curl * q
        spin = 0.5 + 0.5 * math.sin(q * 6 + phase)
    elif family == "petals":
        dx = height * (0.25 * q + 0.25 * curl * q)
        dy = height * 0.4 * q * q + height * 0.18 * math.sin(q * 7 + phase) * q
        scale = 1 - 0.2 * q
        spin = 0.55 + 0.35 * math.sin(q * 9 + phase)
    elif family == "snow":
        dx = height * 0.35 * curl * q
        dy = height * 0.45 * q * q
        scale = 1 - 0.12 * q
        spin = 0.25
    elif family == "smoke":
        dx = height * (0.2 * curl + 0.12 * math.sin(q * 11 + phase)) * q
        dy = -height * (0.25 * q + 0.35 * q * q)
        scale = 1 + 1.5 * q * q
        spin = 0.1
    elif family == "bubbles":
        dx = height * 0.15 * curl * q
        dy = -height * 0.7 * q * q
        spin = 0.1
    elif family == "ink":
        dy = height * 1.25 * q * q
        scale = 1 - 0.3 * q
        spin = 0.2
    elif family == "vortex":
        dx = height * 0.12 * math.cos(phase + q * 12) * q
        dy = height * 0.12 * math.sin(phase + q * 12) * q
        spin = 0.7 + q * 1.8
    elif family == "magnetic":
        dx = height * 0.22 * math.sin(q * math.pi * 4) * q * (1 - q)
        dy = height * 0.08 * math.sin(q * math.pi * 2) * q
        spin = 0.15
    return dx, dy, scale, spin


def terminal_particles(layer, center, piece, family, q, values, alpha):
    """A pop/split continues the original particle's motion instead of fading a tile."""
    if family not in ("bubbles", "pixels", "sparks", "ink"):
        return False
    start = 0.58 + values[0] * 0.16
    if q < start:
        return False
    progress = (q - start) / (1 - start)
    bounds = piece.getchannel("A").getbbox()
    if not bounds:
        return True
    radius = max(2.0, max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.4)
    ink = next(
        (pixel[:3] for pixel in piece.getdata() if pixel[3] > 80), (220, 230, 240)
    )
    count = 8 if family == "bubbles" else 4 if family == "pixels" else 3
    span = max(8, round(radius * (2 + progress * 4)))
    image = Image.new("RGBA", (span * 2 + 8, span * 2 + 8))
    draw = ImageDraw.Draw(image)
    c = image.width / 2
    for index in range(count):
        angle = index * math.tau / count + values[1] * math.tau
        distance = radius * (1 + progress * 2)
        dx, dy = math.cos(angle) * distance, math.sin(angle) * distance
        if family == "ink":
            dy += radius * progress * progress * 2
        elif family == "sparks":
            dx *= 1.5
            dy += radius * progress * progress
        size = max(
            0.7,
            radius * (0.17 if family == "bubbles" else 0.35) * (1 - progress * 0.65),
        )
        color = (*ink, round(255 * alpha * (1 - progress * 0.65)))
        box = (c + dx - size, c + dy - size, c + dx + size, c + dy + size)
        if family == "pixels":
            draw.rectangle(box, fill=color)
        else:
            draw.ellipse(box, fill=color)
    layer.alpha_composite(
        image, (round(center[0] - image.width / 2), round(center[1] - image.height / 2))
    )
    return True


def entrance_opacity(progress):
    """Fade botanical pieces and shards in over most of their arrival."""
    p=max(0.,min(1.,progress/.9))
    return p*p*(3-2*p)
