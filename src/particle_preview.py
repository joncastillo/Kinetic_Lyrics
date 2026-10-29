"""Bounded, cached animated samples of the exact declarative effect selected."""

from io import BytesIO
import os
from threading import Semaphore

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from kinetic_effects import paint_word

_RENDER_SLOTS = Semaphore(1)


def _render_effect(effect, phase, intensity=1.0, speed=1.0,font_family="auto",font_style="auto",font_scale=1.25):
    with _RENDER_SLOTS:
        growing=effect.trajectory=='grow'
        detailed=growing or effect.family in ('cinematic','material')
        canvas=(800,450) if detailed else (480,240)
        from typography_settings import selected_font,typography_options
        typography_options(dict(font_family=font_family,font_style=font_style,font_scale=font_scale))
        font_path=str(selected_font(font_family,font_style) or 'C:/Windows/Fonts/seguisb.ttf')
        font=ImageFont.truetype(font_path,round((96 if detailed else 62)*font_scale))
        small = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 14)
        label = {'prismatic-helix':'PRISM','prismatic-singularity':'PRISM','liquid-chrome-assembly':'CHROME','liquid-chrome-collapse':'CHROME','ember-forge':'EMBER','ember-ash-drift':'EMBER','old-oak-lettering':'OAK','autumn-maple-lettering':'MAPLE','clockwork-lettering':'GEARS','folded-paper-lettering':'PAPER','obsidian-lattice-lettering':'VOID','gold-filigree-lettering':'GILDED','pearl-lace-lettering':'LACE','jeweled-brocade-lettering':'JEWEL','luminous-coral-lettering':'CORAL','frost-crystal-lettering':'FROST','ink-bloom-lettering':'INK','thread-stitch-lettering':'STITCH'}.get(effect.id,'BLOOM' if effect.family=='petals' else effect.name.split()[0].upper() if effect.family=='material' else effect.family.upper())
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
        kinetic=dict(fade=False),
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



SCENE_SAMPLE = ((.4, 'golden light upon the water'), (3.3, 'hold me close until the morning'))
SCENE_SIZE, SCENE_SECONDS, SCENE_FPS = (480, 270), 6.6, 12


def scene_backdrop(folder, size):
    """A neutral dusk painting for scene samples: deep blue above, a warm glow low on the horizon."""
    import numpy as np
    path = folder/f'scene-backdrop-{size[0]}x{size[1]}.png'
    if not path.is_file():
        w, h = size
        y, x = np.mgrid[0:h, 0:w]/np.array((h, w))[:, None, None]
        top, low, glow = np.array((22, 34, 58)), np.array((58, 78, 104)), np.array((214, 150, 110))
        sky = top+(low-top)*(y**1.3)[..., None]
        halo = np.exp(-(((x-.62)/.38)**2+((y-.78)/.22)**2))[..., None]
        image = np.clip(sky+(glow-sky)*halo*.55, 0, 255).astype('uint8')
        folder.mkdir(exist_ok=True)
        Image.fromarray(image, 'RGB').filter(ImageFilter.GaussianBlur(2)).save(path)
    return path


