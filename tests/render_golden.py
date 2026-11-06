"""Golden frames: hashes of rendered frames, so a refactor can prove it changed no pixel.

    python tests/render_golden.py save     record the current output (after an intended visual change)
    python tests/render_golden.py check    compare; lists every case that changed

tests/test_render_golden.py runs the check. Hashes depend on the fonts, Pillow and NumPy of the machine that saved
them, so the fixture records an environment fingerprint and the test skips (saying why) anywhere else. The 3D stage
with artwork is left out: its GPU texture sampling varies by a level on a handful of pixels from run to run.
"""
import hashlib
import json
import platform
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'src'))
FIXTURE = Path(__file__).with_name('golden')/'render.json'
TIMES = (.5, 1.3, 2.6, 4.0, 5.1, 7.9, 9.0, 11.5, 13.2)


def fingerprint():
    import numpy
    import PIL
    from core.fonts import WINDOWS_FONTS
    fonts = sorted(p.name for p in WINDOWS_FONTS.glob('*.tt[fc]')) if WINDOWS_FONTS.is_dir() else []
    return dict(python=platform.python_version(), system=platform.system(), pillow=PIL.__version__,
                numpy=numpy.__version__, fonts=hashlib.sha256('\n'.join(fonts).encode()).hexdigest()[:12])


def lyrics():
    data = []
    for start, text in ((1., "black hole sun won't you come"), (4.2, 'and wash away the rain'),
                        (7.4, 'love is a garden of stars'), (10.6, 'dance with me tonight')):
        words, t = [], start
        for word in text.split():
            words.append(dict(text=word, start=round(t, 3), end=round(t+.42, 3)))
            t += .5
        data.append(dict(text=text, words=words))
    return data


def digest(image):
    return hashlib.sha256(image.tobytes()).hexdigest()[:16]


def frames(**options):
    from direction.theme import theme_for
    from direction.typography import rules_plan
    from render.compositor import Compositor
    data = lyrics()
    plan = rules_plan(data, theme_for('bright'))
    if 'scene' in options:
        plan['scene_flows'] = [dict(start=0, end=len(data), scene=options.pop('scene'))]
    options = dict(dict(entrance_effect='none', exit_effect='none', layout_seed=7), **options)
    c = Compositor(data, plan, 480, 270, 14., **options)
    if uses_stage(c):
        # The 3D stage's GPU sampling varies by a level on a few pixels from run to run, so its frames are kept as
        # small thumbnails and compared with a tolerance instead of hashed.
        return dict(thumbnails=[thumbnail(c.frame(t)) for t in TIMES])
    return [digest(c.frame(t)) for t in TIMES]


def thumbnail(image):
    from PIL import Image
    return image.convert('RGB').resize((48, 27), Image.Resampling.BOX).tobytes().hex()


def same(saved, current, tolerance=3):
    """Equal hashes, or thumbnails no pixel of which moved by more than `tolerance` levels."""
    if isinstance(saved, dict) and isinstance(current, dict) and 'thumbnails' in saved and 'thumbnails' in current:
        return len(saved['thumbnails']) == len(current['thumbnails']) and all(
            max(abs(a-b) for a, b in zip(bytes.fromhex(x), bytes.fromhex(y))) <= tolerance
            for x, y in zip(saved['thumbnails'], current['thumbnails']))
    return saved == current


def uses_stage(c):
    from render.stage_3d import Stage3D
    engines = getattr(c.realtime, 'engines', {}) or {}
    return isinstance(c.realtime, Stage3D) or any(isinstance(e, Stage3D) for e in engines.values())


