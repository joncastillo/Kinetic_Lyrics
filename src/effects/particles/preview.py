"""Bounded, cached animated samples of the exact declarative effect selected."""

from io import BytesIO
import os
from threading import Semaphore

from PIL import Image, ImageDraw

from render.text_effects import paint_word
from core.fonts import truetype
from effects.particles.scene_backdrops import DEFAULT_BACKDROP, backdrop_spec, scene_backdrop

_RENDER_SLOTS = Semaphore(1)
SAMPLE_FPS = 20


def _effect_frames(
    effect, phase, intensity=1.0, speed=1.0, font_family="auto", font_style="auto", font_scale=1.25, part=0, parts=1
):
    """Frames part, part + parts, part + 2 * parts, ... of an effect sample, as (index, size, RGB bytes). Every frame
    is a pure function of its time, so a sample can be split across worker processes and stitched back together."""
    with _RENDER_SLOTS:
        growing = effect.trajectory == 'grow'
        detailed = growing or effect.family in ('cinematic', 'material')
        garden = effect.id == 'succulent-garden-lettering'
        canvas = (1200, 675) if garden else (800, 450) if detailed else (480, 240)
        from render.typography_settings import selected_font, typography_options

        typography_options(dict(font_family=font_family, font_style=font_style, font_scale=font_scale))
        font_path = str(selected_font(font_family, font_style) or 'C:/Windows/Fonts/seguisb.ttf')
        font = truetype(font_path, round((144 if garden else 96 if detailed else 62) * font_scale))
        small = truetype("C:/Windows/Fonts/segoeui.ttf", 14)
        label = {
            'prismatic-helix': 'PRISM',
            'prismatic-singularity': 'PRISM',
            'liquid-chrome-assembly': 'CHROME',
            'liquid-chrome-collapse': 'CHROME',
            'ember-forge': 'EMBER',
            'ember-ash-drift': 'EMBER',
            'old-oak-lettering': 'OAK',
            'autumn-maple-lettering': 'MAPLE',
            'clockwork-lettering': 'GEARS',
            'folded-paper-lettering': 'PAPER',
            'succulent-garden-lettering': 'SUCCULENT',
            'obsidian-lattice-lettering': 'VOID',
            'gold-filigree-lettering': 'GILDED',
            'pearl-lace-lettering': 'LACE',
            'jeweled-brocade-lettering': 'JEWEL',
            'luminous-coral-lettering': 'CORAL',
            'frost-crystal-lettering': 'FROST',
            'ink-bloom-lettering': 'INK',
            'thread-stitch-lettering': 'STITCH',
        }.get(
            effect.id,
            'BLOOM'
            if effect.family == 'petals'
            else effect.name.split()[0].upper()
            if effect.family == 'material'
            else effect.family.upper(),
        )
        while font.getlength(label) > canvas[0] - 80:
            font = truetype(font_path, font.size - 2)
        bounds = font.getbbox(label)
        sprite = Image.new("RGBA", (bounds[2] - bounds[0] + 24, bounds[3] - bounds[1] + 24))
        ImageDraw.Draw(sprite).text((12 - bounds[0], 12 - bounds[1]), label, font=font, fill="#edf1f5")
        x, y = (canvas[0] - sprite.width) // 2, (canvas[1] - sprite.height) // 2
        catalog = {"entrance": {}, "exit": {}}
        catalog[phase][effect.id] = effect
        glyph_bounds = (
            [0] + [round(12 + font.getlength(label[:index])) for index in range(1, len(label))] + [sprite.width]
        )
        spans = list(zip(glyph_bounds, glyph_bounds[1:]))
        cache, frames = {}, []
        transition = (1.8 if detailed else 0.8) / speed
        duration = 0.7 + transition + 0.35
        for number in range(part, round(duration * SAMPLE_FPS), parts):
            t = number / SAMPLE_FPS
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
            rgb = frame.convert("RGB")
            frames.append((number, rgb.size, rgb.tobytes()))
        return frames


def _gif(frames, fps):
    """Stitch (index, size, RGB bytes) frames, in any order, into a looping GIF."""
    images = [Image.frombytes("RGB", size, data) for _, size, data in sorted(frames, key=lambda f: f[0])]
    result = BytesIO()
    images[0].save(
        result, format="GIF", append_images=images[1:], save_all=True, duration=round(1000 / fps), loop=0, disposal=2
    )
    return result.getvalue()


def _render_effect(effect, phase, intensity=1.0, speed=1.0, font_family="auto", font_style="auto", font_scale=1.25):
    """A whole effect sample in this process."""
    return _gif(_effect_frames(effect, phase, intensity, speed, font_family, font_style, font_scale), SAMPLE_FPS)


