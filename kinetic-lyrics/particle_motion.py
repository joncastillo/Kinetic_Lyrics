"""Glyph-bound fragments with deterministic motion and perspective tumbling."""
from particle_cache import sprite_key


from dataclasses import dataclass
import json
import math
from pathlib import Path
import random

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter
from particle_materials import make_material, blend_material
from particle_morph import prepare_morph
from particle_choreography import dynamics, terminal_particles, entrance_opacity


@dataclass
class Fragment:
    image: Image.Image
    edge: Image.Image
    center: tuple
    random: tuple
    material: Image.Image | None = None
    morph: object = None
    children: tuple = ()


def _glass_children(image, seed):
    """Four irregular sub-shards cover the parent's original glyph surface."""
    rng = random.Random(seed)
    width, height = image.size
    center = (width * rng.uniform(0.3, 0.7), height * rng.uniform(0.3, 0.7))
    corners = [(0, 0), (width, 0), (width, height), (0, height)]
    children = []
    for index in range(4):
        polygon = [corners[index], corners[(index + 1) % 4], center]
        left, top = math.floor(min(p[0] for p in polygon)), math.floor(
            min(p[1] for p in polygon)
        )
        right, bottom = math.ceil(max(p[0] for p in polygon)), math.ceil(
            max(p[1] for p in polygon)
        )
        if right <= left or bottom <= top:
            continue
        points = [(px - left, py - top) for px, py in polygon]
        piece = image.crop((left, top, right, bottom))
        mask = Image.new("L", piece.size)
        ImageDraw.Draw(mask).polygon(points, fill=255)
        piece.putalpha(ImageChops.multiply(piece.getchannel("A"), mask))
        if piece.getchannel("A").getbbox() is None:
            continue
        edge = Image.new("RGBA", piece.size)
        ImageDraw.Draw(edge).line(
            points + points[:1], fill=(220, 242, 255, 220), width=1
        )
        edge.putalpha(ImageChops.multiply(edge.getchannel("A"), piece.getchannel("A")))
        children.append(
            Fragment(
                piece,
                edge,
                ((left + right) / 2, (top + bottom) / 2),
                tuple(rng.random() for _ in range(8)),
            )
        )
    return tuple(children)


def _clip(polygon, nx, ny, limit):
    result = []
    previous = polygon[-1]
    before = previous[0] * nx + previous[1] * ny - limit
    for point in polygon:
        after = point[0] * nx + point[1] * ny - limit
        if (after <= 0) != (before <= 0):
            fraction = before / (before - after)
            result.append(
                (
                    previous[0] + fraction * (point[0] - previous[0]),
                    previous[1] + fraction * (point[1] - previous[1]),
                )
            )
        if after <= 0:
            result.append(point)
        previous, before = point, after
    return result


def fracture_cells(size, count, seed):
    """Jittered Voronoi cells share crack edges instead of rectangular tile seams."""
    width, height = size
    rng = random.Random(seed)
    columns = max(2, round(math.sqrt(count * width / height)))
    rows = max(2, round(count / columns))
    sites = [
        (
            (x + rng.uniform(0.12, 0.88)) * width / columns,
            (y + rng.uniform(0.12, 0.88)) * height / rows,
        )
        for y in range(rows)
        for x in range(columns)
    ]
    polygons = []
    for ax, ay in sites:
        polygon = [
            (0.0, 0.0),
            (float(width), 0.0),
            (float(width), float(height)),
            (0.0, float(height)),
        ]
        for bx, by in sites:
            if (ax, ay) == (bx, by):
                continue
            polygon = _clip(
                polygon, bx - ax, by - ay, (bx * bx + by * by - ax * ax - ay * ay) / 2
            )
            if not polygon:
                break
        if len(polygon) >= 3:
            polygons.append(polygon)
    return polygons


