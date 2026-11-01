"""Real-time kinetic typography over one full-frame illustration at a time.

The typography camera glides at a constant speed from the first frame to the last. Each
line is written onto its path ahead of the camera as it is sung, sized so it stays fully
on screen until its last word, then drifts away. Background illustrations remain screen
aligned so adjacent paintings cannot overlap. Words use a role-based font mix (small typewriter function words, heavy content
words, huge condensed hero words); hero words form through the line's particle entrance;
melody drives colour and pace. A per-line backdrop (marquee, echo, giant word...) adds
variety. Every frame is a pure function of time, so renders split across processes exactly.
When the video mixes scenes, `only` limits the drawn lines (and the thread between hero words)
to the song sections this scene films; the canvas and camera still span the whole song.
"""
import bisect
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import random
import string

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

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
DIE_TIME, HEAD_FADE = 4., .8  # when a wisp's run ends: its tail fades back to the head; the head dims out
INSTRUMENT_GLOWS = {'drums': ('#FF3D7F', .18),
                    'other': ('#FFD23F', .3),
                    'bass': ('#8A6BFF', .4)}
WORD_SHAPE_FILL, WORD_SHAPE_FADE = 60, .6
MIN_SHAPE_CONTRAST = 3.
MIN_GLOW_CONTRAST = 1.5
SHAPE_COLORS = ('#FF3D7F', '#4CC9FF', '#FFD23F', '#8A6BFF', '#F2F2F2', '#16243F', '#3B1230', '#0E3B43')
FRAME_RETRACT = .9
SHAPES = ('triangle', 'square', 'hexagon')
SHAPE_LIFE = 3.2
LINE_FRAMES = ('ellipse', 'frame', 'hexagon', 'diamond')
ROW_LEADING = .12  # gap between the rows of one line, as a share of its base size
LINE_GAP = .05  # clear space between separate lines on the canvas, as a share of the screen height
HIDE_TIME = .5
TRACE_TIME = (1.5, 6.)  # seconds the wisp may take round a traced shape
CURL_TIME = (1.2, 4.)
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
    ink: tuple = (0., 0.)  # top and bottom of the drawn glyphs, relative to y
    effect: object = None  # a letter effect a special instruction gave this word


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
    """Mixed-size, left-justified rows inside a box (screen coordinates at the line's start). Rows sit
    close together, measured from the glyphs' own ink so no row touches the next."""

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
            leading = base*scale*ROW_LEADING
            height = sum(r['height'] for r in rows)+leading*(len(rows)-1)
            if height <= h or scale <= min_scale:
                break
            scale *= .92
        self.height = height
        self.width = max(r['width'] for r in rows)
        self.gap = rows[0]['gap']
        y = y0+(h-height)/2
        for number, row in enumerate(rows):
            x, baseline = x0, y-row['top']
            for word in row['words']:
                word.row = number
                word.x, word.y = x, baseline-role_font(word.role, word.size).getmetrics()[0]
                x += word.width+row['gap']
            y += row['height']+leading

    def bounds(self):
        return (min(w.x for w in self.words), min(w.y+w.ink[0] for w in self.words),
                max(w.x+w.width for w in self.words), max(w.y+w.ink[1] for w in self.words))

    def move(self, dx, dy):
        for word in self.words:
            word.x += dx
            word.y += dy

    def _flow(self, base, max_width):
        for word in self.words:
            word.size = max(10, round(base*ROLE_SCALE[word.role]))
            word.width = role_font(word.role, word.size).getlength(word.text)
            if word.width > max_width:
                word.size = max(10, round(word.size*max_width/word.width))
                word.width = role_font(word.role, word.size).getlength(word.text)
        for word in self.words:
            font = role_font(word.role, word.size)
            box = font.getbbox(word.text)
            word.ink = (box[1], box[3])
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
            # Ink extents relative to the shared baseline.
            ascents = [role_font(w.role, w.size).getmetrics()[0] for w in row]
            top = min(w.ink[0]-a for w, a in zip(row, ascents))
            bottom = max(w.ink[1]-a for w, a in zip(row, ascents))
            result.append(dict(words=row, gap=gap, top=top, height=bottom-top,
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
    def __init__(self, compositor, melody=None, speed=1., rhythm=None, options=None, only=None, large=()):
        from typography_settings import kinetic_options
        self.c = compositor
        self.only = frozenset(only) if only is not None else None
        self.large = frozenset(large)
        self.options = kinetic_options(options)
        self.rhythm = rhythm or {}
        self.melody = melody.get('lines') if isinstance(melody, dict) else None
        self.speed = max(.2, speed)
        self.lines = self.path = self.world = None
        self.veils = []  # (start, end) times when the scene mix carries the wisp instead (see wisp_screen)
        self.still = self.options['camera'] == 'still'
        self.shapes = None


    def plan(self):
        """Lay out every line once: where on the canvas it is written and which backdrop it gets."""
        if self.lines is not None:
            return self.lines
        from kinetic_director import PALETTES
        from world_canvas import CameraPath
        c = self.c
        paths = getattr(c, 'illustration_paths', [])
        starts = list(getattr(c, 'art_starts', None) or [0.])
        if not (c.artwork_mode in ('fullscreen', 'verse') and paths):
            starts = [0.]
        starts = starts[:max(1, len(paths))]
        spans = [(s, starts[i+1] if i+1 < len(starts) else c.duration) for i, s in enumerate(starts)]
        self.still = self.options['camera'] == 'still'
        self.path = CameraPath(spans, 0. if self.still else max(1e-3, self.options['pan_speed'])*c.width, c.duration)
        margin = c.width*MARGIN
        self.lines, previous = [], None
        for index, line in enumerate(c.data):
            start, end = line['words'][0]['start'], line['words'][-1]['end']
            large = index in self.large
            box, region = self.reading_box(index, start, end+LINE_LINGER, c.width*.03 if large else margin, full=large)
            scene = c.plan['scenes'][index]
            features = self.melody[index] if self.melody and index < len(self.melody) else None
            base_size = c.reading_size()*BASE_SCALE*(2.1 if index in self.large else 1.)
            layout = LineLayout(line, features, scene, c.scene_palette(scene), base_size, box)
            for word in layout.words:  # special instructions typed for the renderer
                directive = getattr(c, 'word_directives', {}).get((index, word.index), {})
                word.color = directive.get('color') or word.color
                word.effect = c.effect_catalog['entrance'].get(directive.get('effect'))
            camera = self.path.at(start)
            offset = (camera[0]-c.width/2, camera[1]-c.height/2)
            if self.shown(index) and not self.still:
                self.keep_clear(layout, offset, region, start)
            bounds = layout.bounds()
            rng = random.Random(index*7919+13)
            kinds = [b for b in self.options['backdrops'] if b != previous] or self.options['backdrops']
            backdrop = rng.choice(kinds) if kinds and rng.random() < self.options['backdrop_rate'] else 'none'
            previous = backdrop
            self.lines.append(dict(layout=layout, start=start, end=end, offset=offset,
                                   bounds=(bounds[0]+offset[0], bounds[1]+offset[1], bounds[2]+offset[0], bounds[3]+offset[1]),
                                   backdrop=backdrop, color=hex_rgb(rng.choice(BACKDROP_COLORS)), direction=rng.choice((-1, 1)),
                                   frame=rng.choice(LINE_FRAMES) if self.still or rng.random() < self.options['frames'] else None,
                                   filled=rng.random() < .5,
                                   pulse=self.line_instrument(start, end) if rng.random() < self.options['text_pulse'] else None))
        if self.still:
            for index, line in enumerate(self.lines):
                line['exit'] = self.exit_window(index)
        self.assign_accents()
        return self.lines

    def shown(self, index):
        return self.only is None or index in self.only

    def lingers(self, index, t):
        """Whether an already planned line is still on the panning canvas at time t (see opacity)."""
        if self.lines[index].get('hide', math.inf) <= t:
            return False
        return index+2 >= len(self.lines) or t < self.lines[index+2]['start']+FADE_TIME

    def keep_clear(self, layout, offset, region, start):
        """Slide a new line up or down within its reading region so a clear LINE_GAP separates it from every
        earlier line still on screen. Lines it cannot get clear of fade out just before it starts."""
        c = self.c
        gap = c.height*LINE_GAP
        left, top, right, bottom = layout.bounds()
        height = bottom-top
        others = [j for j in range(len(self.lines)) if self.shown(j) and self.lingers(j, start)]
        rects = {j: (self.lines[j]['bounds'][0]-offset[0], self.lines[j]['bounds'][1]-offset[1],
                     self.lines[j]['bounds'][2]-offset[0], self.lines[j]['bounds'][3]-offset[1]) for j in others}
        across = {j: r for j, r in rects.items() if r[0] < right+gap and r[2] > left-gap}
        blocked = [(r[1]-gap-height, r[3]+gap) for r in across.values()]
        low, high = min(top, region[0]), max(top, region[1]-height)
        candidates = sorted({top, low, high, *(min(high, max(low, y)) for pair in blocked for y in pair)}, key=lambda y: abs(y-top))
        y = next((y for y in candidates if all(not a < y < b for a, b in blocked)), None)
        if y is None:
            y = top
            for j, r in across.items():
                if r[1]-gap < bottom and r[3]+gap > top:
                    self.lines[j]['hide'] = min(self.lines[j].get('hide', math.inf), start)
        layout.move(0., y-top)

    def assign_accents(self):
        """Pick the few words that glow with an instrument (`glow_words` share of the content and hero words;
        small function words never glow) and the hero words
        that get a translucent shape behind them (`word_shapes` share), in a colour that keeps them readable."""
        from effect_colors import contrast
        enabled = [stem for stem in INSTRUMENT_GLOWS if stem in self.options['glows']]
        for index, line in enumerate(self.lines):
            material = self.effect(index) is not None
            for word in line['layout'].words:
                rng = random.Random(round(word.start*1000)*31+word.index)
                if enabled and word.role != 'function' and rng.random() < self.options['glow_words'] and not (material and word.role == 'hero'):
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
        recipe = c.effect_catalog['exit'].get(c.effect_pairs[index][1]) if c.effect_intensity(c.effect_pairs[index][1]) > 0 else None
        length = STILL_EXIT/c.effect_speed(recipe.id) if recipe else FADE_TIME
        later = [j for j in range(index+1, len(self.lines)) if self.shown(j)][:2]
        due = self.lines[later[1]]['start'] if len(later) > 1 else c.duration
        start = max(line['end']+.3, min(due-length, line['end']+STILL_HOLD))
        return start, length, recipe

    def line_instrument(self, start, end):
        """The instrument with the most onsets while the line is sung (never the voice)."""
        counts = {stem: sum(1 for time, _ in (self.rhythm.get(stem) or []) if start <= time <= end) for stem in INSTRUMENT_GLOWS}
        best = max(counts, key=counts.get, default=None)
        return best if best and counts[best] else None

    def instrument_signals(self, t):
        """Compute each stem's envelope and recent hits once for the whole frame."""
        from rhythm import pulse
        return {stem: pulse(self.rhythm.get(stem), t, decay)
                for stem, (_, decay) in INSTRUMENT_GLOWS.items()}

    def text_pulse(self, index, signals):
        """Instrument colour and strength pulsing through this line's words, if the line was chosen."""
        stem = self.lines[index].get('pulse')
        if not stem:
            return None, 0.
        return hex_rgb(INSTRUMENT_GLOWS[stem][0]), signals[stem].level

    def reading_box(self, index, start, end, margin, full=False):
        """Write the line ahead of the camera, on the side it is heading, so the camera travels onto it and it
        stays wholly on screen while it is sung. Also returns the vertical span (the region) the line may slide
        within and still stay on screen. A `full` (full-screen typography) line takes all the room the camera's
        travel leaves instead of one half of the screen."""
        c = self.c
        a, b = self.path.at(start), self.path.at(end)
        dx, dy = b[0]-a[0], b[1]-a[1]
        lead = 1. if self.still or full else LEAD_WIDTH
        width = min(c.width*lead-(2*margin if self.still else 0), max(c.width*MIN_WIDTH, c.width-2*margin-abs(dx)))
        height = max(c.height*MIN_HEIGHT, c.height-2*margin-abs(dy))
        x = c.width-margin-width if dx >= 0 else margin
        y = c.height-margin-height if dy >= 0 else margin
        region = (y, y+height)
        if height >= c.height*.5 and not full:
            height = (height-margin)/2
            y += (index % 2)*(height+margin)
        return (x, y, width, height), region

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
        if 'hide' in lines[index]:
            value *= 1-smooth((t-lines[index]['hide']+HIDE_TIME)/HIDE_TIME)
        return value

    def visible(self, t):
        """Include the entrance lead so the first word can finish arriving at its cue."""
        lines = self.plan()
        newest = max((i for i, line in enumerate(lines)
                      if line['start']-max(PARTICLE_ENTRY, .38/self.speed) <= t and self.shown(i)), default=None)
        if newest is None:
            return []
        shown = [(i, self.opacity(i, t)) for i in range(newest, max(-1, newest-(8 if self.still else 4)), -1) if self.shown(i)]
        return [(i, value) for i, value in shown if value > .005]


    def frame(self, t):
        c = self.c
        self.plan()
        center = self.path.at(t)
        left, top = center[0]-c.width/2, center[1]-c.height/2
        base = (math.floor(left), math.floor(top))
        fraction = (left-base[0], top-base[1])
        index = max(0, sum(1 for line in c.data if line['words'][0]['start'] <= t)-1)
        signals = self.instrument_signals(t)
        screen = c.background(index, t, veil=False).convert('RGBA')
        c.illustration(screen, index, t)
        chorus_hit = self.c.chorus_fx.active(t) is not None
        shaking = chorus_hit or self.options.get('shake_all', False)
        if shaking and (self.options['background_shake'] > 0 or self.options['beat_dim'] > 0):
            # The same four-on-the-floor kicks that the words react to (the drum track holds one pulse per
            # beat): in the chorus sections, or all through the song with "Shake all song".
            from drum_typography import shake_background
            screen = shake_background(screen, signals['drums'].hit, self.options['background_shake'],
                                      self.options['beat_dim'])
        # The painting is fixed to the screen; only the camera-borne layer (words, traces, backdrops) takes the
        # camera's sub-pixel offset. Shifting the painting too made it creep a fraction and snap back a whole pixel
        # on slow pans, a slight, dizzying shake.
        canvas = Image.new('RGBA', (c.width+2, c.height+2))
        visible = self.visible(t)
        if visible:
            newest = visible[0][0]
            handover = smooth((t-self.lines[newest]['start'])/BACKDROP_FADE)
            if newest and handover < 1 and self.shown(newest-1):
                self.paint_backdrop(canvas, newest-1, t, fraction, 1-handover)
            self.paint_backdrop(canvas, newest, t, fraction)
        if self.options['traces'] or self.options['geometry'] > 0:
            self.paint_traces(canvas, t, base, visible)
        for index, opacity in visible:
            if self.still and t >= self.lines[index]['exit'][0]:
                self.paint_exit(canvas, index, t, base)
                continue
            if self.still:  # on the panning canvas the wisp traces the frames instead (see trace_shape)
                self.paint_frame(canvas, index, t, opacity, base)
            self.paint_line(canvas, index, t, opacity, base, impact=chorus_hit and index == newest, signals=signals)
        shifted = canvas.transform((c.width, c.height), Image.Transform.AFFINE, (1, 0, fraction[0], 0, 1, fraction[1]),
                                   resample=Image.Resampling.BILINEAR)
        screen.alpha_composite(shifted)
        return screen.convert('RGB')

    def shift(self, index, base):
        offset = self.lines[index]['offset']
        return offset[0]-base[0], offset[1]-base[1]

    def paint_line(self, layer, index, t, opacity, base, impact=False, signals=None):
        entrance = self.effect(index)
        signals = signals if signals is not None else self.instrument_signals(t)
        pulse_color, pulse = self.text_pulse(index, signals)
        shift = self.shift(index, base)
        layout = self.lines[index]['layout']
        hit, target = None, None
        if impact and self.options['drum_reactivity'] > 0:
            hit = signals['drums'].hit
            if hit:
                def settled_at_hit(w):
                    recipe = w.effect or entrance
                    particle = w.effect is not None or (entrance is not None and w.role == 'hero')
                    if particle and (getattr(recipe, 'trajectory', '') == 'grow' or
                                     getattr(recipe, 'hold', 'solid') == 'particles'):
                        return False
                    entry = min(1., PARTICLE_ENTRY/self.c.effect_speed(recipe.id)) if particle else .28/self.speed
                    return w.start+(0 if particle else entry) <= t-hit[1]
                ready = [w for w in layout.words if w.role != 'function' and
                         settled_at_hit(w) and t-w.start < 5.]
                if ready:
                    # One word takes each impact. The newest hero carries heavy hits;
                    # otherwise the newest landed content word answers the drum.
                    heroes = [w for w in ready if w.role == 'hero']
                    target = max(heroes if hit[2] >= .68 and heroes else ready, key=lambda w: w.start)
        for word in layout.words:
            recipe = word.effect or entrance
            particle = word.effect is not None or (entrance is not None and word.role == 'hero')
            text_motion = self.c.word_animations[index][word.index]
            designed_motion = text_motion in ('mask-rise', 'cartoon-pop')
            if designed_motion:
                particle = False
            entry = min(1., PARTICLE_ENTRY/self.c.effect_speed(recipe.id)) if particle else ((.38 if designed_motion else .1 if word.fast else .2 if word.role == 'function' else .28)/self.speed)
            if t < word.start-(entry if particle or designed_motion else 0):
                continue
            word_hit = hit if word is target else None
            if word.shape and self.still:
                self.paint_word_shape(layer, word, shift, t, opacity)
            glow_stem = 'drums' if word_hit and 'drums' in self.options['glows'] else word.glow
            if glow_stem:
                glow_strength = self.options['glow_strength']
                if word_hit and glow_stem == 'drums':
                    glow_strength = max(glow_strength, self.options['drum_reactivity']*.7)
                self.paint_word_glow(layer, word, shift, t, opacity, glow_stem,
                                     signals[glow_stem].level, glow_strength)
            progress = (t-word.start+(entry if particle or designed_motion else 0))/entry
            settled = overshoot(progress)
            drift = math.sin((t-word.start)*1.6+word.index*.9)*word.size*.015
            tint = (pulse_color, pulse*.7) if pulse > .02 else None
            if word_hit and 'drums' in self.options['glows']:
                tint = (hex_rgb(INSTRUMENT_GLOWS['drums'][0]), signals['drums'].level*.3)
            if particle:
                if word_hit and progress >= 1.:
                    self.paint_word(layer, word, 1., shift, drift, opacity, active=word.start <= t < word.end,
                                    tint=tint, hit=word_hit)
                    continue
                self.paint_particle_word(layer, word, shift, drift, max(0., 1-progress), recipe, opacity)
                continue
            # Words grow into place rather than shrinking onto it, and never wider than the gap beside them.
            scale, dy, alpha = 1., drift, smooth(progress*1.6)
            if text_motion == 'mask-rise':
                alpha = 1.
            elif text_motion == 'cartoon-pop':
                from kinetic_effects import cartoon_scale
                scale, alpha = cartoon_scale(progress), 1.
                dy -= (1-smooth(progress))*word.size*.16
            elif word.role == 'function':
                dy += (1-smooth(progress))*word.size*.25
            elif word.role == 'content':
                scale = .82+.18*settled
            else:
                scale = .6+.4*settled
            if word.held and t < word.end:
                scale *= 1+.08*smooth((t-word.start)/max(.2, word.end-word.start))
            scale = min(scale, 1+layout.gap/max(1., word.width))
            self.paint_word(layer, word, scale, shift, dy, alpha*opacity, glitch=self.options['glitch'] and not designed_motion and word.role == 'hero' and progress < .8,
                            active=word.start <= t < word.end, tint=tint,
                            hit=word_hit, mask_progress=progress if text_motion == 'mask-rise' else None)

    def word_box(self, word, shift):
        left = word.x+shift[0]
        return left, word.y+shift[1]+word.ink[0], left+word.width, word.y+shift[1]+word.ink[1]

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

    def paint_word_glow(self, layer, word, shift, t, opacity, stem, pulse_level, strength):
        """A soft halo in the instrument's colour behind the word, pulsing on that instrument's hits."""
        color, _ = INSTRUMENT_GLOWS[stem]
        level = pulse_level*strength*opacity*smooth((t-word.start)/.4)
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
        return c.effect_catalog['entrance'].get(c.effect_pairs[index][0]) if c.effect_intensity(c.effect_pairs[index][0]) > 0 else None

    def paint_word(self, layer, word, scale, shift, dy, alpha, glitch=False, active=False, tint=None, hit=None, mask_progress=None):
        if alpha <= .01:
            return
        size = max(8, round(word.size*scale))
        color = word.color if active or word.role != 'content' else tuple(round(v*.92) for v in word.color)
        if tint:
            color = tuple(round(a+(b-a)*tint[1]) for a, b in zip(color, tint[0]))
        sprite, pad, spans = word_sprite(word, size, color, 1., glitch)
        if mask_progress is not None:
            from kinetic_effects import mask_rise
            sprite = mask_rise(sprite, mask_progress)
        font = role_font(word.role, size)
        x = word.x+shift[0]+word.width/2-font.getlength(word.text)/2-pad
        y = word.y+shift[1]+role_font(word.role, word.size).getmetrics()[0]-font.getmetrics()[0]+dy-pad
        if hit:
            from drum_typography import paint_impact
            paint_impact(layer, sprite, x, y, spans, hit, self.options['drum_reactivity'], alpha)
        else:
            if alpha < .999:
                sprite.putalpha(sprite.getchannel('A').point(lambda a: round(a*alpha)))
            paste_clipped(layer, sprite, round(x), round(y))

    def paint_particle_word(self, layer, word, shift, dy, amount, recipe, opacity):
        from particle_motion import paint_transition
        sprite, pad, spans = word_sprite(word, word.size, word.color)
        x, y = round(word.x+shift[0]-pad), round(word.y+shift[1]+dy-pad)
        if opacity >= .99:
            paint_transition(layer, sprite, x, y, 'entrance', amount, recipe, word.index, self.c.effect_intensity(recipe), .6,
                             self.c.effect_cache, glyph_spans=spans)
            return
        overlay = Image.new('RGBA', layer.size)
        paint_transition(overlay, sprite, x, y, 'entrance', amount, recipe, word.index, self.c.effect_intensity(recipe), .6,
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
        from particle_motion import paint_transition
        paint_transition(layer, line.crop(bounds), bounds[0], bounds[1], 'exit', amount, recipe, index, self.c.effect_intensity(recipe), .6,
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
        """Choose bass-led shape loops for the traveling white thread head."""
        if self.shapes is None:
            count = round(self.options['geometry']*self.c.duration/(SHAPE_LIFE*1.7))
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
                mode = ('glide', 'word', 'glide', 'loop', 'word', 'glide')[len(self.shapes) % 6]
                self.shapes.append(dict(start=time, kind=rng.choice(SHAPES), size=rng.uniform(.12, .24), mode=mode))
        return self.shapes


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
        for thread in self.thread_path():
            head = thread_distance(thread['keys'], t)
            if head is None:
                continue
            tail = dying_tail(thread['keys'], t)
            samples = sample_thread(thread['pieces'], tail, head, STRAND_STEP)
            if len(samples) >= 2 and tail < thread['pieces'][-1]['end']:
                self.paint_bands(draw, fill_layer, samples, samples[0][2], samples[-1][2], t, base)
                alive = 1-smooth((t-thread['keys'][0][-1])/HEAD_FADE)
                if alive > .01 and not any(start <= t < end for start, end in self.veils):
                    from wisp_forms import forms_at, heading_at, paint_head
                    x, y = samples[-1][0]-base[0], samples[-1][1]-base[1]
                    angle = heading_at(thread['pieces'], head, max(12., self.c.height*.025))
                    size = max(9., self.c.height*.026)
                    for form, weight in forms_at(thread.get('forms', ()), t):
                        paint_head(draw, x, y, angle, form, 230*alive*weight, size, t)

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
            # Drawn opaque as one small quad per step (a closed loop stays a ring, never a filled disc), then
            # made translucent as a whole so the quads' shared edges do not show.
            band_layer = Image.new('RGBA', fill_layer.size)
            band_draw = ImageDraw.Draw(band_layer)
            runs = list(zip(group_by_color(upper), group_by_color(lower)))
            for (color, top), (_, bottom) in runs:
                for a, b, c, d in zip(top, top[1:], bottom[1:], bottom):
                    band_draw.polygon((a, b, c, d), fill=(*color, 255))
            box = band_layer.getbbox()
            if not box:
                continue
            band_layer.putalpha(band_layer.getchannel('A').point(lambda a: a*BAND_ALPHA//255))
            for (color, top), _ in runs:
                band_draw.line(top, fill=(*color, 150), width=2, joint='curve')
            bands.alpha_composite(band_layer)
        box = bands.getbbox()
        if box:
            box = (max(0, box[0]-4), max(0, box[1]-4), min(bands.width, box[2]+4), min(bands.height, box[3]+4))
            fill_layer.alpha_composite(bands.crop(box).filter(ImageFilter.GaussianBlur(1.1)), box[:2])

    def wisp_runs(self):
        """(start, end) time of each thread run's wisp."""
        if not self.options['traces'] and self.options['geometry'] <= 0:
            return []
        return [(thread['keys'][0][0], thread['keys'][0][-1]) if thread['keys'][0] else (math.inf, -math.inf)
                for thread in self.thread_path()]

    def wisp_screen(self, number, when, t):
        """Screen pixel of thread run `number`'s wisp where it was at time `when`, with the camera at time t."""
        thread = self.thread_path()[number]
        head = thread_distance(thread['keys'], when)
        if head is None:
            return None
        samples = sample_thread(thread['pieces'], max(0., head-1.), head, STRAND_STEP)
        if not samples:
            return None
        center = self.path.at(t)
        return samples[-1][0]-(center[0]-self.c.width/2), samples[-1][1]-(center[1]-self.c.height/2)

    def thread_path(self):
        """The whole thread on the canvas: a smooth path through each hero word, with the distance its head
        has reached as each is sung. It turns continuously and keeps one cruising speed (see flow_path)."""
        if getattr(self, '_thread', None) is not None:
            return self._thread
        stops = []
        for index, line in enumerate(self.plan()):
            if not self.shown(index):
                continue
            for word in line['layout'].words:
                if word.role == 'hero':
                    left, top, right, bottom = self.word_box(word, line['offset'])
                    stops.append(dict(word=word, line=index, anchor=((left+right)/2, (top+bottom)/2)))
        stops.sort(key=lambda stop: stop['word'].start)
        times = []
        for stop in stops:
            times.append(max(stop['word'].start, times[-1]+.05) if times else stop['word'].start)
        from flow_path import build_flows
        self._thread = build_flows(times, [stop['anchor'] for stop in stops], [stop['word'].color for stop in stops],
                                   amplitude=self.c.height*.3, lines=[stop['line'] for stop in stops])
        # The white head traces each floating shape as part of its own route. On the panning canvas no shape
        # is drawn: the wisp, tail and all, runs round each hero word's shape and each line frame (see trace_shape).
        traced = [] if self.still else self.traced_shapes(stops)
        if self.options['geometry'] > 0:
            painted_words = {id(target['stop']['word']) for target in traced}
            for thread in self._thread:
                for shape in self.shape_events():
                    if shape['mode'] == 'glide':
                        continue
                    moment = shape['start']
                    original_keys = thread['keys']
                    if not original_keys[0] or not original_keys[0][0]+.5 < moment < original_keys[0][-1]-1.2:
                        continue
                    original_distance = thread_distance(original_keys, moment)
                    if original_distance is None or original_distance <= 0 or original_distance >= thread['pieces'][-1]['end']:
                        continue
                    point = sample_thread(thread['pieces'], original_distance-.01, original_distance, 1.)[-1]
                    x, y = point[:2]
                    permanent = shape['mode'] == 'word'
                    if permanent:
                        candidates = [stop for stop in stops if original_keys[0][0] <= stop['word'].start <= original_keys[0][-1]
                                      and stop['word'].role == 'hero' and id(stop['word']) not in painted_words]
                        if not candidates:
                            continue
                        selected = min(candidates, key=lambda stop: abs(stop['word'].start-moment))
                        if abs(selected['word'].start-moment) > 2.5:
                            continue
                        word = selected['word']
                        painted_words.add(id(word))
                        if not self.still:
                            traced.append(self.traced_shape(selected, random.Random(round(moment*1000)).choice(LINE_FRAMES)))
                            continue
                        left, top, right, bottom = self.word_box(word, self.lines[selected['line']]['offset'])
                        pad = max(8., word.size*.22)
                        route = swash_route(x, y, (left+right)/2, (top+bottom)/2, (right-left)/2+pad*1.4, (bottom-top)/2+pad)
                        color = word.color
                    else:
                        radius = max(20., self.c.height*shape['size']*.42)
                        route = curl_route(x, y, radius, 1. if round(moment*10) % 2 else -1.)
                        color = point[3]
                    # The ribbon itself draws the flourish: no filled shape is revealed behind it.
                    length = insert_thread_loop(thread['pieces'], original_distance, route, color, shape=False)
                    duration = loop_duration(original_keys, length, (2.2, TRACE_TIME[1]) if permanent else CURL_TIME)
                    clock, distances, _ = original_keys
                    thread['keys'] = monotone_keys(clock, [distance+length*smooth((time-moment)/duration)
                                                           for time, distance in zip(clock, distances)])
        for number, target in enumerate(sorted(traced, key=lambda target: target['stop']['word'].start)):
            self.trace_shape(target, unique_color(number, target['stop']['word'].color))
        for thread in self._thread:  # every run brakes to a stop rather than halting dead
            thread['keys'] = settle_keys(thread['keys'])
            from wisp_forms import form_for
            begin, end = thread['keys'][0][0], thread['keys'][0][-1]
            thread['forms'] = [(stop['word'].start,
                                form_for(stop['word'].text, self.c.data[stop['line']]['text']))
                               for stop in stops if begin <= stop['word'].start <= end]
        return self._thread

    def traced_shapes(self, stops):
        """The shapes the wisp traces: a frame round a whole line (one per framed line, at its first hero word)
        and a shape round each hero word that was given one."""
        targets, framed = [], set()
        for stop in stops:
            line = self.lines[stop['line']]
            if line['frame'] and stop['line'] not in framed:
                framed.add(stop['line'])
                targets.append(self.traced_shape(stop, line['frame'], whole_line=True))
            elif stop['word'].shape:
                targets.append(self.traced_shape(stop, stop['word'].shape[0]))
        return targets

    def traced_shape(self, stop, kind, whole_line=False):
        line = self.lines[stop['line']]
        if whole_line:
            left, top, right, bottom = line['bounds']
            pad = (right-left)*.04+self.c.height*.02
        else:
            word = stop['word']
            left, top, right, bottom = self.word_box(word, line['offset'])
            pad = max(8., word.size*.16)
        return dict(stop=stop, line=stop['line'], outline=shape_outline(kind, left, top, right, bottom, pad))

    def trace_shape(self, target, color):
        """Splice the shape's outline into the thread where it first enters the shape on its way to the hero
        word, and let the head (with its ribbon) ease once round it. The ribbon takes the shape's own colour
        along the outline; nothing else is drawn."""
        word, anchor = target['stop']['word'], target['stop']['anchor']
        thread = next((thread for thread in self._thread if thread['keys'][0]
                       and thread['keys'][0][0] <= word.start <= thread['keys'][0][-1]), None)
        if thread is None:
            return
        pieces, keys = thread['pieces'], thread['keys']
        ring = target['outline'][:-1]
        perimeter = sum(math.dist(a, b) for a, b in zip(ring, ring[1:]+ring[:1]))
        guess = thread_distance(keys, word.start) or 0.
        loops = thread.setdefault('shape_loops', [])
        floor = loops[-1]['end_distance'] if loops else 0.
        window = sample_thread(pieces, max(floor, guess-perimeter*2), min(pieces[-1]['end'], guess+perimeter), 4.)
        if not window:
            return
        nearest = min(range(len(window)), key=lambda k: math.dist(window[k][:2], anchor))
        entry = nearest
        while entry > 0 and inside(ring, window[entry][:2]):
            entry -= 1
        point, distance = window[entry][:2], window[entry][2]
        first = min(range(len(ring)), key=lambda k: math.dist(ring[k], point))
        ring = ring[first:]+ring[:first]
        loop = [point]+ring+[ring[0], point]
        length = insert_thread_loop(pieces, distance, loop, color, shape=False)
        if not length:
            return
        clock, distances, _ = keys
        begin = clock[min(len(clock)-1, bisect.bisect_left(distances, distance))]
        duration = loop_duration(keys, length, TRACE_TIME)
        times = sorted(set(clock) | {begin+duration*k/12 for k in range(13)})
        thread['keys'] = monotone_keys(times, [(thread_distance(keys, time) or 0.)+length*smooth((time-begin)/duration)
                                               for time in times])
        loops.append(dict(start_distance=distance, end_distance=distance+length))


    def paint_backdrop(self, layer, index, t, fraction, strength=1.):
        """One of several treatments behind a line; marquees fade in place."""
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
        if marquee:
            alpha *= self.opacity(index, t)
            if self.still:
                exit_start, exit_length, _ = line['exit']
                alpha *= 1-smooth((t-exit_start)/exit_length)
        if alpha <= .01:
            return
        art = Image.new('RGBA', layer.size)
        draw = ImageDraw.Draw(art)
        elapsed = (t-start)*self.speed
        if marquee:
            size = round(c.height*.28)
            font = role_font('hero', size)
            phrase = '  •  '.join(w.text.upper() for w in words)
            length = layer.height if kind == 'vertical' else layer.width
            while size > 12 and font.getlength(phrase) > length*.94:
                size = max(12, round(size*.9))
                font = role_font('hero', size)
            style = dict(fill=(*color, round(60*alpha))) if kind == 'filled' else \
                dict(fill=(0, 0, 0, 0), stroke_width=max(2, round(size*.02)), stroke_fill=(*color, round(150*alpha)))
            strip = Image.new('RGBA', (round(length), round(size*1.5)))
            ImageDraw.Draw(strip).text(((length-font.getlength(phrase))/2, 0), phrase, font=font, **style)
            if kind == 'vertical':
                strip = strip.rotate(90 if line['direction'] > 0 else -90, expand=True)
                edge = round(c.width*.02) if index % 2 else layer.width-strip.width-round(c.width*.02)
                paste_clipped(art, strip, edge, 0)
            else:
                paste_clipped(art, strip, 0, round(c.height*.62))
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
        # Decorative lettering leaves room for the words being sung: it parts round each word's own letter
        # shapes (their soft halo), never in boxes.
        camera = self.path.at(t)
        base = (math.floor(camera[0]-c.width/2), math.floor(camera[1]-c.height/2))
        knockout = Image.new('L', art.size)
        for active, _ in self.visible(t):
            shift = self.shift(active, base)
            for word in self.lines[active]['layout'].words:
                if word.start > t:
                    continue
                halo, pad = self.word_halo(word, (255, 255, 255))
                paste_lighter(knockout, halo.getchannel('A'), round(word.x+shift[0]-pad), round(word.y+shift[1]-pad))
        if knockout.getbbox():
            art.putalpha(ImageChops.multiply(art.getchannel('A'), ImageChops.invert(knockout)))
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


def dying_tail(keys, t, reach=math.inf):
    """Where the ribbon's tail is: THREAD_LIFE behind the head (and no more than `reach` behind it). Once the
    run ends and its wisp dies, the tail slowly fades back from its end to where the head stopped."""
    head = thread_distance(keys, t) or 0.
    tail = max(thread_distance(keys, t-THREAD_LIFE) or 0., head-reach)
    end = keys[0][-1] if keys[0] else t
    if t <= end:
        return tail
    last = thread_distance(keys, end) or 0.
    stopped = max(thread_distance(keys, end-THREAD_LIFE) or 0., last-reach)
    return max(tail, stopped+(last-stopped)*smooth((t-end)/DIE_TIME))


def loop_duration(keys, length, limits):
    """How long the head takes over an extra loop of `length`: about as long as it would take at its cruising
    pace, within limits, so it eases round instead of whipping through (and its tail does the same later)."""
    times, distances, _ = keys
    cruise = (distances[-1]-distances[0])/max(1e-6, times[-1]-times[0]) if len(times) > 1 else 0.
    return min(limits[1], max(limits[0], length/cruise if cruise > 1e-6 else limits[0]))


def inside(polygon, point):
    """Even-odd test: is the point inside the closed polygon?"""
    x, y = point
    result = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:]+polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0+(y-y0)*(x1-x0)/(y1-y0):
            result = not result
    return result


def unique_color(number, ink):
    """A distinct hue for the ribbon round each traced shape (golden-ratio steps round the colour wheel),
    light or dark enough to stand apart from the word it circles."""
    import colorsys
    from effect_colors import contrast
    hue = (.07+number*.618034) % 1
    options = [tuple(round(v*255) for v in colorsys.hls_to_rgb(hue, light, .78)) for light in (.62, .72, .38, .26)]
    return next((c for c in options if contrast(c, ink) >= MIN_SHAPE_CONTRAST), max(options, key=lambda c: contrast(c, ink)))


def curl_route(x, y, radius, lean=1., steps=40):
    """A graceful loop-de-loop for the thread: it rises from (x, y), swings once round a slightly tilted
    teardrop and carries on from where it started, so the ribbon itself draws the flourish."""
    points = []
    for k in range(steps+1):
        a = k/steps
        theta = math.pi/2-lean*a*math.tau
        r = radius*(1+.28*math.sin(math.pi*a))
        drift = radius*.35*math.sin(math.pi*a)*lean
        points.append((x+drift+r*math.cos(theta), y-radius+r*math.sin(theta)))
    points[-1] = (x, y)
    return points


def swash_route(x, y, cx, cy, rx, ry, tilt=-.12, steps=56):
    """A calligraphic swash round a word: an open, tilted oval that swells and thins like a pen stroke,
    starting and ending where the thread meets it."""
    start = math.atan2((y-cy)/max(ry, 1e-6), (x-cx)/max(rx, 1e-6))
    points = [(x, y)]
    for k in range(steps+1):
        a = k/steps
        theta = start+a*math.tau*1.08
        swell = 1+.12*math.sin(a*math.pi*2+.6)
        px, py = rx*swell*math.cos(theta), ry*swell*math.sin(theta)
        points.append((cx+px*math.cos(tilt)-py*math.sin(tilt), cy+px*math.sin(tilt)+py*math.cos(tilt)))
    points.append((x, y))
    return points


def insert_thread_loop(pieces, distance, loop, color, shape=True):
    """Splice a closed route into the flowing path so its head and tail trace it. With shape=False the
    ribbon itself draws the route (a curl or swash) instead of revealing a filled shape."""
    result = []
    inserted = False
    for piece in pieces:
        points = piece['points']
        if not inserted and distance <= piece['start']:
            result.append(dict(points=loop, color=color, shape=shape))
            inserted = True
        if not inserted and piece['start'] < distance < piece['end']:
            remaining = distance-piece['start']
            for index, (a, b) in enumerate(zip(points, points[1:])):
                span = math.dist(a, b)
                if remaining <= span:
                    u = remaining/max(span, 1e-9)
                    knot = tuple(a[k]+(b[k]-a[k])*u for k in range(len(a)))
                    result.extend((dict(points=points[:index+1]+[knot], color=piece['color']),
                                   dict(points=loop, color=color, shape=shape),
                                   dict(points=[knot]+points[index+1:], color=piece['color'])))
                    inserted = True
                    break
                remaining -= span
            if inserted:
                continue
        result.append(dict(points=points, color=piece['color']))
    if not inserted:
        return 0.
    travelled = 0.
    for piece in result:
        piece['start'] = travelled
        travelled += sum(math.dist(a, b) for a, b in zip(piece['points'], piece['points'][1:]))
        piece['end'] = travelled
    pieces[:] = result
    return sum(math.dist(a, b) for a, b in zip(loop, loop[1:]))


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
                    position = tuple(a[k]+(b[k]-a[k])*u for k in range(len(a)))
                    samples.append((*position, distance, piece['color']))
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


def settle_keys(keys, seconds=1.):
    """The same timing with its last `seconds` replaced by a gentle braking stop: the head's speed eases from
    what it was to nothing (its acceleration changing smoothly too), instead of halting dead at the end."""
    times, distances, _ = keys
    if len(times) < 2:
        return keys
    end = times[-1]
    start = max(times[0], end-seconds)
    window = end-start
    if window <= 1e-3:
        return keys
    d0 = thread_distance(keys, start)
    v0 = (d0-thread_distance(keys, start-1e-3))/1e-3 if start-1e-3 >= times[0] else (distances[1]-distances[0])/max(1e-6, times[1]-times[0])
    kept = [(t, d) for t, d in zip(times, distances) if t < start-1e-6]
    braking = [(start+window*k/12, d0+v0*window*(s-s**3+s**4/2)) for k in range(13) for s in [k/12]]
    clock, travelled = zip(*(kept+braking))
    return monotone_keys(list(clock), list(travelled))


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


def paste_lighter(mask, sprite, x, y):
    """Merge a greyscale sprite into a mask at (x, y), keeping the brighter value, clipped to the mask."""
    box = (max(0, -x), max(0, -y), min(sprite.width, mask.width-x), min(sprite.height, mask.height-y))
    if box[2] > box[0] and box[3] > box[1]:
        at = (max(0, x), max(0, y), max(0, x)+box[2]-box[0], max(0, y)+box[3]-box[1])
        mask.paste(ImageChops.lighter(mask.crop(at), sprite.crop(box)), at[:2])


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
