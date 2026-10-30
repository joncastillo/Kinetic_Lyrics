"""Small animated artworks that live inside or beside lyric words.

A word such as MOON or LOVE can trade its letter O for a little picture (a moon with
drifting clouds, a beating heart), and other themed words get a small picture floating
beside them. Each picture is a few layers that move separately (clouds drift in front of
the moon, sun rays turn), so in 3D they separate in depth as the camera moves.

Pictures come from an animated GIF or WebP in assets/ornaments/<kind>.gif or .webp when
one is present (for example Google's Noto Animated Emoji, CC BY 4.0), otherwise from the
built-in drawings below, or from a cutout the image model painted for the lyric (see
ornament_director), which is moved by the motion the director chose. Every pose is a pure
function of time.
"""
from functools import lru_cache
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageSequence

from core.paths import PROJECT_ROOT

LIBRARY = PROJECT_ROOT/'assets'/'ornaments'
SIZE = 256
KEYWORDS = {
    'moon': 'moon moonlight night nights midnight tonight dark darkness dream dreams dreaming sleep lunar',
    'sun': 'sun sunshine sunrise sunset day days morning light gold golden summer bright',
    'heart': 'love loved loving lover heart hearts kiss soul hold',
    'star': 'star stars starlight wish shine shining sparkle glow glowing sky skies',
    'flower': 'rose roses flower flowers bloom blooming garden spring petal petals',
    'drop': 'rain raining tear tears cry crying ocean sea water blue river',
    'flame': 'fire fires burn burning flame flames hot heat ignite',
    'cloud': 'cloud clouds air wind fly flying heaven float',
}
THEMES = {word: kind for kind, words in KEYWORDS.items() for word in words.split()}
ROUND = frozenset(('moon', 'sun', 'heart', 'star', 'flower'))


def theme(word):
    """The picture that suits a bare lowercase word, or None."""
    return THEMES.get(word)


def replaces_letter(kind, text):
    """Index of the letter O the picture can stand in for, or None (then it floats beside the word)."""
    if kind not in ROUND:
        return None
    index = text.upper().find('O')
    return index if index >= 0 else None


def canvas():
    return Image.new('RGBA', (SIZE*2, SIZE*2))


def finish(image, blur=0):
    image = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    return image.filter(ImageFilter.GaussianBlur(blur)) if blur else image


def glow(color, reach=.42, strength=150):
    image = canvas()
    r = SIZE*2*reach
    ImageDraw.Draw(image).ellipse((SIZE-r, SIZE-r, SIZE+r, SIZE+r), fill=(*color, strength))
    return finish(image, SIZE*.12)


def cloud(color=(246, 244, 255), alpha=235, seed=0):
    image = canvas()
    draw = ImageDraw.Draw(image)
    rng = random.Random(seed)
    for k in range(5):
        r = SIZE*rng.uniform(.17, .26)
        cx = SIZE*(.55+k*.22)
        cy = SIZE*(1.1-math.sin(k/4*math.pi)*.18)
        draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(*color, alpha))
    draw.rounded_rectangle((SIZE*.5, SIZE*1.05, SIZE*1.5, SIZE*1.32), radius=SIZE*.13, fill=(*color, alpha))
    return finish(image)


def star_points(cx, cy, outer, inner, points=5, turn=-math.pi/2):
    return [(cx+(outer if k % 2 == 0 else inner)*math.cos(turn+k*math.pi/points),
             cy+(outer if k % 2 == 0 else inner)*math.sin(turn+k*math.pi/points)) for k in range(points*2)]


