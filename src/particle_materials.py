"""Distinct particle silhouettes derived from the ink color of each glyph fragment."""

import math

from PIL import Image, ImageDraw, ImageFilter


def _mix(a, b, fraction):
    return tuple(round(x + (y - x) * fraction) for x, y in zip(a, b))


def make_material(family, source, values):
    if family == "glass":
        return None
    ink = next(
        (pixel[:3] for pixel in source.getdata() if pixel[3] > 120), (220, 230, 240)
    )
    light_ink = sum(ink) > 400
    pale = (245, 250, 255) if light_ink else (38, 69, 94)
    base = max(7, min(22, max(source.size)))
    size = base * 3
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    c = size / 2
    if family == "dust":
        for index in range(7):
            angle = index * 2.399 + values[1] * math.tau
            distance = base * (0.1 + values[index % 8] * 0.75)
            x, y = c + math.cos(angle) * distance, c + math.sin(angle) * distance
            radius = 0.7 + values[(index + 2) % 8] * 1.1
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=(*ink, 160 + index * 12),
            )
    elif family == "sparks":
        warm = (255, 183, 72) if light_ink else (171, 77, 14)
        length = base * (1 + values[2] * 0.5)
        draw.polygon(
            [
                (c - length, c),
                (c + base * 0.35, c - base * 0.1),
                (c + base * 0.65, c),
                (c + base * 0.35, c + base * 0.1),
            ],
            fill=(*warm, 230),
        )
        draw.line((c - base * 0.2, c, c + base * 0.5, c), fill=(*pale, 255), width=2)
        image = image.filter(ImageFilter.GaussianBlur(0.25))
    elif family == "pixels":
        r = base * 0.36
        draw.rectangle((c - r, c - r, c + r, c + r), fill=(*ink, 245))
        draw.line(
            (c - r, c + r, c - r, c - r, c + r, c - r),
            fill=(*_mix(ink, pale, 0.5), 255),
            width=1,
        )
    elif family == "smoke":
        for index in range(3):
            radius = base * (0.45 + values[index] * 0.3)
            x = c + (values[index + 2] - 0.5) * base
            y = c + (values[index + 4] - 0.5) * base
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius), fill=(*ink, 65)
            )
        image = image.filter(ImageFilter.GaussianBlur(base * 0.2))
    elif family == "bubbles":
        r = base * (0.38 + values[2] * 0.15)
        color = _mix(ink, (155, 224, 245) if light_ink else (30, 94, 119), 0.55)
        draw.ellipse(
            (c - r, c - r, c + r, c + r),
            fill=(*color, 12),
            outline=(*color, 190),
            width=1,
        )
        draw.arc(
            (c - r + 2, c - r + 2, c + r - 2, c + r - 2),
            205,
            290,
            fill=(*pale, 240),
            width=2,
        )
        draw.ellipse(
            (c + r * 0.3, c + r * 0.2, c + r * 0.4 + 1, c + r * 0.3 + 1),
            fill=(*pale, 170),
        )
    elif family == "snow":
        color = _mix(ink, (191, 231, 250) if light_ink else (29, 77, 102), 0.5)
        r = base * 0.65
        for branch in range(6):
            angle = branch * math.tau / 6
            dx, dy = math.cos(angle), math.sin(angle)
            draw.line((c, c, c + dx * r, c + dy * r), fill=(*color, 235), width=1)
            for side in (-1, 1):
                tip = angle + side * 0.65
                x, y = c + dx * r * 0.55, c + dy * r * 0.55
                draw.line(
                    (x, y, x - math.cos(tip) * r * 0.28, y - math.sin(tip) * r * 0.28),
                    fill=(*color, 210),
                    width=1,
                )
        draw.ellipse((c - 1, c - 1, c + 1, c + 1), fill=(*pale, 245))
    elif family == "petals":
        from botanical_materials import botanical_sprite, FLOWERS
        kind='petal' if values[0]<.43 else 'leaf' if values[0]<.84 else FLOWERS[min(2,int(values[1]*3))]
        return botanical_sprite(kind,min(12,base*(.55+values[3]*.45)),values)
    elif family == "ribbons":
        points = [
            (
                c + math.sin(t / 16 * math.pi * 2) * base * 0.22,
                c + (t / 16 - 0.5) * base * 2.6,
            )
            for t in range(17)
        ]
        draw.line(points, fill=(*ink, 240), width=max(3, base // 3))
        draw.line(
            [(x - 1, y) for x, y in points], fill=(*_mix(ink, pale, 0.6), 190), width=1
        )
    elif family == "ink":
        r = base * 0.4
        draw.ellipse((c - r, c - r, c + r, c + r), fill=(*ink, 240))
        draw.ellipse(
            (c + base * 0.5, c - base * 0.45, c + base * 0.7, c - base * 0.25),
            fill=(*ink, 190),
        )
        draw.ellipse(
            (c - base * 0.7, c + base * 0.2, c - base * 0.53, c + base * 0.37),
            fill=(*ink, 180),
        )
    elif family == "vortex":
        color = _mix(ink, (150, 205, 255) if light_ink else (50, 79, 155), 0.5)
        r = base * 0.48
        draw.arc((c - r, c - r, c + r, c + r), 20, 260, fill=(*color, 200), width=2)
        draw.ellipse(
            (c + r * 0.7 - 2, c + r * 0.3 - 2, c + r * 0.7 + 2, c + r * 0.3 + 2),
            fill=(*pale, 245),
        )
    elif family == "magnetic":
        color = _mix(ink, (165, 190, 215) if light_ink else (44, 76, 101), 0.45)
        draw.rounded_rectangle(
            (c - base * 0.55, c - base * 0.17, c + base * 0.55, c + base * 0.17),
            radius=1,
            fill=(*color, 245),
            outline=(*pale, 210),
            width=1,
        )
        draw.line(
            (c - base, c - base * 0.5, c - base * 0.4, c - base * 0.5),
            fill=(*color, 115),
            width=1,
        )
    else:
        return None
    return image


def blend_material(source, material, amount):
    """An intact glyph changes into its particle material as it separates."""
    fraction = min(1.0, amount / 0.32)
    if fraction <= 0:
        return source
    if fraction >= 1:
        return material
    size = tuple(max(a, b) for a, b in zip(source.size, material.size))
    result = Image.new("RGBA", size)
    for image, alpha in ((source, 1 - fraction), (material, fraction)):
        piece = image.copy()
        piece.putalpha(piece.getchannel("A").point(lambda value: round(value * alpha)))
        result.alpha_composite(
            piece, ((size[0] - piece.width) // 2, (size[1] - piece.height) // 2)
        )
    return result
