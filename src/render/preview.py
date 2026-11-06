"""The preview reading flow: each line set whole in its box, words arriving as sung.

The compositor draws this flow, and every flow's text-only layers, through PreviewTypography. Song timing,
effects and artwork stay on the compositor (`self.c`). This class only holds the current line's layout and
box, and the child compositors for early entrances and exit tails.
"""
import bisect
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from core.color import hex_rgb as rgb
from core.imaging import turn
from direction.typography import PALETTES
from render.compositor import SIZE_SPREAD, Compositor, font_at
from render.text_effects import cartoon_scale, highlight_overlay, highlight_word, mask_rise, paint_word

HIGHLIGHT_COLORS = {'midnight': '#FFD23F', 'paper': '#C2185B', 'wine': '#FFD23F', 'slate': '#FF6B6B',
                    'electric': '#FF5DA2', 'violet': '#FFD23F'}

RISE_COLORS = {'midnight': '#8FC1E3', 'paper': '#2F6F8F', 'wine': '#C6A6E8', 'slate': '#9FD8C8',
               'electric': '#7FD8FF', 'violet': '#9FE3D2'}

SLIDE_DIRECTIONS = ((1, 0), (0, -1), (-1, 0), (0, 1))

def settle(value):
    """Ease out with a small overshoot, so a sliding word lands and settles."""
    value = max(0., min(1., value))-1
    return 1+2.2*value**3+1.2*value**2

def word_progress(t, cue, scene_start, lead_in, duration=.24):
    """Activate at the sung cue. lead_in controls phrase preview only."""
    if t < max(cue, scene_start):
        return 0.
    if duration <= 0:
        return 1.
    fraction = max(0., min(1., (t - max(cue, scene_start)) / duration))
    return fraction * fraction * (3 - 2 * fraction)



