"""Bounded, cached animated samples of the exact declarative effect selected."""

from functools import lru_cache
from io import BytesIO
import os
from threading import Semaphore

from PIL import Image, ImageDraw, ImageFont

from render.text_effects import paint_word

_RENDER_SLOTS = Semaphore(1)


def _render_effect(effect, phase, intensity=1.0, speed=1.0,font_family="auto",font_style="auto",font_scale=1.25):
    with _RENDER_SLOTS:
        growing=effect.trajectory=='grow'
        detailed=growing or effect.family=='cinematic'
        canvas=(800,450) if detailed else (480,240)
        from render.typography_settings import selected_font, typography_options
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


def _render_text(animation,font_family="auto",font_style="auto",font_scale=1.25,speed=1.):
    from render.compositor import Compositor; from direction.typography import rules_plan
    from direction.theme import theme_for

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


_POOL = None
PREVIEW_SOURCES = ('effects/particles/preview.py', 'render/compositor.py', 'render/text_effects.py', 'effects/particles/motion.py',
                   'render/line_arrival.py', 'render/typography_settings.py', 'effects/particles/cinematic.py',
                   'effects/growth/material.py', 'effects/growth/botanical.py', 'effects/growth/arboreal.py',
                   'effects/growth/ornate.py', 'effects/growth/mechanical.py', 'effects/particles/petals.py')


def _pool():
    """Persistent worker processes, so many samples render at once without holding the server's GIL."""
    global _POOL
    if _POOL is None:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        from render.parallel import hardware
        _POOL = ProcessPoolExecutor(max_workers=max(2, min(12, hardware()[0]-2)), mp_context=multiprocessing.get_context('spawn'))
    return _POOL


def _source_version():
    from pathlib import Path
    from core.paths import PROJECT_ROOT, SRC_ROOT
    paths = [SRC_ROOT/name for name in PREVIEW_SOURCES]+sorted((PROJECT_ROOT/'particles').rglob('*.json'))
    return max((path.stat().st_mtime_ns for path in paths if path.exists()), default=0)


def _cached(kind, args, renderer):
    """Disk-cached sample, invalidated whenever the renderer or recipes change."""
    import hashlib
    from pathlib import Path
    from core.paths import PROJECT_ROOT
    folder = PROJECT_ROOT/'.preview-cache'
    key = hashlib.sha256(repr((kind, args, _source_version())).encode()).hexdigest()[:32]
    target = folder/f'{key}.gif'
    try:
        return target.read_bytes()
    except OSError:
        pass
    data = _pool().submit(renderer, *args).result()
    folder.mkdir(exist_ok=True)
    temporary = target.with_suffix(f'.{os.getpid()}.tmp')
    temporary.write_bytes(data)
    temporary.replace(target)
    return data


@lru_cache(maxsize=96)
def render_preview(effect, phase, intensity=1.0, speed=1.0, font_family="auto", font_style="auto", font_scale=1.25):
    return _cached('effect', (effect, phase, intensity, speed, font_family, font_style, font_scale), _render_effect)


@lru_cache(maxsize=48)
def render_text_preview(animation, font_family="auto", font_style="auto", font_scale=1.25, speed=1.):
    return _cached('text', (animation, font_family, font_style, font_scale, speed), _render_text)