@lru_cache(maxsize=None)
def drawings(kind):
    """The still layers of a built-in picture: {name: RGBA image}."""
    S = SIZE
    if kind == 'moon':
        disc = canvas()
        draw = ImageDraw.Draw(disc)
        draw.ellipse((S*.28, S*.28, S*1.72, S*1.72), fill=(250, 238, 196, 255))
        for x, y, r in ((.75, .8, .16), (1.25, .7, .1), (1.15, 1.25, .2), (.7, 1.3, .08)):
            draw.ellipse((S*(x-r), S*(y-r), S*(x+r), S*(y+r)), fill=(226, 210, 165, 255))
        return dict(glow=glow((255, 236, 170)), disc=finish(disc), front=cloud(seed=1), back=cloud((214, 220, 246), 210, 2))
    if kind == 'sun':
        rays = canvas()
        draw = ImageDraw.Draw(rays)
        for k in range(12):
            a = k*math.pi/6
            draw.polygon([(S+math.cos(a-.12)*S*.62, S+math.sin(a-.12)*S*.62), (S+math.cos(a)*S*.96, S+math.sin(a)*S*.96),
                          (S+math.cos(a+.12)*S*.62, S+math.sin(a+.12)*S*.62)], fill=(255, 196, 64, 255))
        disc = canvas()
        ImageDraw.Draw(disc).ellipse((S*.42, S*.42, S*1.58, S*1.58), fill=(255, 214, 82, 255))
        return dict(glow=glow((255, 190, 70), .5), rays=finish(rays), disc=finish(disc))
    if kind == 'heart':
        heart = canvas()
        draw = ImageDraw.Draw(heart)
        draw.ellipse((S*.3, S*.38, S*1.06, S*1.14), fill=(255, 61, 110, 255))
        draw.ellipse((S*.94, S*.38, S*1.7, S*1.14), fill=(255, 61, 110, 255))
        draw.polygon([(S*.34, S*.9), (S*1.66, S*.9), (S, S*1.66)], fill=(255, 61, 110, 255))
        draw.ellipse((S*.5, S*.55, S*.78, S*.75), fill=(255, 170, 196, 200))
        return dict(glow=glow((255, 60, 120), .5, 120), heart=finish(heart))
    if kind == 'star':
        star = canvas()
        ImageDraw.Draw(star).polygon(star_points(S, S*1.05, S*.78, S*.33), fill=(255, 222, 92, 255))
        spark = canvas()
        ImageDraw.Draw(spark).polygon(star_points(S, S, S*.9, S*.12, 4), fill=(255, 255, 255, 255))
        return dict(glow=glow((255, 220, 120), .5, 130), star=finish(star), spark=finish(spark))
    if kind == 'flower':
        petals = canvas()
        draw = ImageDraw.Draw(petals)
        for k in range(8):
            a = k*math.pi/4
            cx, cy = S+math.cos(a)*S*.45, S+math.sin(a)*S*.45
            draw.ellipse((cx-S*.3, cy-S*.3, cx+S*.3, cy+S*.3), fill=(255, 140, 180, 245))
        middle = canvas()
        ImageDraw.Draw(middle).ellipse((S*.72, S*.72, S*1.28, S*1.28), fill=(255, 210, 70, 255))
        return dict(petals=finish(petals), middle=finish(middle))
    if kind == 'drop':
        drop = canvas()
        draw = ImageDraw.Draw(drop)
        draw.ellipse((S*.55, S*.85, S*1.45, S*1.75), fill=(90, 190, 255, 245))
        draw.polygon([(S*.58, S*1.15), (S*1.42, S*1.15), (S, S*.2)], fill=(90, 190, 255, 245))
        draw.ellipse((S*.75, S*1.05, S*.92, S*1.3), fill=(220, 245, 255, 220))
        ring = canvas()
        ImageDraw.Draw(ring).ellipse((S*.2, S*.8, S*1.8, S*1.2), outline=(150, 215, 255, 220), width=round(S*.05))
        return dict(drop=finish(drop), ring=finish(ring))
    if kind == 'flame':
        layers = {}
        for name, color, scale in (('outer', (255, 104, 40), 1.), ('inner', (255, 214, 80), .6)):
            image = canvas()
            draw = ImageDraw.Draw(image)
            w, h = S*.62*scale, S*1.5*scale
            base = S*1.78
            draw.ellipse((S-w, base-w*2, S+w, base), fill=(*color, 250))
            draw.polygon([(S-w*.98, base-w), (S+w*.98, base-w), (S+w*.2, base-h), (S-w*.15, base-h*.75)], fill=(*color, 250))
            layers[name] = finish(image, 1.5)
        layers['glow'] = glow((255, 120, 40), .5, 110)
        return layers
    return dict(back=cloud((214, 220, 246), 210, 3), front=cloud(seed=4))


