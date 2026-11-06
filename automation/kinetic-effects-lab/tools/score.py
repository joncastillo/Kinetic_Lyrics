"""Render kinetic entrance effects and score smoothness, consistency and uniqueness.

usage: python score.py OUTDIR effect-id [effect-id ...]     (OUTDIR is usually automation/kinetic-effects-lab/runs/<round>)
       python score.py OUTDIR --baseline                      (signatures of the existing curated entrances)
Set PAINTING=1 to show the sample illustration behind (and inside) effects that read the frame's artwork.
Set PHASE=exit to score exit effects: they start exactly on the plain word, stay readable early, and leave nothing.
Effect ids are any curated effect; a bare kinetic name (`starburst`) means `kinetic-starburst`.
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from effects.particles.catalog import discover_effects  # noqa: E402
from effects.particles.motion import paint_transition  # noqa: E402

FONTS = ROOT/'assets'/'fonts'
PHASE = __import__('os').environ.get('PHASE', 'entrance')
FPS = 30
CASES = [  # word, font file, size, colour, variation (wght)
    ('MOVE', 'Anton-Regular.ttf', 120, (246, 244, 238), None),
    ('tonight', 'DelaGothicOne-Regular.ttf', 92, (255, 214, 120), None),
    ('Starlight', 'BigShouldersDisplay[wght].ttf', 128, (236, 240, 255), 800),
    ('I', 'ArchivoBlack-Regular.ttf', 110, (250, 250, 250), None),
]
SIZE = (1100, 480)


def font(name, size, weight=None):
    f = ImageFont.truetype(str(FONTS/name), size)
    if weight is not None:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def word_sprite(text, f, color):
    """The realtime renderer's word sprite: soft shadow plus fill, with padding and glyph spans."""
    size = f.size
    pad = max(8, round(size*.12))
    sprite = Image.new('RGBA', (math.ceil(f.getlength(text))+pad*2, round(size*1.4)+pad*2))
    shadow = Image.new('RGBA', sprite.size)
    ImageDraw.Draw(shadow).text((pad, pad+round(size*.04)), text, font=f, fill=(0, 0, 0, 150))
    sprite.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1, size*.05))))
    ImageDraw.Draw(sprite).text((pad, pad), text, font=f, fill=(*color, 255))
    edges = [0]+[pad+round(f.getlength(text[:k])) for k in range(1, len(text))]+[sprite.width]
    return sprite, list(zip(edges, edges[1:]))


def backdrop(kind):
    """With PAINTING=1 the dark backgrounds are the sample illustration (for effects that show the artwork)."""
    import os
    if kind == 'dusk' and os.environ.get('PAINTING'):
        from PIL import ImageEnhance
        art = Image.open(ROOT/'assets'/'reference_female_2.jpeg').convert('RGB').resize(SIZE)
        return ImageEnhance.Brightness(art).enhance(.5).convert('RGBA')  # a mid-tone painting
    w, h = SIZE
    yy, xx = np.mgrid[0:h, 0:w]/np.array((h, w))[:, None, None]
    if kind == 'dusk':
        top, low, glow = np.array((22, 34, 58)), np.array((58, 78, 104)), np.array((214, 150, 110))
        sky = top+(low-top)*(yy**1.3)[..., None]
        halo = np.exp(-(((xx-.62)/.38)**2+((yy-.78)/.22)**2))[..., None]
        img = sky+(glow-sky)*halo*.55
    else:
        img = np.zeros((h, w, 3))+np.array((232, 226, 214))
    return Image.fromarray(np.clip(img, 0, 255).astype('uint8'), 'RGB').convert('RGBA')


def amount(p):
    """paint_transition's amount (0 intact, 1 dispersed) at progress p through the effect."""
    return 1-p if PHASE == 'entrance' else p


def render(effect, case, duration=.6, intensity=1., seed=None, extra=0):
    seed = 4+CASES.index(case) if seed is None else seed  # each word in a song has its own seed
    text, fname, size, color, weight = case
    f = font(fname, size, weight)
    sprite, spans = word_sprite(text, f, color)
    x, y = (SIZE[0]-sprite.width)//2, (SIZE[1]-sprite.height)//2
    frames, cache = [], {'backdrop': backdrop('dusk')}
    count = round(duration*FPS)
    for n in range(count+1+extra):
        p = min(1., n/count)
        layer = Image.new('RGBA', SIZE)
        paint_transition(layer, sprite, x, y, PHASE, amount(p), effect, seed, intensity, .6, cache, glyph_spans=spans)
        frames.append(layer)
    rest = Image.new('RGBA', SIZE)
    if decorated(effect):  # a lettering that ends on the decorated word: that is its landing, not the plain word
        paint_transition(rest, sprite, x, y, PHASE, 0., effect, seed, intensity, .6, cache, glyph_spans=spans)
    else:
        rest.alpha_composite(sprite, (x, y))
    return frames, rest, sprite, (x, y)


