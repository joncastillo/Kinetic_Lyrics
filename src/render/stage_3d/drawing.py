"""Builds the items the GL stage draws each frame: camera, backdrop, words and bass shapes."""
from __future__ import annotations
import bisect
import math
import numpy as np
from PIL import Image, ImageDraw
import render.glyph_art as glyph_art
from render.realtime import SHAPE_LIFE, overshoot, smooth
from render.thread_path import thread_distance
from render.stage_3d.common import BACKDROP_TINT, BOUNCE_ENTRY, BOUNCE_STAGGER, DIM_TIME, EFFECT_FONT, ENTRY, ENTRY_LEAD, EXTRUDE_DEPTH, EXTRUDE_LAYERS, FONT_LIMITS, GROW_ENTRY, HOP, LETTER_STAGGER, MOVE, OLD_BLOCK, ORNAMENT_SIZE, PARTICLE_ENTRY, REFERENCE, SLOT_PICTURE, SWAY, artwork_token, elastic, normalized, ornament_image, shape_image, stage_font, text_sprite
from render.stage_3d.gl import rotation, scaling, translation


class StageDrawing:
    def backdrop(self, gl, t):
        # The shared compositor stitches adjacent paintings at one narrow seam. The flat texture
        # sits behind the perspective lettering, so no folded 3D surfaces can double-expose it.
        starts = self.c.art_starts
        current = max(0, min(len(self.c.art)-1, bisect.bisect_right(starts, t)-1))
        if current and t < starts[current]+self.c.art_crossing(current):
            texture = gl.transient(self.c.background(0, t, veil=False).convert('RGBA'))
        else:
            # a painting with an AI clip (or an uploaded video) moves: its frame at this moment, uploaded each frame;
            # a still painting is uploaded once and kept
            clips = getattr(self.c, 'clips', None) or []
            moving = current in getattr(self.c, 'videos', {}) or (current < len(clips) and clips[current] is not None)
            texture = (gl.transient(self.c.art_frame(current, t).convert('RGBA')) if moving
                       else gl.texture(('backdrop', artwork_token(self.c), current), lambda: self.c.art[current].convert('RGBA')))
        gl.quad(texture, scaling(2., 2.), 1., (BACKDROP_TINT,)*3)

    def shape_items(self, gl, t):
        items = []
        for shape in self.shapes:
            age = t-shape['start']
            if not 0 <= age < SHAPE_LIFE:
                continue
            fade = smooth(age/.6)*(1-smooth((age-SHAPE_LIFE+1.2)/1.2))
            if fade <= .01:
                continue
            block = self.blocks[shape['block']]
            x, y, z = (p+d*age for p, d in zip(shape['position'], shape['drift']))
            size = shape['size']*(.85+.25*smooth(age/SHAPE_LIFE))  # swells gently as it draws itself on
            step = max(1, min(24, round(24*smooth(age/1.1))))
            kind = shape.get('ornament', 'ring')
            texture = gl.texture(('ornament-line', kind, step), lambda kind=kind, step=step: ornament_image(kind, step))
            model = (block['placement']@translation(x, y, z)@rotation(shape['tilt'][0]*.4, shape['tilt'][1]*.4,
                     roll=shape['spin']*.5*age)@scaling(size, size))
            items.append((model, texture, .6*fade, tuple(min(1., v/255*.6+.4) for v in shape['color'])))
        return items

    def shape_fill_items(self, gl, t):
        """Reveal each solid polygon only as the white ribbon head traces its route."""
        items = []
        for run in self.ribbon:
            head = thread_distance(run['keys'], t)
            if head is None:
                continue
            for shape in run['shape_fills']:
                start, end = shape['start_distance'], shape['end_distance']
                if head <= start or (not shape['permanent'] and t >= shape['time']+SHAPE_LIFE):
                    continue
                progress = min(1., (head-start)/max(1e-6, end-start))
                step = max(1, round(progress*40))
                texture = gl.texture(('shape-fill', shape['kind'], step),
                                     lambda shape=shape, step=step: shape_image(shape['kind'], progress=step/40))
                model = np.identity(4)
                model[:3, 0] = shape['right']*shape['rx']*2.15
                model[:3, 1] = shape['up']*shape['ry']*2.15
                model[:3, 2] = normalized(np.cross(shape['right'], shape['up']))
                model[:3, 3] = shape['centre']
                fade = 1. if shape['permanent'] else 1-smooth((t-shape['time']-SHAPE_LIFE+.8)/.8)
                alpha = .4 if shape['permanent'] else .5
                items.append((model, texture, alpha*smooth(progress)*fade, tuple(v/255 for v in shape['color'])))
        return items

    def hold_pose(self, block, t):
        middle = (block['start']+block['end'])/2
        target = block['focus']+block['cruise']*(t-middle)
        eye = target+block['view']*block['camera_distance']
        return eye, target

    def camera(self, t):
        blocks = self.plan()
        number = max(0, bisect.bisect_right([b['move'] for b in blocks], t)-1)
        def pose(index):
            block = blocks[index]
            eye, target = self.hold_pose(block, t)
            roll = block['shot_roll']
            if index and t < block['move']+MOVE:
                # A new move may begin before the previous one finishes. Blend from its actual in-progress
                # pose so the camera cannot jump to the previous shot's unblended zoom or position.
                u = smooth(max(0., min(1., (t-block['move'])/MOVE)))
                old_eye, old_target, old_roll = pose(index-1)
                eye = old_eye+(eye-old_eye)*u
                target = old_target+(target-old_target)*u
                roll = old_roll+(roll-old_roll)*u
            return eye, target, roll

        eye, target, roll = pose(number)
        forward = normalized(target-eye)
        angle = math.radians(roll)
        up = np.array([0., 1., 0.])
        up = up*math.cos(angle)+np.cross(forward, up)*math.sin(angle)+forward*np.dot(forward, up)*(1-math.cos(angle))
        return eye, target, number, up

    def beat(self, t):
        drums = self.rhythm.get('drums')
        if not drums:
            return 0.
        from audio.rhythm import envelope
        return envelope(drums, t, .18)

    def block_opacity(self, number, current, t):
        """Earlier blocks stay where they were written, dimmed once the next block starts."""
        if number >= current:
            return 1.
        return 1-(1-OLD_BLOCK)*smooth((t-self.blocks[number+1]['start'])/DIM_TIME)

    def billboard(self, position, view, size):
        model = np.identity(4)
        model[:3, :3] = view[:3, :3].T*size
        model[:3, 3] = position
        return model

    def entrance(self, block, word, progress, anchor_x):
        """Local transform of a landing word (or letter) about its baseline anchor."""
        cap = word['cap']
        settled = overshoot(progress)
        if word.get('bouncy'):
            s = max(.01, elastic(progress))
            return translation(0, (1-smooth(progress))*cap*.7)@np.diag((s, s, 1., 1.))
        kind = 'pop' if word['role'] == 'hero' and block['entrance'] in ('rise',) else block['entrance']
        if kind == 'flip':
            return rotation(pitch=-95*(1-smooth(progress)))
        if kind == 'swing':
            return translation(-anchor_x)@rotation(yaw=85*(1-smooth(progress)))@translation(anchor_x)
        if kind == 'drop':
            return translation(0, (1-settled)*cap*1.4)
        if kind == 'pop':
            s = max(.01, settled)
            return translation(0, 0, (1-smooth(progress))*-cap*2)@np.diag((s, s, 1., 1.))
        return translation(0, -(1-settled)*cap*.6, (1-smooth(progress))*-cap*3)

    def effect_items(self, gl, block, word, t, opacity):
        """A top-row word forming through the block's particle effect, drawn flat and turned gently in 3D."""
        c, recipe = self.c, word['effect']
        length = (GROW_ENTRY if recipe.trajectory == 'grow' else PARTICLE_ENTRY)/c.effect_speed(recipe.id)
        progress = min(1., (t-word['start']+length)/length)
        if progress <= 0:
            return []
        size = max(FONT_LIMITS[0], min(EFFECT_FONT, round(REFERENCE*word['scale']*self.ppu)))
        k = REFERENCE*word['scale']/size
        font = stage_font(word['font'], size)
        ascent, descent = font.getmetrics()
        pad = max(6, round(size*.14))
        side, top, bottom = round(size*.6), round(size*1.1), round(size*.5)

        def draw():
            from effects.particles.motion import paint_transition
            sprite = Image.new('RGBA', (math.ceil(font.getlength(word['text']))+pad*2, ascent+descent+pad*2))
            ImageDraw.Draw(sprite).text((pad, pad+ascent), word['text'], font=font, fill=word['color'], anchor='ls')
            edges = [0]+[pad+round(font.getlength(word['text'][:n])) for n in range(1, len(word['text']))]+[sprite.width]
            layer = Image.new('RGBA', (sprite.width+side*2, sprite.height+top+bottom))
            paint_transition(layer, sprite, side, top, 'entrance', 1-progress, recipe, word['line']*31+word['index'],
                             c.effect_intensity(recipe), .6, c.effect_cache, glyph_spans=list(zip(edges, edges[1:])))
            return layer
        if progress >= 1:
            texture = gl.texture(('effect', word['text'], recipe.id, size, word['color'], word['line'], word['index']), draw)
        else:
            texture = gl.transient(draw())
        width, height = texture.size
        middle = font.getlength(word['text'])*k/2
        sway = rotation(yaw=math.sin(t*.7+word['index'])*5*smooth(max(0., t-word['start'])/2))
        model = (block['placement']@word['frame']@translation(word['x']+middle, word['baseline'], 0.)@sway
                 @translation((width/2-side-pad)*k-middle, (top+pad+ascent-height/2)*k, 0.)@scaling(width*k, height*k))
        return [(model, texture, opacity, (1., 1., 1.))]

    def word_items(self, gl, block, word, t, opacity, beat):
        if word['effect']:
            return self.effect_items(gl, block, word, t, opacity)
        size = max(FONT_LIMITS[0], min(FONT_LIMITS[1], round(REFERENCE*word['scale']*self.ppu)))
        k = REFERENCE*word['scale']/size
        letters = word['motion'] in ('wave', 'bounce') or word['letter'] is not None or word.get('bouncy')
        pieces = list(enumerate(word['text'])) if letters else [(None, word['text'])]
        font = stage_font(word['font'], size)
        entry, stagger = (BOUNCE_ENTRY, BOUNCE_STAGGER) if word.get('bouncy') else (ENTRY, LETTER_STAGGER)
        lead = entry+(len(word['text'])-1)*stagger if letters else entry
        sweet = bool(word.get('sweet'))
        items = []
        for number, text in pieces:
            if number is not None and (number == word['letter'] or not text.strip()):
                continue
            offset = font.getlength(word['text'][:number])*k if number is not None else 0.
            delay = (number or 0)*stagger
            progress = min(1., (t-word['start']+lead-delay)/entry)
            if progress <= 0:
                continue
            color = (255, 255, 255) if sweet else word['color']
            key = ('word', text, word['font'], size, color)
            sprite = gl.texture(key, lambda text=text, color=color: text_sprite(text, word['font'], size, color)[0])
            pad = max(6, round(size*.14))
            ascent = font.getmetrics()[0]
            width, height = sprite.size
            relative = np.array([(width/2-pad)*k, (ascent+pad-height/2)*k])
            glyph_width = font.getlength(text)*k
            anchor = np.array([word['x']+offset+glyph_width/2, word['baseline']])
            local = self.motion(word, t, beat, number, anchor_x=glyph_width/2)
            local = local@self.entrance(block, word, progress, glyph_width/2)
            alpha = smooth(progress*2.2)*opacity
            base = (block['placement']@word['frame']@translation(*anchor, 0.)@local
                    @translation(relative[0]-glyph_width/2, relative[1], 0.))
            if sweet:
                fill = dict(word['fills'][(number or 0) % len(word['fills'])], time=t,
                            origin=(-pad*k/word['cap'], -(height-ascent-pad)*k/word['cap']),
                            span=(width*k/word['cap'], height*k/word['cap']))
                items.append((base@scaling(width*k, height*k), sprite, alpha, (1., 1., 1.), fill))
                continue
            if word['role'] == 'hero':
                depth = EXTRUDE_DEPTH*word['cap']
                for layer in range(EXTRUDE_LAYERS, 0, -1):
                    shade = .22+.25*(1-layer/EXTRUDE_LAYERS)
                    items.append((base@translation(0, 0, -depth*layer/EXTRUDE_LAYERS)@scaling(width*k, height*k), sprite, alpha,
                                  (shade, shade, shade*1.1)))
            items.append((base@scaling(width*k, height*k), sprite, alpha, (1., 1., 1.)))
        if word['ornament']:
            items.extend(self.ornament_items(gl, block, word, font, k, t, opacity, beat))
        return items

    def motion(self, word, t, beat, letter, anchor_x):
        """Continuing movement of a landed word: a travelling letter wave, a beat pulse or a slow 3D tilt."""
        cap, age = word['cap'], max(0., t-word['start'])
        settle = smooth(age/.6)
        if word['motion'] == 'wave' and letter is not None:
            return translation(0, math.sin(t*4.2-letter*.7)*cap*.09*settle)
        if word['motion'] == 'bounce' and letter is not None:
            hop = abs(math.sin(t*3.2-letter*.55))
            return translation(0, hop*cap*HOP*settle)@rotation(roll=math.sin(t*3.2-letter*.55)*SWAY*settle)
        if word['motion'] == 'pulse':
            s = 1+.09*beat*settle+.03*math.sin(t*3.1)*settle
            return translation(0, cap/2)@np.diag((s, s, 1., 1.))@translation(0, -cap/2)
        if word['motion'] == 'tilt':
            return rotation(yaw=math.sin(t*1.3+word['index'])*16*settle, pitch=math.sin(t*.9)*6*settle)
        return np.identity(4)

    def ornament_items(self, gl, block, word, font, k, t, opacity, beat):
        cap = word['cap']
        progress = min(1., (t-word['start']+ENTRY_LEAD)/(ENTRY*1.6))
        grow = max(0., overshoot(progress))
        if word['letter'] is not None:
            letter = word['text'][word['letter']]
            middle = word['x']+(font.getlength(word['text'][:word['letter']])+font.getlength(letter)/2)*k
            center, size = np.array([middle, word['baseline']+cap/2, 0.]), cap*ORNAMENT_SIZE
            if word['motion'] == 'wave':
                center[1] += math.sin(t*4.2-word['letter']*.7)*cap*.09*smooth(max(0., t-word['start'])/.6)
        else:
            x, y, size = word['slot']
            size *= SLOT_PICTURE
            center = np.array([x, y+math.sin(t*1.7)*cap*.05, cap*.15])
        items = []
        for key, image, pose in glyph_art.ornament_layers(word['ornament'], t, beat):
            texture = gl.texture(('ornament',)+tuple(key), image)
            scale = size*pose['scale']*grow
            if scale <= 1e-4:
                continue
            model = (block['placement']@word['frame']@translation(*(center+np.array([pose['dx'], pose['dy'], pose['dz']])*size))
                     @rotation(roll=pose['angle'])@scaling(scale, scale))
            items.append((model, texture, pose['alpha']*opacity*smooth(progress*2), (1., 1., 1.)))
        return items