def build_fragments(sprite, effect, seed, intensity):
    rng = random.Random(seed)
    granularity = {
        "dust": 2.8,
        "sparks": 2.1,
        "snow": 2.1,
        "smoke": 1.6,
        "bubbles": 1.6,
        "vortex": 1.8,
        "magnetic": 1.5,
    }.get(effect.family, 1.0)
    count = max(16, min(180, round(65 * effect.density * intensity * granularity)))
    width, height = sprite.size
    if effect.family not in ("pixels", "ribbons"):
        cells = fracture_cells(sprite.size, count, seed)
    else:
        tile = max(2, math.ceil(math.sqrt(width * height / count)))
        tw, th = (
            (max(2, tile // 2), height) if effect.family == "ribbons" else (tile, tile)
        )
        cells = [
            [
                (x, y),
                (min(width, x + tw), y),
                (min(width, x + tw), min(height, y + th)),
                (x, min(height, y + th)),
            ]
            for y in range(0, height, th)
            for x in range(0, width, tw)
        ]
    fragments = []
    for polygon in cells:
        left = max(0, math.floor(min(x for x, y in polygon)))
        top = max(0, math.floor(min(y for x, y in polygon)))
        right = min(width, math.ceil(max(x for x, y in polygon)))
        bottom = min(height, math.ceil(max(y for x, y in polygon)))
        if right <= left or bottom <= top:
            continue
        points = [(x - left, y - top) for x, y in polygon]
        piece = sprite.crop((left, top, right, bottom))
        mask = Image.new("L", piece.size)
        ImageDraw.Draw(mask).polygon(points, fill=255)
        piece.putalpha(ImageChops.multiply(piece.getchannel("A"), mask))
        if piece.getchannel("A").getbbox() is None:
            continue
        edge = Image.new("RGBA", piece.size)
        ImageDraw.Draw(edge).line(
            points + points[:1], fill=(220, 242, 255, 220), width=1
        )
        edge.putalpha(ImageChops.multiply(edge.getchannel("A"), piece.getchannel("A")))
        values = tuple(rng.random() for _ in range(8))
        material = make_material(effect.family, piece, values)
        fragments.append(
            Fragment(
                piece,
                edge,
                ((left + right) / 2, (top + bottom) / 2),
                values,
                material,
                prepare_morph(material, piece) if material is not None else None,
                (
                    _glass_children(piece, seed + round(left) * 79 + round(top) * 151)
                    if effect.family == "glass"
                    else ()
                ),
            )
        )
    return fragments


def _alpha(image, value):
    if value >= 1:
        return image
    result = image.copy()
    result.putalpha(image.getchannel("A").point(lambda a: round(a * max(0.0, value))))
    return result


def _rotation(ax, ay, az):
    cx, sx, cy, sy, cz, sz = (
        math.cos(ax),
        math.sin(ax),
        math.cos(ay),
        math.sin(ay),
        math.cos(az),
        math.sin(az),
    )
    return (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )


def _combine(a, b):
    return tuple(
        tuple(sum(a[row][k] * b[k][column] for k in range(3)) for column in range(3))
        for row in range(3)
    )


def tumble(image, ax, ay, az, scale, parent=None):
    """Project a rotating plane; its inverse affine map preserves edge-on flips."""
    cx, sx, cy, sy, cz, sz = (
        math.cos(ax),
        math.sin(ax),
        math.cos(ay),
        math.sin(ay),
        math.cos(az),
        math.sin(az),
    )
    a = cz * cy
    b = cz * sy * sx - sz * cx
    c = sz * cy
    d = sz * sy * sx + cz * cx
    if parent is not None:
        rotation = _combine(parent, _rotation(ax, ay, az))
        a, b = rotation[0][:2]
        c, d = rotation[1][:2]
    a, b, c, d = (v * scale for v in (a, b, c, d))
    determinant = a * d - b * c
    if abs(determinant) < 0.012:
        return None
    width, height = image.size
    out_w = max(1, math.ceil(abs(a) * width + abs(b) * height))
    out_h = max(1, math.ceil(abs(c) * width + abs(d) * height))
    ia, ib, ic, id_ = (
        d / determinant,
        -b / determinant,
        -c / determinant,
        a / determinant,
    )
    transform = (
        ia,
        ib,
        width / 2 - ia * out_w / 2 - ib * out_h / 2,
        ic,
        id_,
        height / 2 - ic * out_w / 2 - id_ * out_h / 2,
    )
    return image.transform(
        (out_w, out_h),
        Image.Transform.AFFINE,
        transform,
        resample=Image.Resampling.BICUBIC,
    )


def _paint_splinters(layer, fragment, center, motion, effect, height, alpha):
    """Children inherit the parent pose/trajectory before gaining a new impulse."""
    elapsed = (motion - 0.48) / 0.52
    values = fragment.random
    ax, ay, az = (
        (values[4] - 0.5) * 8 * motion * effect.spin,
        (values[5] - 0.5) * 10 * motion * effect.spin,
        (values[6] - 0.5) * 7 * motion * effect.spin,
    )
    parent = _rotation(ax, ay, az)
    depth = 1 / (1 - (values[7] - 0.5) * motion * 0.65)
    for child in fragment.children:
        r = child.random
        delta = (
            (r[2] - 0.5) * 24 * elapsed * effect.spin,
            (r[3] - 0.5) * 28 * elapsed * effect.spin,
            (r[4] - 0.5) * 22 * elapsed * effect.spin,
        )
        rotation = _combine(parent, _rotation(*delta))
        normal = [rotation[row][2] for row in range(3)]
        brightness = 0.5 + 0.65 * abs(
            normal[0] * 0.4 - normal[1] * 0.6 + normal[2] * 0.7
        )
        piece = ImageEnhance.Brightness(child.image).enhance(brightness)
        piece.alpha_composite(_alpha(child.edge, 0.3 + 0.6 * (1 - abs(normal[2]))))
        piece = tumble(piece, *delta, depth, parent=parent)
        if piece is None:
            continue
        local_x = child.center[0] - fragment.image.width / 2
        local_y = child.center[1] - fragment.image.height / 2
        offset_x = (parent[0][0] * local_x + parent[0][1] * local_y) * depth
        offset_y = (parent[1][0] * local_x + parent[1][1] * local_y) * depth
        kick = height * (0.45 + r[0]) * 0.9 * elapsed
        offset_x += math.cos(r[1] * math.tau) * kick
        offset_y += math.sin(r[1] * math.tau) * kick + height * 0.5 * elapsed * elapsed
        piece = _alpha(piece, alpha * (1 - 0.15 * elapsed))
        layer.alpha_composite(
            piece,
            (
                round(center[0] + offset_x - piece.width / 2),
                round(center[1] + offset_y - piece.height / 2),
            ),
        )


def _cracked(sprite, fragments, amount):
    result = sprite.copy()
    reveal = min(1.0, amount / 0.12)
    for fragment in fragments:
        if fragment.random[0] > reveal:
            continue
        edge = _alpha(fragment.edge, 0.7)
        x = round(fragment.center[0] - edge.width / 2)
        y = round(fragment.center[1] - edge.height / 2)
        shadow = Image.new("RGBA", edge.size, (10, 18, 27, 0))
        shadow.putalpha(edge.getchannel("A"))
        result.alpha_composite(shadow, (x + 1, y + 1))
        result.alpha_composite(edge, (x, y))
    result.putalpha(sprite.getchannel("A"))
    return result


READABLE_AT = 0.85
GONE_AT = 0.25
_PACING = None


def measured_pacing(phase, effect):
    """Audited progress at which a recipe's word is readable (entrance) or mostly gone (exit)."""
    global _PACING
    if _PACING is None:
        try:
            _PACING = json.loads((Path(__file__).with_name('particles')/'pacing.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _PACING = {}
    return _PACING.get(f'{phase}/{getattr(effect, "id", "")}')


def warp(progress, measured, target):
    """Piecewise-linear retiming that moves `measured` to `target` and keeps both endpoints."""
    if progress <= target:
        return progress*measured/target
    return measured+(progress-target)*(1-measured)/(1-target)


def paint_transition(
    layer,
    sprite,
    x,
    y,
    phase,
    amount,
    effect,
    seed,
    intensity=1.0,
    energy=0.5,
    cache=None,
    glyph_spans=None,
    paced=True,
):
    """amount=0 is intact; amount=1 is dispersed. No frame-history state."""
    amount = max(0.0, min(1.0, amount))
    measured = measured_pacing(phase, effect) if paced else None
    if measured:
        amount = 1-warp(1-amount, measured, READABLE_AT) if phase == 'entrance' else warp(amount, measured, GONE_AT)
    if phase=='entrance' and effect.trajectory=='grow' and intensity>0:
        if effect.family=='petals':
            from botanical_growth import paint_growth,grown_sprite
        else:
            from material_growth import paint_growth,grown_sprite
        extra={'glyph_spans':glyph_spans} if effect.family=='trees' else {}
        if amount<=.001:
            held,padding=grown_sprite(sprite,effect,seed,intensity,cache,**extra)
            layer.alpha_composite(held,(round(x)-padding,round(y)-padding))
        else:
            paint_growth(layer,sprite,x,y,1-amount,effect,seed,intensity,cache,**extra)
        return
    if (
        phase == "entrance"
        and getattr(effect, "hold", "solid") == "particles"
        and intensity > 0
    ):
        from petal_formation import paint_petal_formation, petal_word

        if amount <= 0.001:
            layer.alpha_composite(
                petal_word(sprite, effect, seed, intensity, cache), (round(x), round(y))
            )
        else:
            paint_petal_formation(
                layer, sprite, x, y, amount, effect, seed, intensity, cache
            )
        return
    if amount <= 0.001 or intensity <= 0:
        layer.alpha_composite(sprite, (round(x), round(y)))
        return
    if amount >= 1:
        return
    if effect.family == 'cinematic':
        from cinematic_particles import paint_cinematic
        paint_cinematic(layer,sprite,x,y,phase,amount,effect,seed,intensity,cache)
        return
    if effect.family == "letters":
        from letter_motion import paint_spinning_letters

        paint_spinning_letters(layer, sprite, x, y, amount, effect, seed, glyph_spans)
        return
    key = (sprite_key(sprite), effect, seed, intensity)
    if cache is None:
        fragments = build_fragments(sprite, effect, seed, intensity)
    else:
        if key not in cache:
            cache[key] = build_fragments(sprite, effect, seed, intensity)
        fragments = cache[key]
    if effect.family == "glass" and phase == "exit":
        if amount <= 0.25:
            layer.alpha_composite(
                _cracked(sprite, fragments, amount), (round(x), round(y))
            )
            return
        amount = (amount - 0.25) / 0.75
    distance = sprite.height * effect.spread * (0.65 + energy * 0.6)
    for fragment in fragments:
        r = fragment.random
        delay = effect.stagger * r[0]
        if phase == "entrance":
            arrival = max(0.0, min(1.0, ((1 - amount) - delay) / (1 - delay)))
            motion = 1 - arrival * arrival * (3 - 2 * arrival)
        else:
            motion = max(0.0, min(1.0, (amount - delay) / (1 - delay)))
        angle = (
            math.atan2(
                fragment.center[1] - sprite.height * 0.5,
                fragment.center[0] - sprite.width * 0.5,
            )
            + (r[1] - 0.5) * 0.8
        )
        travel = distance * (0.45 + r[2]) * motion
        if effect.trajectory == "spiral":
            angle += effect.twist * motion
        dx, dy = math.cos(angle) * travel, math.sin(angle) * travel * 0.8
        if effect.trajectory in ("left", "right"):
            dx = travel * (-1 if effect.trajectory == "left" else 1)
            dy *= 0.4
        elif effect.trajectory in ("up", "down"):
            dy = travel * (-1 if effect.trajectory == "up" else 1)
            dx *= 0.5
        elif effect.trajectory == "wave":
            dx = travel * (1 if r[1] > 0.5 else -1)
            dy = math.sin(r[3] * math.tau + motion * 6) * travel * 0.5
        elif effect.trajectory == "fan":
            dx = (fragment.center[0] / sprite.width - 0.5) * travel * 2
            dy = -travel * (0.3 + r[3] * 0.7)
        family = effect.family
        if family == "vortex":
            direction = -1 if effect.trajectory in ("left", "down") else 1
            turns = (
                effect.twist
                if effect.trajectory == "spiral"
                else 2.5 if effect.trajectory == "fan" else 5
            )
            dx, dy = (
                math.cos(angle + motion * turns * direction) * travel,
                math.sin(angle + motion * turns * direction) * travel * 0.7,
            )
        elif family == "magnetic":
            dx += math.sin(motion * math.pi * 3) * sprite.height * 0.3 * motion
            dy *= 0.2
        elif family == "sparks":
            dy -= travel * 0.65
        elif family in ("dust", "smoke"):
            dx += math.sin(r[3] * math.tau + motion * 4) * travel * 0.35
            dy -= travel * 0.5
        elif family == "ribbons":
            dy += math.sin(r[3] * math.tau + motion * 8) * travel * 0.3
        elif family == "bubbles":
            dy = -abs(travel)
            dx += math.sin(motion * 8 + r[3] * math.tau) * travel * 0.25
        elif family == "ink":
            dy += travel * motion
        dy += sprite.height * effect.gravity * motion * motion
        drift_x, drift_y, material_scale, spin_rate = dynamics(
            family, motion, r, sprite.height
        )
        dx += drift_x
        dy += drift_y
        piece = fragment.image
        if phase == "entrance" and fragment.morph is not None:
            fraction = min(1.0, max(0.0, 1 - motion / 0.45))
            fraction = fraction * fraction * (3 - 2 * fraction)
            piece = fragment.morph.frame(fraction)
        elif fragment.material is not None:
            piece = blend_material(piece, fragment.material, motion)
        if family == "pixels":
            step = max(3, sprite.height * 0.06)
            dx, dy = round(dx / step) * step, round(dy / step) * step
        alpha = max(0.0, 1 - motion**2)
        if phase == "entrance":
            alpha = entrance_opacity(1 - amount)
        if family == "glass":
            if phase == "exit" and motion >= 0.48 and fragment.children:
                _paint_splinters(
                    layer,
                    fragment,
                    (x + fragment.center[0] + dx, y + fragment.center[1] + dy),
                    motion,
                    effect,
                    sprite.height,
                    alpha,
                )
                continue
            ax, ay, az = (
                (r[4] - 0.5) * 8 * motion * effect.spin,
                (r[5] - 0.5) * 10 * motion * effect.spin,
                (r[6] - 0.5) * 7 * motion * effect.spin,
            )
            brightness = 0.65 + 0.5 * abs(math.cos(ax) * math.cos(ay))
            piece = ImageEnhance.Brightness(piece).enhance(brightness)
            piece.alpha_composite(_alpha(fragment.edge, 0.35 + 0.6 * abs(math.sin(ay))))
            depth = 1 / (1 - (r[7] - 0.5) * motion * 0.65)
            piece = tumble(piece, ax, ay, az, depth)
            if piece is None:
                continue
            alpha *= 1 - 0.12 * motion
        else:
            rotation = (r[4] - 0.5) * 300 * motion * effect.spin * spin_rate
            if family in ("petals", "snow", "ribbons"):
                piece = tumble(
                    piece,
                    motion * (r[5] + 0.2) * 5,
                    motion * r[6] * 4,
                    math.radians(rotation),
                    1.0,
                )
                if piece is None:
                    continue
            else:
                sx, sy = 1.0, 1.0
                if family == "sparks":
                    sx, sy = 1 + motion * 2, max(0.15, 1 - motion * 0.7)
                elif family == "ink":
                    sx, sy = max(0.25, 1 - motion * 0.6), 1 + motion * 2
                elif family in ("smoke", "bubbles"):
                    sx = sy = 1 + motion * 0.8
                piece = piece.resize(
                    (max(1, round(piece.width * sx)), max(1, round(piece.height * sy))),
                    Image.Resampling.BICUBIC,
                )
                if family == "smoke":
                    piece = piece.filter(ImageFilter.GaussianBlur(motion * 2))
                piece = piece.rotate(rotation, Image.Resampling.BICUBIC, expand=True)
            if abs(material_scale - 1) > 0.005:
                piece = piece.resize(
                    (
                        max(1, round(piece.width * material_scale)),
                        max(1, round(piece.height * material_scale)),
                    ),
                    Image.Resampling.BICUBIC,
                )
            if phase == "exit" and terminal_particles(
                layer,
                (x + fragment.center[0] + dx, y + fragment.center[1] + dy),
                piece,
                family,
                motion,
                r,
                alpha,
            ):
                continue
        piece = _alpha(piece, alpha)
        layer.alpha_composite(
            piece,
            (
                round(x + fragment.center[0] + dx - piece.width / 2),
                round(y + fragment.center[1] + dy - piece.height / 2),
            ),
        )
