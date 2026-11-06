"""The frame compositor: backgrounds, artwork and lyric typography for each video frame."""
from __future__ import annotations
from core.imaging import flat_pixels
import bisect
import math
from pathlib import Path
import subprocess
from core.progress import emit
from PIL import Image, ImageDraw, ImageOps, ImageFilter
from render.layout import FULL_FRAME
from render.text_effects import EFFECTS, TEXT_ANIMATIONS
from effects.particles.catalog import discover_effects, resolve_effect, parse_pool
from render.line_arrival import line_arrivals, reading_lanes, reading_regions
from render.timeline import tighten_line_starts
from direction.typography import FONTS, PALETTES, STYLES, validate_plan
from render.typography_settings import KINETIC_TEXT_SCALE, typography_options, selected_font, selected_word_animation
from core.fonts import first_font
from core.easing import cubic_out as ease  # shared curves, under this module's own names
from core.color import hex_rgb as rgb

READING_HOLD = 0.
_REPORTED = set()  # special-instruction problems already reported in this process
EDGE_FADE = (1., 1.5)  # seconds the video fades in from black and out to black (the `fade` setting)

LIGHT_INK = {'paper': 'midnight'}

SIZE_SPREAD = (.85, 1.15)

READING_FLOOR = .075

def mix(a, b, value):
    return tuple(round(x + (y - x) * value) for x, y in zip(a, b))


def font_at(family, size, custom=None):
    found = first_font([str(custom)] if custom else FONTS[family], size)
    if found is None:
        raise ValueError('No bold font found. Supply --font with a TTF/OTF font.')
    return found


