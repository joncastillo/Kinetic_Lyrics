"""Deterministic raster typography effects; illustration layers stay untouched."""

from core.imaging import turn
import math
from PIL import Image, ImageDraw, ImageChops

PARTICLE_EFFECTS = ("sparks", "dust", "trails", "fragments", "orbits", "confetti")
EFFECTS = ("none", "mixed", *PARTICLE_EFFECTS, "shatter", "melt", "slime", "liquid")
LETTER_MIX = ("shatter", "melt", "liquid", "slime", "dust", "fragments")
TEXT_ANIMATIONS = ("ai", "mixed", "directed", "highlight", "karaoke", "slide", "fade", "none")


def highlight_word(sprite, color, fraction, glyph_mask=None):
    """Preserve the glyph alpha while revealing accent ink from left to right."""
    fraction = max(0.0, min(1.0, fraction))
    if fraction <= 0:
        return sprite
    glyph_mask = sprite.getchannel('A') if glyph_mask is None else glyph_mask
    bounds = glyph_mask.getbbox()
    if not bounds:
        return sprite
    right = round(bounds[0] + (bounds[2] - bounds[0]) * fraction)
    mask = Image.new("L", sprite.size)
    ImageDraw.Draw(mask).rectangle((0, 0, right - 1, sprite.height), fill=255)
    tint = Image.new("RGBA", sprite.size, color)
    tint.putalpha(ImageChops.multiply(glyph_mask,mask))
    result = sprite.copy()
    result.alpha_composite(tint)
    result.putalpha(sprite.getchannel("A"))
    return result


def highlight_overlay(size, color, fraction, glyph_mask, strength=0.85):
    """Accent ink shaped like the glyphs, revealed left to right, to lay over material lettering."""
    bounds = glyph_mask.getbbox()
    if fraction <= 0 or not bounds:
        return None
    right = round(bounds[0] + (bounds[2] - bounds[0]) * min(1.0, fraction))
    region = Image.new("L", size)
    ImageDraw.Draw(region).rectangle((0, 0, right - 1, size[1]), fill=255)
    overlay = Image.new("RGBA", size, color)
    overlay.putalpha(ImageChops.multiply(glyph_mask, region).point(lambda a: round(a * strength)))
    return overlay


def selected_effect(choice, scene):
    return (
        LETTER_MIX[scene.get("effect_index", 0) % len(LETTER_MIX)]
        if choice == "mixed"
        else choice
    )


def paint_particles(
    layer,
    anchors,
    elapsed,
    duration,
    effect,
    ink,
    accent,
    seed,
    intensity=1.0,
    speed=1.0,
):
    """Composite the GPU-rendered 3D layer into the final video frame."""
    if effect not in PARTICLE_EFFECTS or not anchors or intensity <= 0:
        return
    from effects.particles.gl import render_particles

    layer.alpha_composite(
        render_particles(
            layer.size,
            anchors,
            elapsed,
            duration,
            effect,
            ink,
            accent,
            seed,
            intensity,
            speed,
        )
    )


def opacity(image, alpha):
    if alpha >= 0.999:
        return image
    result = image.copy()
    result.putalpha(result.getchannel("A").point(lambda a: round(a * max(0.0, alpha))))
    return result


