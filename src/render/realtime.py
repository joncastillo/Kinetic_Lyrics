"""Real-time kinetic typography on a continuously panning, stitched canvas.

The camera glides across one panorama of every illustration at a constant speed, from the
first frame to the last. Each line is written onto the canvas ahead of the camera as it is
sung, sized so it stays fully on screen until its last word, then drifts away with the
picture. Words use a role-based font mix (small typewriter function words, heavy content
words, huge condensed hero words); hero words form through the line's particle entrance;
melody drives colour and pace. A per-line backdrop (marquee, echo, giant word...) adds
variety. Every frame is a pure function of time, so renders split across processes exactly.
"""
import bisect
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import random
import string

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FUNCTION_WORDS = frozenset('''
a an and are as at be but by for from i if in is it its me my of on or our so than that the their them they this to
too up us was we were what when where which who will with you your i'm don't can't won't im
ang ng sa mga at ay ko ka na ni si kay ito iyan iyon ako ikaw siya kami tayo kayo sila ka'y ko'y
'''.split())
ROLE_FONTS = {'function': ('cour.ttf', 'georgiai.ttf', 'DejaVuSansMono.ttf'),
              'content': ('ariblk.ttf', 'seguibl.ttf', 'DejaVuSans-Bold.ttf'),
              'hero': ('impact.ttf', 'bahnschrift.ttf', 'DejaVuSansCondensed-Bold.ttf')}
ROLE_SCALE = {'function': .6, 'content': 1., 'hero': 2.2}
HOT_COLORS = ('#FF3D7F', '#FFD23F')
BACKDROP_COLORS = ('#FF3D7F', '#4CC9FF', '#FFD23F')
MARGIN, MIN_WIDTH, MIN_HEIGHT, LEAD_WIDTH = .04, .42, .3, .55
LINE_LINGER = 1.5
BACKDROP_FADE, UNDERLINE_LINGER = .8, .6
BANDS = 3
BAND_UNIT = .014
BAND_ALPHA = 46
STRAND_STEP = 6.
THREAD_LIFE = 30.
INSTRUMENT_GLOWS = {'drums': ('#FF3D7F', .18),
                    'other': ('#FFD23F', .3),
                    'bass': ('#8A6BFF', .4)}
WORD_SHAPE_FILL, WORD_SHAPE_FADE = 60, .6
MIN_SHAPE_CONTRAST = 3.
MIN_GLOW_CONTRAST = 1.5
SHAPE_COLORS = ('#FF3D7F', '#4CC9FF', '#FFD23F', '#8A6BFF', '#F2F2F2', '#16243F', '#3B1230', '#0E3B43')
FRAME_RETRACT = .9
SHAPES = ('ring', 'circle', 'triangle', 'square', 'hexagon')
SHAPE_LIFE = 3.2
LINE_FRAMES = ('ellipse', 'frame', 'hexagon', 'diamond')
BASE_SCALE = .75
OLDER_LINES, DIM_TIME, FADE_TIME = .5, .8, 1.2
STILL_HOLD = 6.
STILL_EXIT = .8
PARTICLE_ENTRY = .6


@lru_cache(maxsize=256)
def role_font(role, size):
    for name in ROLE_FONTS[role]:
        for folder in ('', 'C:/Windows/Fonts/'):
            try:
                return ImageFont.truetype(folder+name, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def smooth(value):
    value = max(0., min(1., value))
    return value*value*(3-2*value)


def overshoot(value):
    value = max(0., min(1., value))-1
    return 1+2.4*value**3+1.4*value**2


def hex_rgb(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


@dataclass
class Word:
    index: int
    text: str
    role: str
    start: float
    end: float
    size: int
    color: tuple
    hot: bool
    held: bool
    fast: bool
    x: float = 0.
    y: float = 0.
    width: float = 0.
    row: int = 0
    glow: str = ''
    shape: tuple = ()


def bare(text):
    return text.strip(string.punctuation+'“”‘’').lower()


def assign_roles(line, features, emphasis):
    """Function words stay small; the planned emphasis and the most sung-out words become heroes."""
    words = line['words']
    roles = ['function' if len(words) > 2 and bare(w['text']) in FUNCTION_WORDS else 'content' for w in words]
    def weight(i):
        f = features[i] if features else {}
        return (f.get('pitch_rank') or 0)+(f.get('duration_rank') or 0)+(f.get('loudness_rank') or 0)*.5
    candidates = [i for i, role in enumerate(roles) if role == 'content']
    heroes = {emphasis} if 0 <= emphasis < len(words) and roles[emphasis] == 'content' else set()
    for i in sorted(candidates, key=weight, reverse=True):
        if len(heroes) >= (2 if len(words) > 4 else 1):
            break
        if not heroes or weight(i) >= 1.6:
            heroes.add(i)
    return ['hero' if i in heroes else role for i, role in enumerate(roles)]


class LineLayout:
    """Mixed-size, left-justified rows inside a box (screen coordinates at the line's start)."""

    def __init__(self, line, features, scene, palette, base, box, min_scale=.55):
        ink, accent = hex_rgb(palette[2]), hex_rgb(palette[3])
        roles = assign_roles(line, features, scene.get('emphasis', -1))
        self.words = []
        for i, (word, role) in enumerate(zip(line['words'], roles)):
            f = features[i] if features else {}
            hot = (f.get('pitch_rank') or 0) >= .8
            color = hex_rgb(HOT_COLORS[i % 2]) if role == 'hero' and hot else accent if role == 'hero' else ink
            self.words.append(Word(i, word['text'].upper() if role != 'function' else word['text'].lower(), role,
                                   word['start'], word['end'], 1, color, hot,
                                   held=(f.get('duration_rank') or 0) >= .75, fast=(f.get('rate_rank') or 0) >= .7))
        x0, y0, w, h = box
        scale = 1.
        while True:
            rows = self._flow(base*scale, w)
            height = sum(r['height'] for r in rows)*1.08
            if height <= h or scale <= min_scale:
                break
            scale *= .92
        self.height = height
        self.width = max(r['width'] for r in rows)
        y = y0+(h-height)/2
        for number, row in enumerate(rows):
            x, baseline = x0, y+row['ascent']
            for word in row['words']:
                word.row = number
                word.x, word.y = x, baseline-role_font(word.role, word.size).getmetrics()[0]
                x += word.width+row['gap']
            y += row['height']*1.08

    def _flow(self, base, max_width):
        for word in self.words:
            word.size = max(10, round(base*ROLE_SCALE[word.role]))
            word.width = role_font(word.role, word.size).getlength(word.text)
            if word.width > max_width:
                word.size = max(10, round(word.size*max_width/word.width))
                word.width = role_font(word.role, word.size).getlength(word.text)
        rows, current = [], []
        gap = base*.24
        for word in self.words:
            if current and sum(w.width for w in current)+gap*len(current)+word.width > max_width:
                rows.append(current)
                current = []
            current.append(word)
        if current:
            rows.append(current)
        result = []
        for row in rows:
            metrics = [role_font(w.role, w.size).getmetrics() for w in row]
            ascent, descent = max(m[0] for m in metrics), max(m[1] for m in metrics)
            result.append(dict(words=row, gap=gap, ascent=ascent, height=ascent+descent*.6,
                               width=sum(w.width for w in row)+gap*(len(row)-1)))
        return result


def word_sprite(word, size, color, alpha=1., glitch=False):
    """The word drawn at `size` with a soft shadow; also returns padding and glyph spans."""
    font = role_font(word.role, size)
    pad = max(8, round(size*.12))
    sprite = Image.new('RGBA', (math.ceil(font.getlength(word.text))+pad*2, round(size*1.4)+pad*2))
    shadow = Image.new('RGBA', sprite.size)
    ImageDraw.Draw(shadow).text((pad, pad+round(size*.04)), word.text, font=font, fill=(0, 0, 0, round(150*alpha)))
    sprite.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1, size*.05))))
    draw = ImageDraw.Draw(sprite)
    if glitch:
        shift = max(1, round(size*.03))
        draw.text((pad-shift, pad), word.text, font=font, fill=(255, 40, 120, round(170*alpha)))
        draw.text((pad+shift, pad), word.text, font=font, fill=(40, 220, 255, round(170*alpha)))
    draw.text((pad, pad), word.text, font=font, fill=(*color, round(255*alpha)))
    edges = [0]+[pad+round(font.getlength(word.text[:k])) for k in range(1, len(word.text))]+[sprite.width]
    return sprite, pad, list(zip(edges, edges[1:]))