class PreviewTypography:
    def __init__(self, compositor):
        self.c = compositor
        self.cache_index, self.layout = None, None
        self.text_box = compositor.text_box
        self._tail_compositors, self._arrival_compositors = {}, {}

    def plan(self):
        """Nothing to plan. Each line is laid out when first drawn."""

    def frame(self, t, text_only=False):
        c = self.c
        frame = self.paint(t, text_only)
        scenery = None if text_only else c.scenery(t)
        if scenery is None:
            return frame
        frame = frame.convert('RGBA')
        frame.alpha_composite(scenery)
        return frame.convert('RGB')

    def _paint_early_entrances(self,frame,t):
        for index,arrival in enumerate(self.c.arrivals):
            if arrival is None or not arrival.start <= t < self.c.starts[index]:
                continue
            if index not in self._arrival_compositors:
                entrance,_ = self.c.effect_pairs[index]
                child = Compositor([self.c.data[index]],dict(self.c.plan,scenes=[self.c.plan['scenes'][index]],word_layouts=[self.c.plan['word_layouts'][index]] if self.c.plan.get('word_layouts') else None),
                    self.c.width,self.c.height,self.c.duration,custom_font=self.c.custom_font,cinematic=self.c.cinematic,
                    particle_intensity=self.c.particle_intensity,particle_speed=self.c.particle_speed,
                    entrance_effect=entrance,exit_effect='none',text_animation=self.c.text_animations[index],report_instructions=False,**self.c.typography)
                child.arrivals = [arrival]
                child.word_effect_pairs=[self.c.word_effect_pairs[index]]
                child.word_animations=[self.c.word_animations[index]]
                child.text_animations=[self.c.text_animations[index]]
                child.starts = [arrival.start]
                child.ends = [self.c.effect_end_times[index]]
                child.line_lanes,child.lane_count = [0],1
                child.reading_band = self.c.reading_band
                child.default_text_box = self.c.line_box(index)
                child.line_regions = [self.c.line_box(index)]
                child._reading_size = self.c.reading_size()
                self._arrival_compositors[index] = child
            layer = self._arrival_compositors[index].frame(t,text_only=True)
            frame.paste(layer,(0,0),layer)

    def rises_into_place(self, index, position, particle_entry):
        """Words that slide up from below during the staggered entrance."""
        motion = self.c.word_animations[index][position]
        if particle_entry or self.c.plan.get('word_layouts') or motion in ('fade', 'none'):
            return False
        if motion == 'slide':
            return SLIDE_DIRECTIONS[position % len(SLIDE_DIRECTIONS)][1] > 0
        return self.c.plan['scenes'][index]['mode'] == 'stack'

    def word_arrival(self, index, position, count, t):
        """Stagger words inside the line's arrival window; the last one still lands before the vocal."""
        arrival = self.c.arrivals[index]
        if arrival.finish <= arrival.start:
            return 1. if t >= arrival.start else 0.
        raw = max(0., min(1., (t-arrival.start)/(arrival.finish-arrival.start)))
        step = min(.16, .55/max(1, count-1)) if count > 1 else 0.
        return max(0., min(1., (raw-step*position)/max(.2, 1-step*(count-1))))

    def prepare(self, index):
        scene, line = self.c.plan['scenes'][index], self.c.data[index]
        text_animation = self.c.text_animations[index]
        self.text_box = self.c.line_box(index)
        _, _, w, h = self.text_box
        particle_entry = self.c.effect_pairs[index][0] in self.c.effect_catalog['entrance'] and self.c.effect_intensity(self.c.effect_pairs[index][0])>0
        if self.c.plan.get('word_layouts'):
            from render.free_typography import build_layout
            scene_colors=dict(scene,colors=self.c.scene_palette(scene)[2:])
            botanical=self.c.effect_catalog['entrance'].get(self.c.effect_pairs[index][0]) is not None and self.c.effect_catalog['entrance'][self.c.effect_pairs[index][0]].family=='petals'
            self.layout=build_layout(line,self.c.plan['word_layouts'][index],scene_colors,w,h,
                lambda size:font_at(scene['font'],size,self.c.custom_font),self.c.typography['font_scale'],botanical)
            self.cache_index=index;self.c.effect_cache.clear()
            return
        fit = self.c.fit_line(index, w, h)
        base = self.c.reading_size()
        if fit['size'] > base*SIZE_SPREAD[1]:
            fit = self.c.fit_line(index, w, h, start=round(base*SIZE_SPREAD[1]))
        elif fit['size'] < base*SIZE_SPREAD[0]:
            x0, y0, _, _ = self.text_box
            w2, h2 = min(self.c.width*.94, max(w, w*base/max(1, fit['size']))), min(self.c.height*.9, max(h, h*1.15))
            x2 = round(min(max(0, x0+w/2-w2/2), self.c.width-w2)); y2 = round(min(max(0, y0+h/2-h2/2), self.c.height-h2))
            self.text_box = (x2, y2, round(w2), round(h2))
            _, _, w, h = self.text_box
            fit = self.c.fit_line(index, w, h, floor=round(base*SIZE_SPREAD[0]))
        style, family, size, rows, font, gap, pitch, above = (fit[key] for key in ('style', 'family', 'size', 'rows', 'font', 'gap', 'pitch', 'above'))
        def display(word):
            return word.upper()
        top = (h - len(rows)*pitch) / 2 + size*above
        center = (self.text_box[0]+w/2)/self.c.width
        align = 'left' if center < 1/3 else 'right' if center > 2/3 else 'center'
        ink, accent = self.c.scene_palette(scene)[2:]
        words = []
        for r, row in enumerate(rows):
            row_width = sum(length for _, length in row) + gap * (len(row)-1)
            x = w*.04 if align == 'left' else w*.96-row_width if align == 'right' else (w-row_width)/2
            for i, length in row:
                word = line['words'][i]
                color = ink if text_animation in ('highlight','karaoke') else accent if i == scene['emphasis'] else ink
                if self.rises_into_place(index, i, particle_entry):
                    color = RISE_COLORS.get(scene['palette'], accent)
                pad = max(4, round(size*.08))
                label = display(word['text'])
                bbox = font.getbbox(label)
                sprite = Image.new('RGBA', (math.ceil(length)+pad*2, size+pad*2))
                draw = ImageDraw.Draw(sprite)
                boxed = style == 'cutout' or (i == scene['emphasis'] and (scene['mode'] == 'blocks' or style == 'outline'))
                backdrop = None
                if boxed:
                    fill = accent if i == scene['emphasis'] else ink
                    if particle_entry:
                        backdrop = Image.new('L', sprite.size, 255)
                    else:
                        draw.rectangle((0, 0, sprite.width, sprite.height), fill=fill)
                    color = PALETTES[scene['palette']][0]
                glyph_mask = Image.new('L',sprite.size)
                mask_draw = ImageDraw.Draw(glyph_mask)
                if style == 'outline' and i != scene['emphasis']:
                    mask_draw.text((pad-bbox[0],pad-bbox[1]),label,font=font,fill=0,
                                   stroke_width=max(2,round(size*.025)),stroke_fill=255)
                    draw.text((pad-bbox[0], pad-bbox[1]), label, font=font, fill=(0,0,0,0),
                              stroke_width=max(2, round(size*.025)), stroke_fill=color)
                else:
                    mask_draw.text((pad-bbox[0],pad-bbox[1]),label,font=font,fill=255)
                    origin = (pad-bbox[0], pad-bbox[1])
                    if style == 'extrude' and not boxed:
                        depth = max(2, round(size*.05))
                        shade = tuple(round(v*.45) for v in rgb(accent))
                        for step in range(depth, 0, -1):
                            draw.text((origin[0]+step, origin[1]+step), label, font=font, fill=shade)
                        draw.text(origin, label, font=font, fill=color)
                    elif style == 'neon' and not boxed:
                        glow = Image.new('RGBA', sprite.size)
                        ImageDraw.Draw(glow).text(origin, label, font=font, fill=(0, 0, 0, 0),
                                                  stroke_width=max(2, round(size*.04)), stroke_fill=accent)
                        sprite.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(1, size*.05))))
                        sprite.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(1, size*.02))))
                        draw.text(origin, label, font=font, fill=color, stroke_width=max(1, round(size*.012)), stroke_fill=accent)
                    elif style == 'split' and not boxed:
                        draw.text(origin, label, font=font, fill=color)
                        lower = Image.new('RGBA', sprite.size)
                        ImageDraw.Draw(lower).text(origin, label, font=font, fill=accent)
                        half = Image.new('L', sprite.size)
                        ImageDraw.Draw(half).rectangle((0, pad+size*.52, sprite.width, sprite.height), fill=255)
                        lower.putalpha(ImageChops.multiply(lower.getchannel('A'), half))
                        sprite.alpha_composite(lower)
                    else:
                        draw.text(origin, label, font=font, fill=color)
                if style == 'cutout':
                    glyph_mask = glyph_mask.rotate((-1 if i % 2 else 1)*1.1,
                                                  resample=Image.Resampling.BICUBIC,expand=False)
                    sprite = turn(sprite, (-1 if i % 2 else 1)*1.1, expand=False)
                    if backdrop is not None:
                        backdrop = turn(backdrop, (-1 if i % 2 else 1)*1.1, expand=False)
                boundaries = [0]+[max(0,min(sprite.width,round(pad+font.getlength(label[:k])))) for k in range(1,len(label))]+[sprite.width]
                words.append(dict(index=i, row=r, x=x-pad, y=top+r*pitch,
                                  glyph_spans=list(zip(boundaries,boundaries[1:])),
                                  sprite=sprite, glyph_mask=glyph_mask, boxed=boxed, start=word['start'], length=length,
                                  backdrop=(rgb(fill), rgb(ink if fill == accent else accent), backdrop) if backdrop is not None else None))
                x += length + gap
        self.layout = dict(words=words, size=size, gap=gap)
        self.cache_index = index
        self.c.effect_cache.clear()

    def _paint_exit_tails(self, frame, index, t):
        active = [previous for previous in range(index)
                  if self.c.ends[previous] <= t < self.c.effect_end_times[previous]]
        self._tail_compositors = {key:value for key,value in self._tail_compositors.items() if key in active}
        for previous in active:
            if previous not in self._tail_compositors:
                entrance, exit_effect = self.c.effect_pairs[previous]
                child_plan = dict(self.c.plan, scenes=[dict(self.c.plan['scenes'][previous])],word_layouts=[self.c.plan['word_layouts'][previous]] if self.c.plan.get('word_layouts') else None)
                child = Compositor([self.c.data[previous]], child_plan, self.c.width, self.c.height,
                    self.c.duration, custom_font=self.c.custom_font, lead_in=0., cinematic=self.c.cinematic,
                    type_effect='none', particle_intensity=self.c.particle_intensity,
                    particle_speed=self.c.particle_speed, entrance_effect=entrance, exit_effect=exit_effect,
                    text_animation=self.c.text_animations[previous],report_instructions=False,**self.c.typography)
                child.arrivals = [self.c.arrivals[previous]]
                child.word_effect_pairs=[self.c.word_effect_pairs[previous]]
                child.word_animations=[self.c.word_animations[previous]]
                child.text_animations=[self.c.text_animations[previous]]
                child.line_lanes,child.lane_count = [0],1
                child.reading_band = self.c.reading_band
                child.default_text_box = self.c.line_box(previous)
                child.line_regions = [self.c.line_box(previous)]
                child._reading_size = self.c.reading_size()
                child.ends = [self.c.effect_end_times[previous]]
                self._tail_compositors[previous] = child
            tail = self._tail_compositors[previous].frame(t, text_only=True)
            frame.paste(tail,(0,0),tail)

    def paint(self, t, text_only):
        """The frame up to and including the lyrics; greenscreen scenery goes on top in `frame`."""
        index = bisect.bisect_right(self.c.starts, t) - 1
        frame = Image.new('RGBA',(self.c.width,self.c.height)) if text_only else self.c.background(index,t)
        if index < 0 or t >= self.c.ends[index]:
            if not text_only:
                self.c.illustration(frame,index,t)
                self._paint_exit_tails(frame,index,t)
                self._paint_early_entrances(frame,t)
            return frame
        if self.cache_index != index:
            self.prepare(index)
        scene = self.c.plan['scenes'][index]
        tx, ty, w, h = self.text_box
        energy, mode = scene['energy'], scene['mode']
        entrance, exit_effect = self.c.effect_pairs[index]
        text_animation = self.c.text_animations[index]
        full_screen = entrance != 'none' or exit_effect != 'none'
        if full_screen:
            mode = 'letters'
        if text_animation == 'slide':
            mode = 'slide'
        elif text_animation in ('fade','none','highlight','karaoke','mask-rise','cartoon-pop'):
            mode = 'letters'
        line_fade=min(1.,max(0.,(self.c.effect_end_times[index]-t)/self.c.exit_lengths[index]))
        fade=line_fade
        line_entrance,line_exit=self.c.effect_pairs[index]
        camera = 1.
        if mode == 'zoom':
            camera = 1. + (.12 + energy*.10) * (1-word_progress(t, self.c.cues[index], self.c.starts[index], self.c.lead_in))


        if not text_only:
            self.c.illustration(frame,index,t)
            self._paint_exit_tails(frame,index,t)
            self._paint_early_entrances(frame,t)

        text_layer = Image.new('RGBA', frame.size if full_screen else (w, h))

        positions = {}
        if scene['mode'] == 'push':
            for row in sorted({item['row'] for item in self.layout['words']}):
                items = [item for item in self.layout['words'] if item['row'] == row]
                total = sum(item['length'] + self.layout['gap'] for item in items)
                x = (w-total+self.layout['gap'])/2
                for item in items:
                    positions[item['index']] = x
                    x += item['length'] + self.layout['gap']
        for item in self.layout['words']:
            word = self.c.data[index]['words'][item['index']]
            entrance,exit_effect=line_entrance,'none'
            text_animation=self.c.word_animations[index][item['index']]
            if text_animation in ('mask-rise','cartoon-pop'):
                entrance='none'
            particle_in = entrance in self.c.effect_catalog['entrance'] and self.c.effect_intensity(entrance) > 0
            mode = 'letters' if particle_in or self.c.plan.get('word_layouts') else scene['mode']
            if text_animation == 'slide':mode = 'slide'
            elif text_animation in ('fade','none','mask-rise','cartoon-pop'):mode = 'letters'
            if particle_in:
                progress = self.c.arrivals[index].progress(t)
            else:
                progress = self.word_arrival(index, item['index'], len(self.layout['words']), t)
            if text_animation == 'none' and not particle_in:progress = 1. if t >= self.c.arrivals[index].start else 0.
            fade = 1.
            if progress <= 0:continue
            motion = settle(progress)
            x, y = item['x'], item['y']
            scale = 1.
            size = self.layout['size']
            if mode == 'drop':
                y -= (1-motion)*size*1.6
            elif mode == 'push':
                x = positions[item['index']]+(1-motion)*size*1.2
                scale = .8+.2*motion
            elif mode == 'zoom':
                scale = 1+(.35+energy*.25)*(1-motion)
            elif mode == 'blocks':
                x -= (1-motion)*size*1.4
            elif mode == 'stack':
                y += (1-motion)*size*1.4
            elif mode == 'slide':
                dx, dy = SLIDE_DIRECTIONS[item['index'] % len(SLIDE_DIRECTIONS)]
                x += dx*(1-motion)*size*1.8
                y += dy*(1-motion)*size*1.2
            elif mode != 'letters':
                x += (1-motion)*size*1.2
            if text_animation == 'cartoon-pop':
                scale = cartoon_scale(progress)
            sprite = item['sprite']
            overlay = None
            box_fraction = 0.
            if text_animation in ('highlight','karaoke') and progress >= 1:
                fraction = 1. if text_animation == 'highlight' and word['start']<=t<word['end'] else 0.
                if text_animation == 'karaoke':
                    fraction = max(0., min(1., (t-word['start']) / max(.001, word['end']-word['start'])))
                if self.c.plan.get('word_layouts') and t>=word['end']:fraction=0.
                highlight_color = item.get('highlight_color',rgb(PALETTES[scene['palette']][0] if item['boxed'] else (self.c.scene_palette(scene)[3] if self.c.accent_override else HIGHLIGHT_COLORS.get(scene['palette'],PALETTES[scene['palette']][3]))))
                held = self.c.effect_catalog['entrance'].get(entrance)
                if item.get('backdrop'):
                    box_fraction = fraction
                elif held is not None and self.c.effect_intensity(held) > 0 and (held.trajectory == 'grow' or getattr(held, 'hold', 'solid') == 'particles'):
                    overlay = highlight_overlay(sprite.size, highlight_color, fraction, item['glyph_mask'])
                else:
                    sprite = highlight_word(sprite,highlight_color,fraction,glyph_mask=item['glyph_mask'])
            if abs(scale-1) > .005:
                sprite = sprite.resize((max(1, round(sprite.width*scale)), max(1, round(sprite.height*scale))), Image.Resampling.BICUBIC)
                if overlay is not None:
                    overlay = overlay.resize(sprite.size, Image.Resampling.BICUBIC)
            if text_animation == 'mask-rise':
                sprite = mask_rise(sprite, progress)
            spans = item['glyph_spans']
            if scale != 1:
                spans = [(round(a*scale),round(b*scale)) for a,b in spans]
            if item.get('backdrop'):
                fill, accent_ink, box_mask = item['backdrop']
                box = Image.new('RGBA', box_mask.size, fill)
                if box_fraction > 0:
                    ImageDraw.Draw(box).rectangle((0, 0, round(box.width*box_fraction)-1, box.height), fill=accent_ink)
                box.putalpha(box_mask.point(lambda a: round(a*min(1., progress))))
                if box.size != sprite.size:
                    box = box.resize(sprite.size, Image.Resampling.BICUBIC)
                text_layer.alpha_composite(box, (round(x+tx if full_screen else x), round(y+ty if full_screen else y)))
            paint_word(text_layer, sprite, x+tx if full_screen else x, y+ty if full_screen else y, progress, 1., t-self.c.arrivals[index].start, item['index'], 'none', energy, spans, intensity=self.c.effect_intensity(entrance), speed=self.c.effect_speed(entrance),
                       entrance_effect=entrance, exit_effect=exit_effect, effect_catalog=self.c.effect_catalog, cache=self.c.effect_cache)
            if overlay is not None:
                text_layer.alpha_composite(overlay, (round(x+tx if full_screen else x), round(y+ty if full_screen else y)))
        if mode == 'marquee':
            font = font_at(scene['font'], max(10, round(h*.065)), self.c.custom_font)
            text = '  /  ' * 24
            span = max(1, math.ceil(font.getlength(text)))
            offset = -((t-self.c.starts[index]) * w * (.025+energy*.035)) % span - span
            draw = ImageDraw.Draw(text_layer)
            ink = rgb(self.c.scene_palette(scene)[2])
            for k in range(math.ceil(w/span)+2):
                draw.text((offset+k*span, h*.88), text, font=font, fill=(*ink, round(70*fade)))
        if camera != 1:
            enlarged = text_layer.resize((round(w*camera), round(h*camera)), Image.Resampling.BICUBIC)
            text_layer = ImageOps.fit(enlarged, (w, h), centering=(.5, .5))
        if line_fade<1.:
            if line_exit in self.c.effect_catalog['exit'] and self.c.effect_intensity(line_exit)>0:
                from effects.particles.motion import paint_transition
                bounds=text_layer.getchannel('A').getbbox()
                exiting=Image.new('RGBA',text_layer.size)
                if bounds:
                    paint_transition(exiting,text_layer.crop(bounds),bounds[0],bounds[1],'exit',1-line_fade,
                        self.c.effect_catalog['exit'][line_exit],index,self.c.effect_intensity(line_exit),energy,self.c.effect_cache)
                text_layer=exiting
            else:
                text_layer.putalpha(text_layer.getchannel('A').point(lambda a:round(a*line_fade)))
        overlay_frame = frame.convert('RGBA')
        overlay_frame.alpha_composite(text_layer, (0, 0) if full_screen else (tx, ty))
        frame = overlay_frame if text_only else overlay_frame.convert('RGB')
        return frame
