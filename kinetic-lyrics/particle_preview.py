"""Bounded, cached animated samples of the exact declarative effect selected."""

from functools import lru_cache
from io import BytesIO
from threading import Semaphore

from PIL import Image, ImageDraw, ImageFont

from kinetic_effects import paint_word

_RENDER_SLOTS = Semaphore(2)


@lru_cache(maxsize=16)
def render_preview(effect, phase, intensity=1.0, speed=1.0,font_family="auto",font_style="auto",font_scale=1.25):
    with _RENDER_SLOTS:
        growing=effect.trajectory=='grow'
        detailed=growing or effect.family=='cinematic'
        canvas=(800,450) if detailed else (480,240)
        from typography_settings import selected_font,typography_options
        typography_options(dict(font_family=font_family,font_style=font_style,font_scale=font_scale))
        font_path=str(selected_font(font_family,font_style) or 'C:/Windows/Fonts/seguisb.ttf')
        font=ImageFont.truetype(font_path,round((96 if detailed else 62)*font_scale))
        small = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 14)
        label = {'prismatic-helix':'PRISM','prismatic-singularity':'PRISM','aurora-silk-unravel':'SILK','liquid-chrome-assembly':'CHROME','liquid-chrome-collapse':'CHROME','ember-forge':'EMBER','ember-ash-drift':'EMBER','old-oak-lettering':'OAK','autumn-maple-lettering':'MAPLE','clockwork-lettering':'GEARS','folded-paper-lettering':'PAPER','obsidian-lattice-lettering':'VOID','gold-filigree-lettering':'GILDED','pearl-lace-lettering':'LACE','jeweled-brocade-lettering':'JEWEL','luminous-coral-lettering':'CORAL','frost-crystal-lettering':'FROST','ink-bloom-lettering':'INK','thread-stitch-lettering':'STITCH'}.get(effect.id,'BLOOM' if effect.family=='petals' else effect.family.upper())
        while font.getlength(label) > canvas[0]-80:
            font = ImageFont.truetype(font_path, font.size - 2)
        bounds = font.getbbox(label)
        sprite = Image.new(
            "RGBA", (bounds[2] - bounds[0] + 24, bounds[3] - bounds[1] + 24)
        )
        ImageDraw.Draw(sprite).text(
            (12 - bounds[0], 12 - bounds[1]), label, font=font, fill="#edf1f5"
        )
        x, y = (canvas[0] - sprite.width) // 2, (canvas[1] - sprite.height) // 2
        catalog = {"entrance": {}, "exit": {}}
        catalog[phase][effect.id] = effect
        glyph_bounds = (
            [0]
            + [
                round(12 + font.getlength(label[:index]))
                for index in range(1, len(label))
            ]
            + [sprite.width]
        )
        spans = list(zip(glyph_bounds, glyph_bounds[1:]))
        cache, frames = {}, []
        transition = (1.8 if detailed else .8) / speed
        duration = 0.7 + transition + 0.35
        fps = 20
        for number in range(round(duration * fps)):
            t = number / fps
            frame = Image.new("RGBA", canvas, "#111a21")
            layer = Image.new("RGBA", frame.size)
            progress, fade = 1.0, 1.0
            if phase == "entrance":
                p = min(1.0, max(0.0, (t - 0.25) / transition))
                progress = p * p * (3 - 2 * p)
            else:
                fade = min(1.0, max(0.0, 1 - (t - 0.65) / transition))
            paint_word(
                layer,
                sprite,
                x,
                y,
                progress,
                fade,
                t,
                4,
                "none",
                intensity=intensity,
                entrance_effect=effect.id if phase == "entrance" else "none",
                exit_effect=effect.id if phase == "exit" else "none",
                effect_catalog=catalog,
                cache=cache,
                glyph_spans=spans,
            )
            frame.alpha_composite(layer)
            draw = ImageDraw.Draw(frame)
            draw.text((16, 14), f"{effect.name} / {phase}", font=small, fill="#b5c4ce")
            frames.append(frame.convert("RGB"))
        result = BytesIO()
        frames[0].save(
            result,
            format="GIF",
            append_images=frames[1:],
            save_all=True,
            duration=round(1000 / fps),
            loop=0,
            disposal=2,
        )
        return result.getvalue()


@lru_cache(maxsize=24)
def render_text_preview(animation,font_family="auto",font_style="auto",font_scale=1.25,speed=1.):
    from kinetic_director import Compositor, rules_plan
    from kinetic_lyrics import theme_for

    data = [
        dict(
            text="Move with time",
            words=[
                dict(text="Move", start=2., end=2.8),
                dict(text="with", start=2.8, end=3.5),
                dict(text="time", start=3.5, end=4.6),
            ],
        )
    ]
    plan = rules_plan(data, theme_for("bright"))
    plan["scenes"][0].update(style="swiss", align="center")
    compositor = Compositor(
        data,
        plan,
        480,
        240,
        6.1,
        text_animation=animation,font_family=font_family,font_style=font_style,font_scale=font_scale,particle_speed=speed,
        entrance_effect="none",
        exit_effect="none",
    )
    with _RENDER_SLOTS:
        frames = [compositor.frame(index / 14) for index in range(86)]
        result = BytesIO()
        frames[0].save(
            result,
            format="GIF",
            append_images=frames[1:],
            save_all=True,
            duration=71,
            loop=0,
            disposal=2,
        )
        return result.getvalue()
