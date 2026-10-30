"""Black hole sun: minimal cinematic typography, one short phrase at a time over the full-frame artwork.

Each line is cut into chunks of one to three words at the sung timings. A chunk is stacked in the
middle of the frame, one word per row, in two weights only: a hairline, widely tracked geometric
sans and an ultra-black one, so "BLACK" sits thin above a heavy "HOLE". Words arrive as they are sung:
hairline words settle in from oversized and faint, heavy words slide in with motion blur and brighten
from grey, some flip in mirrored, and the odd last word stands on end. While a chunk holds it pushes in
slowly; it leaves by flipping, sliding or blurring away just before the next one. The artwork behind it
pushes in too. Every frame is a pure function of time.
"""
import bisect
import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from project_paths import PROJECT_ROOT

FONT = PROJECT_ROOT/'assets'/'fonts'/'Montserrat-Variable.ttf'
FALLBACK = {'thin': ('segoeuil.ttf', 'arial.ttf'), 'heavy': ('seguibl.ttf', 'ariblk.ttf', 'arialbd.ttf')}
WEIGHT = {'thin': 200, 'heavy': 900}
TRACKING = {'thin': .1, 'heavy': .0}  # extra space between letters, as a share of the size
WHITE, GREY = (246, 246, 244), (150, 152, 156)
ANCHOR_Y = .46  # where a chunk is centred, as a share of the frame height
CHUNK_GAP = .32  # a pause this long (seconds) always starts a new chunk
LEAD, ENTRY, EXIT, HOLD = .06, .42, .3, .9
PUSH = .05  # how much a holding chunk grows over its time on screen
ART_PUSH = .06


def ease(value):
    value = max(0., min(1., value))
    return 1-(1-value)**3


def smooth(value):
    value = max(0., min(1., value))
    return value*value*(3-2*value)


@lru_cache(maxsize=256)
def font(weight, size):
    size = max(6, int(size))
    if FONT.is_file():
        try:
            face = ImageFont.truetype(str(FONT), size)
            face.set_variation_by_axes([WEIGHT[weight]])
            return face
        except (OSError, ValueError):
            pass
    for name in FALLBACK[weight]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


@lru_cache(maxsize=512)
def word_mask(text, weight, size):
    """The word as a white-on-black 'L' mask, tracked out, with a little room around it for blur."""
    face = font(weight, size)
    spacing = size*TRACKING[weight]
    widths = [face.getlength(ch) for ch in text]
    width = sum(widths)+spacing*max(0, len(text)-1)
    ascent, descent = face.getmetrics()
    pad = round(size*.12)
    mask = Image.new('L', (max(1, math.ceil(width)+2*pad), ascent+descent+2*pad))
    draw = ImageDraw.Draw(mask)
    x = pad
    for ch, w in zip(text, widths):
        draw.text((x, pad), ch, font=face, fill=255)
        x += w+spacing
    box = mask.getbbox() or (0, 0, mask.width, mask.height)
    # Keep the full line height so rows of one chunk share a baseline rhythm, but trim the sides.
    return mask.crop((max(0, box[0]-pad), max(0, box[1]-pad), min(mask.width, box[2]+pad), min(mask.height, box[3]+pad)))


def fit_size(text, weight, width, height_cap):
    """The size at which `text` spans `width` pixels, no taller than `height_cap`."""
    probe = 100
    measured = word_mask(text, weight, probe).width or 1
    return max(8, min(height_cap, probe*width/measured))


def is_function(word):
    from realtime_typography import FUNCTION_WORDS, bare
    return bare(word) in FUNCTION_WORDS


