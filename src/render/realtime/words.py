"""Paints a line: backdrop, frame shape, and each word with its shape, glow, pulse and
entrance or exit."""
import math
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from core.easing import smoothstep as smooth
from core.color import hex_rgb
from render.realtime.common import BACKDROP_FADE, FRAME_RETRACT, HALO_CACHE, INSTRUMENT_GLOWS, PARTICLE_ENTRY, WORD_SHAPE_FADE, WORD_SHAPE_FILL, overshoot, paste_clipped, paste_lighter, shape_outline, trace_outline
from render.realtime.layout import role_font, word_sprite



class LinePainting:
    def instrument_signals(self, t):
        """Compute each stem's envelope and recent hits once for the whole frame."""
        from audio.rhythm import pulse
        return {stem: pulse(self.rhythm.get(stem), t, decay)
                for stem, (_, decay) in INSTRUMENT_GLOWS.items()}

    def text_pulse(self, index, signals):
        """Instrument colour and strength pulsing through this line's words, if the line was chosen."""
        stem = self.lines[index].get('pulse')
        if not stem:
            return None, 0.
        return hex_rgb(self.lines[index].get('glows', {}).get(stem) or INSTRUMENT_GLOWS[stem][0]), signals[stem].level

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
                tint = (hex_rgb(getattr(word, 'glows', {}).get('drums') or INSTRUMENT_GLOWS['drums'][0]), signals['drums'].level*.3)
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
                from render.text_effects import cartoon_scale
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
        color = getattr(word, 'glows', {}).get(stem) or INSTRUMENT_GLOWS[stem][0]
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
            # Only the words around the current frame are needed; keeping every word of a song would cost
            # hundreds of MB per render worker at full resolution.
            while len(halos) >= HALO_CACHE:
                halos.pop(next(iter(halos)))
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
            from render.text_effects import mask_rise
            sprite = mask_rise(sprite, mask_progress)
        font = role_font(word.role, size)
        x = word.x+shift[0]+word.width/2-font.getlength(word.text)/2-pad
        y = word.y+shift[1]+role_font(word.role, word.size).getmetrics()[0]-font.getmetrics()[0]+dy-pad
        if hit:
            from render.drum_typography import paint_impact
            paint_impact(layer, sprite, x, y, spans, hit, self.options['drum_reactivity'], alpha)
        else:
            if alpha < .999:
                sprite.putalpha(sprite.getchannel('A').point(lambda a: round(a*alpha)))
            paste_clipped(layer, sprite, round(x), round(y))

    def paint_particle_word(self, layer, word, shift, dy, amount, recipe, opacity):
        from effects.particles.motion import paint_transition
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
        from effects.particles.motion import paint_transition
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