class Compositor:
    def __init__(self, data, plan, width, height, duration, custom_font=None,
                 background=None, lead_in=1., illustrations=None, illustration_lines=2,
                 cinematic=False, preserve_art_slots=False, type_effect='none',
                 particle_intensity=1., artwork_mode='cutout', layout_seed=42,
                 particle_speed=1., entrance_effect=None, exit_effect=None, entrance_pool=None, exit_pool=None, text_animation='directed', font_family='auto', font_style='auto', font_scale=1.25, text_pool=None, lettering_styles=None, reading_flow='preview', melody=None, rhythm=None, kinetic=None, effect_speeds=None,
                 effect_intensities=None, instruments=None, instructions='', art_times=None, video_clips=None,
                 report_instructions=True):
        self.source_cues=[line['words'][0]['start'] for line in data]
        self.data, self.plan = data, validate_plan(plan, data)
        self.width, self.height, self.duration = width, height, duration
        if not math.isfinite(lead_in) or not 0 <= lead_in <= 5:
            raise ValueError('Lead-in must be finite and between 0 and 5 seconds.')
        self.artwork_mode, self.layout_seed = artwork_mode, layout_seed
        if artwork_mode in FULL_FRAME:
            self.plan = dict(self.plan, scenes=[dict(scene, palette=LIGHT_INK.get(scene['palette'], scene['palette'])) for scene in self.plan['scenes']])
        allowed = typography_options(dict(lettering_styles=lettering_styles))['lettering_styles']
        if set(allowed) != set(STYLES):
            self.plan = dict(self.plan, scenes=[scene if scene['style'] in allowed else dict(scene, style=allowed[number % len(allowed)])
                                                for number, scene in enumerate(self.plan['scenes'])])
        self.cinematic = cinematic
        if type_effect not in EFFECTS:
            raise ValueError('Unknown typography effect: '+str(type_effect))
        if text_animation not in TEXT_ANIMATIONS:
            raise ValueError('Unknown word animation: '+str(text_animation))
        self.text_animation = text_animation
        self.typography = typography_options(dict(font_family=font_family,font_style=font_style,font_scale=font_scale,text_pool=text_pool,lettering_styles=lettering_styles,reading_flow=reading_flow,kinetic=kinetic,instructions=instructions,effect_speeds=effect_speeds,effect_intensities=effect_intensities))
        if not self.typography['kinetic']['overlay_text']:
            text_animation = self.text_animation = 'none'
            entrance_effect = exit_effect = 'none'
        from render.chorus_fx import ChorusFX
        beat = self.typography['kinetic']
        self.chorus_fx = ChorusFX(data, (rhythm or {}).get('drums'), beat['beat_intensity'],
                                  lights=beat['beat_effect'] == 'lights', confetti=beat['beat_confetti'],
                                  whole_song=beat['beat_scope'] == 'song', confetti_strength=beat['confetti_intensity'],
                                  blur=beat['beat_blur'])
        # Song-wide lettering colours typed in the special instructions replace each scene palette's ink and accent.
        from direction.instructions import typography_colors
        self.ink_override, self.accent_override = typography_colors(self.typography['instructions'])
        self.word_animations=[[selected_word_animation(text_animation,self.typography['text_pool'],index)]*len(line['words'])
                              for index,line in enumerate(data)]
        self.text_animations=[motions[0] for motions in self.word_animations]
        self.type_effect = type_effect
        self.particle_intensity = float(particle_intensity)
        self.particle_speed = float(particle_speed)
        self.instrument_stage = None
        if instruments:
            from render.instrument_stage import InstrumentStage
            self.instrument_stage = InstrumentStage(instruments, rhythm, width, height)
        if not math.isfinite(self.particle_intensity) or not 0 <= self.particle_intensity <= 2:
            raise ValueError('Particle intensity must be finite and between 0 and 2.')
        if not math.isfinite(self.particle_speed) or not .2 <= self.particle_speed <= 3:
            raise ValueError('Particle speed must be finite and between 0.2 and 3.')
        line_effects, entrance_effect, entrance_pool = self._assign_effects(
            data, plan, text_animation, entrance_effect, exit_effect, type_effect, entrance_pool, exit_pool, report_instructions)
        self._plan_timing(data, duration, lead_in)
        self.custom_font = custom_font or selected_font(font_family,font_style)
        self._choose_engine(melody, rhythm, particle_speed)
        self.photo = (ImageOps.fit(Image.open(background).convert('RGB'), (width, height))
                      if background else None)
        self.backgrounds = {}
        self.illustration_lines = illustration_lines
        if type(illustration_lines) is not int or illustration_lines < 1:
            raise ValueError('Illustration line count must be a positive integer.')
        from render.artwork_track import ArtworkTrack
        self.artwork = ArtworkTrack(width, height, duration, artwork_mode, cinematic, layout_seed, lead_in,
                                    self.source_cues, illustration_lines)
        self.artwork.load(illustrations, preserve_art_slots, art_times, video_clips)
        self.text_box = self.default_text_box = self.artwork.default_text_box

        base_boxes=[]
        for cue in self.cues:
            artwork=max(0,bisect.bisect_right(self.art_starts,cue)-1) if self.art_starts else None
            base_boxes.append(self.composition(artwork)[1] if artwork is not None else self.default_text_box)
        self.line_regions=reading_regions(self.starts,self.effect_end_times,base_boxes)
        from render.preview import PreviewTypography
        self.preview = PreviewTypography(self)  # preview flow, plus every flow's text-only layers
        self.match_artwork_colors()
        if not line_effects:
            self.keep_effects_readable(entrance_effect, entrance_pool)

    def _assign_effects(self, data, plan, text_animation, entrance_effect, exit_effect, type_effect, entrance_pool, exit_pool,
                        report_instructions):
        """Every word's (entrance, exit) effect and animation: planned by the AI, chosen per line, or resolved from
        the pools, then overridden by the special instructions. Returns what the readability check needs."""
        self.effect_catalog = discover_effects()
        self.effect_cache = {}
        entrance_pool = parse_pool(entrance_pool, 'entrance', self.effect_catalog, strict=False)
        self.entrance_pool = entrance_pool  # the ticked entrances (None: all); scenes' own effects honour it too
        if self.typography['reading_flow'] == 'realtime' and self.typography['kinetic']['camera'] == 'pan':
            exit_effect, exit_pool = 'none', None
        exit_pool = parse_pool(exit_pool, 'exit', self.effect_catalog, strict=False)
        self.word_effect_pairs=[]
        total=0
        planned=plan.get('word_effects') if text_animation=='ai' else None
        line_effects=plan.get('line_effects') if entrance_effect=='ai' else None
        line_exits=plan.get('line_exits') if exit_effect=='ai' else None
        if line_effects is not None and (len(line_effects)!=len(data) or any(e not in self.effect_catalog['entrance'] and e!='none' for e in line_effects)):
            line_effects=None
        if line_exits is not None and (len(line_exits)!=len(data) or any(e not in self.effect_catalog['exit'] and e!='none' for e in line_exits)):
            line_exits=None
        if entrance_effect=='ai':
            entrance_effect='mixed'
        if exit_effect=='ai':
            exit_effect='mixed'
        if text_animation=='ai' and (not isinstance(planned,list) or len(planned)!=len(data)):
            raise ValueError('AI word animation choices must be planned before rendering')
        for index,line in enumerate(data):
            effects=[]
            if planned is not None and len(planned[index])!=len(line['words']):
                raise ValueError('AI animation choices do not match the aligned words')
            for j,_ in enumerate(line['words']):
                if planned is not None:
                    chosen=planned[index][j]
                    self.word_animations[index][j]=chosen['motion']
                    effects.append((chosen['entrance'],chosen['exit']))
                else:
                    effects.append((line_effects[index] if line_effects else resolve_effect(entrance_effect,'entrance',self.effect_catalog,total+j,type_effect,entrance_pool),
                                    line_exits[index] if line_exits else resolve_effect(exit_effect,'exit',self.effect_catalog,total+j,type_effect,exit_pool)))
            self.word_effect_pairs.append(effects)
            total+=len(line['words'])
        self.text_animations=[motions[0] for motions in self.word_animations]
        # Special instructions typed for the renderer override the chosen effect and colour of the words they name.
        from direction.instructions import word_directives
        self.word_directives, problems = word_directives(data, self.typography['instructions'], self.effect_catalog['entrance'])
        import multiprocessing
        # Once per run: the compositor is rebuilt, and render workers build their own. A one-line child compositor
        # (report_instructions=False) sees only its line, so every other named word would look unsung.
        for problem in problems if report_instructions else ():
            if multiprocessing.parent_process() is None and problem not in _REPORTED:
                _REPORTED.add(problem)
                print('Special instructions: '+problem, flush=True)
        self.effect_pairs=[(next((a for a,b in effects if a!='none'),'none'),
                            next((b for a,b in effects if b!='none'),'none')) for effects in self.word_effect_pairs]
        for (line, index), directive in self.word_directives.items():  # after the lines' own effects are settled
            if directive.get('effect'):
                self.word_effect_pairs[line][index] = (directive['effect'], self.word_effect_pairs[line][index][1])
        return line_effects, entrance_effect, entrance_pool

    def _plan_timing(self, data, duration, lead_in):
        """When each line arrives, holds, exits and ends, and the reading lanes they share."""
        self.lead_in = lead_in
        self.cues = [line['words'][0]['start'] for line in data]
        self.exit_lengths = [
            (.8 if effect != 'none' and self.effect_intensity(effect) > 0 else .22) / self.effect_speed(effect)
            for _, effect in self.effect_pairs]
        self.arrivals = line_arrivals(data,self.effect_pairs,self.effect_catalog,
                                      [self.effect_speed(entrance) for entrance,_ in self.effect_pairs],
                                      self.particle_intensity,lead_in,self.word_animations)
        self.starts=[arrival.start for arrival in self.arrivals]
        self.exit_starts = [line['words'][-1]['end'] + READING_HOLD for line in data]
        self.effect_end_times = [min(duration,start+self.exit_lengths[index])
                                 for index,start in enumerate(self.exit_starts)]
        self.ends = [min(end,self.starts[index+1] if index+1 < len(data) else duration)
                     for index,end in enumerate(self.effect_end_times)]
        self._tail_compositors = {}
        self._arrival_compositors = {}
        visible_starts = [arrival.start if arrival is not None else start
                          for arrival,start in zip(self.arrivals,self.starts)]
        reading_ends=self.effect_end_times
        self.line_lanes,self.lane_count = reading_lanes(visible_starts,reading_ends)
        self.reading_band = self.lane_count > 1

    def _choose_engine(self, melody, rhythm, particle_speed):
        """The engine that draws the lyrics for the reading flow; None keeps the preview flow drawn here."""
        if not self.typography['kinetic']['overlay_text']:
            self.realtime = None
            return
        from render.realtime import RealtimeTypography
        self.realtime = (RealtimeTypography(self, melody, particle_speed, rhythm, self.typography['kinetic'])
                         if self.typography['reading_flow'] == 'realtime' else None)
        if self.typography['reading_flow'] == 'stage':
            from render.stage_3d import Stage3D
            self.realtime = Stage3D(self, melody, rhythm)
        elif self.typography['reading_flow'] == 'cinema':
            from render.cinema import CinemaTypography
            self.realtime = CinemaTypography(self, melody, particle_speed, rhythm, self.typography['kinetic'])
        elif self.typography['reading_flow'] == 'mixed':
            from render.scene_mix import SceneMix
            self.realtime = SceneMix(self, melody, particle_speed, rhythm, self.typography['kinetic'], self.plan.get('scene_flows'))

    # The artwork lives in self.artwork (render/artwork_track.py); these keep the names the engines use.
    @property
    def art(self):
        return self.artwork.art

    @art.setter
    def art(self, value):
        self.artwork.art = value

    @property
    def art_starts(self):
        return self.artwork.art_starts

    @art_starts.setter
    def art_starts(self, value):
        self.artwork.art_starts = value

    @property
    def mattes(self):
        return self.artwork.mattes

    @mattes.setter
    def mattes(self, value):
        self.artwork.mattes = value

    @property
    def open_boxes(self):
        return self.artwork.open_boxes

    @open_boxes.setter
    def open_boxes(self, value):
        self.artwork.open_boxes = value

    @property
    def videos(self):
        return self.artwork.videos

    @videos.setter
    def videos(self, value):
        self.artwork.videos = value

    @property
    def clips(self):
        return self.artwork.clips

    @clips.setter
    def clips(self, value):
        self.artwork.clips = value

    @property
    def illustration_paths(self):
        return self.artwork.illustration_paths

    @illustration_paths.setter
    def illustration_paths(self, value):
        self.artwork.illustration_paths = value

    @property
    def artwork_revisions(self):
        return self.artwork.artwork_revisions

    @artwork_revisions.setter
    def artwork_revisions(self, value):
        self.artwork.artwork_revisions = value

    def composition(self, *args):
        return self.artwork.composition(*args)

    def scenery(self, *args):
        return self.artwork.scenery(*args)

    def illustration(self, *args):
        return self.artwork.illustration(*args)

    def art_frame(self, *args):
        return self.artwork.art_frame(*args)

    def art_crossing(self, *args):
        return self.artwork.art_crossing(*args)

    def advance_videos(self, *args):
        return self.artwork.advance_videos(*args)

    def step_aside(self, record):
        self.scene_windows = []

    def match_artwork_colors(self):
        """With 'match text colours to the artwork' on, give every line colours from the painting behind it, keeping
        the role (light or dark ink, warm or cool accent) the typography director chose (see render.art_colors)."""
        if not self.typography['kinetic'].get('match_art_colors') or not self.art or self.artwork_mode not in FULL_FRAME:
            return
        from render.art_colors import accent_set, image_palette, matched_palette
        palettes = {}
        scenes = [dict(scene) for scene in self.plan['scenes']]
        for index, scene in enumerate(scenes):
            artwork = max(0, bisect.bisect_right(self.art_starts, self.cues[index])-1) if self.art_starts else 0
            artwork = min(artwork, len(self.art)-1)
            if artwork not in palettes:
                palettes[artwork] = image_palette(self.art[artwork])
            try:
                behind = self.line_background(index)
            except (IndexError, ValueError):
                behind = max(palettes[artwork], key=lambda c: c[1])[0]
            scene['art_colors'] = matched_palette(PALETTES[scene['palette']], palettes[artwork], behind)
            ink = self.scene_palette(scene)[2]
            scene['art_glows'] = dict(zip(('drums', 'other', 'bass'), accent_set(palettes[artwork], ink, 3, 1.5)))
            scene['art_shapes'] = accent_set(palettes[artwork], ink, 6, 3.)
        self.plan = dict(self.plan, scenes=scenes)
        every = [c for colors in palettes.values() for c in colors]
        self.art_duet = accent_set(every, '#808080', 4, 1.)   # the wisp's duet colours, from the whole song

    def scene_palette(self, scene):
        """The scene's (background, gradient, ink, accent) hex colours, with song-wide lettering colours applied."""
        background, gradient, ink, accent = scene.get('art_colors') or PALETTES[scene['palette']]
        hexed = lambda color: '#%02X%02X%02X' % tuple(color)  # noqa: E731
        return (background, gradient, hexed(self.ink_override) if self.ink_override else ink,
                hexed(self.accent_override) if self.accent_override else accent)

    def effect_speed(self, effect_id):
        """An effect's own particle speed from the profile, or the global speed."""
        return self.typography['effect_speeds'].get(effect_id, self.particle_speed)

    def effect_intensity(self, effect_id):
        """An effect's own letter-effect intensity from the profile, or the global intensity."""
        from effects.particles.catalog import split_color
        name = getattr(effect_id, 'id', effect_id)
        return self.typography['effect_intensities'].get(split_color(name)[0], self.particle_intensity)  # a colour does not change it

    def line_background(self, index, box=None):
        """Average colour behind a line's reading area: its artwork, or the scene's backdrop colour."""
        x, y, w, h = box or self.line_box(index)
        if self.art and self.artwork_mode in FULL_FRAME:
            artwork = max(0, bisect.bisect_right(self.art_starts, self.cues[index])-1) if self.art_starts else 0
            region = self.art[min(artwork, len(self.art)-1)].convert('RGB').crop((max(0, x), max(0, y), max(1, x+w), max(1, y+h)))
            pixels = list(flat_pixels(region.resize((8, 8))))
            return tuple(round(sum(p[i] for p in pixels)/len(pixels)) for i in range(3))
        return rgb(PALETTES[self.plan['scenes'][index]['palette']][0])

    def keep_effects_readable(self, entrance_effect, entrance_pool):
        """Mixed entrances never pair lettering with a background of the same colour."""
        if entrance_effect != 'mixed' or self.particle_intensity <= 0:
            return
        from effects.colors import readable_effect
        candidates = [e for e in (entrance_pool or list(self.effect_catalog['entrance'])) if e in self.effect_catalog['entrance']]
        if self.realtime is not None:
            from direction.effects import dominant_colors, line_backdrops
            backdrops = [dominant_colors(image) for image in line_backdrops(self)]
        else:
            backdrops = [[(self.line_background(index), 1.)] for index in range(len(self.effect_pairs))]
        for index, (entrance, exit_effect) in enumerate(self.effect_pairs):
            if entrance not in self.effect_catalog['entrance']:
                continue
            ink = rgb(self.scene_palette(self.plan['scenes'][index])[2])
            neighbours = {self.effect_pairs[i][0] for i in (index-1, index+1) if 0 <= i < len(self.effect_pairs)}
            chosen = readable_effect(entrance, candidates, ink, backdrops[index], neighbours)
            if chosen != entrance:
                self.effect_pairs[index] = (chosen, exit_effect)
                self.word_effect_pairs[index] = [(chosen if a == entrance else a, b) for a, b in self.word_effect_pairs[index]]

    def background(self, index, t, veil=True, zoom=None):
        """`zoom(number)` optionally scales painting `number` about its centre before a crossing blends it, so a
        painting that is still leaving keeps its own push-in instead of snapping back with the new one."""
        scene = self.plan['scenes'][max(0, index)]
        if self.artwork_mode in FULL_FRAME and self.art_starts:
            def painting(number):
                image = self.art_frame(number, t)
                grow = zoom(number) if zoom else 1.
                if grow > 1.0005:
                    w, h = image.size
                    cw, ch = w/grow, h/grow
                    image = image.resize(image.size, Image.Resampling.BILINEAR,
                                         box=((w-cw)/2, (h-ch)/2, (w+cw)/2, (h+ch)/2))
                return image
            current = max(0, bisect.bisect_right(self.art_starts,t)-1)
            frame = painting(current)
            if current > 0:
                blend = min(1., max(0., (t-self.art_starts[current])/self.art_crossing(current)))
                if blend < 1:
                    previous = painting(current-1)
                    feather = max(2, round(self.width*.03))
                    edge = round(blend*(self.width+4*feather)-2*feather)
                    seam = Image.new('L', frame.size)
                    if edge > 0:
                        ImageDraw.Draw(seam).rectangle((0, 0, edge, self.height), fill=255)
                        seam = seam.filter(ImageFilter.GaussianBlur(feather))
                    frame = Image.composite(frame, previous, seam)
            if not veil:
                return frame
            _, (x,y,w,h) = self.composition(current)
            if self.reading_band:
                x,y,w,h = self.default_text_box
            ink=rgb(self.scene_palette(scene)[2])
            tone=(12,16,24) if sum(ink)>384 else (246,241,230)
            mask=Image.new('L',frame.size)
            ImageDraw.Draw(mask).rectangle((x,y,x+w,y+h),fill=185)
            mask=mask.filter(ImageFilter.GaussianBlur(max(1,self.height*.045)))
            frame.paste(Image.new('RGB',frame.size,tone),(0,0),mask)
            return frame
        key = scene['palette']
        if key not in self.backgrounds:
            a, b, _, _ = map(rgb, PALETTES[key])
            texture = Image.new('RGB', (96, 96))
            texture.putdata([mix(a, b, .55 * (x + y) / 190) for y in range(96) for x in range(96)])
            base = texture.resize((self.width, self.height), Image.Resampling.BILINEAR)
            if self.photo:
                base = Image.blend(base, self.photo, .16)
            self.backgrounds[key] = base
        frame = self.backgrounds[key].copy()
        if index > 0 and t - self.starts[index] < .8:
            previous = self.background(index - 1, self.starts[index] - .001)
            frame = Image.blend(previous, frame, ease((t - self.starts[index]) / .8))
        overlay = Image.new('RGBA', frame.size)
        draw = ImageDraw.Draw(overlay)
        w, h = self.width, self.height
        accent = rgb(PALETTES[key][3])
        phase = t * .07
        if scene['background'] == 'diagonal':
            drift = math.sin(phase) * w * .06
            draw.polygon([(w*.68+drift, 0), (w, 0), (w, h), (w*.22+drift, h)], fill=(*accent, 11))
        elif scene['background'] == 'rings':
            cx, cy = w * .80, h * .28
            for k in range(3):
                r = h * (.25 + k * .14 + .025 * math.sin(phase))
                draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=(*accent, 16), width=max(1, round(h*.002)))
        else:
            cx, cy = w * (.78 + .04*math.sin(phase)), h * .25
            for k in range(9, 0, -1):
                r = h * k * .075
                draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(*accent, 2))
        if self.cinematic:
            drift = math.sin(t*.045)*w*.12
            draw.polygon([(w*.08+drift, 0), (w*.21+drift, 0), (w*.65+drift, h), (w*.40+drift, h)], fill=(*accent, 7))
        frame.paste(overlay, (0, 0), overlay)
        return frame

    def line_box(self,index):
        return self.line_regions[index]

    def growth_extent(self, index, family, word):
        """How far grown lettering reaches above and below a word, as fractions of the font size."""
        effect = self.effect_catalog['entrance'].get(self.effect_pairs[index][0])
        if effect is None or effect.trajectory != 'grow' or self.effect_intensity(effect) <= 0:
            return 0., 0.
        extents = self.__dict__.setdefault('_growth_extents', {})
        key = (effect.id, family, self.effect_intensity(effect))
        if key not in extents:
            if effect.family == 'petals':
                from effects.growth.botanical import grown_sprite
            else:
                from effects.growth.material import grown_sprite
            size = 120
            font = font_at(family, size, self.custom_font)
            pad = max(4, round(size*.08))
            bbox = font.getbbox(word)
            sprite = Image.new('RGBA', (math.ceil(font.getlength(word))+pad*2, size+pad*2))
            ImageDraw.Draw(sprite).text((pad-bbox[0], pad-bbox[1]), word, font=font, fill=(255, 255, 255, 255))
            boundaries = [0]+[max(0, min(sprite.width, round(pad+font.getlength(word[:k])))) for k in range(1, len(word))]+[sprite.width]
            above = below = 0.
            for seed in range(4):
                extra = {'glyph_spans': list(zip(boundaries, boundaries[1:]))} if effect.family == 'trees' else {}
                held, padding = grown_sprite(sprite, effect, seed, self.effect_intensity(effect), None, **extra)
                box = held.getchannel('A').getbbox()
                if box:
                    above = max(above, (padding-box[1])/size)
                    below = max(below, (box[3]-padding-sprite.height)/size)
            extents[key] = (max(0., above), max(0., below))
        return extents[key]

    def fit_line(self, index, w, h, start=None, floor=10):
        """Largest size (from `start`, never below `floor`) whose rows fit the reading area."""
        scene, line = self.plan['scenes'][index], self.data[index]
        style = scene['style']
        size = max(12, round(min(h*(.22 if style == 'swiss' else .27), w*.15)))
        if self.reading_band or (self.cinematic and h < self.height*.4):
            size = max(12, round(min(h*.55, self.height*.14, w*.15)))
        botanical=self.effect_catalog['entrance'].get(self.effect_pairs[index][0]) is not None and self.effect_catalog['entrance'][self.effect_pairs[index][0]].family=='petals'
        size = max(12,round(size*self.typography['font_scale']*KINETIC_TEXT_SCALE*(3 if botanical else 1)))
        if start is not None:
            size = min(size, start)
        max_width = w * .92
        family = 'grotesk' if style == 'swiss' and scene['font'] == 'condensed' else scene['font']
        longest = max((word['text'].upper() for word in line['words']), key=len)
        above, below = self.growth_extent(index, family, longest)
        while True:
            font = font_at(family, size, self.custom_font)
            pitch = size*(1.17+above+below)
            gap = size * .22
            rows, row, used = [], [], 0
            for i, word in enumerate(line['words']):
                length = font.getlength(word['text'].upper())
                if row and used + gap + length > max_width:
                    rows.append(row)
                    row, used = [], 0
                row.append((i, length))
                used += length + (gap if len(row) > 1 else 0)
            if row:
                rows.append(row)
            fits = len(rows) * pitch <= h*.92 and all(length <= max_width for row in rows for _, length in row)
            if fits or size <= max(floor, 10):
                break
            size -= 2
        return dict(style=style, family=family, size=size, rows=rows, font=font, gap=gap, pitch=pitch, above=above)

    def reading_size(self):
        """One song-wide lyric size; every line stays within SIZE_SPREAD of it."""
        if getattr(self, '_reading_size', None) is None:
            sizes = [self.fit_line(i, *self.line_box(i)[2:])['size'] for i in range(len(self.data))]
            floor = round(self.height*READING_FLOOR*self.typography['font_scale'])
            self._reading_size = max(floor, sorted(sizes)[len(sizes)//2] if sizes else floor)
        return self._reading_size

    def frame(self, t, *, text_only=False):
        self.advance_videos(t)
        image = self._frame(t, text_only=text_only)
        if self.instrument_stage is not None and not text_only:
            image = self.instrument_stage.paint(image, t)
        if text_only:
            return image
        if self.typography['kinetic'].get('overlay_text', True):  # beat lights, confetti and blur are overlay effects
            image = self.chorus_fx.paint(image, t)
        # The encoder reads raw rgb24: any other mode would shift every later frame and end the video early.
        image = image if image.mode == 'RGB' else image.convert('RGB')
        if self.typography['kinetic']['fade']:
            level = max(0., min(1., t/EDGE_FADE[0], (self.duration-t)/EDGE_FADE[1]))
            if level < 1:
                image = Image.blend(Image.new('RGB', image.size), image, level)
        return image

    def _frame(self, t, *, text_only=False):
        if not self.typography['kinetic'].get('overlay_text', True) or any(a <= t < b for a, b in getattr(self, 'scene_windows', [])):
            return self.artwork_only(t, text_only)
        if self.realtime is not None and not text_only:
            return self.realtime.frame(t)
        return self.preview.frame(t, text_only=text_only)

    def artwork_only(self, t, text_only):
        """With the lyrics overlay off: the artwork and clips alone (lyrics placed in the scene are part of the clips)."""
        if text_only:
            return Image.new('RGBA', (self.width, self.height))
        index = max(0, bisect.bisect_right(self.starts, t)-1)
        frame = self.background(index, t, veil=False).convert('RGBA')
        self.illustration(frame, index, t)
        scenery = self.scenery(t)
        if scenery is not None:
            frame.alpha_composite(scenery)
        return frame.convert('RGB')

BT709_OUTPUT = ['-vf', 'scale=out_color_matrix=bt709:out_range=tv', '-colorspace', 'bt709',
                '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
                '-bsf:v', 'h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1']


def video_color(path):
    """'bt709' for tagged exports; 'legacy' for older untagged ones, so section rebuilds match them."""
    try:
        tag = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=color_space',
                              '-of', 'default=nw=1:nk=1', str(path)], capture_output=True, text=True,
                             encoding='utf-8', errors='replace').stdout.strip()
    except OSError:
        return 'legacy'
    return 'bt709' if tag == 'bt709' else 'legacy'