class RealtimeTypography:
    def __init__(self, compositor, melody=None, speed=1., rhythm=None, options=None):
        from render.typography_settings import kinetic_options
        self.c = compositor
        self.options = kinetic_options(options)
        self.rhythm = rhythm or {}
        self.melody = melody.get('lines') if isinstance(melody, dict) else None
        self.speed = max(.2, speed)
        self.lines = self.path = self.world = self.mattes = None
        self.still = self.options['camera'] == 'still'
        self.shapes = None


    def plan(self):
        """Lay out every line once: where on the canvas it is written and which backdrop it gets."""
        if self.lines is not None:
            return self.lines
        from direction.typography import PALETTES
        from render.world_canvas import ALONG_HORIZON, DIRECTIONS, CameraPath, WorldCanvas
        c = self.c
        paths = getattr(c, 'illustration_paths', [])
        starts = list(getattr(c, 'art_starts', None) or [0.])
        from render.layout import FULL_FRAME
        if not (c.artwork_mode in FULL_FRAME and paths):
            starts = [0.]
        starts = starts[:max(1, len(paths))]
        spans = [(s, starts[i+1] if i+1 < len(starts) else c.duration) for i, s in enumerate(starts)]
        self.still = self.options['camera'] == 'still'
        self.path = CameraPath(spans, 0. if self.still else max(1e-3, self.options['pan_speed'])*c.width, c.duration,
                               ALONG_HORIZON if c.artwork_mode == 'matte' else DIRECTIONS)
        if c.artwork_mode in FULL_FRAME and paths and not self.still:
            if c.artwork_mode == 'matte':
                import artwork.greenscreen as greenscreen
                self.world = WorldCanvas(paths[:len(spans)], spans, c.width, c.height, self.path, load=lambda p: greenscreen.load(p)[0])
                self.mattes = WorldCanvas(paths[:len(spans)], spans, c.width, c.height, self.path, load=lambda p: greenscreen.load(p)[1], mode='L')
            else:
                self.world = WorldCanvas(paths[:len(spans)], spans, c.width, c.height, self.path)
        margin = c.width*MARGIN
        self.lines, previous = [], None
        for index, line in enumerate(c.data):
            start, end = line['words'][0]['start'], line['words'][-1]['end']
            box = self.reading_box(index, start, end+LINE_LINGER, margin)
            scene = c.plan['scenes'][index]
            features = self.melody[index] if self.melody and index < len(self.melody) else None
            layout = LineLayout(line, features, scene, PALETTES[scene['palette']], c.reading_size()*BASE_SCALE, box)
            camera = self.path.at(start)
            row_starts = {}
            for word in layout.words:
                row_starts.setdefault(word.row, word.start)
            shifts, floor = {}, -math.inf
            for row in sorted(row_starts):
                words = [w for w in layout.words if w.row == row]
                there = self.path.at(row_starts[row])
                top = min(w.y for w in words)
                shifts[row] = (there[0]-camera[0], max(there[1]-camera[1], floor-top))
                floor = max(w.y+w.size*1.15 for w in words)+shifts[row][1]
            for word in layout.words:
                word.x += shifts[word.row][0]
                word.y += shifts[word.row][1]
            rng = random.Random(index*7919+13)
            kinds = [b for b in self.options['backdrops'] if b != previous] or self.options['backdrops']
            backdrop = rng.choice(kinds) if kinds and rng.random() < self.options['backdrop_rate'] else 'none'
            previous = backdrop
            self.lines.append(dict(layout=layout, start=start, end=end, offset=(camera[0]-c.width/2, camera[1]-c.height/2),
                                   backdrop=backdrop, color=hex_rgb(rng.choice(BACKDROP_COLORS)), direction=rng.choice((-1, 1)),
                                   frame=rng.choice(LINE_FRAMES) if self.still or rng.random() < self.options['frames'] else None,
                                   filled=rng.random() < .5,
                                   pulse=self.line_instrument(start, end) if rng.random() < self.options['text_pulse'] else None))
        if self.still:
            for index, line in enumerate(self.lines):
                line['exit'] = self.exit_window(index)
        self.assign_accents()
        return self.lines

    def assign_accents(self):
        """Pick the words that glow with an instrument (`glow_words` share of all words) and the hero words
        that get a translucent shape behind them (`word_shapes` share), in a colour that keeps them readable."""
        from effects.colors import contrast
        enabled = [stem for stem in INSTRUMENT_GLOWS if stem in self.options['glows']]
        for index, line in enumerate(self.lines):
            material = self.effect(index) is not None
            for word in line['layout'].words:
                rng = random.Random(round(word.start*1000)*31+word.index)
                if enabled and rng.random() < self.options['glow_words'] and not (material and word.role == 'hero'):
                    hits = {stem: sum(1 for time, _ in (self.rhythm.get(stem) or []) if word.start-.5 <= time <= word.end+3)
                            for stem in enabled if contrast(hex_rgb(INSTRUMENT_GLOWS[stem][0]), word.color) >= MIN_GLOW_CONTRAST}
                    best = max(hits, key=hits.get, default=None)
                    word.glow = best if best and hits[best] else ''
                if word.role == 'hero' and rng.random() < self.options['word_shapes']:
                    colors = [hex_rgb(c) for c in SHAPE_COLORS]
                    readable = [c for c in colors if contrast(c, word.color) >= MIN_SHAPE_CONTRAST]
                    color = rng.choice(readable) if readable else max(colors, key=lambda c: contrast(c, word.color))
                    word.shape = (rng.choice(LINE_FRAMES), color)

    def exit_window(self, index):
        """On a still camera a line stays until its half of the screen is needed again (or a long pause), then exits."""
        c, line = self.c, self.lines[index]
        recipe = c.effect_catalog['exit'].get(c.effect_pairs[index][1]) if c.particle_intensity > 0 else None
        length = STILL_EXIT/c.effect_speed(recipe.id) if recipe else FADE_TIME
        due = self.lines[index+2]['start'] if index+2 < len(self.lines) else c.duration
        start = max(line['end']+.3, min(due-length, line['end']+STILL_HOLD))
        return start, length, recipe

    def line_instrument(self, start, end):
        """The instrument with the most onsets while the line is sung (never the voice)."""
        counts = {stem: sum(1 for time, _ in (self.rhythm.get(stem) or []) if start <= time <= end) for stem in INSTRUMENT_GLOWS}
        best = max(counts, key=counts.get, default=None)
        return best if best and counts[best] else None

    def text_pulse(self, index, t):
        """Instrument colour and strength pulsing through this line's words, if the line was chosen."""
        stem = self.lines[index].get('pulse')
        if not stem:
            return None, 0.
        from audio.rhythm import envelope
        return hex_rgb(INSTRUMENT_GLOWS[stem][0]), envelope(self.rhythm.get(stem), t, INSTRUMENT_GLOWS[stem][1])

    def reading_box(self, index, start, end, margin):
        """Write the line where the camera is heading, so it crosses the whole screen while it is sung."""
        c = self.c
        a, b = self.path.at(start), self.path.at(end)
        dx, dy = b[0]-a[0], b[1]-a[1]
        sky = None
        if self.mattes:
            sky = self.travelled_sky(a, b, margin)
        elif getattr(c, 'open_boxes', None):
            sky = c.open_boxes[min(len(c.open_boxes)-1, max(0, bisect.bisect_right(c.art_starts, start)-1))]
        if self.still and sky:
            x, y, width, height = sky
            if height >= c.height*.3:
                height = (height-margin/2)/2
                y += (index % 2)*(height+margin/2)
            return x, y, width, height
        lead = 1. if self.still else LEAD_WIDTH
        width = min(c.width*lead-(2*margin if self.still else 0), max(c.width*MIN_WIDTH, c.width-2*margin-abs(dx)))
        height = max(c.height*MIN_HEIGHT, c.height-2*margin-abs(dy))
        x = c.width-margin-width if dx >= 0 else margin
        y = c.height-margin-height if dy >= 0 else margin
        if sky:
            # Keep the line inside greenscreen sky that stays open while the camera carries it across.
            left, right = max(x, sky[0]), min(x+width, sky[0]+sky[2])
            if right-left < c.width*MIN_WIDTH:
                left, right = sky[0], sky[0]+sky[2]
            x, y, width, height = left, sky[1], right-left, sky[3]
            if height >= c.height*.3:
                height = (height-margin/2)/2
                y += (index % 2)*(height+margin/2)
            return x, y, width, height
        if height >= c.height*.5:
            height = (height-margin)/2
            y += (index % 2)*(height+margin)
        return x, y, width, height

    def travelled_sky(self, a, b, margin):
        """Screen box (at camera position `a`) that is open sky in every view between camera positions a and b."""
        from artwork.greenscreen import open_box
        c = self.c
        left, top = math.floor(min(a[0], b[0])-c.width/2), math.floor(min(a[1], b[1])-c.height/2)
        span = (math.ceil(c.width+abs(b[0]-a[0])), math.ceil(c.height+abs(b[1]-a[1])))
        box = open_box(self.mattes.view(left, top, *span), round(margin/2))
        if not box:
            return None
        return box[0]+left-(a[0]-c.width/2), box[1]+top-(a[1]-c.height/2), box[2], box[3]

    def opacity(self, index, t):
        """Full while newest, easing to half when the next line starts, then out after the one after.
        On a still camera lines stay at full strength until their exit animation has finished."""
        lines = self.lines
        if self.still:
            start, length, _ = lines[index]['exit']
            return 1. if t < start+length else 0.
        value = 1.
        if index+1 < len(lines):
            value -= (1-OLDER_LINES)*smooth((t-lines[index+1]['start'])/DIM_TIME)
        if index+2 < len(lines):
            value *= 1-smooth((t-lines[index+2]['start'])/FADE_TIME)
        return value

    def visible(self, t):
        """Started lines that are still visible, newest first, each with its eased opacity."""
        lines = self.plan()
        newest = max((i for i, line in enumerate(lines) if line['start'] <= t), default=None)
        if newest is None:
            return []
        shown = [(i, self.opacity(i, t)) for i in range(newest, max(-1, newest-(8 if self.still else 4)), -1)]
        return [(i, value) for i, value in shown if value > .005]


    def frame(self, t):
        c = self.c
        self.plan()
        center = self.path.at(t)
        left, top = center[0]-c.width/2, center[1]-c.height/2
        base = (math.floor(left), math.floor(top))
        fraction = (left-base[0], top-base[1])
        scenery = None
        if self.world:
            canvas = self.world.view(base[0], base[1], c.width+2, c.height+2)
            if self.mattes:
                scenery = canvas.copy()
                scenery.putalpha(self.mattes.view(base[0], base[1], c.width+2, c.height+2))
        else:
            scenery = c.scenery(t)
            index = max(0, sum(1 for line in c.data if line['words'][0]['start'] <= t)-1)
            screen = c.background(index, t, veil=False).convert('RGBA')
            c.illustration(screen, index, t)
            canvas = Image.new('RGBA', (c.width+2, c.height+2))
            canvas.paste(screen, (0, 0))
        visible = self.visible(t)
        if visible:
            newest = visible[0][0]
            handover = smooth((t-self.lines[newest]['start'])/BACKDROP_FADE)
            if newest and handover < 1:
                self.paint_backdrop(canvas, newest-1, t, fraction, 1-handover)
            self.paint_backdrop(canvas, newest, t, fraction)
        self.paint_shapes(canvas, t, fraction)
        if self.options['traces']:
            self.paint_traces(canvas, t, base, visible)
        for index, opacity in visible:
            if self.still and t >= self.lines[index]['exit'][0]:
                self.paint_exit(canvas, index, t, base)
                continue
            self.paint_frame(canvas, index, t, opacity, base)
            self.paint_line(canvas, index, t, opacity, base)
        if scenery is not None:
            canvas.alpha_composite(scenery)
        shifted = canvas.transform((c.width, c.height), Image.Transform.AFFINE, (1, 0, fraction[0], 0, 1, fraction[1]),
                                   resample=Image.Resampling.BILINEAR)
        return shifted.convert('RGB')

    def shift(self, index, base):
        offset = self.lines[index]['offset']
        return offset[0]-base[0], offset[1]-base[1]

    def paint_line(self, layer, index, t, opacity, base):
        entrance = self.effect(index)
        pulse_color, pulse = self.text_pulse(index, t)
        shift = self.shift(index, base)
        for word in self.lines[index]['layout'].words:
            if t < word.start:
                continue
            if word.shape:
                self.paint_word_shape(layer, word, shift, t, opacity)
            if word.glow:
                self.paint_word_glow(layer, word, shift, t, opacity)
            particle = entrance is not None and word.role == 'hero'
            entry = min(1., PARTICLE_ENTRY/self.c.effect_speed(entrance.id)) if particle else (.1 if word.fast else .2 if word.role == 'function' else .28)/self.speed
            progress = (t-word.start)/entry
            settled = overshoot(progress)
            drift = math.sin((t-word.start)*1.6+word.index*.9)*word.size*.015
            if particle:
                self.paint_particle_word(layer, word, shift, drift, max(0., 1-progress), entrance, opacity)
                continue
            scale, dy, alpha = 1., drift, smooth(progress*1.6)
            if word.role == 'function':
                dy += (1-smooth(progress))*word.size*.5
            elif word.role == 'content':
                scale = 1.35-.35*settled
            else:
                scale = 2.1-1.1*settled
            if word.held and t < word.end:
                scale *= 1+.08*smooth((t-word.start)/max(.2, word.end-word.start))
            self.paint_word(layer, word, scale, shift, dy, alpha*opacity, glitch=self.options['glitch'] and word.role == 'hero' and progress < .8,
                            active=word.start <= t < word.end, tint=(pulse_color, pulse*.7) if pulse > .02 else None)

    def word_box(self, word, shift):
        ascent = role_font(word.role, word.size).getmetrics()[0]
        left, top = word.x+shift[0], word.y+shift[1]+ascent*.08
        return left, top, left+word.width, word.y+shift[1]+ascent*1.02

    def paint_word_shape(self, layer, word, shift, t, opacity):
        """A polygon or ellipse that fades in behind the word with a translucent fill and a clean edge."""
        fade = smooth((t-word.start)/WORD_SHAPE_FADE)*opacity
        if fade <= .01:
            return
        kind, color = word.shape
        outline = shape_outline(kind, *self.word_box(word, shift), word.size*.14)
        art = Image.new('RGBA', layer.size)
        draw = ImageDraw.Draw(art)
        draw.polygon(outline, fill=(*color, round(WORD_SHAPE_FILL*fade)))
        draw.line(outline, fill=(*color, round(200*fade)), width=max(2, round(self.c.height*.004)), joint='curve')
        layer.alpha_composite(art)

    def paint_word_glow(self, layer, word, shift, t, opacity):
        """A soft halo in the instrument's colour behind the word, pulsing on that instrument's hits."""
        from audio.rhythm import envelope
        color, decay = INSTRUMENT_GLOWS[word.glow]
        level = envelope(self.rhythm.get(word.glow), t, decay)*self.options['glow_strength']*opacity*smooth((t-word.start)/.4)
        if level <= .02:
            return
        halo, pad = self.word_halo(word, hex_rgb(color))
        halo = halo.copy()
        halo.putalpha(halo.getchannel('A').point(lambda a: round(a*min(1., level*1.4))))
        paste_clipped(layer, halo, round(word.x+shift[0]-pad), round(word.y+shift[1]-pad))

    def word_halo(self, word, color):
        halos = self.__dict__.setdefault('_halos', {})
        key = (id(word), color)
        if key not in halos:
            sprite, pad, _ = word_sprite(word, word.size, (255, 255, 255))
            reach = max(4, round(word.size*.18))
            canvas = Image.new('L', (sprite.width+reach*4, sprite.height+reach*4))
            canvas.paste(sprite.getchannel('A').point(lambda a: 255 if a > 200 else 0), (reach*2, reach*2))
            glow = canvas.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(reach))
            halo = Image.new('RGBA', canvas.size, color)
            halo.putalpha(glow.point(lambda a: min(255, a*2)))
            halos[key] = (halo, pad+reach*2)
        return halos[key]

    def effect(self, index):
        c = self.c
        return c.effect_catalog['entrance'].get(c.effect_pairs[index][0]) if c.particle_intensity > 0 else None

    def paint_word(self, layer, word, scale, shift, dy, alpha, glitch=False, active=False, tint=None):
        if alpha <= .01:
            return
        size = max(8, round(word.size*scale))
        color = word.color if active or word.role != 'content' else tuple(round(v*.92) for v in word.color)
        if tint:
            color = tuple(round(a+(b-a)*tint[1]) for a, b in zip(color, tint[0]))
        sprite, pad, _ = word_sprite(word, size, color, alpha, glitch)
        font = role_font(word.role, size)
        x = word.x+shift[0]+word.width/2-font.getlength(word.text)/2-pad
        y = word.y+shift[1]+role_font(word.role, word.size).getmetrics()[0]-font.getmetrics()[0]+dy-pad
        paste_clipped(layer, sprite, round(x), round(y))

    def paint_particle_word(self, layer, word, shift, dy, amount, recipe, opacity):
        from effects.particles.motion import paint_transition
        sprite, pad, spans = word_sprite(word, word.size, word.color)
        x, y = round(word.x+shift[0]-pad), round(word.y+shift[1]+dy-pad)
        if opacity >= .99:
            paint_transition(layer, sprite, x, y, 'entrance', amount, recipe, word.index, self.c.particle_intensity, .6,
                             self.c.effect_cache, glyph_spans=spans)
            return
        overlay = Image.new('RGBA', layer.size)
        paint_transition(overlay, sprite, x, y, 'entrance', amount, recipe, word.index, self.c.particle_intensity, .6,
                         self.c.effect_cache, glyph_spans=spans)
        overlay.putalpha(overlay.getchannel('A').point(lambda a: round(a*opacity)))
        layer.alpha_composite(overlay)

    def paint_exit(self, layer, index, t, base):
        """The finished line and its shape leave together with the line's exit effect (or a fade without one)."""
        start, length, recipe = self.lines[index]['exit']
        amount = min(1., (t-start)/length)
        line = Image.new('RGBA', layer.size)
        self.paint_frame(line, index, start, 1., base)
        self.paint_line(line, index, start, 1., base)
        bounds = line.getbbox()
        if not bounds:
            return
        if recipe is None:
            line.putalpha(line.getchannel('A').point(lambda a: round(a*(1-smooth(amount)))))
            layer.alpha_composite(line)
            return
        from effects.particles.motion import paint_transition
        paint_transition(layer, line.crop(bounds), bounds[0], bounds[1], 'exit', amount, recipe, index, self.c.particle_intensity, .6,
                         self.c.effect_cache)

    def paint_frame(self, layer, index, t, opacity, base):
        """Some lines are built inside a shape whose outline draws on as the first word lands."""
        line = self.lines[index]
        if line['frame'] is None or t < line['start']:
            return
        words = line['layout'].words
        shift = self.shift(index, base)
        left = min(w.x for w in words)+shift[0]
        right = max(w.x+w.width for w in words)+shift[0]
        top = min(w.y for w in words)+shift[1]
        bottom = max(w.y+w.size*1.15 for w in words)+shift[1]
        pad = self.c.height*.02 if self.still else (right-left)*.08+self.c.height*.03
        outline = shape_outline(line['frame'], left, top, right, bottom, pad)
        reveal = smooth((t-line['start'])/(.7/self.speed))
        following = math.inf if self.still else self.lines[index+1]['start'] if index+1 < len(self.lines) else math.inf
        retract = smooth((t-following)/FRAME_RETRACT)
        if retract >= 1:
            return
        art = Image.new('RGBA', layer.size)
        draw = ImageDraw.Draw(art)
        color = line['color']
        if line['filled']:
            draw.polygon(outline, fill=(*color, round(42*reveal*(1-retract))))
        trace_outline(draw, outline, retract, reveal, color, max(2, round(self.c.height*.005)))
        layer.alpha_composite(art)


    def shape_events(self):
        """Shapes on strong bass notes (or line starts without bass), on screen for about the
        `geometry` share of the song and spread across it."""
        if self.shapes is None:
            count = round(self.options['geometry']*self.c.duration/SHAPE_LIFE)
            moments = [time for time, strength in (self.rhythm.get('bass') or []) if strength >= .6]
            if not moments:
                moments = [line['start'] for line in self.plan()]
            spacing = self.c.duration/max(1, count)
            self.shapes, last = [], -spacing
            for time in moments:
                if len(self.shapes) >= count:
                    break
                if time-last < spacing:
                    continue
                last = time
                rng = random.Random(round(time*1000))
                self.shapes.append(dict(start=time, kind=rng.choice(SHAPES), filled=rng.random() < .4,
                                        x=rng.uniform(.12, .88), y=rng.uniform(.15, .85), size=rng.uniform(.12, .32),
                                        spin=rng.uniform(-25, 25), drift=(rng.uniform(-.03, .03), rng.uniform(-.03, .03)),
                                        color=hex_rgb(rng.choice(BACKDROP_COLORS))))
        return self.shapes

    def paint_shapes(self, layer, t, fraction):
        """Outlined or translucent shapes that drift, turn slowly and fade in and out."""
        import bisect
        events = self.shape_events()
        live = events[max(0, bisect.bisect_right([e['start'] for e in events], t-SHAPE_LIFE)):
                      bisect.bisect_right([e['start'] for e in events], t)]
        if not live:
            return
        c = self.c
        art = Image.new('RGBA', layer.size)
        draw = ImageDraw.Draw(art)
        for shape in live:
            age = t-shape['start']
            reveal = smooth(age/.8)
            retract = smooth((age-SHAPE_LIFE+1.)/1.)
            if retract >= 1:
                continue
            radius = c.height*shape['size']*(1+.08*age/SHAPE_LIFE)
            cx = (shape['x']+shape['drift'][0]*age)*c.width
            cy = (shape['y']+shape['drift'][1]*age)*c.height
            angle = math.radians(shape['spin']*age)
            sides = {'ring': 72, 'circle': 72, 'triangle': 3, 'square': 4, 'hexagon': 6}[shape['kind']]
            points = [(cx+radius*math.cos(angle+2*math.pi*k/sides-math.pi/2), cy+radius*math.sin(angle+2*math.pi*k/sides-math.pi/2))
                      for k in range(sides+1)]
            if shape['filled'] and shape['kind'] != 'ring':
                draw.polygon(points, fill=(*shape['color'], round(45*reveal*(1-retract))))
            trace_outline(draw, points, retract, reveal, shape['color'], max(2, round(c.height*.004)), alpha=170)
        layer.alpha_composite(art.transform(art.size, Image.Transform.AFFINE, (1, 0, -fraction[0], 0, 1, -fraction[1]),
                                            resample=Image.Resampling.BILINEAR))


    def paint_traces(self, layer, t, base, visible):
        """Glowing underlines beneath sung words, and one continuous thread whose head travels from hero
        word to hero word, arriving as each is sung. Most of the time it wraps a shape around the word on
        its way through. Its tail follows THREAD_LIFE seconds behind, so it is erased just as smoothly."""
        trace = Image.new('RGBA', layer.size)
        draw = ImageDraw.Draw(trace)
        for index, _ in visible:
            shift = self.shift(index, base)
            for word in self.lines[index]['layout'].words:
                if word.start > t or t >= word.end+UNDERLINE_LINGER or word.role == 'function':
                    continue
                ascent = role_font(word.role, word.size).getmetrics()[0]
                fraction = smooth((t-word.start)/max(.15, word.end-word.start))
                fade = 1-smooth((t-word.end)/UNDERLINE_LINGER)
                y = word.y+shift[1]+ascent*1.08
                x0 = word.x+shift[0]
                x1 = x0+word.width*fraction
                weight = max(2, round(word.size*.035))
                draw.line((x0, y, x1, y), fill=(*word.color, round(230*fade)), width=weight)
                draw.ellipse((x1-weight*1.6, y-weight*1.6, x1+weight*1.6, y+weight*1.6), fill=(255, 255, 255, round(240*fade)))
        fill_layer = Image.new('RGBA', layer.size)
        self.paint_thread(draw, fill_layer, t, base)
        if fill_layer.getbbox():
            layer.alpha_composite(fill_layer)
        if trace.getbbox():
            glow = trace.filter(ImageFilter.GaussianBlur(6))
            layer.alpha_composite(glow)
            layer.alpha_composite(glow)
            layer.alpha_composite(trace)

    def paint_thread(self, draw, fill_layer, t, base):
        thread = self.thread_path()
        head = thread_distance(thread['keys'], t)
        if head is None:
            return
        tail = thread_distance(thread['keys'], t-THREAD_LIFE) or 0.
        samples = sample_thread(thread['pieces'], tail, head, STRAND_STEP)
        if len(samples) >= 2:
            self.paint_bands(draw, fill_layer, samples, tail, head, t, base)
            x, y = samples[-1][0]-base[0], samples[-1][1]-base[1]
            draw.ellipse((x-5, y-5, x+5, y+5), fill=(255, 255, 255, 230))

    def paint_bands(self, draw, fill_layer, samples, tail, head, t, base):
        """The thread as a few thick translucent bands, like the PSP waves: each swells and narrows in its
        own slow wave, overlaps brighten, a thin crest catches the light, and all pinch together at the
        moving head and at the tail."""
        unit = self.c.height*BAND_UNIT
        normals = strand_normals(samples)
        bands = Image.new('RGBA', fill_layer.size)
        for band in range(BANDS):
            centre = band-(BANDS-1)/2
            upper, lower = [], []
            for (x, y, distance, color), normal in zip(samples, normals):
                pinch = smooth(min(head-distance, distance-tail)/(unit*12))
                phase = distance/(unit*14)+t*.5+band*1.7
                middle = (centre*1.4+math.sin(phase)*1.2)*unit*pinch
                half = (1.1+.8*math.sin(phase*.6+band))*unit*pinch
                px, py = x-base[0], y-base[1]
                upper.append((px+normal[0]*(middle-half), py+normal[1]*(middle-half), color))
                lower.append((px+normal[0]*(middle+half), py+normal[1]*(middle+half), color))
            band_layer = Image.new('RGBA', fill_layer.size)
            band_draw = ImageDraw.Draw(band_layer)
            for (color, top), (_, bottom) in zip(group_by_color(upper), group_by_color(lower)):
                band_draw.polygon(top+bottom[::-1], fill=(*color, BAND_ALPHA))
                band_draw.line(top, fill=(*color, 150), width=2, joint='curve')
            bands.alpha_composite(band_layer)
        box = bands.getbbox()
        if box:
            box = (max(0, box[0]-4), max(0, box[1]-4), min(bands.width, box[2]+4), min(bands.height, box[3]+4))
            fill_layer.alpha_composite(bands.crop(box).filter(ImageFilter.GaussianBlur(1.1)), box[:2])

    def thread_path(self):
        """The whole thread on the canvas: a curve into each hero word, with the distance its head has
        reached as each is sung. Joins match direction so it never kinks, and each curve bends just
        enough to fill its time at one cruising speed."""
        if getattr(self, '_thread', None) is not None:
            return self._thread
        stops = []
        for line in self.plan():
            for word in line['layout'].words:
                if word.role == 'hero':
                    ascent = role_font(word.role, word.size).getmetrics()[0]
                    top = word.y+line['offset'][1]+ascent*.08
                    bottom = word.y+line['offset'][1]+ascent*1.02
                    stops.append(dict(word=word, anchor=(word.x+line['offset'][0]+word.width/2, (top+bottom)/2)))
        stops.sort(key=lambda stop: stop['word'].start)
        times = []
        for stop in stops:
            times.append(max(stop['word'].start, times[-1]+.05) if times else stop['word'].start)
        for number, stop in enumerate(stops):
            stop['arrive'] = stop['leave'] = direction(stops[number-1]['anchor'], stop['anchor']) if number else (1., 0.)
        rates = sorted(math.dist(stops[n]['anchor'], stops[n+1]['anchor'])/(times[n+1]-times[n]) for n in range(len(stops)-1))
        cruise = rates[len(rates)//2] if rates else 0.
        pieces, distances, total = [], [], 0.
        for number, stop in enumerate(stops):
            if number:
                wanted = cruise*(times[number]-times[number-1])
                curve = thread_curve(stops[number-1], stop, wanted, 1 if number % 2 else -1)
                total = add_piece(pieces, curve, stop['word'].color, total)
            distances.append(total)
        self._thread = dict(pieces=pieces, keys=monotone_keys(times, distances))
        return self._thread


    def paint_backdrop(self, layer, index, t, fraction, strength=1.):
        """One of several treatments behind a line, using only words already sung; eases in and hands over.
        Marquees always carry the entire line, laid out once, with each word appearing as it is sung."""
        line = self.lines[index]
        words = line['layout'].words
        sung = [w for w in words if w.start <= t]
        strong = [w.text.upper() for w in sung if w.role == 'hero'] or [w.text.upper() for w in sung if w.role == 'content'][:2]
        if line['backdrop'] == 'none' or not sung:
            return
        c, color, kind = self.c, line['color'], line['backdrop']
        marquee = kind in ('outline', 'filled', 'vertical')
        if not marquee and not strong:
            return
        start = words[0].start if marquee else min(w.start for w in sung if w.text.upper() in strong)
        arrive = smooth((t-start)/BACKDROP_FADE)
        alpha = arrive*strength
        if alpha <= .01:
            return
        art = Image.new('RGBA', layer.size)
        draw = ImageDraw.Draw(art)
        elapsed = (t-start)*self.speed
        if marquee:
            size = round(c.height*.28)
            font = role_font('hero', size)
            gap, separator = font.getlength(' '), '  •  '
            positions, cursor = [], 0.
            for word in words:
                positions.append((word, cursor))
                cursor += font.getlength(word.text.upper())+gap
            period = cursor+font.getlength(separator)
            style = dict(fill=(*color, round(60*alpha))) if kind == 'filled' else \
                dict(fill=(0, 0, 0, 0), stroke_width=max(2, round(size*.02)), stroke_fill=(*color, round(150*alpha)))
            length = layer.height if kind == 'vertical' else layer.width
            offset = (line['direction']*(elapsed*c.width*.08+(1-arrive)*c.width*.2)) % period-period
            strip = Image.new('RGBA', (round(length+period*2), round(size*1.5)))
            strip_draw = ImageDraw.Draw(strip)
            for copy in range(int(length//period)+2):
                for word, x in positions:
                    if word.start <= t:
                        strip_draw.text((offset+copy*period+x, 0), word.text.upper(), font=font, **style)
            if kind == 'vertical':
                strip = strip.crop((0, 0, length, strip.height)).rotate(90 if line['direction'] > 0 else -90, expand=True)
                edge = round(c.width*.02) if index % 2 else layer.width-strip.width-round(c.width*.02)
                paste_clipped(art, strip, edge, 0)
            else:
                paste_clipped(art, strip.crop((0, 0, length, strip.height)), 0, round(c.height*.62))
        elif kind == 'echo':
            word = strong[0]
            for step in range(4):
                size = round(c.height*.22*(1+.18*step+.04*elapsed)*(1+.12*(1-arrive)))
                font = role_font('hero', size)
                draw.text(((layer.width-font.getlength(word))/2, c.height*.5-size*.6), word, font=font, fill=(0, 0, 0, 0),
                          stroke_width=max(2, round(size*.015)), stroke_fill=(*color, round(120*alpha/(step+1))))
        elif kind == 'giant':
            word = strong[0]
            size = round(c.height*.62*(1+.06*min(1., elapsed/6))*(1+.12*(1-arrive)))
            font = role_font('hero', size)
            draw.text(((layer.width-font.getlength(word))/2, c.height*.5-size*.62), word, font=font, fill=(0, 0, 0, 0),
                      stroke_width=max(3, round(size*.012)), stroke_fill=(*color, round(110*alpha)))
        layer.alpha_composite(art.transform(art.size, Image.Transform.AFFINE, (1, 0, -fraction[0], 0, 1, -fraction[1]),
                                            resample=Image.Resampling.BILINEAR))


def shape_outline(kind, left, top, right, bottom, pad):
    """Closed outline of a shape fitted around a box, starting at its left-middle point."""
    cx, cy = (left+right)/2, (top+bottom)/2
    rx, ry = (right-left)/2+pad, (bottom-top)/2+pad
    if kind == 'ellipse':
        rx, ry = rx*1.12, ry*1.25
        return [(cx+rx*math.cos(a), cy+ry*math.sin(a)) for a in (math.pi+2*math.pi*k/72 for k in range(73))]
    if kind == 'frame':
        corners = [(cx-rx, cy), (cx-rx, cy-ry), (cx+rx, cy-ry), (cx+rx, cy+ry), (cx-rx, cy+ry)]
    elif kind == 'hexagon':
        corners = [(cx+rx*1.08*math.cos(a), cy+ry*1.15*math.sin(a)) for a in (math.pi+math.pi/3*k for k in range(6))]
    else:
        corners = [(cx-rx*1.25, cy), (cx, cy-ry*1.4), (cx+rx*1.25, cy), (cx, cy+ry*1.4)]
    return rounded(corners, cy)


def rounded(corners, cy, passes=4):
    """Corner-cut a closed polygon into a smooth loop that starts at its left-middle point."""
    ring = list(corners)
    for _ in range(passes):
        ring = [point for a, b in zip(ring, ring[1:]+ring[:1])
                for point in ((.75*a[0]+.25*b[0], .75*a[1]+.25*b[1]), (.25*a[0]+.75*b[0], .25*a[1]+.75*b[1]))]
    start = min(range(len(ring)), key=lambda i: (round(ring[i][0]), abs(ring[i][1]-cy)))
    ring = ring[start:]+ring[:start]
    return ring+[ring[0]]


def direction(a, b):
    length = math.hypot(b[0]-a[0], b[1]-a[1]) or 1.
    return (b[0]-a[0])/length, (b[1]-a[1])/length


def polyline_length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def thread_curve(previous, stop, wanted, side, most=2.5):
    """Cubic curve between two thread stops, leaving and arriving along their directions, bowed sideways
    until it is about `wanted` long (never more than `most` times the straight distance)."""
    a, b = previous['anchor'], stop['anchor']
    span = math.dist(a, b) or 1.
    normal = ((a[1]-b[1])/span*side, (b[0]-a[0])/span*side)

    def curve(bow):
        reach = span*.45
        c1 = (a[0]+previous['leave'][0]*reach+normal[0]*bow, a[1]+previous['leave'][1]*reach+normal[1]*bow)
        c2 = (b[0]-stop['arrive'][0]*reach+normal[0]*bow, b[1]-stop['arrive'][1]*reach+normal[1]*bow)
        return [((1-u)**3*a[0]+3*(1-u)**2*u*c1[0]+3*(1-u)*u*u*c2[0]+u**3*b[0],
                 (1-u)**3*a[1]+3*(1-u)**2*u*c1[1]+3*(1-u)*u*u*c2[1]+u**3*b[1]) for u in (k/48 for k in range(49))]
    target = min(wanted, span*most)
    low, high = 0., span*2
    if polyline_length(curve(0.)) >= target:
        return curve(0.)
    for _ in range(18):
        middle = (low+high)/2
        low, high = (middle, high) if polyline_length(curve(middle)) < target else (low, middle)
    return curve(low)


def sample_thread(pieces, tail, head, step):
    """Evenly spaced (x, y, distance, colour) points along the thread, starting exactly at `tail` and
    ending exactly at `head` so both ends move every frame instead of in whole steps."""
    samples = []
    for piece in pieces:
        if piece['end'] <= tail or piece['start'] >= head:
            continue
        travelled = piece['start']
        for a, b in zip(piece['points'], piece['points'][1:]):
            length = math.dist(a, b)
            if length < 1e-6:
                continue
            first = max(tail, travelled)
            last = min(head, travelled+length)
            if first > last:
                travelled += length
                continue
            marks = [first, last]
            distance = math.ceil(first/step)*step
            while distance <= last:
                marks.append(distance)
                distance += step
            for distance in sorted(set(marks)):
                if not samples or distance > samples[-1][2]+1e-6:
                    u = (distance-travelled)/length
                    samples.append((a[0]+(b[0]-a[0])*u, a[1]+(b[1]-a[1])*u, distance, piece['color']))
            travelled += length
    return samples


def strand_normals(samples):
    normals = []
    for i in range(len(samples)):
        a, b = samples[max(0, i-1)], samples[min(len(samples)-1, i+1)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dy) or 1.
        normals.append((-dy/length, dx/length))
    return normals


def group_by_color(points):
    """Consecutive runs of points sharing a colour, overlapping by one point so runs join up."""
    runs, current, color = [], [], None
    for x, y, c in points:
        if c != color and current:
            runs.append((color, current+[(x, y)]))
            current = []
        color = c
        current.append((x, y))
    if len(current) >= 2:
        runs.append((color, current))
    return runs


def add_piece(pieces, points, color, total):
    length = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(points, points[1:]))
    if length > 1e-6:
        pieces.append(dict(points=points, color=color, start=total, end=total+length))
    return total+length


def monotone_keys(times, distances):
    """Monotone cubic (PCHIP) slopes through (time, distance) keys: the thread keeps moving forward, at a
    steady pace between keys, and its speed changes smoothly at each one instead of jumping."""
    deltas = [(d1-d0)/(t1-t0) for t0, t1, d0, d1 in zip(times, times[1:], distances, distances[1:])]
    if not deltas:
        return times, distances, [0.]*len(times)
    slopes = [deltas[0]]
    for k in range(1, len(deltas)):
        h0, h1, a, b = times[k]-times[k-1], times[k+1]-times[k], deltas[k-1], deltas[k]
        if a <= 0 or b <= 0:
            slopes.append(0.)
        else:
            w1, w2 = 2*h1+h0, h1+2*h0
            slopes.append((w1+w2)/(w1/a+w2/b))
    slopes.append(deltas[-1])
    return times, distances, slopes


def thread_distance(keys, t):
    """How far along the thread its head is at time t, or None before the first hero word."""
    times, distances, slopes = keys
    if not times or t < times[0]:
        return None
    if t >= times[-1]:
        return distances[-1]
    i = bisect.bisect_right(times, t)-1
    h = times[i+1]-times[i]
    u = (t-times[i])/h
    return ((2*u**3-3*u*u+1)*distances[i]+(u**3-2*u*u+u)*h*slopes[i]
            + (-2*u**3+3*u*u)*distances[i+1]+(u**3-u*u)*h*slopes[i+1])


def trace_outline(draw, points, start, end, color, width, alpha=210):
    """Draw the part of a closed outline between two fractions of its perimeter, with a bright head
    while it is still drawing on, so shapes are traced in and erased rather than faded."""
    if end <= start:
        return
    lengths = [0.]
    for a, b in zip(points, points[1:]):
        lengths.append(lengths[-1]+math.hypot(b[0]-a[0], b[1]-a[1]))
    def at(distance):
        for (a, b), first, last in zip(zip(points, points[1:]), lengths, lengths[1:]):
            if distance <= last:
                u = (distance-first)/max(1e-6, last-first)
                return a[0]+(b[0]-a[0])*u, a[1]+(b[1]-a[1])*u
        return points[-1]
    total = lengths[-1]
    begin, finish = total*start, total*end
    path = [at(begin)]+[p for p, d in zip(points, lengths) if begin < d < finish]+[at(finish)]
    draw.line(path, fill=(*color, alpha), width=width, joint='curve')
    if end < 1:
        head = path[-1]
        draw.ellipse((head[0]-5, head[1]-5, head[0]+5, head[1]+5), fill=(255, 255, 255, 230))


def paste_clipped(layer, sprite, x, y):
    box = (max(0, -x), max(0, -y), min(sprite.width, layer.width-x), min(sprite.height, layer.height-y))
    if box[2] > box[0] and box[3] > box[1]:
        layer.alpha_composite(sprite.crop(box), (max(0, x), max(0, y)))


def melody_for(folder):
    """Cached melody features from a project folder, if present."""
    try:
        return json.loads((Path(folder)/'video.melody.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