def paint_word(
    layer,
    sprite,
    x,
    y,
    progress,
    fade,
    elapsed,
    word,
    effect,
    energy=0.5,
    glyph_spans=None,
    intensity=1.0,
    speed=1.0,
    entrance_effect=None,
    exit_effect=None,
    effect_catalog=None,
    cache=None,
):
    """Readable holds with assembled entrances, viscous exits or buoyant glyphs."""
    if sprite.getchannel("A").getbbox() is None:
        return
    x, y = round(x), round(y)
    intensity = max(0.0, min(2.0, float(intensity)))
    speed = max(0.1, min(5.0, float(speed)))
    elapsed *= speed
    strength = (0.55 + 0.45 * energy) * (0.6 + 0.4 * intensity)
    if intensity <= 0:
        effect = "none"
    alpha = progress * fade
    if entrance_effect is not None or exit_effect is not None:
        from effects.particles.motion import paint_transition

        phase = "exit" if fade < 1 else "entrance"
        if phase == "exit" and effect_catalog is not None:
            entrance = effect_catalog["entrance"].get(entrance_effect)
            if (
                entrance is not None
                and getattr(entrance, "hold", "solid") == "particles"
                and intensity > 0
            ):
                from effects.particles.petals import petal_word

                if entrance.trajectory=='grow':
                    if entrance.family=='petals':
                        from effects.growth.botanical import grown_sprite
                    else:
                        from effects.growth.material import grown_sprite
                    extra={'glyph_spans':glyph_spans} if entrance.family=='trees' else {}
                    sprite,padding=grown_sprite(sprite,entrance,word,intensity,cache,**extra)
                    x-=padding;y-=padding
                else:
                    sprite = petal_word(sprite, entrance, word, intensity, cache)
        effect = (exit_effect if phase == "exit" else entrance_effect) or "none"
        if (
            effect_catalog is not None
            and effect in effect_catalog[phase]
            and intensity > 0
        ):
            amount = 1 - (fade if phase == "exit" else progress)
            paint_transition(
                layer,
                sprite,
                x,
                y,
                phase,
                amount,
                effect_catalog[phase][effect],
                word,
                intensity,
                energy,
                cache,
                glyph_spans=glyph_spans,
            )
            return
        if intensity <= 0:
            effect = "none"
    if effect in PARTICLE_EFFECTS:
        paint_letter_particles(
            layer,
            sprite,
            x,
            y,
            progress,
            fade,
            elapsed,
            word,
            effect,
            strength,
            intensity,
        )
        return
    if effect == "none":
        layer.alpha_composite(opacity(sprite, alpha), (x, y))
        return
    if effect == "shatter":
        from effects.particles.catalog import discover_effects
        from effects.particles.motion import paint_transition

        recipe = discover_effects()["exit"].get("glass-shatter")
        if recipe is None:
            layer.alpha_composite(opacity(sprite, alpha), (x, y))
        elif fade >= 1:
            layer.alpha_composite(opacity(sprite, progress), (x, y))
        else:
            paint_transition(
                layer,
                sprite,
                x,
                y,
                "exit",
                1 - fade,
                recipe,
                word,
                intensity,
                energy,
                cache,
            )
        return
    if effect == "melt":
        amount = (1 - fade) * strength
        if amount < 0.002:
            layer.alpha_composite(opacity(sprite, alpha), (x, y))
            return
        stripe = max(2, sprite.height // 22)
        for sx in range(0, sprite.width, stripe):
            piece = sprite.crop((sx, 0, min(sprite.width, sx + stripe), sprite.height))
            drop = (
                amount
                * sprite.height
                * (0.2 + 2.2 * (0.5 + 0.5 * math.sin(sx * 0.071 + word * 2)) ** 3)
            )
            piece = piece.resize(
                (piece.width, max(1, round(piece.height + drop * 0.8))),
                Image.Resampling.BICUBIC,
            )
            layer.alpha_composite(opacity(piece, alpha), (x + sx, round(y + drop)))
        return
    if effect == "slime":
        squish = (1 - progress) * 0.65 + (1 - fade) * 0.75
        width = max(1, round(sprite.width * (1 + 0.2 * squish)))
        height = max(1, round(sprite.height * (1 - 0.48 * squish)))
        slime = sprite.resize((width, height), Image.Resampling.BICUBIC)
        px, py = round(x + (sprite.width - width) / 2), round(
            y + sprite.height - height
        )
        layer.alpha_composite(opacity(slime, alpha), (px, py))
        if squish > 0.03:
            color = next(
                (
                    sprite.getpixel((sx, sprite.height // 2))[:3]
                    for sx in range(0, sprite.width, max(1, sprite.width // 20))
                    if sprite.getpixel((sx, sprite.height // 2))[3] > 200
                ),
                (180, 220, 130),
            )
            draw = ImageDraw.Draw(layer)
            for k in range(4):
                radius = max(1, sprite.height * 0.035 * (1 + k % 2) * squish)
                cx = x + sprite.width * (k + 0.5) / 4
                cy = (
                    y + sprite.height + (1 - fade) * sprite.height * 0.5 * (0.5 + k / 5)
                )
                draw.ellipse(
                    (cx - radius, cy - radius * 1.8, cx + radius, cy + radius * 1.8),
                    fill=(*color, round(200 * alpha * squish)),
                )
        return
    spans = glyph_spans or [(0, sprite.width)]
    for k, (left, right) in enumerate(spans):
        if right <= left:
            continue
        piece = sprite.crop((left, 0, right, sprite.height))
        buoyancy = (
            math.sin(elapsed * 1.65 + k * 0.55 + word) * sprite.height * 0.14 * strength
        )
        tilt = math.sin(elapsed * 1.3 + k * 0.55 + word) * 6 * strength
        piece = turn(opacity(piece, alpha), tilt)
        layer.alpha_composite(
            piece,
            (round(x + left - (piece.width - (right - left)) / 2), round(y + buoyancy)),
        )
    draw = ImageDraw.Draw(layer)
    for wave in range(2):
        points = [
            (
                x + sx,
                y
                + sprite.height * (1.08 + wave * 0.07)
                + math.sin(sx * 0.08 - elapsed * 1.8 + wave) * sprite.height * 0.025,
            )
            for sx in range(0, sprite.width + 1, max(2, sprite.width // 45))
        ]
        if len(points) > 1:
            draw.line(points, fill=(130, 195, 210, round(55 * alpha)), width=1)
    for k in range(3):
        phase = (elapsed * 0.22 + k * 0.34 + word * 0.13) % 1
        cx = x + sprite.width * (0.18 + k * 0.3)
        cy = y + sprite.height * (1.35 - phase * 0.65)
        r = max(1, sprite.height * 0.025)
        draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            outline=(180, 210, 220, round(65 * alpha)),
            width=1,
        )


def paint_letter_particles(
    layer,
    sprite,
    x,
    y,
    progress,
    fade,
    elapsed,
    word,
    effect,
    strength=1.0,
    intensity=1.0,
):
    """Break the actual glyph mask into moving pieces, with an intact reading hold."""
    motion = max(1 - progress, 1 - fade)
    if motion < 0.002:
        layer.alpha_composite(opacity(sprite, fade), (x, y))
        return
    limit = max(24, int(90 * intensity))
    tile = max(3, math.ceil(math.sqrt(sprite.width * sprite.height / limit)))
    alpha = min(1.0, progress * 3) * fade
    if alpha <= 0:
        return
    for row, sy in enumerate(range(0, sprite.height, tile)):
        for col, sx in enumerate(range(0, sprite.width, tile)):
            piece = sprite.crop(
                (sx, sy, min(sprite.width, sx + tile), min(sprite.height, sy + tile))
            )
            if piece.getchannel("A").getbbox() is None:
                continue
            seed = (row * 73 + col * 151 + word * 97) % 997
            angle = seed * 0.61803398875 * math.tau
            spread = sprite.height * (0.5 + (seed % 79) / 79 * 1.7) * motion * strength
            dx = math.cos(angle) * spread
            dy = math.sin(angle) * spread * 0.7
            if effect == "dust":
                dx += (elapsed * 0.4 + seed % 7) * motion * sprite.height * 0.08
                dy -= motion * sprite.height * (0.3 + (seed % 5) * 0.12)
            elif effect == "sparks":
                dy -= spread * 0.65
            elif effect == "trails":
                dx = -(1 if word % 2 else -1) * spread
                dy = math.sin(angle + elapsed) * sprite.height * 0.12 * motion
            elif effect == "orbits":
                dx = math.cos(angle + elapsed * 2) * spread
                dy = math.sin(angle + elapsed * 2) * spread * 0.55
            elif effect == "confetti":
                dy += sprite.height * motion * motion * 1.2
            rotation = (
                math.sin(angle + elapsed) * 95 * motion
                if effect in ("confetti", "fragments", "orbits")
                else 0
            )
            piece = turn(opacity(piece, alpha), rotation)
            layer.alpha_composite(
                piece,
                (
                    round(x + sx + dx - (piece.width - tile) / 2),
                    round(y + sy + dy - (piece.height - tile) / 2),
                ),
            )
