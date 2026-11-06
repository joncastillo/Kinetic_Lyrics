"""Plans the stage once per song: where blocks stand, their words, layout, entrances, accents
and motion, the bass shapes and the ribbon route."""
from __future__ import annotations
import bisect
import colorsys
import math
import random
import numpy as np
from PIL import Image
import render.glyph_art as glyph_art
from render.lyric_blocks import TARGET_RATIO, group_lines, layout_block
from render.realtime import BACKDROP_COLORS, CURL_TIME, FUNCTION_WORDS, TRACE_TIME, SHAPE_LIFE, SHAPES, assign_roles, bare, hex_rgb, smooth
from render.thread_path import curl_route, insert_thread_loop, loop_duration, monotone_keys, sample_thread, swash_route, thread_distance
from render.stage_3d.common import ACCENT, BLOCK_WIDTH, COLUMN_GAP, COLUMN_LIMIT, CONTRAST_LEADING, CRUISE, DEPTHS, EFFECT_ROOM, ENTRANCES, FILL_HEIGHT, FILL_WIDTH, FOV, GROW_ROOM, MOTES, MOTIONS, MOVE_LEAD, ORNAMENTS, REFERENCE, RIBBON_DEPTH, RIBBON_SWING, ROLL_RANGE, SHAPE_DEPTHS, SHAPE_REACH, VIEW_TILT, ZOOM_RANGE, letter_fills, normalized, rounded_run, stage_font
from render.stage_3d.gl import rotation, translation