def decorated(effect):
    """Entrances whose last frame is the decorated word (grown or particle letterings), by design."""
    return PHASE == 'entrance' and (effect.trajectory == 'grow' or getattr(effect, 'hold', 'solid') == 'particles')


def at(effect, case, p, intensity=1., seed=None):
    seed = 4+CASES.index(case) if seed is None else seed
    text, fname, size, color, weight = case
    sprite, spans = word_sprite(text, font(fname, size, weight), color)
    x, y = (SIZE[0]-sprite.width)//2, (SIZE[1]-sprite.height)//2
    layer = Image.new('RGBA', SIZE)
    paint_transition(layer, sprite, x, y, PHASE, amount(p), effect, seed, intensity, .6, {'backdrop': backdrop('dusk')}, glyph_spans=spans)
    return layer, sprite, (x, y)


def arr(image):
    a = np.asarray(image, np.float32)/255
    return np.concatenate([a[..., :3]*a[..., 3:4], a[..., 3:4]], axis=-1)


def smoothness(frames):
    """Share of all visible change that happens in the busiest frame step (pops), and how evenly it ramps."""
    data = [arr(f) for f in frames]
    steps = np.array([np.abs(b-a).mean() for a, b in zip(data, data[1:])])
    total = steps.sum()+1e-9
    pop = steps.max()/total
    # Reversals of large frame-to-frame changes: flicker (on/off) rather than motion.
    alpha = np.stack([d[..., 3] for d in data])
    tv = np.abs(np.diff(alpha, axis=0)).sum(axis=0)
    net = np.abs(alpha[-1]-alpha[0])
    peak = alpha.max(axis=0)-np.minimum(alpha[0], alpha[-1])
    flicker = float((tv-(2*peak-net)).clip(0).sum()/(tv.sum()+1e-9))
    score = 100.
    score -= max(0., pop-.16)/(.5-.16)*70
    score -= max(0., flicker-.25)/.5*30
    return dict(pop=round(float(pop), 3), flicker=round(flicker, 3), score=round(max(0., score), 1))


def consistency(effect):
    """Exact landing, readable by 85%, no spill far outside the word, robust across words, fonts, intensities."""
    notes = []
    landing, readable, spill = [], [], []
    for case in CASES:
        frames, rest, sprite, (x, y) = render(effect, case)
        target = arr(rest)
        if PHASE == 'entrance':  # lands exactly on the word, and is all but there just before
            landing.append(float(np.abs(arr(frames[-1])-target).max()))
            near, *_ = at(effect, case, .985)
            landing.append(float(np.abs(arr(near)-target).mean()*SIZE[0]*SIZE[1]/max(1, sprite.width*sprite.height)))
            r, *_ = at(effect, case, .85)
        else:  # starts exactly on the word, and leaves nothing behind
            landing.append(float(np.abs(arr(frames[0])-target).max()))
            landing.append(float(arr(frames[-1])[..., 3].sum()/max(1., target[..., 3].sum())))
            r, *_ = at(effect, case, .15)
        a, b = arr(r)[..., 3].ravel(), target[..., 3].ravel()
        readable.append(float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 else 0.)
        h = sprite.height
        box = (x-h*1.2, y-h*.9, x+sprite.width+h*1.2, y+sprite.height+h*.9)
        out = 0.
        for f in frames:
            al = arr(f)[..., 3]
            mask = np.ones_like(al, bool)
            mask[max(0, int(box[1])):int(box[3]), max(0, int(box[0])):int(box[2])] = False
            out = max(out, float(al[mask].sum()/(al.sum()+1e-9)))
        spill.append(out)
        for intensity in (.4, 1.8):
            try:
                render(effect, case, intensity=intensity)
            except Exception as exc:
                notes.append(f'intensity {intensity} on {case[0]}: {exc!r}')
    exact = max(landing[0::2])
    approach = max(landing[1::2])
    score = 100.
    if exact > 1e-6:
        score -= 30
        notes.append(f'{"final" if PHASE == "entrance" else "first"} frame differs from the word by {exact:.3f}')
    score -= min(25., max(0., approach-.02)*120)
    score -= sum(min(10., max(0., .93-r)*60) for r in readable)
    if effect.family == 'kinetic':  # for particle and material families, travel beyond the word is the effect
        score -= sum(min(10., max(0., s-.02)*120) for s in spill)
    score -= 15*len(notes)
    return dict(exact=round(exact, 4), approach=round(approach, 4), readable=[round(r, 3) for r in readable],
                spill=[round(s, 3) for s in spill], notes=notes, score=round(max(0., score), 1))


