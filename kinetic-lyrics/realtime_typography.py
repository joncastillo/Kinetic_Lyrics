"""Real-time kinetic typography on a continuously panning, stitched canvas.

The camera glides across one panorama of every illustration at a constant speed, from the
first frame to the last. Each line is written onto the canvas ahead of the camera as it is
sung, sized so it stays fully on screen until its last word, then drifts away with the
picture. Words use a role-based font mix (small typewriter function words, heavy content
words, huge condensed hero words); hero words form through the line's particle entrance;
melody drives colour and pace. A per-line backdrop (marquee, echo, giant word...) adds
variety. Every frame is a pure function of time, so renders split across processes exactly.
"""
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
MARGIN, MIN_WIDTH, MIN_HEIGHT = .04, .42, .3
LINE_LINGER = 1.5
BACKDROP_FADE, UNDERLINE_LINGER = .8, .6
THREAD_LIFE, THREAD_ERASE = 30., 1.5
GLOW_REACH = .5
INSTRUMENT_GLOWS = {'drums': ('corners', '#FF3D7F', .18),
                    'other': ('sides', '#FFD23F', .3),
                    'bass': ('bottom', '#8A6BFF', .4)}
FRAME_RETRACT = .9
SHAPES = ('ring', 'circle', 'triangle', 'square', 'hexagon')
SHAPE_LIFE = 3.2
LINE_FRAMES = ('ellipse', 'frame', 'hexagon', 'diamond')
BASE_SCALE = .75
OLDER_LINES, DIM_TIME, FADE_TIME = .5, .8, 1.2
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
        for row in rows:
            x, baseline = x0, y+row['ascent']
            for word in row['words']:
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
        from typography_settings import kinetic_options
        self.c = compositor
        self.options = kinetic_options(options)
        self.rhythm = rhythm or {}
        self.melody = melody.get('lines') if isinstance(melody, dict) else None
        self.speed = max(.2, speed)
        self.lines = self.path = self.world = None
        self.shapes = None


    def plan(self):
        """Lay out every line once: where on the canvas it is written and which backdrop it gets."""
        if self.lines is not None:
            return self.lines
        from kinetic_director import PALETTES
        from world_canvas import CameraPath, WorldCanvas
        c = self.c
        paths = getattr(c, 'illustration_paths', [])
        starts = list(getattr(c, 'art_starts', None) or [0.])
        if not (c.artwork_mode in ('fullscreen', 'verse') and paths):
            starts = [0.]
        starts = starts[:max(1, len(paths))]
        spans = [(s, starts[i+1] if i+1 < len(starts) else c.duration) for i, s in enumerate(starts)]
        self.path = CameraPath(spans, max(1e-3, self.options['pan_speed'])*c.width, c.duration)
        if c.artwork_mode in ('fullscreen', 'verse') and paths:
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
            rng = random.Random(index*7919+13)
            kinds = [b for b in self.options['backdrops'] if b != previous] or self.options['backdrops']
            backdrop = rng.choice(kinds) if kinds and rng.random() < self.options['backdrop_rate'] else 'none'
            previous = backdrop
            self.lines.append(dict(layout=layout, start=start, end=end, offset=(camera[0]-c.width/2, camera[1]-c.height/2),
                                   backdrop=backdrop, color=hex_rgb(rng.choice(BACKDROP_COLORS)), direction=rng.choice((-1, 1)),
                                   frame=rng.choice(LINE_FRAMES) if rng.random() < self.options['frames'] else None,
                                   filled=rng.random() < .5,
                                   pulse=self.line_instrument(start, end) if rng.random() < self.options['text_pulse'] else None))
        return self.lines

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
        from rhythm import envelope
        return hex_rgb(INSTRUMENT_GLOWS[stem][1]), envelope(self.rhythm.get(stem), t, INSTRUMENT_GLOWS[stem][2])

    def reading_box(self, index, start, end, margin):
        """Write the line where the camera is heading, so it crosses the whole screen while it is sung."""
        c = self.c
        a, b = self.path.at(start), self.path.at(end)
        dx, dy = b[0]-a[0], b[1]-a[1]
        width = max(c.width*MIN_WIDTH, c.width-2*margin-abs(dx))
        height = max(c.height*MIN_HEIGHT, c.height-2*margin-abs(dy))
        x = c.width-margin-width if dx >= 0 else margin
        y = c.height-margin-height if dy >= 0 else margin
        if height >= c.height*.5:
            height = (height-margin)/2
            y += (index % 2)*(height+margin)
        return x, y, width, height

    def opacity(self, index, t):
        """Full while newest, easing to half when the next line starts, then out after the one after."""
        lines = self.lines
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
        shown = [(i, self.opacity(i, t)) for i in range(newest, max(-1, newest-4), -1)]
        return [(i, value) for i, value in shown if value > .005]


    def frame(self, t):
        c = self.c
        self.plan()
        center = self.path.at(t)
        left, top = center[0]-c.width/2, center[1]-c.height/2
        base = (math.floor(left), math.floor(top))
        fraction = (left-base[0], top-base[1])
        if self.world:
            canvas = self.world.view(base[0], base[1], c.width+2, c.height+2, t)
        else:
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
            self.paint_frame(canvas, index, t, opacity, base)
            self.paint_line(canvas, index, t, opacity, base)
        shifted = canvas.transform((c.width, c.height), Image.Transform.AFFINE, (1, 0, fraction[0], 0, 1, fraction[1]),
                                   resample=Image.Resampling.BILINEAR)
        return self.accents(shifted.convert('RGB'), t)

    def glow_mask(self, region):
        """Soft edge glow for one region of the frame, cached per region."""
        masks = self.__dict__.setdefault('_glow_masks', {})
        if region not in masks:
            import numpy as np
            w, h = self.c.width, self.c.height
            ys, xs = np.mgrid[0:h, 0:w].astype(float)
            reach = h*GLOW_REACH
            if region == 'corners':
                glow = np.zeros((h, w))
                for cx, cy in ((0, 0), (w, 0), (0, h), (w, h)):
                    glow = np.maximum(glow, np.clip(1-np.hypot(xs-cx, ys-cy)/reach, 0, 1)**2)
            elif region == 'sides':
                glow = np.clip(1-np.minimum(xs, w-xs)/(reach*.6), 0, 1)**2
            else:
                glow = np.clip(1-(h-ys)/(reach*.5), 0, 1)**2
            masks[region] = Image.fromarray((glow*255).astype('uint8'), 'L')
        return masks[region]

    def accents(self, frame, t):
        """Edge glows pulsing with the instruments, each with its own place and colour; never the voice."""
        from rhythm import envelope
        for stem, (region, color, decay) in INSTRUMENT_GLOWS.items():
            if stem not in self.options['glows']:
                continue
            level = envelope(self.rhythm.get(stem), t, decay)*self.options['glow_strength']
            if level > .005:
                mask = self.glow_mask(region).point(lambda a, level=level: round(a*level))
                frame = Image.composite(Image.new('RGB', frame.size, hex_rgb(color)), frame, mask)
        return frame

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
        from particle_motion import paint_transition
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
        outline = shape_outline(line['frame'], left, top, right, bottom, (right-left)*.08+self.c.height*.03)
        reveal = smooth((t-line['start'])/(.7/self.speed))
        following = self.lines[index+1]['start'] if index+1 < len(self.lines) else math.inf
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
        """Glowing underlines beneath sung words, and one continuous thread that runs from hero word to
        hero word, each segment staying about 30 s before it retracts from its tail. Most of the time the
        thread wraps a geometric shape around the hero word it reaches, then leaves from that shape."""
        trace = Image.new('RGBA', layer.size)
        draw = ImageDraw.Draw(trace)
        heroes = []
        newest = visible[0][0] if visible else -1
        first = next((i for i in range(newest+1) if self.lines[i]['start'] >= t-THREAD_LIFE-THREAD_ERASE-20), newest+1)
        for index in range(max(0, first-1), newest+1):
            shift = self.shift(index, base)
            for word in self.lines[index]['layout'].words:
                if word.start > t:
                    continue
                ascent = role_font(word.role, word.size).getmetrics()[0]
                if word.role == 'hero':
                    heroes.append(self.thread_stop(word, shift, ascent))
                if index in dict(visible) and t < word.end+UNDERLINE_LINGER and word.role != 'function':
                    fraction = smooth((t-word.start)/max(.15, word.end-word.start))
                    fade = 1-smooth((t-word.end)/UNDERLINE_LINGER)
                    y = word.y+shift[1]+ascent*1.08
                    x0 = word.x+shift[0]
                    x1 = x0+word.width*fraction
                    weight = max(2, round(word.size*.035))
                    draw.line((x0, y, x1, y), fill=(*word.color, round(230*fade)), width=weight)
                    draw.ellipse((x1-weight*1.6, y-weight*1.6, x1+weight*1.6, y+weight*1.6), fill=(255, 255, 255, round(240*fade)))
        for number, stop in enumerate(heroes):
            word = stop['word']
            age = t-word.start
            reveal = smooth(age/.9) if number else 1.
            retract = smooth((age-THREAD_LIFE)/THREAD_ERASE)
            if retract >= 1:
                continue
            if number:
                a, b = heroes[number-1]['anchor'], stop['anchor']
                side = 1 if number % 2 else -1
                bend = ((b[1]-a[1])*.3*side, (a[0]-b[0])*.3*side)
                control = ((a[0]+b[0])/2+bend[0], (a[1]+b[1])/2+bend[1])
                curve = [((1-u)**2*a[0]+2*(1-u)*u*control[0]+u*u*b[0], (1-u)**2*a[1]+2*(1-u)*u*control[1]+u*u*b[1])
                         for u in (k/48 for k in range(49))]
                trace_outline(draw, curve, retract, reveal, word.color, 3, alpha=200)
            if stop['outline']:
                wrap = smooth((age-(.9 if number else 0.))/.8)
                trace_outline(draw, stop['outline'], smooth((age-THREAD_LIFE-THREAD_ERASE*.5)/THREAD_ERASE), wrap,
                              word.color, 3, alpha=200)
        if trace.getbbox():
            glow = trace.filter(ImageFilter.GaussianBlur(6))
            layer.alpha_composite(glow)
            layer.alpha_composite(glow)
            layer.alpha_composite(trace)

    def thread_stop(self, word, shift, ascent):
        """Where the thread meets a hero word: the start of a shape around it, or the word's centre."""
        rng = random.Random(round(word.start*1000)+word.index)
        left, top = word.x+shift[0], word.y+shift[1]+ascent*.08
        right, bottom = left+word.width, word.y+shift[1]+ascent*1.02
        outline = None
        if rng.random() < self.options['thread_shapes']:
            outline = shape_outline(rng.choice(LINE_FRAMES), left, top, right, bottom, word.size*.18)
        anchor = outline[0] if outline else ((left+right)/2, (top+bottom)/2)
        return dict(word=word, outline=outline, anchor=anchor)


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
        return [(cx-rx, cy), (cx-rx, cy-ry), (cx+rx, cy-ry), (cx+rx, cy+ry), (cx-rx, cy+ry), (cx-rx, cy)]
    if kind == 'hexagon':
        return [(cx+rx*1.08*math.cos(a), cy+ry*1.15*math.sin(a)) for a in (math.pi+math.pi/3*k for k in range(7))]
    return [(cx-rx*1.25, cy), (cx, cy-ry*1.4), (cx+rx*1.25, cy), (cx, cy+ry*1.4), (cx-rx*1.25, cy)]


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