class StagePlanning:
    def plan(self):
        if self.blocks is not None:
            return self.blocks
        c = self.c
        self.blocks = []
        center = np.zeros(3)
        previous_extent = 0.
        groups = group_lines(c.data, self.art_breaks() | self.breaks)
        groups = [g for g in ([i for i in group if self.only is None or i in self.only] for group in groups) if g]
        direction = self.directions()
        for number, members in enumerate(groups):
            rng = random.Random(self.seed*7919+number*104729)
            directed = direction.get(members[0]) if direction is not None else None
            scene = c.plan['scenes'][members[0]]
            palette = [hex_rgb(v) for v in c.scene_palette(scene)]
            words = self.block_words(members, palette)
            accent = self.artwork_accent(words[0]['start'], palette[3])
            style = self.contrast_style(words, rng, accent) if self.layouts.get(members[0]) == 'contrast' else None
            arrange = (lambda pictured=None: self.arrange_contrast(words, members, style, pictured)) if style else \
                (lambda pictured=None: self.arrange(words, members, pictured))
            height = arrange()
            effect = self.block_effect(members, number, directed)
            self.crown(words, effect)
            self.choose_accent(words, palette[2], accent, style)
            self.follow_instructions(words)
            ornament = (directed or {}).get('ornament') if direction is not None else None
            no_pictures = self.c.plan.get('pictures') == 'off'  # the setting turns off keyword pictures too
            self.choose_motion(words, rng, None if no_pictures else ornament if direction is not None else False)
            pictured = next((w for w in words if w['ornament'] and w['letter'] is None), None)
            if pictured is not None:
                height = arrange(pictured)
                self.crown(words, effect)
                self.choose_accent(words, palette[2], accent, style)
                self.follow_instructions(words)
            room = (GROW_ROOM if effect.trajectory == 'grow' else EFFECT_ROOM)*REFERENCE*words[0]['scale'] if effect else 0.
            extent = max(BLOCK_WIDTH, height+room)
            if number:
                heading = self.heading(number, rng)
                center = center+heading*(1.1*(previous_extent+extent)/2+.7)
                center[2] = rng.uniform(*DEPTHS)
            previous_extent = extent
            tilt = 1.6 if rng.random() < .2 else 1.
            yaw, pitch, roll = rng.uniform(-24, 24)*tilt, rng.uniform(-10, 10)*tilt, rng.uniform(-4, 4)
            placement = translation(*center)@rotation(yaw, pitch, roll)
            normal = placement[:3, :3]@np.array([0., 0., 1.])
            view = normalized(normal*VIEW_TILT+np.array([0., 0., 1.])*(1-VIEW_TILT))
            half = math.tan(math.radians(FOV)/2)
            angle = math.radians(abs(style['roll'])) if style else 0.  # the tilted block's bounding box must fit
            wide = BLOCK_WIDTH*math.cos(angle)+(height+room)*math.sin(angle)
            tall = BLOCK_WIDTH*math.sin(angle)+(height+room)*math.cos(angle)
            distance = max(tall/2/half/FILL_HEIGHT, wide/2/(half*self.aspect)/FILL_WIDTH)*(style['zoom'] if style else 1.)
            focus = (placement@np.array([0., room/2, 0., 1.]))[:3]
            margin = .9*min(distance*half*self.aspect-wide/2, distance*half-tall/2)
            self.blocks.append(dict(lines=members, words=words, height=height, center=center, focus=focus, placement=placement,
                                    view=view, distance=distance, side=normalized(np.cross([0., 1., 0.], view)),
                                    start=min(w['start'] for w in words), end=max(w['end'] for w in words),
                                    palette=palette, entrance=rng.choice(ENTRANCES), motes=self.motes(rng, height),
                                    drift=rng.choice((-1., 1.)), accent=accent, layout='contrast' if style else 'justified', margin=max(0., margin),
                                    roll=style['roll'] if style else 0., zoom=style['zoom'] if style else 1.))
            if directed and directed.get('entrance') in ENTRANCES:
                self.blocks[-1]['entrance'] = directed['entrance']
        for number, block in enumerate(self.blocks):
            required = block['distance']*1.06
            if number == 0:
                block['camera_distance'] = required*1.08
            else:
                previous = self.blocks[number-1]['camera_distance']
                phase = number % 5
                scale = (1.16, 1.12, 1., .84, .9)[phase-1]
                block['camera_distance'] = max(required, min(required*1.65, previous*scale))
            block['shot_roll'] = (0., 0., 7., -6., 0., 5.)[number % 6]+block['roll']*.25
            block['move'] = block['start']-MOVE_LEAD if number else -math.inf
            following = self.blocks[number+1]['start']-MOVE_LEAD if number+1 < len(self.blocks) else self.c.duration
            block['hold'] = (max(0., block['start']-MOVE_LEAD), max(block['start']+1., following))
            ahead = self.blocks[number+1]['focus'] if number+1 < len(self.blocks) else block['focus']+self.heading(number+1, random.Random(number))
            reach = max(.5, (block['end']-block['start'])/2+MOVE_LEAD)
            block['cruise'] = normalized((ahead-block['focus'])*np.array([1., 1., 0.]))*min(CRUISE, block['margin']/reach)
        self.world = self.plan_world()
        self.shapes = self.plan_shapes()
        self.ribbon = self.plan_ribbon()
        return self.blocks

    def art_breaks(self):
        """Line indices where a new illustration starts, so a block never straddles two pictures."""
        c, breaks = self.c, set()
        cues = [line['words'][0]['start'] for line in c.data]
        lead = getattr(c, 'lead_in', 0.)
        for start in list(getattr(c, 'art_starts', None) or [])[1:]:
            for index, cue in enumerate(cues):
                if abs(cue-start) < 1e-6 or abs(max(0., cue-lead)-start) < 1e-6:
                    breaks.add(index)
                    break
        return breaks

    def artwork_accent(self, time, fallback):
        """Pick a readable backdrop hue while keeping purple out of textured lettering."""
        c = self.c
        if c.artwork_mode not in ('fullscreen', 'verse') or not getattr(c, 'art', None) or not c.art_starts:
            return fallback
        slot = max(0, min(len(c.art)-1, bisect.bisect_right(c.art_starts, time)-1))
        if slot not in self.art_tones:
            swatches = c.art[slot].convert('RGB').resize((96, 54), Image.Resampling.BILINEAR).quantize(colors=12)
            colors = swatches.convert('RGB').getcolors() or []
            choices = []
            for count, color in colors:
                h, s, v = colorsys.rgb_to_hsv(*(component/255 for component in color))
                if s >= .14 and .25 <= v <= .96 and not .69 <= h <= .96:
                    choices.append((count*(.2+s)*(.5+v), h, s, v))
            if choices:
                _, h, s, v = max(choices)
                rgb = colorsys.hsv_to_rgb(h, min(.55, max(.26, s)), max(.78, min(.94, v*1.35)))
                self.art_tones[slot] = tuple(round(component*255) for component in rgb)
            else:
                self.art_tones[slot] = fallback
        return self.art_tones[slot]

    def heading(self, number, rng):
        """Direction from one block to the next: right, rising, falling or diving, never straight back."""
        options = ((1., 0., 0.), (1., -.55, 0.), (1., .5, 0.), (.35, -1., 0.), (.8, .25, 0.), (.55, .8, 0.), (1., -.25, 0.))
        return normalized(options[(number*3+rng.randrange(len(options))) % len(options)])

    def block_words(self, members, palette):
        c, words = self.c, []
        ink, accent = palette[2], palette[3]
        for index in members:
            line = c.data[index]
            features = self.melody[index] if self.melody and index < len(self.melody) else None
            roles = assign_roles(line, features, c.plan['scenes'][index].get('emphasis', -1))
            for k, (word, role) in enumerate(zip(line['words'], roles)):
                text = word['text'].strip()
                upper = role != 'function' or bare(text) not in FUNCTION_WORDS
                words.append(dict(text=text.upper() if upper else text.lower(), bare=bare(text), role=role, font='content' if role == 'function' else role, line=index,
                                  index=k, start=word['start'], end=word['end'],
                                  color=accent if role == 'hero' else ink if role == 'content' else tuple(round(v*.86) for v in ink)))
        return words

    def contrast_style(self, words, rng, accent):
        """The contrast layout's choices for one block: the vertical word (the last word that is not a short
        function word), the textured word (a hero word), how thin and heavy fonts pair, and the camera's tilt."""
        content = [w for w in words if w['role'] != 'function' and len(w['bare']) > 2] or words
        vertical = content[-1]
        heroes = [w for w in words if w['role'] == 'hero' and w is not vertical]
        sweet = (heroes or [w for w in content if w is not vertical] or [None])[0]
        pairing = rng.choice(('roles', 'lines'))
        for word in words:
            line = sorted({w['line'] for w in words}).index(word['line'])
            thin = word['role'] == 'function' if pairing == 'roles' else line % 2 == 0 and word['role'] != 'hero'
            word.update(font='thin' if thin else 'heavy', text=word['text'].upper(), bouncy=True)
        vertical.update(font='heavy', vertical=True)
        if sweet is not None:
            sweet.update(font='sweet', sweet=True, text=sweet['text'].lower(), fills=letter_fills(accent, len(sweet['text']), rng))
        return dict(vertical=vertical, side=rng.choice((-1, 1)), reads=rng.choice(('up', 'down')),
                    roll=rng.choice((-1, 1))*rng.uniform(*ROLL_RANGE), zoom=rng.uniform(*ZOOM_RANGE))

    def arrange_contrast(self, words, members, style, pictured=None):
        """Rows of the other words beside a column holding the vertical word, which runs the block's full height."""
        vertical = style['vertical']
        rest = [w for w in words if w is not vertical]
        font = stage_font(vertical['font'], REFERENCE)
        length, cap = max(1., font.getlength(vertical['text'])), -font.getbbox('H', anchor='ls')[1]
        column = .2*BLOCK_WIDTH
        for _ in range(4):
            width = BLOCK_WIDTH-column-COLUMN_GAP*BLOCK_WIDTH
            left = -BLOCK_WIDTH/2+(column+COLUMN_GAP*BLOCK_WIDTH if style['side'] < 0 else 0.)
            height = self.arrange(rest, members, pictured, width, left, CONTRAST_LEADING)
            wanted = min(COLUMN_LIMIT*BLOCK_WIDTH, cap*height/length)
            if abs(wanted-column) < 1e-3:
                break
            column = wanted
        scale = column/cap
        span = length*scale
        edge = -BLOCK_WIDTH/2 if style['side'] < 0 else BLOCK_WIDTH/2-column
        if style['reads'] == 'up':
            frame = translation(edge+column, -span/2)@rotation(roll=90)
        else:
            frame = translation(edge, span/2)@rotation(roll=-90)
        vertical.update(row=-1, scale=scale, cap=column, width=span, x=0., baseline=0., slot=None, frame=frame)
        return height

    def arrange(self, words, members, pictured=None, width=BLOCK_WIDTH, left=-BLOCK_WIDTH/2, leading=None):
        """Set the words as a justified block (with a square slot for the picture beside `pictured`) of the
        given width from `left`; returns the block height. Each word gets its row, size and baseline position."""
        sizes, slot = [], None
        lengths = [sum(1 for w in words if w['line'] == i) for i in members]
        for word in words:
            font = stage_font(word['font'], REFERENCE)
            cap = -font.getbbox('H', anchor='ls')[1]
            sizes.append((max(1., font.getlength(word['text'])), cap))
            if word is pictured:
                slot = len(sizes)
                sizes.append((cap*1.15, cap))
                lengths[members.index(word['line'])] += 1
        layout = layout_block(sizes, TARGET_RATIO/self.aspect*width/BLOCK_WIDTH, width, [n for n in lengths if n],
                              *(() if leading is None else (leading,)))
        height = layout['height']
        caps = {}
        for size, place in zip(sizes, layout['words']):
            caps[place['row']] = max(caps.get(place['row'], 0.), size[1]*place['scale'])
        places = [place for number, place in enumerate(layout['words']) if number != slot]
        measured = [size for number, size in enumerate(sizes) if number != slot]
        for word, size, place in zip(words, measured, places):
            cap = caps[place['row']]
            word.update(row=place['row'], scale=place['scale'], cap=cap, width=size[0]*place['scale'],
                        x=place['x']+left, baseline=height/2-(place['y']+cap), slot=None, frame=np.identity(4))
        if pictured is not None:
            place = layout['words'][slot]
            cap = caps[place['row']]
            size = min(cap*1.1, sizes[slot][0]*place['scale'])
            pictured['slot'] = (place['x']+left+sizes[slot][0]*place['scale']/2, height/2-(place['y']+cap)+cap/2, size)
        return height

    def crown(self, words, effect):
        """The block's particle effect grows on its top row only, never on the word carrying a picture."""
        for word in words:
            word['effect'] = effect if word['row'] == 0 and not word.get('ornament') else None

    def follow_instructions(self, words):
        """Special instructions typed for the renderer: the words they name take that effect and colour."""
        for word in words:
            directive = getattr(self.c, 'word_directives', {}).get((word['line'], word['index']), {})
            if directive.get('effect'):
                word['effect'] = self.c.effect_catalog['entrance'].get(directive['effect'], word['effect'])
            if directive.get('color'):
                word['color'] = tuple(directive['color'])

    def block_effect(self, members, number=0, directed=None):
        """The block's particle entrance. In a scene that owns particle effects: the one the block director
        picked, or the scene's effects in turn. Otherwise a top-only effect if any of its lines has one,
        else the first line's."""
        c = self.c
        if getattr(c, 'particle_intensity', 0) <= 0:
            return None
        if self.crowns is not None:
            owned = self.owned_effects(members[0])
            if not owned:
                return None
            pick = (directed or {}).get('particle')
            preferred = [e for e in (self.crowns or {}).get(members[0]) or [] if e in owned]
            fallback = preferred or owned
            return c.effect_catalog['entrance'][pick if pick in owned else fallback[number % len(fallback)]]
        recipes = [c.effect_catalog['entrance'].get(c.effect_pairs[index][0]) for index in members]
        recipes = [recipe for recipe in recipes if recipe is not None]
        return next((r for r in recipes if r.placement == 'top'), recipes[0] if recipes else None)

    def owned_effects(self, line):
        """Allowed entrances for a scene block; tree canopy alone is restricted to tree effects."""
        c = self.c
        pool = getattr(c, 'entrance_pool', None)
        flow = next((f for f in c.plan.get('scene_flows', []) if f['start'] <= line < f['end']), None)
        tree = flow is not None and flow['scene'] == 'tree-canopy'
        choices = (self.crowns or {}).get(line) or [] if tree else c.effect_catalog['entrance']
        return [e for e in choices
                if e in c.effect_catalog['entrance'] and (pool is None or e in pool)]

    def choose_accent(self, words, ink, color=ACCENT, style=None):
        """All words in ink except one accent below the top row: the first hero there, else the longest-held word.
        In the contrast layout the vertical word carries the accent."""
        if style is not None:
            for word in words:
                word['color'] = color if word is style['vertical'] else ink
            return
        below = [w for w in words if w['row'] > 0] or words
        accent = next((w for w in below if w['role'] == 'hero'), None) or max(below, key=lambda w: w['end']-w['start'])
        for word in words:
            word['color'] = color if word is accent else ink if word['role'] != 'function' else tuple(round(v*.86) for v in ink)

    def directions(self):
        """The block director's choices by each block's first line, or None when it has not run."""
        directed = self.c.plan.get('stage_direction')
        if not isinstance(directed, list):
            return None
        return {entry['lines'][0]: entry for entry in directed if entry and entry.get('lines')}

    def choose_motion(self, words, rng, directed=False):
        """Some words keep moving after they land, and one word per block may get a picture: the one the
        block director chose (`directed`, None for no picture), or with `directed` False the first word
        matching a keyword picture."""
        for word in words:
            word['motion'] = rng.choice(MOTIONS) if word['role'] == 'hero' and not word['effect'] and rng.random() < .6 else None
            if word.get('sweet'):
                word['motion'] = 'bounce'
            elif word.get('bouncy') and word['motion'] == 'tilt':
                word['motion'] = None
            word['ornament'] = word['letter'] = None
        if directed is None:
            return
        if directed is not False:
            spec = directed
            word = next((w for w in words if (w['line'], w['index']) == (spec.get('line'), spec.get('word'))
                         and not w.get('vertical') and not w.get('sweet')), None)
            if word is None:
                return
            word['ornament'] = dict(kind=spec.get('library') if spec.get('source') == 'library' or not spec.get('image') else None,
                                    image=spec.get('image'), motion=spec.get('motion'))
            if not word['ornament']['kind'] and not word['ornament']['image']:
                word['ornament'] = None
                return
            word['effect'] = None
            letter = word['text'].upper().find('O') if spec.get('placement') == 'letter' else -1
            word['letter'] = letter if letter >= 0 else None
        else:
            themed = [w for w in words if glyph_art.theme(w['bare']) and not w['effect'] and not w.get('vertical') and not w.get('sweet')]
            themed.sort(key=lambda w: (glyph_art.replaces_letter(glyph_art.theme(w['bare']), w['text']) is None,
                                       w['bare'] != glyph_art.theme(w['bare']), w['role'] != 'hero', w['start']))
            if not themed:
                return
            word = themed[0]
            kind = glyph_art.theme(word['bare'])
            word['ornament'] = dict(kind=kind, image=None, motion=None)
            word['letter'] = glyph_art.replaces_letter(kind, word['text'])
        if word['letter'] is not None and word['motion'] == 'tilt':
            word['motion'] = 'wave'

    def motes(self, rng, height):
        return [(rng.uniform(-1.4, 1.4)*BLOCK_WIDTH/2, rng.uniform(-1.6, 1.6)*height/2, rng.uniform(-3., 1.2),
                 rng.uniform(.025, .07), rng.uniform(0, math.tau), rng.uniform(.4, 1.2)) for _ in range(MOTES)]

    def plan_world(self):
        """Whether the screen aligned artwork backdrop is active behind the 3D lettering."""
        c = self.c
        paths = list(getattr(c, 'illustration_paths', None) or [])
        if not paths or c.artwork_mode not in ('fullscreen', 'verse'):
            return None
        return [str(p) for p in paths]

    def plan_shapes(self):
        """Outlined or translucent shapes around the blocks on strong bass notes (or block starts without
        bass), on screen for about the `geometry` share of the stage's time, in the block's own colours."""
        blocks = self.blocks
        span = sum(b['hold'][1]-b['hold'][0] for b in blocks)
        count = round(self.options['geometry']*span/(SHAPE_LIFE*1.7))
        moments = [time for time, strength in (self.rhythm.get('bass') or []) if strength >= .6]
        moments = [m for m in moments if any(b['hold'][0] <= m < b['hold'][1] for b in blocks)] or [b['start'] for b in blocks]
        spacing = span/max(1, count)
        shapes, last = [], -math.inf
        for time in moments:
            if len(shapes) >= count:
                break
            if time-last < spacing:
                continue
            last = time
            rng = random.Random(round(time*1000))
            number = max(0, bisect.bisect_right([b['hold'][0] for b in blocks], time)-1)
            block = blocks[number]
            angle = rng.uniform(0, math.tau)
            x = math.cos(angle)*BLOCK_WIDTH/2*rng.uniform(.6, SHAPE_REACH)
            y = math.sin(angle)*block['height']/2*rng.uniform(.8, SHAPE_REACH*1.4)
            color = block['accent'] if rng.random() < .5 else hex_rgb(rng.choice(BACKDROP_COLORS))
            mode = ('glide', 'word', 'glide', 'loop', 'word', 'glide')[len(shapes) % 6]
            shapes.append(dict(start=time, block=number, kind=rng.choice(SHAPES), ornament=rng.choice(ORNAMENTS), mode=mode,
                               filled=True, color=color,
                               position=(x, y, rng.uniform(*SHAPE_DEPTHS)), size=rng.uniform(.35, 1.1),
                               spin=rng.uniform(-25, 25), tilt=(rng.uniform(-35, 35), rng.uniform(-35, 35)),
                               drift=(rng.uniform(-.06, .06), rng.uniform(-.06, .06), rng.uniform(-.04, .04))))
        return shapes

    def plan_ribbon(self):
        """The bands' path through the world: from block to block, just behind each block's first hero word
        as it is sung, turning continuously at one cruising speed and weaving in the blocks' planes (see
        flow_path). One stop per block keeps the distances and times between stops even, so the band can
        sweep on without braking."""
        stops = []
        for block in self.blocks:
            word = next((w for w in block['words'] if w['role'] == 'hero'), block['words'][0])
            local = np.array([word['x']+word['width']/2, word['baseline']+word['cap']/2, RIBBON_DEPTH, 1.])
            stops.append((word['start'], (block['placement']@word['frame']@local)[:3], block['accent'], block['placement'][:3, 2],
                          block['lines'][0], block['lines'][-1]))
        stops.sort(key=lambda stop: stop[0])
        times = []
        for stop in stops:
            times.append(max(stop[0], times[-1]+.05) if times else stop[0])
        from render.flow_path import build_flows
        runs, runs_of, label = [], [], 0
        for n, stop in enumerate(stops):
            label += 0 if not n else 1 if stop[4] == stops[n-1][5]+1 else 2
            runs_of.append(label)
        painted_words = set()
        for flow in build_flows(times, [stop[1] for stop in stops], [stop[2] for stop in stops], amplitude=RIBBON_SWING,
                                normals=[stop[3] for stop in stops], lines=runs_of):
            if self.options['geometry'] > 0:
                for shape in self.shapes:
                    if shape['mode'] == 'glide':
                        continue
                    moment = shape['start']
                    keys = flow['keys']
                    if not keys[0] or not keys[0][0]+.5 < moment < keys[0][-1]-1.2:
                        continue
                    distance = thread_distance(keys, moment)
                    if distance is None or distance <= .01 or distance >= flow['pieces'][-1]['end']:
                        continue
                    point = sample_thread(flow['pieces'], distance-.01, distance, 1.)[-1]
                    origin = np.array(point[:3])
                    block = self.blocks[shape['block']]
                    permanent = shape['mode'] == 'word'
                    if permanent:
                        choices = [w for w in block['words'] if w['role'] == 'hero' and w['start'] <= moment+.5
                                   and (w['line'], w['index']) not in painted_words]
                        if not choices:
                            continue
                        word = min(choices, key=lambda w: abs(w['start']-moment))
                        painted_words.add((word['line'], word['index']))
                        frame = block['placement']@word['frame']
                        cx, cy = word['x']+word['width']/2, word['baseline']+word['cap']/2
                        rx, ry = word['width']/2+word['cap']*.65, word['cap']*1.1
                        local = np.linalg.inv(frame)@np.array([*origin, 1.])
                        flat = swash_route(local[0], local[1], cx, cy, rx, ry, tilt=.12)
                        route = [tuple((frame@np.array([px, py, RIBBON_DEPTH-.04, 1.]))[:3]) for px, py in flat]
                        route[0] = route[-1] = tuple(origin)
                        color = block['accent']
                    else:
                        right, up = block['placement'][:3, 0], block['placement'][:3, 1]
                        flat = curl_route(0., 0., shape['size']*.2, 1. if round(moment*10) % 2 else -1.)
                        route = [tuple(origin+px*right-py*up) for px, py in flat]  # the curl is drawn with y down
                        color = point[-1]
                    # The ribbon itself draws the curl or swash; no filled shape is revealed behind it.
                    length = insert_thread_loop(flow['pieces'], distance, route, color, shape=False)
                    clock, distances, _ = keys
                    duration = loop_duration(keys, length, (2.2, TRACE_TIME[1]) if permanent else CURL_TIME)
                    flow['keys'] = monotone_keys(clock, [d+length*smooth((time-moment)/duration)
                                                         for time, d in zip(clock, distances)])
            segments, colors, paint = [], [], []
            for piece in flow['pieces']:
                points = [np.array(p) for p in piece['points']]
                segments.extend(zip(points, points[1:]))
                colors.extend([piece['color']]*(len(points)-1))
                paint.extend([not piece.get('shape', False)]*(len(points)-1))
            runs.append(rounded_run(dict(segments=segments, colors=colors, paint=paint, keys=flow['keys'],
                                         shape_fills=flow.get('shape_fills', []))))
        return runs