def signature(effect):
    """Motion fingerprint: the alpha of the word's region at eight moments, plus where it changes."""
    case = CASES[0]
    parts = []
    for p in (.08, .18, .3, .42, .55, .68, .8, .9):
        layer, sprite, (x, y) = at(effect, case, p)
        h = sprite.height
        crop = layer.crop((round(x-h), round(y-h*.7), round(x+sprite.width+h), round(y+sprite.height+h*.7)))
        small = arr(crop.resize((40, 16), Image.Resampling.BOX))
        alpha = small[..., 3]
        rgb = small[..., :3]
        chroma = rgb-rgb.mean(axis=-1, keepdims=True)  # colour away from grey, premultiplied
        parts.append(np.concatenate([alpha[..., None], chroma*1.6, (rgb.mean(axis=-1, keepdims=True)-alpha[..., None]*.9)*.8], axis=-1))
    stack = np.stack(parts)
    feature = np.concatenate([stack.ravel(), np.diff(stack, axis=0).ravel()*1.5])
    feature -= feature.mean()
    return feature/(np.linalg.norm(feature)+1e-9)


def sheet(effect, path):
    """Contact sheet: three words on dusk and paper backgrounds at 10 moments, plus a GIF of all four words."""
    moments = [.05, .12, .2, .3, .4, .5, .6, .7, .82, 1.]
    rows = []
    for case, bg in ((CASES[0], 'dusk'), (CASES[1], 'paper'), (CASES[2], 'dusk')):
        back = backdrop(bg)
        tiles = []
        for p in moments:
            layer, sprite, (x, y) = at(effect, case, p)
            frame = back.copy(); frame.alpha_composite(layer)
            h = sprite.height
            mx, my = (.9, .6) if effect.family == 'kinetic' else (1.7, 1.1)  # travelling effects get a wider view
            box = (max(0, round(x-h*mx)), max(0, round(y-h*my)), min(SIZE[0], round(x+sprite.width+h*mx)),
                   min(SIZE[1], round(y+sprite.height+h*my)))
            tiles.append(frame.crop(box))
        th = 150
        tiles = [t.resize((max(1, round(t.width*th/t.height)), th)) for t in tiles]
        tw = max(t.width for t in tiles)
        row = Image.new('RGB', (tw*5, th*2), 'black')
        for i, t in enumerate(tiles):
            row.paste(t.convert('RGB'), ((i % 5)*tw+(tw-t.width)//2, (i//5)*th))
        rows.append(row)
    width = max(r.width for r in rows)
    out = Image.new('RGB', (width, sum(r.height+6 for r in rows)), (40, 40, 40))
    top = 0
    for r in rows:
        out.paste(r, (0, top)); top += r.height+6
    out.save(path)
    gif = []
    for case, bg in ((CASES[0], 'dusk'), (CASES[1], 'paper'), (CASES[2], 'dusk'), (CASES[3], 'paper')):
        frames, *_ = render(effect, case, duration=.6, extra=12)
        back = backdrop(bg)
        for f in [frames[0]]*4+frames:
            fr = back.copy(); fr.alpha_composite(f); gif.append(fr.convert('RGB').resize((550, 240)))
    gif[0].save(str(path).replace('.png', '.gif'), save_all=True, append_images=gif[1:], duration=round(1000/FPS), loop=0)


def strip(effect, path, case_index=0, bg='dusk'):
    """Every frame of the 0.6 s entrance in a grid, for checking smoothness by eye."""
    frames, rest, sprite, (x, y) = render(effect, CASES[case_index], extra=2)
    back = backdrop(bg)
    h = sprite.height
    mx, my = (.9, .6) if effect.family == 'kinetic' else (1.7, 1.1)
    box = (max(0, round(x-h*mx)), max(0, round(y-h*my)), min(SIZE[0], round(x+sprite.width+h*mx)), min(SIZE[1], round(y+sprite.height+h*my)))
    tiles = []
    for f in frames:
        fr = back.copy(); fr.alpha_composite(f); tiles.append(fr.crop(box).convert('RGB'))
    tw, th = tiles[0].size
    scale = 260/tw
    tiles = [t.resize((260, round(th*scale))) for t in tiles]
    th = tiles[0].height
    cols = 7
    out = Image.new('RGB', (260*cols, th*math.ceil(len(tiles)/cols)))
    for i, t in enumerate(tiles):
        out.paste(t, ((i % cols)*260, (i//cols)*th))
    out.save(path)


def main():
    out = Path(sys.argv[1]).resolve(); out.mkdir(parents=True, exist_ok=True)
    catalog = discover_effects()[PHASE]
    if sys.argv[2] == '--baseline':
        sigs = {}
        for key, effect in catalog.items():
            if effect.family == 'kinetic':
                continue
            t0 = time.time()
            try:
                sigs[key] = signature(effect).tolist()
            except Exception as exc:
                print('skip', key, exc)
            print(key, round(time.time()-t0, 1), flush=True)
        (out/'baseline.json').write_text(json.dumps(sigs))
        return
    base = out/'baseline.json' if (out/'baseline.json').exists() else out.parent/'baseline.json'
    baseline = json.loads(base.read_text()) if base.exists() else {}
    others = {k: np.array(v) for k, v in baseline.items()}
    ids = [a if a in catalog else 'kinetic-'+a for a in sys.argv[2:]]
    if PHASE == 'entrance' and all(catalog[k].family == 'kinetic' for k in ids):
        own = {key: signature(catalog[key]) for key in catalog if catalog[key].family == 'kinetic'}
    else:  # compare against every effect of the phase (signatures cached per phase)
        cache = out.parent/f'signatures-{PHASE}.json'
        known = json.loads(cache.read_text()) if cache.exists() else {}
        for key in catalog:
            if key not in known or key in ids:
                known[key] = signature(catalog[key]).tolist()
        cache.write_text(json.dumps(known))
        own = {k: np.array(v) for k, v in known.items()}
        others = {}
    results = {}
    for key in ids:
        effect = catalog[key]
        t0 = time.time()
        frames, *_ = render(effect, CASES[0])
        frames2, *_ = render(effect, CASES[2])
        s1, s2 = smoothness(frames), smoothness(frames2)
        smooth = dict(cases=[s1, s2], score=round(min(s1['score'], s2['score']), 1))
        cons = consistency(effect)
        sig = own[key]
        sims = {k: float(sig@v) for k, v in others.items()}
        sims.update({k: float(sig@v) for k, v in own.items() if k != key})
        nearest = sorted(sims.items(), key=lambda kv: -kv[1])[:3]
        d = 1-nearest[0][1] if nearest else 1.
        unique = round(min(100., 100*d/.30), 1)
        ms = (time.time()-t0)
        sheet(effect, out/f'{key}.png')
        strip(effect, out/f'{key}-strip.png')
        results[key] = dict(smoothness=smooth, consistency=cons,
                            uniqueness=dict(nearest=[(k, round(v, 3)) for k, v in nearest], score=unique))
        print(key, 'smooth', smooth['score'], 'consistency', cons['score'], 'unique', unique, 'nearest', nearest[0],
              'notes', cons['notes'], f'{ms:.1f}s', flush=True)
        video(effect, out/f'{key}.mp4')
    path = out/'metrics.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    previous.update(results)
    path.write_text(json.dumps(previous, indent=1, default=float))
    showcase(out, sorted(previous))


def label_font(size):
    return ImageFont.truetype(str(FONTS/'DejaVuSans-Bold.ttf'), size)


def video(effect, path, title=None):
    """An MP4 of the effect on all four words: each entrance (0.6 s) then a short hold, at 30 fps."""
    import subprocess
    width, height = 960, 420
    proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s',
                             f'{width}x{height}', '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                             '-crf', '18', str(path)], stdin=subprocess.PIPE)
    small = label_font(18)
    for case, bg in ((CASES[0], 'dusk'), (CASES[1], 'paper'), (CASES[2], 'dusk'), (CASES[3], 'paper')):
        frames, *_ = render(effect, case, duration=.6, extra=15)
        back = backdrop(bg)
        for f in [frames[0]]*6+frames:
            fr = back.copy(); fr.alpha_composite(f)
            fr = fr.convert('RGB').resize((width, height), Image.Resampling.LANCZOS)
            ImageDraw.Draw(fr).text((16, 12), title or effect.name, font=small,
                                    fill=(30, 30, 30) if bg == 'paper' else (220, 225, 235))
            proc.stdin.write(fr.tobytes())
    proc.stdin.close()
    proc.wait()


def showcase(out, keys):
    """All of a round's MP4s joined into one, and the latest copies in scratchpad/showcase/."""
    import shutil
    import subprocess
    files = [out/f'{k}.mp4' for k in keys if (out/f'{k}.mp4').exists()]
    if not files:
        return
    listing = out/'concat.txt'
    listing.write_text(''.join(f"file '{f.as_posix()}'\n" for f in files))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-c', 'copy',
                    str(out/'all-effects.mp4')])
    show = out.parent/'showcase'
    show.mkdir(exist_ok=True)
    for f in [*files, out/'all-effects.mp4']:
        if f.exists():
            shutil.copy2(f, show/f.name)
        gif = f.with_suffix('.gif')
        if gif.exists():
            shutil.copy2(gif, show/gif.name)


if __name__ == '__main__':
    main()