def pictures(folder):
    from PIL import Image, ImageDraw
    paths = []
    for n, colour in enumerate(((200, 60, 40), (40, 120, 200), (200, 60, 40))):  # the third repeats the first
        image = Image.new('RGBA', (640, 360), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((120+n*30, 60, 520, 330), fill=(*colour, 255))
        draw.rectangle((0, 300, 640, 360), fill=(20, 160, 60, 255))
        path = Path(folder)/f'{n:03d}.png'
        image.save(path)
        paths.append(path)
    return paths


def cases():
    from direction.scene_catalog import scene_catalog
    from render.text_effects import EFFECTS
    yield from ((f'flow/{flow}/{entrance}', lambda flow=flow, entrance=entrance, exit_effect=exit_effect: frames(
        reading_flow=flow, entrance_effect=entrance, exit_effect=exit_effect))
        for flow in ('preview', 'realtime', 'stage', 'cinema')
        for entrance, exit_effect in (('none', 'none'), ('glass-assemble', 'glass-shatter'), ('petals-breeze-lettering', 'petals-scatter')))
    yield from ((f'scene/{scene}', lambda scene=scene: frames(reading_flow='mixed', scene=scene)) for scene in sorted(scene_catalog()))
    yield from ((f'type-effect/{effect}', lambda effect=effect: frames(reading_flow='preview', type_effect=effect))
                for effect in EFFECTS if effect != 'none')
    folder = tempfile.mkdtemp(prefix='golden-art-')
    art = pictures(folder)
    yield from ((f'artwork/{mode}/{flow}', lambda mode=mode, flow=flow: frames(
        reading_flow=flow, illustrations=art, artwork_mode=mode, illustration_lines=1))
        for mode in ('cutout', 'fullscreen', 'verse', 'matte') for flow in ('preview', 'realtime', 'cinema'))
    yield from ((f'word-effect/{effect}', lambda effect=effect: word_effect(effect)) for effect in EFFECTS)
    yield 'recipes', recipes


def word_effect(effect):
    """paint_word on its own (no effect catalogue), through the hold and the exit."""
    from PIL import Image, ImageDraw
    from render.text_effects import paint_word
    sprite = Image.new('RGBA', (120, 50))
    ImageDraw.Draw(sprite).text((6, 6), 'Rain', fill=(240, 220, 120, 255), font_size=34)
    hashes = []
    for progress, fade, elapsed in ((.3, 1., .4), (1., 1., 1.1), (1., .6, 2.3), (1., .2, 3.1)):
        layer = Image.new('RGBA', (320, 200), (20, 30, 60, 255))
        paint_word(layer, sprite, 90, 60, progress, fade, elapsed, 3, effect, glyph_spans=[(6, 40), (40, 70), (70, 90), (90, 114)])
        hashes.append(digest(layer))
    return hashes


def recipes():
    from PIL import Image, ImageDraw
    from effects.particles.catalog import EFFECT_ROOT, discover_effects
    from effects.particles.motion import paint_transition
    sprite = Image.new('RGBA', (90, 40))
    ImageDraw.Draw(sprite).text((4, 4), 'Wave', fill=(240, 230, 220, 255), font_size=30)
    result = {}
    catalog = discover_effects(root=EFFECT_ROOT)
    for phase in ('entrance', 'exit'):
        for effect in catalog[phase].values():
            hashes = []
            for amount in (.15, .5, .85):
                layer = Image.new('RGBA', (220, 160))
                paint_transition(layer, sprite, 60, 60, phase, amount, effect, 3, 1., .6, {}, paced=False)
                hashes.append(digest(layer))
            result[f'{phase}/{effect.id}'] = hashes
    return result


def collect():
    result = {}
    for name, render in cases():
        try:
            value = render()
        except Exception as exc:  # noqa: BLE001 - a case that fails is a result too
            value = f'error: {type(exc).__name__}: {exc}'
        if name == 'recipes' and isinstance(value, dict):
            result.update({f'recipe/{key}': hashes for key, hashes in value.items()})
        else:
            result[name] = value
    return result


def changes(saved, current):
    return sorted(key for key in set(saved) | set(current) if not same(saved.get(key), current.get(key)))


def main(command):
    current = collect()
    if command == 'save':
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(dict(environment=fingerprint(), frames=current), indent=1, sort_keys=True), encoding='utf-8', newline='')
        errors = [k for k, v in current.items() if isinstance(v, str)]
        print(f'saved {len(current)} cases' + (f'; these failed to render: {errors}' if errors else ''))
        return 0
    saved = json.loads(FIXTURE.read_text(encoding='utf-8'))
    changed = changes(saved['frames'], current)
    print('identical' if not changed else f'{len(changed)} changed: ' + ', '.join(changed))
    return 1 if changed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'check'))