class CinemaTypography:
    def __init__(self, compositor, melody=None, speed=1., rhythm=None, options=None, only=None):
        self.c = compositor
        self.only = frozenset(only) if only is not None else None
        self.speed = max(.2, speed)
        self.chunks = None

    # ---------------------------------------------------------------- planning

    def plan(self):
        if self.chunks is not None:
            return self.chunks
        c = self.c
        scale = c.typography.get('font_scale', 1.25)/1.25
        chunks = []
        for index, line in enumerate(c.data):
            if self.only is not None and index not in self.only:
                continue
            words = [w for w in line['words'] if w['text'].strip()]
            for group in self.group(words):
                chunks.append(self.layout(index, group, len(chunks), scale))
        chunks.sort(key=lambda chunk: chunk['start'])
        for k, chunk in enumerate(chunks):
            following = chunks[k+1]['start'] if k+1 < len(chunks) else c.duration
            chunk['end'] = max(chunk['words'][-1]['start']+ENTRY, min(following-.02, chunk['last']+HOLD))
        self.chunks = chunks
        self.starts = [chunk['start'] for chunk in chunks]
        return chunks

    @staticmethod
    def group(words):
        """Chunks of one or two words (three when the extra ones are short function words), cut at pauses."""
        groups, current = [], []
        for word in words:
            if current:
                pause = word['start']-current[-1]['end']
                small = all(is_function(w['text']) for w in current+[word])
                full = len(current) >= (3 if small else 2)
                if pause > CHUNK_GAP or full:
                    groups.append(current)
                    current = []
            current.append(word)
        if current:
            groups.append(current)
        # A lone function word leans on the next chunk rather than standing alone.
        merged = []
        for group in groups:
            if merged and len(merged[-1]) == 1 and is_function(merged[-1][0]['text']) and len(group) == 1:
                merged[-1] = merged[-1]+group
            else:
                merged.append(group)
        return merged

    def layout(self, line, group, number, scale):
        c = self.c
        rng = random.Random(number*7919+line*131+len(group))
        texts = [w['text'].strip().upper() for w in group]
        content = [k for k, text in enumerate(texts) if not is_function(text)]
        # The heavy word is the chunk's last content word ("black HOLE", "the RAIN"); a lone word is heavy about half the time.
        heavy = content[-1] if content else len(texts)-1
        if len(group) == 1 and rng.random() < .45:
            heavy = None
        W, H = c.width, c.height
        portrait = H > W
        words = []
        heavy_width = None
        if heavy is not None:
            size = fit_size(texts[heavy], 'heavy', W*(.82 if portrait else .5), H*(.16 if portrait else .2)*scale)
            heavy_width = word_mask(texts[heavy], 'heavy', size).width
        for k, (word, text) in enumerate(zip(group, texts)):
            weight = 'heavy' if k == heavy else 'thin'
            vertical = len(group) == 1 and weight == 'heavy' and len(text) >= 4 and rng.random() < .22
            if weight == 'heavy':
                span = W*(.82 if portrait else .5)
                size = fit_size(text, 'heavy', span, H*(.16 if portrait else .2)*scale)
                if vertical:
                    size = fit_size(text, 'heavy', H*.42, W*.12*scale)
                motion = rng.choice(('slide', 'slide', 'zoom', 'flip'))
            else:
                wide = len(group) == 1 and len(text) >= 3 and rng.random() < .5
                if heavy_width:  # a hairline above or below a heavy word matches most of its width
                    span = heavy_width*(.85 if len(text) >= 3 else .45)
                else:
                    span = W*(.88 if wide else .55)*(1 if portrait else .62)
                size = fit_size(text, 'thin', span, H*(.11 if wide else .075)*scale*(1.4 if not portrait else 1))
                motion = rng.choice(('settle', 'settle', 'flip'))
            words.append(dict(text=text, weight=weight, size=size, start=word['start'], end=word['end'],
                              vertical=vertical, motion=motion, side=rng.choice((-1, 1)), axis=rng.choice(('x', 'y'))))
        # Stack the rows, centred on the anchor; a heavy row under a thin one tucks in close.
        heights = [word_mask(w['text'], w['weight'], w['size']).width if w['vertical']
                   else word_mask(w['text'], w['weight'], w['size']).height for w in words]
        gap = -min(w['size'] for w in words)*.08
        total = sum(heights)+gap*(len(words)-1)
        y = H*ANCHOR_Y-total/2
        for w, h in zip(words, heights):
            w['y'] = y+h/2
            y += h+gap
        return dict(line=line, words=words, start=group[0]['start']-LEAD, last=group[-1]['end'],
                    exit=rng.choice(('blur', 'flip', 'slide')), side=rng.choice((-1, 1)))

    # ---------------------------------------------------------------- drawing

    def frame(self, t):
        c = self.c
        self.plan()
        index = max(0, sum(1 for line in c.data if line['words'][0]['start'] <= t)-1)
        screen = self.backdrop(index, t)
        c.illustration(screen, index, t)
        k = bisect.bisect_right(self.starts, t)-1
        for number in (k-1, k):
            if 0 <= number < len(self.chunks) and self.chunks[number]['start'] <= t < self.chunks[number]['end']:
                self.paint_chunk(screen, self.chunks[number], t)
        return screen.convert('RGB')

    def backdrop(self, index, t):
        """The artwork, pushing in slowly from the moment it appears."""
        c = self.c
        image = c.background(index, t, veil=False).convert('RGBA')
        starts = list(getattr(c, 'art_starts', None) or [0.])
        current = max(0, bisect.bisect_right(starts, t)-1)
        span = (starts[current+1] if current+1 < len(starts) else c.duration)-starts[current]
        grow = 1+ART_PUSH*max(0., min(1., (t-starts[current])/max(1., span)))
        w, h = image.size
        cw, ch = w/grow, h/grow
        return image.resize(image.size, Image.Resampling.BILINEAR, box=((w-cw)/2, (h-ch)/2, (w+cw)/2, (h+ch)/2))

    def paint_chunk(self, screen, chunk, t):
        W = self.c.width
        hold = (t-chunk['start'])/max(.5, chunk['end']-chunk['start'])
        push = 1+PUSH*smooth(hold)
        leaving = (t-(chunk['end']-EXIT))/EXIT
        for word in chunk['words']:
            entry = ENTRY/self.speed
            arrive = (t-word['start']+entry)/entry
            if arrive <= 0:
                continue
            p = ease(arrive)
            state = dict(scale=push, alpha=1., flip=1., shift=0., blur=0., grey=0.)
            motion = word['motion']
            if motion == 'settle':  # hairlines come in oversized and faint, then sharpen into place
                state.update(scale=push*(1+.7*(1-p)), alpha=p**1.5, blur=(1-p)*word['size']*.08)
            elif motion == 'slide':  # heavy words sweep in sideways, blurred by their speed, grey to white
                speed = 3*(1-min(1., arrive))**2
                state.update(shift=-word['side']*W*.45*(1-p), blur=speed*word['size']*.18, grey=1-p, alpha=min(1., arrive*3))
            elif motion == 'zoom':  # in huge and grey, settling down to size
                state.update(scale=push*(1+1.2*(1-p)), grey=1-p, alpha=.35+.65*p)
            else:  # flip: turns over from its mirror image like a card
                state.update(flip=-math.cos(math.pi*min(1., arrive)), alpha=min(1., arrive*2), grey=(1-p)*.6)
            if leaving > 0:
                q = smooth(leaving)
                if chunk['exit'] == 'flip':
                    state['flip'] *= math.cos(math.pi*q)
                    state['alpha'] *= 1-q*.85
                elif chunk['exit'] == 'slide':
                    speed = 3*q**2
                    state['shift'] += chunk['side']*W*.5*q**2
                    state['blur'] += speed*word['size']*.18
                    state['alpha'] *= 1-q
                else:
                    state['scale'] *= 1+.25*q
                    state['blur'] += q*word['size']*.15
                    state['alpha'] *= 1-q
            self.paint_word(screen, word, state)

    def paint_word(self, screen, word, state):
        if state['alpha'] <= .01:
            return
        mask = word_mask(word['text'], word['weight'], word['size'])
        sx = state['scale']*state['flip'] if word['axis'] == 'x' else state['scale']
        sy = state['scale']*state['flip'] if word['axis'] == 'y' else state['scale']
        width, height = max(1, round(mask.width*abs(sx))), max(1, round(mask.height*abs(sy)))
        if width > self.c.width*4 or height > self.c.height*4:
            return
        image = mask.resize((width, height), Image.Resampling.BICUBIC)
        if sx < 0:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if sy < 0:
            image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if word['vertical']:
            image = image.rotate(90, expand=True)
        blur = state['blur']
        if blur > .6:
            # Motion blur along the slide; otherwise a soft defocus.
            if state['shift'] or word['motion'] == 'slide':
                steps = max(2, min(9, round(blur/2)))
                streak = Image.new('L', (image.width+round(blur*2), image.height))
                for s in range(steps):
                    layer = Image.new('L', streak.size)
                    layer.paste(image, (round(blur*2*s/(steps-1)), 0))
                    streak = Image.blend(streak, layer, 1/(s+1)) if s else layer
                image = streak
            else:
                image = image.filter(ImageFilter.GaussianBlur(blur))
        image = image.point(lambda v: round(v*min(1., state['alpha'])))
        # A song-wide lettering colour from the special instructions replaces white; its dimmed tone replaces grey.
        light = getattr(self.c, 'ink_override', None)
        light, dim = (light, tuple(round(v*.61) for v in light)) if light else (WHITE, GREY)
        colour = tuple(round(a+(b-a)*state['grey']) for a, b in zip(light, dim))
        x = self.c.width/2+state['shift']-image.width/2
        y = word['y']-image.height/2
        # A faint shadow keeps white hairlines readable over a pale sky.
        shade = image.filter(ImageFilter.GaussianBlur(max(1., word['size']*.06))).point(lambda v: round(v*.35))
        screen.paste((0, 0, 0, 255), (round(x), round(y+word['size']*.03)), shade)
        screen.paste(colour+(255,), (round(x), round(y)), image)
