"""Greenscreen scenery: a horizon painted against a chroma-key sky, keyed over a matching plain plate.

Each lyric group gets two generated images. The scenery shows the land, water, rooftops or trees
along a horizon, with everything above the skyline painted as flat chroma-key green; there is no
main character. The plate is a plain painting of the sky that belongs above that scenery. Keying
the green gives a matte, and the finished artwork is the plate seen through the open (green) part
of the scenery. The renderer paints the plate, then the kinetic typography, then lays the keyed
scenery over both, so lyrics can only ever be seen inside the open area.

The matte travels inside the artwork PNG as a text chunk, so selecting, replacing, archiving or
repairing an image keeps its matte with it. Images without one (uploads, older files) fall back to
their own transparency, then to keying any chroma green they contain.
"""
import base64
import io

import numpy as np
from PIL import Image, ImageFilter
from PIL.PngImagePlugin import PngInfo

MATTE_KEY = 'kinetic-lyrics-matte'
# Green dominance (green minus the stronger of red and blue) that starts and completes keying.
KEY_LOW, KEY_HIGH = 70, 140
# Open areas smaller than this share of the frame are left as scenery, so green leaves or
# clothing in the painting are never punched through.
MIN_REGION = .01
# A scenery plate must open at least this share of the frame for its sky to hold lyrics.
MIN_OPEN, MAX_OPEN = .18, .85

DIRECTOR_PROMPT = (
    'Turn each lyric group and its supplied English meaning into a distinct scenery plate for a kinetic lyric video. '
    'Each scene is seen from a low viewpoint with a clear horizon or skyline: describe the land, water, hills, '
    'rooftops, streets, trees or architecture along the horizon and below it, connected to the lyric meaning. '
    'There is no main character or dominant figure silhouette; any people are small, incidental and below the skyline. '
    'Name the time of day, the light, the palette and the colour of the sky, but place nothing in the sky itself: '
    'no clouds, sun, moon, birds or objects above the skyline. The sky is painted separately. '
    'Keep a coherent rendering style across the song while letting each lyric choose its place. '
    'Describe only what the illustrator should draw. Do not explain the interpretation or quote the lyrics. '
    'No lettering, captions, logos, frames or borders. '
    'Return only JSON with a subjects array in input order.'
)


def image_prompt(subject, layout, style_prompt):
    return (
        'Paint this lyric-grounded scenery as a full-frame matte painting with an empty greenscreen sky: '+subject.strip()+'. '
        +layout['visual_prompt']+' '
        'Whatever sky colour the scene describes, paint the sky area as flat pure chroma-key green; '
        'the real sky is added later. '
        'Use the following only for color, brushwork and mood of the scenery: '+style_prompt+'. '
        'No lettering, written numbers, captions, logos or watermarks. No frame or border.'
    )


def plate_prompt(subject, layout, style_prompt):
    return (
        'Paint only the open sky that belongs above this scenery: '+subject.strip()+'. '
        'Match its time of day, light direction, palette and atmosphere. '
        'A full-bleed, calm, plain sky: a soft smooth gradient with at most faint low-contrast haze or thin cloud, '
        'uncluttered and even in tone so lyrics stay readable over it. '
        'No land, horizon, water, buildings, trees, people, birds, sun disc, moon, stars, '
        'lettering, frame or border. Smooth clean pigment, no grain. '
        'Use the following only for color, brushwork and mood: '+style_prompt+'.'
    )


