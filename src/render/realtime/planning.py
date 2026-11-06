"""Plans each line once per song: where it sits on the canvas, its backdrop and accents, and
when it shows."""
import bisect
import math
import random
from core.easing import smoothstep as smooth
from core.color import hex_rgb
from render.realtime.common import BACKDROP_COLORS, BASE_SCALE, DIM_TIME, FADE_TIME, HIDE_TIME, INSTRUMENT_GLOWS, LEAD_WIDTH, LINE_FRAMES, LINE_GAP, LINE_LINGER, MARGIN, MIN_GLOW_CONTRAST, MIN_HEIGHT, MIN_SHAPE_CONTRAST, MIN_WIDTH, OLDER_LINES, PARTICLE_ENTRY, SHAPE_COLORS, STILL_EXIT, STILL_HOLD
from render.realtime.layout import LineLayout



class LinePlanning:
    def plan(self):
        """Lay out every line once: where on the canvas it is written and which backdrop it gets."""
        if self.lines is not None:
            return self.lines
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
        if c.artwork_mode == 'matte' and paths and not self.still:
            # Greenscreen scenery is one canvas the camera pans across, with a matching canvas of mattes so
            # lyrics stay inside the open sky; other artwork comes from the compositor's background.
            import artwork.greenscreen as greenscreen
            self.world = WorldCanvas(paths[:len(spans)], spans, c.width, c.height, self.path, load=lambda p: greenscreen.load(p)[0])
            self.mattes = WorldCanvas(paths[:len(spans)], spans, c.width, c.height, self.path, load=lambda p: greenscreen.load(p)[1], mode='L')
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
        from effects.colors import contrast
        enabled = [stem for stem in INSTRUMENT_GLOWS if stem in self.options['glows']]
        for index, line in enumerate(self.lines):
            material = self.effect(index) is not None
            scene = self.c.plan['scenes'][index]
            glows = {stem: scene.get('art_glows', {}).get(stem) or INSTRUMENT_GLOWS[stem][0] for stem in INSTRUMENT_GLOWS}
            line['glows'] = glows   # matched to the painting when "match text colours to the artwork" is on
            for word in line['layout'].words:
                word.glows = glows
                rng = random.Random(round(word.start*1000)*31+word.index)
                if enabled and word.role != 'function' and rng.random() < self.options['glow_words'] and not (material and word.role == 'hero'):
                    hits = {stem: sum(1 for time, _ in (self.rhythm.get(stem) or []) if word.start-.5 <= time <= word.end+3)
                            for stem in enabled if contrast(hex_rgb(glows[stem]), word.color) >= MIN_GLOW_CONTRAST}
                    best = max(hits, key=hits.get, default=None)
                    word.glow = best if best and hits[best] else ''
                if word.role == 'hero' and rng.random() < self.options['word_shapes']:
                    colors = [hex_rgb(c) for c in scene.get('art_shapes') or SHAPE_COLORS]
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

    def reading_box(self, index, start, end, margin, full=False):
        """Write the line ahead of the camera, on the side it is heading, so the camera travels onto it and it
        stays wholly on screen while it is sung. Also returns the vertical span (the region) the line may slide
        within and still stay on screen. A `full` (full-screen typography) line takes all the room the camera's
        travel leaves instead of one half of the screen."""
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
            return (x, y, width, height), (y, y+height)
        lead = 1. if self.still or full else LEAD_WIDTH
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
            region = (y, y+height)
            if height >= c.height*.3 and not full:
                height = (height-margin/2)/2
                y += (index % 2)*(height+margin/2)
            return (x, y, width, height), region
        region = (y, y+height)
        if height >= c.height*.5 and not full:
            height = (height-margin)/2
            y += (index % 2)*(height+margin)
        return (x, y, width, height), region

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