def render(audio, output, data, plan, duration, args):
    try:
        return _render_video(audio, output, data, plan, duration, args)
    finally:
        from effects.particles.gl import close_particle_renderer
        close_particle_renderer()
        from render.stage_3d import close_stage
        close_stage()


def render_compositor(data,plan,duration,args):
    compositor = Compositor(
        tighten_line_starts(data), plan, args.width, args.height, duration,
        custom_font=args.font, background=args.background,
        lead_in=getattr(args, 'lead_in', 1.), illustrations=getattr(args, 'illustrations', None),
        illustration_lines=getattr(args, 'illustration_lines', 2),
        cinematic=getattr(args, 'cinematic', False),
        preserve_art_slots=getattr(args, 'preserve_art_slots', getattr(args, 'review_artwork', False)),
        type_effect=getattr(args, 'type_effect', 'none'),
        particle_intensity=getattr(args, 'particle_intensity', 1.),
        artwork_mode=getattr(args, 'artwork_mode', 'cutout'), layout_seed=getattr(args, 'image_seed', 42),
        particle_speed=getattr(args, 'particle_speed', 1.),
        entrance_effect=getattr(args, 'entrance_effect', None), exit_effect=getattr(args, 'exit_effect', None),
        entrance_pool=getattr(args, 'entrance_pool', None), exit_pool=getattr(args, 'exit_pool', None),
        text_animation=getattr(args, 'text_animation', 'directed'), melody=getattr(args, 'melody', None), rhythm=getattr(args, 'rhythm', None),
        instruments=getattr(args, 'instrument_pictures', None), art_times=getattr(args, 'art_times', None),
        video_clips=getattr(args, 'video_clips', None), **typography_options(vars(args)))
    if getattr(args, 'scene_lyrics_record', None):
        compositor.step_aside(args.scene_lyrics_record)
    return compositor