def key_green(image):
    """Matte from chroma green: 255 keeps the scenery, 0 opens the sky. Small green islands stay scenery."""
    import scipy.ndimage as ndi
    rgb = np.asarray(image.convert('RGB')).astype(np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    dominance = g-np.maximum(r, b)
    openness = np.clip((dominance-KEY_LOW)/(KEY_HIGH-KEY_LOW), 0, 1)
    labels, count = ndi.label(openness > .5)
    if count:
        sizes = ndi.sum(np.ones_like(openness), labels, index=np.arange(1, count+1))
        small = np.isin(labels, np.flatnonzero(sizes < MIN_REGION*openness.size)+1)
        openness[small] = 0
        # Fringe pixels belong to the open area only when they touch a large region.
        large = ndi.binary_dilation(labels*~small > 0, iterations=2)
        openness[~large] = 0
    else:
        openness[:] = 0
    return Image.fromarray(np.round((1-openness)*255).astype(np.uint8), 'L')


def despill(image, matte):
    """Pull the green fringe out of scenery edges next to the keyed sky."""
    import scipy.ndimage as ndi
    rgb = np.asarray(image.convert('RGB')).astype(np.int16)
    kept = np.asarray(matte) > 0
    edge = ndi.binary_dilation(np.asarray(matte) < 255, iterations=3) & kept
    limit = np.maximum(rgb[..., 0], rgb[..., 2])
    rgb[..., 1] = np.where(edge, np.minimum(rgb[..., 1], limit), rgb[..., 1])
    return Image.fromarray(rgb.astype(np.uint8), 'RGB')


def open_share(matte):
    return 1-float(np.asarray(matte, dtype=np.float32).mean())/255


def usable(image):
    """A scenery plate whose keyed sky is large enough to hold lyrics, and still shows scenery."""
    return MIN_OPEN <= open_share(key_green(image)) <= MAX_OPEN


def flat_plate(rgb, matte):
    """A plain stand-in plate for artwork without one: the scenery's average colour along the skyline, lightened."""
    pixels = np.asarray(rgb.convert('RGB')).astype(np.float32)
    alpha = np.asarray(matte)
    import scipy.ndimage as ndi
    band = ndi.binary_dilation(alpha < 128, iterations=6) & (alpha >= 128)
    if not band.any():
        band = alpha >= 128
    colour = pixels[band].mean(axis=0) if band.any() else np.array([200., 210., 225.])
    colour = colour+(255-colour)*.35
    return Image.new('RGB', rgb.size, tuple(int(round(v)) for v in colour))


def compose(scenery, plate, matte=None):
    """The plate seen through the keyed sky of the scenery, and the matte that separates them."""
    matte = matte or key_green(scenery)
    plate = plate.convert('RGB').resize(scenery.size, Image.Resampling.LANCZOS)
    return Image.composite(despill(scenery, matte), plate, matte), matte


def save(rgb, matte, path):
    """Write opaque artwork with its matte embedded as a PNG text chunk."""
    encoded = io.BytesIO()
    matte.save(encoded, format='PNG', optimize=True)
    info = PngInfo()
    info.add_text(MATTE_KEY, base64.b64encode(encoded.getvalue()).decode('ascii'), zip=True)
    rgb.convert('RGB').save(path, pnginfo=info)


def compose_files(raw, plate, target):
    with Image.open(raw) as scenery, Image.open(plate) as background:
        rgb, matte = compose(scenery.convert('RGB'), background)
    save(rgb, matte, target)


def load(path):
    """(rgb, matte) for greenscreen artwork. A matte of 255 is scenery in front of the lyrics; 0 is open sky."""
    with Image.open(path) as source:
        source.load()
        embedded = getattr(source, 'text', {}).get(MATTE_KEY)
        rgb = source.convert('RGB')
        if embedded:
            with Image.open(io.BytesIO(base64.b64decode(embedded))) as stored:
                matte = stored.convert('L')
            if matte.size != rgb.size:
                matte = matte.resize(rgb.size, Image.Resampling.BILINEAR)
            return rgb, matte
        if source.mode in ('RGBA', 'LA', 'PA') or 'transparency' in source.info:
            alpha = source.convert('RGBA').getchannel('A')
            if alpha.getextrema()[0] < 255:
                return Image.composite(rgb, flat_plate(rgb, alpha), alpha), alpha
    matte = key_green(rgb)
    if open_share(matte) >= MIN_REGION:
        return compose(rgb, flat_plate(rgb, matte), matte)
    # No sky to key: the whole picture is the plate.
    return rgb, Image.new('L', rgb.size, 0)


def open_box(matte, margin=0):
    """The largest rectangle (x, y, w, h) that is open sky everywhere, inset by `margin` pixels, or None."""
    width, height = matte.size
    cols, rows = 48, max(8, round(48*height/width))
    grid = np.asarray(matte.resize((cols, rows), Image.Resampling.BOX).filter(ImageFilter.MaxFilter(3))) < 8
    best, heights = (0, None), np.zeros(cols, dtype=int)
    for row in range(rows):
        heights = np.where(grid[row], heights+1, 0)
        stack = []
        for col in range(cols+1):
            current = heights[col] if col < cols else 0
            while stack and heights[stack[-1]] >= current:
                tall = heights[stack.pop()]
                left = stack[-1]+1 if stack else 0
                if tall*(col-left) > best[0]:
                    best = (tall*(col-left), (left, row-tall+1, col-left, tall))
            stack.append(col)
    if best[1] is None:
        return None
    left, top, span, tall = best[1]
    x, y = left*width/cols+margin, top*height/rows+margin
    w, h = span*width/cols-2*margin, tall*height/rows-2*margin
    if w < width*.15 or h < height*.08:
        return None
    return round(x), round(y), round(w), round(h)