def built_in_pose(kind, t, beat):
    """[(layer name, pose)] back to front; a pose is dx, dy (fractions of the picture size,
    y up), dz (depth in picture sizes), scale, angle (degrees) and alpha."""
    def pose(dx=0., dy=0., dz=0., scale=1., angle=0., alpha=1.):
        return dict(dx=dx, dy=dy, dz=dz, scale=scale, angle=angle, alpha=alpha)
    if kind == 'moon':
        return [('glow', pose(scale=1.25+.08*math.sin(t*1.3), alpha=.8)),
                ('back', pose(dx=.35-((t*.06) % 1.)*1.1, dy=.28, dz=.12, scale=.55, alpha=.85)),
                ('disc', pose(angle=math.sin(t*.4)*4)),
                ('front', pose(dx=-.6+((t*.09+.3) % 1.)*1.3, dy=-.18, dz=.3, scale=.7, alpha=.95))]
    if kind == 'sun':
        return [('glow', pose(scale=1.3+.12*beat)), ('rays', pose(angle=-t*18, scale=1+.05*math.sin(t*2))), ('disc', pose(dz=.05))]
    if kind == 'heart':
        pulse = .1*beat+.06*max(0., math.sin(t*math.tau*1.4))**8
        return [('glow', pose(scale=1.2+pulse*2, alpha=.5+beat*.5)), ('heart', pose(scale=1+pulse, angle=math.sin(t*1.1)*5))]
    if kind == 'star':
        return [('glow', pose(scale=1.2+.15*math.sin(t*2.2))), ('star', pose(angle=math.sin(t*.9)*12, scale=1+.06*beat)),
                ('spark', pose(dx=.45, dy=.42, dz=.25, scale=.35*abs(math.sin(t*2.6)), angle=t*40)),
                ('spark', pose(dx=-.42, dy=-.38, dz=.2, scale=.25*abs(math.sin(t*2.1+1.3)), angle=-t*30))]
    if kind == 'flower':
        return [('petals', pose(angle=t*14, scale=1+.04*math.sin(t*1.7))), ('middle', pose(dz=.08, scale=1+.08*beat))]
    if kind == 'drop':
        fall = (t*.7) % 1.
        return [('ring', pose(dy=-.42, scale=.4+fall*.9, alpha=1-fall)),
                ('drop', pose(dy=.06*math.sin(t*2.4), angle=math.sin(t*1.8)*6))]
    if kind == 'flame':
        flicker = math.sin(t*9.1)*.05+math.sin(t*13.7)*.03
        return [('glow', pose(scale=1.25+flicker*3+.1*beat, alpha=.8)),
                ('outer', pose(scale=1+flicker, angle=math.sin(t*3.3)*5)),
                ('inner', pose(dz=.06, dy=-.12, scale=1+flicker*1.6, angle=math.sin(t*4.1)*7))]
    return [('back', pose(dx=.3*math.sin(t*.5), dy=.18, dz=-.1, scale=.7, alpha=.8)),
            ('front', pose(dx=-.2*math.sin(t*.4+1), dy=-.08+.03*math.sin(t*1.3)))]


@lru_cache(maxsize=None)
def library_frames(kind):
    """(frames, frame durations in seconds) from an animated file in the library, or None."""
    for suffix in ('.webp', '.gif', '.png'):
        path = LIBRARY/(kind+suffix)
        if path.is_file():
            with Image.open(path) as source:
                frames, durations = [], []
                for frame in ImageSequence.Iterator(source):
                    image = frame.convert('RGBA')
                    image.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
                    frames.append(image)
                    durations.append(max(.02, frame.info.get('duration', 80)/1000))
                return frames, durations
    return None