def ffmpeg_failure(log, code):
    """FFmpeg's own error text, or its exit code when it died without writing one (a crash)."""
    log.seek(0)
    text = log.read().decode(errors='replace').strip()
    return f'FFmpeg (exit {code}): {text}' if text else f'FFmpeg exited with code {code} ({code & 0xFFFFFFFF:#x}) without an error message'


def _render_video(audio, output, data, plan, duration, args):
    import tempfile
    from audio.rhythm import audio_for_mode
    export_audio = audio_for_mode(audio, Path(output).parent, getattr(args, 'audio_mode', 'original'))
    args.scene_lyrics_record = str(Path(output).parent/'scene-lyrics.json')
    compositor = render_compositor(data,plan,duration,args)
    overlay_on = compositor.typography['kinetic']['overlay_text']
    if overlay_on and getattr(args, 'entrance_effect', None) == 'ai' and compositor.particle_intensity > 0:
        from direction.effects import ensure_line_effects
        emit('direction', 0, message='AI choosing effects for each line')
        plan = ensure_line_effects(data, plan, compositor, vars(args), Path(output).parent)
        compositor = render_compositor(data,plan,duration,args)
    if overlay_on and getattr(args, 'exit_effect', None) == 'ai' and compositor.particle_intensity > 0:
        from direction.effects import ensure_line_effects
        emit('direction', 0, message='AI choosing exits for each line')
        plan = ensure_line_effects(data, plan, compositor, vars(args), Path(output).parent, phase='exit')
        compositor = render_compositor(data,plan,duration,args)
    if overlay_on and compositor.typography['reading_flow'] == 'mixed':
        from render.scene_mix import ensure_scenes
        emit('direction', 0, message='AI choosing a scene effect for each song section')
        plan = ensure_scenes(data, plan, vars(args), Path(output).parent)
        compositor = render_compositor(data,plan,duration,args)
    compositor.step_aside(Path(output).parent/'scene-lyrics.json')
    pictures = getattr(args, 'stage_pictures', 'ai-painted')
    has_stage = compositor.typography['reading_flow'] == 'stage' or getattr(compositor.realtime, 'stage', None) is not None
    if overlay_on and has_stage and pictures != 'keywords':
        if pictures == 'off':
            plan = dict(plan, ornaments=[], pictures='off')
        else:
            from direction.ornaments import ensure_ornaments
            emit('pictures', 0, message='AI choosing the small animated pictures for each block')
            plan = ensure_ornaments(data, plan, compositor, dict(vars(args), ornament_images=pictures == 'ai-painted'), Path(output).parent)
        compositor = render_compositor(data,plan,duration,args)
    if overlay_on and getattr(args, 'instruments_found', None) and getattr(args, 'instruments', 'off') != 'off':
        from render.instrument_stage import instrument_pictures
        emit('pictures', .8, message='Painting the instruments heard in the song')
        args.instrument_pictures = instrument_pictures(args.instruments_found, Path(output).parent, vars(args))
        compositor = render_compositor(data,plan,duration,args)
    encoding = (['-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '18', '-b:v', '0']
                if args.encoder == 'h264_nvenc' else ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18'])
    with tempfile.TemporaryDirectory(prefix='kinetic-', dir=output.parent) as temp:
        target = Path(temp)/'video.mp4'
        start = getattr(args, 'render_start', 0.)
        end = getattr(args, 'render_end', duration)
        span = end-start
        if not 0 <= start < end <= duration:
            raise ValueError('Invalid render interval')
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo',
                   '-pixel_format', 'rgb24', '-video_size', f'{args.width}x{args.height}',
                   '-framerate', str(args.fps), '-i', 'pipe:0', '-ss', str(start), '-i', str(export_audio),
                   '-map', '0:v:0', '-map', '1:a:0', '-t', str(span), *encoding,
                   '-force_key_frames', 'expr:gte(t,n_forced*1)',
                   *(BT709_OUTPUT if getattr(args, 'color', 'bt709') == 'bt709' else []),
                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(target)]
        emit('render', 0, message='Compositing frames and encoding video')
        print(f'Rendering {"cinematic" if compositor.cinematic else "editorial"} typography with {args.encoder}...', flush=True)
        with (Path(temp)/'ffmpeg.log').open('w+b') as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
            try:
                count = math.ceil(span*args.fps-1e-6)  # 33.7 s at 30 fps is 1011 frames, not 1012 from float error
                from render.parallel import frame_batches, worker_count
                from artwork.queue import has_pending, ReplacementsPending
                workers=worker_count(args,count)
                print(f'Compositing with {workers} CPU render worker(s); {args.encoder} handles encoding.',flush=True)
                batches=frame_batches(__name__,data,plan,duration,args,compositor,start,count,workers)
                last_second=-1
                try:
                    for number,length,pixels in batches:
                        if has_pending(output.parent):raise ReplacementsPending('Queued image replacements take priority over rendering')
                        process.stdin.write(pixels)
                        second=number//args.fps
                        if second!=last_second:
                            emit('render', number/count, frame=number, frames=count, workers=workers,message=f'Rendering {number/args.fps:.0f}/{span:.0f} seconds · {workers} CPU workers')
                            if second%5==0:print(f'  Render {number/args.fps:.0f}/{span:.0f}s',flush=True)
                            last_second=second
                finally:batches.close()
                process.stdin.close()
                code = process.wait()
                if code:
                    raise ValueError(ffmpeg_failure(log, code))
            except OSError as exc:
                # FFmpeg stopped reading: a broken pipe, or on Windows often EINVAL. Report FFmpeg's own log instead.
                if not isinstance(exc, BrokenPipeError) and process.poll() is None:
                    raise
                raise ValueError(ffmpeg_failure(log, process.wait())) from exc
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if process.stdin and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
        if output.name=='video.mp4' and output.exists():
            from studio.video_versions import archive_video
            archive_video(output)
        from core.files import replace_file
        replace_file(target, output)  # retried while Studio streams the previous video
        from studio.video_versions import write_render_metadata
        write_render_metadata(output, compositor.artwork_revisions, start, end)
        emit('render', 1, message='Video encoding complete')