def _render_scene(scene_id, font_family="auto", font_style="auto", font_scale=1.25):
    """A few seconds of two sample lines filmed in one scene effect, over a neutral dusk backdrop."""
    from kinetic_director import Compositor, rules_plan
    from kinetic_lyrics import theme_for
    from project_paths import PROJECT_ROOT
    data = []
    for start, text in SCENE_SAMPLE:
        words = [dict(text=word, start=round(start+i*.36, 3), end=round(start+i*.36+.32, 3)) for i, word in enumerate(text.split())]
        data.append(dict(text=text, words=words, section_id=0, section_label='Chorus'))
    plan = dict(rules_plan(data, theme_for('bright')), scene_flows=[dict(start=0, end=len(data), scene=scene_id)])
    width, height = SCENE_SIZE
    art = scene_backdrop(PROJECT_ROOT/'.preview-cache', SCENE_SIZE)
    with _RENDER_SLOTS:
        compositor = Compositor(data, plan, width, height, SCENE_SECONDS, illustrations=[str(art)],
                                illustration_lines=len(data), artwork_mode='fullscreen',
                                reading_flow='mixed', entrance_effect='mixed', exit_effect='mixed', font_family=font_family,
                                font_style=font_style, font_scale=font_scale, kinetic=dict(scenes=[scene_id], fade=False))
        try:
            frames = [compositor.frame(index/SCENE_FPS) for index in range(round(SCENE_SECONDS*SCENE_FPS))]
        finally:
            if getattr(compositor.realtime, 'stage', None) is not None:
                from stage_3d import close_stage
                close_stage()
        result = BytesIO()
        frames[0].save(result, format="GIF", append_images=frames[1:], save_all=True, duration=round(1000/SCENE_FPS),
                       loop=0, disposal=2)
        return result.getvalue()


_POOL = None
_POOL_VERSION = None
_SAMPLES = {}  # recent samples held in memory, keyed by what they show and the code that drew them


def _pool(version):
    """Persistent worker processes, so many samples render at once without holding the server's GIL. They import
    the renderer once, so when the code changes they are replaced and the next sample is drawn with the new code."""
    global _POOL, _POOL_VERSION
    if _POOL is not None and _POOL_VERSION != version:
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None
    if _POOL is None:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            os.environ[name] = '1'
        _POOL = ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn'))
        _POOL_VERSION = version
    return _POOL


def _source_version():
    """Fingerprint the code and recipes behind a sample, even if another file has a newer mtime."""
    import hashlib
    from pathlib import Path
    from project_paths import PROJECT_ROOT
    paths = [*Path(__file__).parent.glob('*.py'), *(PROJECT_ROOT/'particles').rglob('*.json'),
             *(PROJECT_ROOT/'scenes').glob('*.json'), *(PROJECT_ROOT/'assets'/'fonts').glob('*')]
    digest = hashlib.sha256()
    for path in sorted(p for p in paths if p.is_file()):
        stat = path.stat()
        digest.update(str(path).encode())
        if path.suffix in ('.py', '.json'):
            digest.update(path.read_bytes())
        else:
            digest.update(str((stat.st_mtime_ns, stat.st_size)).encode())
    return digest.hexdigest()


def _cached(kind, args, renderer):
    """A sample from memory or the disk cache, redrawn whenever the renderer or recipes change."""
    import hashlib
    from project_paths import PROJECT_ROOT
    version = _source_version()
    key = hashlib.sha256(repr((kind, args, version)).encode()).hexdigest()[:32]
    if key in _SAMPLES:
        return _SAMPLES[key]
    folder = PROJECT_ROOT/'.preview-cache'
    target = folder/f'{key}.gif'
    try:
        data = target.read_bytes()
    except OSError:
        data = _pool(version).submit(renderer, *args).result()
        folder.mkdir(exist_ok=True)
        temporary = target.with_suffix(f'.{os.getpid()}.tmp')
        temporary.write_bytes(data)
        temporary.replace(target)
    while len(_SAMPLES) >= 96:
        _SAMPLES.pop(next(iter(_SAMPLES)))
    _SAMPLES[key] = data
    return data


def render_preview(effect, phase, intensity=1.0, speed=1.0, font_family="auto", font_style="auto", font_scale=1.25):
    return _cached('effect', (effect, phase, intensity, speed, font_family, font_style, font_scale), _render_effect)


def render_scene_preview(scene_id, font_family="auto", font_style="auto", font_scale=1.25):
    return _cached('scene', (scene_id, font_family, font_style, font_scale), _render_scene)


def render_text_preview(animation, font_family="auto", font_style="auto", font_scale=1.25, speed=1.):
    return _cached('text', (animation, font_family, font_style, font_scale, speed), _render_text)