def image_pose(motion, t, beat):
    """How a single painted cutout moves: drifting, bobbing, spinning, pulsing on the beat, swaying,
    flickering like a flame or twinkling like a star."""
    pose = dict(dx=0., dy=0., dz=0., scale=1., angle=0., alpha=1.)
    if motion == 'drift':
        pose.update(dx=.12*math.sin(t*.6), dy=.05*math.sin(t*.9), dz=.1*math.sin(t*.4))
    elif motion == 'spin':
        pose.update(angle=-t*35, scale=1+.04*beat)
    elif motion == 'pulse':
        pose.update(scale=1+.14*beat+.04*math.sin(t*3))
    elif motion == 'sway':
        pose.update(angle=math.sin(t*1.4)*12, dx=.03*math.sin(t*1.4))
    elif motion == 'flicker':
        flicker = math.sin(t*9.1)*.05+math.sin(t*13.7)*.03
        pose.update(scale=1+flicker, angle=math.sin(t*3.3)*4, alpha=.9+flicker)
    elif motion == 'twinkle':
        pose.update(scale=.88+.16*abs(math.sin(t*2.4)), angle=math.sin(t*.9)*10)
    else:
        pose.update(dy=.07*math.sin(t*1.8), angle=math.sin(t*1.1)*4)
    return pose


@lru_cache(maxsize=32)
def cutout(path):
    with Image.open(path) as source:
        image = source.convert('RGBA')
    if Path(path).with_suffix('.svg').is_file():
        # The vector renderer already made a clean transparent matte. Avoid the
        # expensive raster background-removal pass, which can erase white details.
        bounds = image.getchannel('A').getbbox()
        if bounds:
            image = image.crop(bounds)
        square = Image.new('RGBA', (max(image.size),)*2)
        square.paste(image, ((square.width-image.width)//2, (square.height-image.height)//2))
        square.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
        return square
    from models.matting.staging import remove_staging
    from scipy.ndimage import binary_dilation, binary_propagation, label
    image = remove_staging(image)  # any flat staging backdrop left around the subject becomes transparent
    pixels = np.array(image)
    rgb = pixels[..., :3].astype(int)
    white = (rgb.min(axis=-1) > 178) & (rgb.max(axis=-1)-rgb.min(axis=-1) < 64)
    outside = pixels[..., 3] < 64
    # Model-made sticker outlines are often separated from the transparent exterior by a grey
    # antialiased shadow. Start a short way inside that fringe, then follow only neutral light pixels.
    seed = binary_dilation(outside, iterations=max(2, round(min(pixels.shape[:2])*.055))) & white
    border = binary_propagation(seed, mask=white) & ~outside
    if border.sum() < .7*(pixels[..., 3] >= 128).sum():
        fringe = binary_dilation(border, iterations=max(1, round(min(pixels.shape[:2])*.003)))
        pixels[..., 3] = np.where(fringe, 0, pixels[..., 3])
    components, count = label(pixels[..., 3] > 32)
    if count:
        sizes = np.bincount(components.ravel())
        substantial = np.flatnonzero(sizes >= max(8, sizes[1:].max()*.001))
        substantial = substantial[substantial != 0]
        keep = binary_dilation(np.isin(components, substantial), iterations=2)
        pixels[..., 3] = np.where(keep, pixels[..., 3], 0)
    image = Image.fromarray(pixels, 'RGBA')
    bounds = image.getchannel('A').getbbox()
    if bounds:
        image = image.crop(bounds)
    square = Image.new('RGBA', (max(image.size),)*2)
    square.paste(image, ((square.width-image.width)//2, (square.height-image.height)//2))
    square.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
    return square


def ornament_layers(spec, t, beat=0.):
    """Layers for an ornament spec: dict(kind=library picture or None, image=painted cutout or None, motion)."""
    if spec.get('image'):
        return [(('painted', spec['image']), cutout(spec['image']), image_pose(spec.get('motion'), t, beat))]
    return layers_at(spec['kind'], t, beat)


def layers_at(kind, t, beat=0.):
    """[(texture key, RGBA image, pose)] back to front for the picture at time t."""
    animated = library_frames(kind)
    if animated:
        frames, durations = animated
        moment = t % sum(durations)
        index = 0
        while moment >= durations[index]:
            moment -= durations[index]
            index += 1
        pose = dict(dx=0., dy=.03*math.sin(t*1.6), dz=0., scale=1+.05*beat, angle=0., alpha=1.)
        return [((kind, 'library', index), frames[index], pose)]
    images = drawings(kind)
    return [((kind, name), images[name], pose) for name, pose in built_in_pose(kind, t, beat)]