def _render_text(animation, font_family="auto", font_style="auto", font_scale=1.25, speed=1.0):
    from render.compositor import Compositor
    from direction.typography import rules_plan
    from direction.theme import theme_for

    data = [
        dict(
            text="Move with time",
            words=[
                dict(text="Move", start=2.0, end=2.8),
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
        text_animation=animation,
        font_family=font_family,
        font_style=font_style,
        font_scale=font_scale,
        particle_speed=speed,
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


SCENE_SAMPLE = ((0.4, 'golden light upon the water'), (3.3, 'hold me close until the morning'))
SCENE_SIZE, SCENE_SECONDS, SCENE_FPS = (480, 270), 6.6, 24


def scene_gif(frames, fps):
    """A shared palette prevents a static backdrop from changing color between GIF frames."""
    count = min(20, len(frames))
    atlas = Image.new('RGB', (480, 68 * ((count + 3) // 4)))
    for i in range(count):
        index = round(i * (len(frames) - 1) / max(1, count - 1))
        atlas.paste(frames[index].convert('RGB').resize((120, 68)), ((i % 4) * 120, (i // 4) * 68))
    palette = atlas.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    indexed = [frame.convert('RGB').quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    output = BytesIO()
    indexed[0].save(
        output,
        format='GIF',
        append_images=indexed[1:],
        save_all=True,
        duration=round(1000 / fps),
        loop=0,
        disposal=1,
        optimize=False,
    )
    return output.getvalue()


def _render_scene(
    scene_id, font_family="auto", font_style="auto", font_scale=1.25, settings="{}", background=DEFAULT_BACKDROP
):
    """A few seconds of two sample lines filmed in one scene effect, over a selected studio backdrop."""
    import json
    from render.compositor import Compositor
    from direction.typography import rules_plan
    from direction.theme import theme_for
    from core.paths import PROJECT_ROOT

    data = []
    for start, text in SCENE_SAMPLE:
        words = [
            dict(text=word, start=round(start + i * 0.36, 3), end=round(start + i * 0.36 + 0.32, 3))
            for i, word in enumerate(text.split())
        ]
        data.append(dict(text=text, words=words, section_id=0, section_label='Chorus'))
    plan = dict(rules_plan(data, theme_for('bright')), scene_flows=[dict(start=0, end=len(data), scene=scene_id)])
    width, height = SCENE_SIZE
    art = scene_backdrop(PROJECT_ROOT / '.preview-cache', SCENE_SIZE, background)
    with _RENDER_SLOTS:
        compositor = Compositor(
            data,
            plan,
            width,
            height,
            SCENE_SECONDS,
            illustrations=[str(art)],
            illustration_lines=len(data),
            artwork_mode='fullscreen',
            reading_flow='mixed',
            entrance_effect='mixed',
            exit_effect='mixed',
            font_family=font_family,
            font_style=font_style,
            font_scale=font_scale,
            kinetic=dict(
                scenes=[scene_id],
                fade=False,
                beat_effect='none',
                beat_confetti=False,
                beat_intensity=0.0,
                beat_blur=0.0,
                background_shake=0.0,
                scene_settings={scene_id: json.loads(settings)},
            ),
        )
        try:
            frames = [compositor.frame(index / SCENE_FPS) for index in range(round(SCENE_SECONDS * SCENE_FPS))]
        finally:
            if getattr(compositor.realtime, 'stage', None) is not None:
                from render.stage_3d import close_stage

                close_stage()
        return scene_gif(frames, SCENE_FPS)


_POOL = None
_POOL_VERSION = None
# worker processes: about two thirds of the cores, at most six (each holds its own copy of the renderer)
WORKERS = max(2, min(6, (os.cpu_count() or 4) * 2 // 3))
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
        _POOL = ProcessPoolExecutor(max_workers=WORKERS, mp_context=multiprocessing.get_context('spawn'))
        _POOL_VERSION = version
    return _POOL


# The storyline, image, video and studio code changes many times a day; none of it draws a sample. Only the
# drawing code (render, effects, core) and the direction modules it imports count, so a commit elsewhere no longer
# throws every cached sample away.
DIRECTION_FILES = (
    'scene_catalog',
    'scene_controls',
    'theme',
    'typography',
    'song_structure',
    'effects',
    'instructions',
    'ornaments',
)


def _version_paths():
    from core.paths import ASSET_ROOT, SRC_ROOT

    return [
        *(SRC_ROOT / 'render').rglob('*.py'),
        *(SRC_ROOT / 'effects').rglob('*.py'),
        *(SRC_ROOT / 'core').rglob('*.py'),
        *(SRC_ROOT / 'direction' / f'{name}.py' for name in DIRECTION_FILES),
        SRC_ROOT / 'audio' / 'rhythm.py',
        *(ASSET_ROOT / 'particles').rglob('*.json'),
        *(ASSET_ROOT / 'scenes').glob('*.json'),
        *(ASSET_ROOT / 'fonts').glob('*'),
    ]


def _source_version():
    """Fingerprint the code and recipes behind a sample, even if another file has a newer mtime."""
    import hashlib

    paths = _version_paths()
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
    from core.paths import PROJECT_ROOT

    version = _source_version()
    key = hashlib.sha256(repr((kind, args, version)).encode()).hexdigest()[:32]
    if key in _SAMPLES:
        return _SAMPLES[key]
    folder = PROJECT_ROOT / '.preview-cache'
    target = folder / f'{key}.gif'
    try:
        data = target.read_bytes()
    except OSError:
        pool = _pool(version)
        if renderer is _render_effect:  # split one sample's frames across every worker, then stitch them
            jobs = [pool.submit(_effect_frames, *args, part, WORKERS) for part in range(WORKERS)]
            data = _gif([frame for job in jobs for frame in job.result()], SAMPLE_FPS)
        else:
            data = pool.submit(renderer, *args).result()
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


def render_scene_preview(
    scene_id, font_family="auto", font_style="auto", font_scale=1.25, settings="{}", background=DEFAULT_BACKDROP
):
    backdrop_spec(background)
    return _cached('scene', (scene_id, font_family, font_style, font_scale, settings, background), _render_scene)


def render_text_preview(animation, font_family="auto", font_style="auto", font_scale=1.25, speed=1.0):
    return _cached('text', (animation, font_family, font_style, font_scale, speed), _render_text)


# Samples drawn ahead of time, so the effect lists open at once instead of each sample taking seconds on first
# view. A background thread draws every sample for one set of settings (the typography and the preview sliders),
# one at a time so a sample asked for by the page is never far behind, and never while a job is running. The
# studio starts it with the defaults; every settings the page then asks a sample for is queued whole, so the rest of
# that list is ready by the time it scrolls into view.
UNDRAWABLE_TEXT = ('ai', 'mixed')  # chosen by the text model per song: no sample of their own
_WARM_QUEUE = None
_WARMED = set()


def prerender(
    font_family='auto', font_style='auto', font_scale=1.25, intensity=1.0, speed=1.0, busy=lambda: False, wait=None
):
    """Draw (or find cached) every sample for these settings: word animations, scenes, entrances and exits. `busy`
    true pauses between samples (a job has the computer); `wait` is how to pause (sleep by default)."""
    import time
    from effects.particles.catalog import discover_effects
    from render.text_effects import TEXT_ANIMATIONS
    from direction.scene_catalog import scene_catalog

    wait = wait or (lambda: time.sleep(5))
    catalog = discover_effects()
    jobs = [
        lambda a=a: render_text_preview(a, font_family, font_style, font_scale, speed)
        for a in TEXT_ANIMATIONS
        if a not in UNDRAWABLE_TEXT
    ]
    jobs += [lambda s=s: render_scene_preview(s, font_family, font_style, font_scale) for s in scene_catalog()]
    jobs += [
        lambda e=e, p=p: render_preview(e, p, intensity, speed, font_family, font_style, font_scale)
        for p in ('entrance', 'exit')
        for e in catalog.get(p, {}).values()
    ]
    drawn = 0
    for job in jobs:
        while busy():
            wait()
        try:
            job()
            drawn += 1
        except Exception as exc:  # noqa: BLE001 (one sample failing must not stop the rest)
            print(f'Preview warm-up: a sample could not be drawn ({exc}).', flush=True)
    return drawn


def request_prerender(font_family='auto', font_style='auto', font_scale=1.25, intensity=1.0, speed=1.0):
    """Queue every sample for these settings, once per settings while the studio runs."""
    key = (str(font_family), str(font_style), float(font_scale), float(intensity), float(speed))
    if _WARM_QUEUE is None or key in _WARMED:
        return False
    _WARMED.add(key)
    _WARM_QUEUE.put(key)
    return True


def start_prerender(busy=lambda: False):
    """Start the warm-up thread (once) and queue the default settings."""
    global _WARM_QUEUE
    if _WARM_QUEUE is not None:
        return
    import queue
    import threading

    _WARM_QUEUE = queue.Queue()

    def run():
        while True:
            key = _WARM_QUEUE.get()
            try:
                prerender(*key, busy=busy)
            except Exception as exc:  # noqa: BLE001
                print(f'Preview warm-up stopped for {key}: {exc}', flush=True)

    threading.Thread(target=run, name='preview-warm-up', daemon=True).start()
    request_prerender()
