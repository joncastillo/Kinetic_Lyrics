"""Local AI art direction and a frame compositor for lyric typography."""
from __future__ import annotations

import bisect
from io import BytesIO
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

from kinetic_progress import emit

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageFilter
from kinetic_layout import illustration_layout
from kinetic_effects import EFFECTS, TEXT_ANIMATIONS, paint_word, highlight_word, highlight_overlay
from particle_catalog import discover_effects, resolve_effect, parse_pool
from line_arrival import line_arrivals, reading_lanes, reading_regions
from typography_settings import KINETIC_TEXT_SCALE, typography_options, selected_font, selected_word_animation

READING_HOLD = 0.


MODES = ('push', 'drop', 'zoom', 'blocks', 'marquee', 'stack')
CAMERAS = ('push-in', 'pull-out', 'pan-left', 'pan-right', 'hold')
STYLES = ('poster', 'swiss', 'outline', 'cutout', 'neon', 'extrude', 'split')
PALETTES = {
    'midnight': ('#101725', '#223348', '#EEE9DE', '#D29A80'),
    'paper': ('#EAE3D5', '#CDC2B3', '#20252C', '#923F48'),
    'wine': ('#291722', '#512939', '#F2E7DE', '#E5AF8F'),
    'slate': ('#25343C', '#3D555C', '#F0ECE1', '#EFC078'),
    'electric': ('#121522', '#283348', '#F8F5EC', '#CDFA55'),
    'violet': ('#291F3D', '#4D365B', '#FAF0E5', '#FFB9AA'),
}
LIGHT_INK = {'paper': 'midnight'}
SIZE_SPREAD = (.85, 1.15)
HIGHLIGHT_COLORS = {'midnight': '#FFD23F', 'paper': '#C2185B', 'wine': '#FFD23F', 'slate': '#FF6B6B',
                    'electric': '#FF5DA2', 'violet': '#FFD23F'}
READING_FLOOR = .075
RISE_COLORS = {'midnight': '#8FC1E3', 'paper': '#2F6F8F', 'wine': '#C6A6E8', 'slate': '#9FD8C8',
               'electric': '#7FD8FF', 'violet': '#9FE3D2'}
FONTS = {'condensed': ['impact.ttf', 'DejaVuSansCondensed-Bold.ttf'],
         'grotesk': ['bahnschrift.ttf', 'DejaVuSans-Bold.ttf'],
         'heavy': ['seguibl.ttf', 'arialbd.ttf', 'DejaVuSans-Bold.ttf']}


from ollama_service import local_json


def rules_plan(data, theme):
    """Explicit offline alternative; never described as AI direction."""
    quiet = theme['name'] in ('solemn', 'romantic')
    palettes = ['midnight', 'slate', 'wine', 'paper'] if quiet else ['electric', 'violet', 'paper']
    return dict(version=1, director='rules', concept='Editorial blocks with measured contrast',
        scenes=[dict(mode=MODES[i % len(MODES)], style=STYLES[(i // 2) % len(STYLES)], palette=palettes[(i // 4) % len(palettes)],
                     font='condensed', align=('left', 'center', 'right')[i % 3],
                     background=('glow', 'diagonal', 'rings')[(i // 4) % 3],
                     emphasis=max(range(len(line['words'])), key=lambda j: len(line['words'][j]['text'])),
                     energy=.35 if quiet else .75) for i, line in enumerate(data)])


def validate_plan(plan, data):
    if not isinstance(plan, dict) or not isinstance(plan.get('scenes'), list) or len(plan['scenes']) != len(data):
        raise ValueError('Art direction must contain exactly one scene per lyric line.')
    for number, (scene, line) in enumerate(zip(plan['scenes'], data), 1):
        if not isinstance(scene, dict):
            raise ValueError('Each art direction scene must be an object.')
        scene.setdefault('style', {'blocks': 'cutout', 'stack': 'swiss', 'marquee': 'outline'}.get(scene.get('mode'), 'poster'))
        for key, options in [('mode', MODES), ('palette', PALETTES), ('font', FONTS),
                             ('style', STYLES),
                             ('align', ('left', 'center', 'right')),
                             ('background', ('glow', 'diagonal', 'rings'))]:
            if scene.get(key) not in options:
                raise ValueError(f'Invalid art direction {key}: {scene.get(key)!r}')
        scene.setdefault('camera', 'hold')
        if scene['camera'] not in CAMERAS:
            raise ValueError(f"Invalid camera move: {scene['camera']!r}")
        emphasis, energy = scene.get('emphasis'), scene.get('energy')
        if type(emphasis) is not int or not 0 <= emphasis < len(line['words']):
            raise ValueError('Art direction emphasis must be a valid zero-based word index.')
        if type(energy) not in (int, float) or not math.isfinite(energy) or not 0 <= energy <= 1:
            raise ValueError(f'Art direction energy must be between zero and one '
                             f'(scene {number}, value {energy!r}).')
    return plan


DIRECTION_RETRY_DELAY = 10.
DIRECTION_ATTEMPTS = ((None, 16384, 12000), (None, 16384, 12000), (12, 8192, 6000))


def direction_schema(count):
    return {'type': 'object', 'properties': {
        'concept': {'type': 'string'},
        'scenes': {'type': 'array', 'minItems': count, 'maxItems': count,
            'items': {'type': 'object', 'properties': {
                'camera': {'type': 'string', 'enum': list(CAMERAS)},
                'mode': {'type': 'string', 'enum': list(MODES)},
                'style': {'type': 'string', 'enum': list(STYLES)},
                'palette': {'type': 'string', 'enum': list(PALETTES)},
                'font': {'type': 'string', 'enum': list(FONTS)},
                'align': {'type': 'string', 'enum': ['left', 'center', 'right']},
                'background': {'type': 'string', 'enum': ['glow', 'diagonal', 'rings']},
                'emphasis': {'type': 'integer', 'minimum': 0},
                'energy': {'type': 'number', 'minimum': 0, 'maximum': 1}},
                'required': ['camera', 'mode', 'style', 'palette', 'font', 'align', 'background', 'emphasis', 'energy'],
                'additionalProperties': False}}},
        'required': ['concept', 'scenes'], 'additionalProperties': False}


def direction_brief(prompt):
    return ('Act as a motion design art director for a polished lyric video. '
            'Return JSON, one scene per input line in the same order. Choose a coherent visual arc, '
            'not random effects. Hold palettes and fonts across related lines; change at section shifts. '
            'Repeat visual motifs for repeated lyrics. Mostly condensed bold text. '
            'Mix distinct visual styles deliberately: poster is huge uppercase condensed type; '
            'swiss is calmer, lighter editorial capitals; neon is glowing letters for night or electric moods; '
            'extrude is bold 3D block letters for impact; split is two-tone letters for contrast and duality; '
            'outline is hollow display lettering '
            'with a solid emphasis word; cutout is colored paper-like word tiles. '
            'Use at least three styles across a full song. Avoid keeping any one treatment throughout. '
            'Use quiet swiss scenes as breathing space between dramatic poster and cutout sections. '
            'Use push for building phrases, drop for impact, zoom for emotional emphasis, '
            'blocks for graphic contrast, marquee sparingly for repetition, stack for quiet holds. '
            'Emphasis is a zero-based index into each line word array. '
            'Energy is a JSON number between 0 and 1 inclusive (for example 0.35), never a percentage. '
            'It controls motion strength; keep solemn songs restrained but visually bold. '
            'Choose camera push-in for emphasis, pull-out for release, pan-left or pan-right for movement, hold for stillness. '
            'Keep camera choices coherent over related lines. '
            'Backgrounds are subtle animated gradients: glow, diagonal or rings. '
            f'Palette colors (background, gradient, ink, accent): {json.dumps(PALETTES)}. '
            'You only have lyrics and word timing, not audio analysis; use phrasing and text meaning. '
            f'User direction: {prompt}')


def request_direction(data, prompt, model, num_ctx, num_predict, chunk=None):
    """One schema-bound plan, optionally requested in consecutive line chunks."""
    from ollama_gpu import gpu_chat
    size = chunk or len(data)
    concept, scenes = None, []
    for first in range(0, len(data), size):
        part = data[first:first+size]
        brief = direction_brief(prompt)
        if chunk:
            brief += f' This request covers lines {first} to {first+len(part)-1} of {len(data)}; keep the arc consistent with a full song.'
        response = gpu_chat('chat', dict(model=model, stream=False, think=False,
            keep_alive=0, format=direction_schema(len(part)), options=dict(temperature=.55, num_ctx=num_ctx, num_predict=num_predict),
            messages=[dict(role='system', content=brief), dict(role='user', content=json.dumps([
                dict(line=first+i, words=[w['text'] for w in line['words']],
                     start=line['words'][0]['start'], end=line['words'][-1]['end'])
                for i, line in enumerate(part)]))]), timeout=900)
        result = json.loads(response['message']['content'])
        if not isinstance(result, dict) or not isinstance(result.get('scenes'), list) or len(result['scenes']) != len(part):
            raise ValueError('Art direction must contain exactly one scene per lyric line.')
        concept = concept or result.get('concept')
        scenes += result['scenes']
    return dict(concept=concept or 'Editorial lyric arc', scenes=scenes)


def bounded_plan(plan, data):
    adjusted = energy_adjusted = 0
    for scene, line in zip(plan['scenes'], data):
        if isinstance(scene, dict) and type(scene.get('emphasis')) is int:
            original = scene['emphasis']
            scene['emphasis'] = max(0, min(len(line['words'])-1, original))
            adjusted += original != scene['emphasis']
        if isinstance(scene, dict):
            energy = scene.get('energy')
            if type(energy) in (int, float) and math.isfinite(energy):
                scene['energy'] = max(0., min(1., energy))
                energy_adjusted += energy != scene['energy']
    if adjusted:
        print(f'Bound {adjusted} AI emphasis selection(s) to their lyric lines.', flush=True)
    if energy_adjusted:
        print(f'Bound {energy_adjusted} AI energy value(s) to the supported 0–1 range.', flush=True)
    return validate_plan(plan, data)


def direct(data, theme, prompt, model='auto', director='ollama'):
    """AI art direction that recovers from runner crashes and bad output without a human."""
    if director == 'rules':
        return rules_plan(data, theme)
    failure = None
    try:
        from gpu_models import resolve_prompt_model
        model = resolve_prompt_model(local_json, model)
    except (urllib.error.URLError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        failure = exc
    if failure is None:
        print(f'AI art direction: {model}; planning {len(data)} scenes locally...', flush=True)
        for attempt, (chunk, num_ctx, num_predict) in enumerate(DIRECTION_ATTEMPTS, 1):
            try:
                plan = bounded_plan(request_direction(data, prompt, model, num_ctx, num_predict, chunk), data)
                plan.update(version=1, director='ollama', model=model)
                return plan
            except (urllib.error.URLError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
                failure = exc
                print(f'Warning: AI art direction attempt {attempt}/{len(DIRECTION_ATTEMPTS)} failed: {exc}', flush=True)
                try:
                    from ollama_gpu import unload_model
                    unload_model(model)
                except (urllib.error.URLError, OSError, ValueError) as cleanup:
                    print(f'Warning: could not unload {model} before retrying: {cleanup}', flush=True)
                if attempt < len(DIRECTION_ATTEMPTS):
                    import time
                    time.sleep(DIRECTION_RETRY_DELAY)
    print(f'Warning: AI art direction unavailable ({failure}); continuing with the offline rules plan so the video can finish.', flush=True)
    plan = rules_plan(data, theme)
    plan.update(director='rules-fallback', fallback_reason=str(failure)[:500])
    return plan


def ease(value):
    value = max(0., min(1., value))
    return 1 - (1 - value) ** 3


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


def rgb(value):
    return tuple(bytes.fromhex(value.lstrip('#')))


def mix(a, b, value):
    return tuple(round(x + (y - x) * value) for x, y in zip(a, b))


def font_at(family, size, custom=None):
    for candidate in ([str(custom)] if custom else FONTS[family]):
        for path in [candidate, str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / candidate)]:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    raise ValueError('No bold font found. Supply --font with a TTF/OTF font.')


class Compositor:
    def __init__(self, data, plan, width, height, duration, custom_font=None,
                 background=None, lead_in=1., illustrations=None, illustration_lines=2,
                 cinematic=False, preserve_art_slots=False, type_effect='none',
                 particle_intensity=1., artwork_mode='cutout', layout_seed=42,
                 particle_speed=1., entrance_effect=None, exit_effect=None, entrance_pool=None, exit_pool=None, text_animation='directed', font_family='auto', font_style='auto', font_scale=1.25, text_pool=None, lettering_styles=None, reading_flow='preview', melody=None, rhythm=None, kinetic=None, effect_speeds=None,
                 effect_intensities=None, instruments=None):
        self.source_cues=[line['words'][0]['start'] for line in data]
        self.focused_words=False
        self.data, self.plan = data, validate_plan(plan, data)
        self.width, self.height, self.duration = width, height, duration
        if not math.isfinite(lead_in) or not 0 <= lead_in <= 5:
            raise ValueError('Lead-in must be finite and between 0 and 5 seconds.')
        self.artwork_mode, self.layout_seed = artwork_mode, layout_seed
        if artwork_mode in ('fullscreen', 'verse'):
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
        self.typography = typography_options(dict(font_family=font_family,font_style=font_style,font_scale=font_scale,text_pool=text_pool,lettering_styles=lettering_styles,reading_flow=reading_flow,kinetic=kinetic,effect_speeds=effect_speeds,effect_intensities=effect_intensities))
        self.word_animations=[[selected_word_animation(text_animation,self.typography['text_pool'],index)]*len(line['words'])
                              for index,line in enumerate(data)]
        self.text_animations=[motions[0] for motions in self.word_animations]
        self.type_effect = type_effect
        self.particle_intensity = float(particle_intensity)
        self.particle_speed = float(particle_speed)
        self.instrument_stage = None
        if instruments:
            from instrument_stage import InstrumentStage
            self.instrument_stage = InstrumentStage(instruments, rhythm, width, height)
        if not math.isfinite(self.particle_intensity) or not 0 <= self.particle_intensity <= 2:
            raise ValueError('Particle intensity must be finite and between 0 and 2.')
        if not math.isfinite(self.particle_speed) or not .2 <= self.particle_speed <= 3:
            raise ValueError('Particle speed must be finite and between 0.2 and 3.')
        self.effect_catalog = discover_effects()
        self.effect_cache = {}
        entrance_pool = parse_pool(entrance_pool, 'entrance', self.effect_catalog, strict=False)
        if self.typography['reading_flow'] == 'realtime' and self.typography['kinetic']['camera'] == 'pan':
            exit_effect, exit_pool = 'none', None
        exit_pool = parse_pool(exit_pool, 'exit', self.effect_catalog, strict=False)
        self.word_effect_pairs=[]
        total=0
        planned=plan.get('word_effects') if text_animation=='ai' else None
        line_effects=plan.get('line_effects') if entrance_effect=='ai' else None
        if line_effects is not None and (len(line_effects)!=len(data) or any(e not in self.effect_catalog['entrance'] and e!='none' for e in line_effects)):
            line_effects=None
        if entrance_effect=='ai':
            entrance_effect='mixed'
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
                                    resolve_effect(exit_effect,'exit',self.effect_catalog,total+j,type_effect,exit_pool)))
            self.word_effect_pairs.append(effects)
            total+=len(line['words'])
        self.text_animations=[motions[0] for motions in self.word_animations]
        self.effect_pairs=[(next((a for a,b in effects if a!='none'),'none'),
                            next((b for a,b in effects if b!='none'),'none')) for effects in self.word_effect_pairs]
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
        reading_ends=[line['words'][-1]['end']+READING_HOLD for line in data] if self.focused_words else self.effect_end_times
        self.line_lanes,self.lane_count = reading_lanes(visible_starts,reading_ends)
        self.reading_band = self.lane_count > 1
        self.custom_font = custom_font or selected_font(font_family,font_style)
        from realtime_typography import RealtimeTypography
        self.realtime = (RealtimeTypography(self, melody, particle_speed, rhythm, self.typography['kinetic'])
                         if self.typography['reading_flow'] == 'realtime' else None)
        if self.typography['reading_flow'] == 'stage':
            from stage_3d import Stage3D
            self.realtime = Stage3D(self, melody, rhythm)
        elif self.typography['reading_flow'] == 'mixed':
            from scene_mix import SceneMix
            self.realtime = SceneMix(self, melody, particle_speed, rhythm, self.typography['kinetic'], self.plan.get('scene_flows'))
        self.cache_index, self.layout = None, None
        self.photo = (ImageOps.fit(Image.open(background).convert('RGB'), (width, height))
                      if background else None)
        self.backgrounds = {}
        self.illustration_lines = illustration_lines
        if type(illustration_lines) is not int or illustration_lines < 1:
            raise ValueError('Illustration line count must be a positive integer.')
        self.art = []
        self.illustration_paths = [Path(p) for p in (illustrations or [])]
        self.artwork_revisions = {}
        self.text_box = (0, 0, width, height)
        if illustrations:
            initial = illustration_layout(0, width, height, cinematic, artwork_mode, layout_seed)
            self.art_box, self.text_box = initial['art_box'], initial['text_box']
            seen = set()
            for slot, path in enumerate(illustrations):
                source_bytes = Path(path).read_bytes()
                fingerprint = hashlib.sha256(source_bytes).digest()
                self.artwork_revisions[str(slot)] = fingerprint.hex()
                if fingerprint in seen and not preserve_art_slots:
                    continue
                seen.add(fingerprint)
                with Image.open(BytesIO(source_bytes)) as source:
                    image = source.convert('RGBA')
                    if artwork_mode in ('fullscreen', 'verse'):
                        self.art.append(ImageOps.fit(image, (width,height), Image.Resampling.LANCZOS))
                        continue
                    bounds = image.getchannel('A').getbbox()
                    if not bounds:
                        raise ValueError(f'Illustration is fully transparent: {path}')
                    image = image.crop(bounds)
                    box = illustration_layout(len(self.art), width, height, cinematic, artwork_mode, layout_seed)['art_box']
                    size = tuple(max(1, round(v*.94)) for v in box[2:]) if cinematic else box[2:]
                    self.art.append(ImageOps.contain(image, size, Image.Resampling.LANCZOS))
        self.default_text_box = self.text_box
        art_cues=[max(0.,cue-self.lead_in) for cue in self.source_cues]
        self.art_starts = [art_cues[i*self.illustration_lines]
                           for i in range(min(len(self.art), math.ceil(len(art_cues)/self.illustration_lines)))]
        if illustrations:
            record=Path(illustrations[0]).parent/'illustrations.json'
            if record.is_file():
                metadata=json.loads(record.read_text(encoding='utf-8'))
                groups=metadata.get('line_groups')
                if groups is not None:
                    from song_structure import valid_line_groups
                    if not valid_line_groups(groups,len(self.source_cues)) or len(groups)!=len(self.art):
                        raise ValueError('Illustration line groups do not match the aligned lyrics')
                    self.art_starts=[self.source_cues[group[0]] for group in groups]


        base_boxes=[]
        for cue in self.cues:
            artwork=max(0,bisect.bisect_right(self.art_starts,cue)-1) if self.art_starts else None
            base_boxes.append(self.composition(artwork)[1] if artwork is not None else self.default_text_box)
        self.line_regions=reading_regions(self.starts,self.effect_end_times,base_boxes)
        if not line_effects:
            self.keep_effects_readable(entrance_effect, entrance_pool)

    def effect_speed(self, effect_id):
        """An effect's own particle speed from the profile, or the global speed."""
        return self.typography['effect_speeds'].get(effect_id, self.particle_speed)

    def effect_intensity(self, effect_id):
        """An effect's own letter-effect intensity from the profile, or the global intensity."""
        return self.typography['effect_intensities'].get(getattr(effect_id, 'id', effect_id), self.particle_intensity)

    def line_background(self, index, box=None):
        """Average colour behind a line's reading area: its artwork, or the scene's backdrop colour."""
        x, y, w, h = box or self.line_box(index)
        if self.art and self.artwork_mode in ('fullscreen', 'verse'):
            artwork = max(0, bisect.bisect_right(self.art_starts, self.cues[index])-1) if self.art_starts else 0
            region = self.art[min(artwork, len(self.art)-1)].convert('RGB').crop((max(0, x), max(0, y), max(1, x+w), max(1, y+h)))
            pixels = list(region.resize((8, 8)).getdata())
            return tuple(round(sum(p[i] for p in pixels)/len(pixels)) for i in range(3))
        return rgb(PALETTES[self.plan['scenes'][index]['palette']][0])

    def keep_effects_readable(self, entrance_effect, entrance_pool):
        """Mixed entrances never pair lettering with a background of the same colour."""
        if entrance_effect != 'mixed' or self.particle_intensity <= 0:
            return
        from effect_colors import readable_effect
        candidates = [e for e in (entrance_pool or list(self.effect_catalog['entrance'])) if e in self.effect_catalog['entrance']]
        if self.realtime is not None:
            from effect_director import dominant_colors, line_backdrops
            backdrops = [dominant_colors(image) for image in line_backdrops(self)]
        else:
            backdrops = [[(self.line_background(index), 1.)] for index in range(len(self.effect_pairs))]
        for index, (entrance, exit_effect) in enumerate(self.effect_pairs):
            if entrance not in self.effect_catalog['entrance']:
                continue
            ink = rgb(PALETTES[self.plan['scenes'][index]['palette']][2])
            neighbours = {self.effect_pairs[i][0] for i in (index-1, index+1) if 0 <= i < len(self.effect_pairs)}
            chosen = readable_effect(entrance, candidates, ink, backdrops[index], neighbours)
            if chosen != entrance:
                self.effect_pairs[index] = (chosen, exit_effect)
                self.word_effect_pairs[index] = [(chosen if a == entrance else a, b) for a, b in self.word_effect_pairs[index]]

    def composition(self, artwork):
        """A stable reading area for each drawing; change only with new art."""
        layout = illustration_layout(artwork, self.width, self.height, self.cinematic, self.artwork_mode, self.layout_seed)
        return layout['art_box'], layout['text_box']

    def illustration(self, frame, index, t):
        if self.artwork_mode in ('fullscreen', 'verse'):
            return
        if not self.art_starts or t < self.art_starts[0] or t >= self.duration:
            return
        current = bisect.bisect_right(self.art_starts, t)-1
        progress = ease((t-self.art_starts[current])/.9)
        def draw_art(number, opacity):
            (x, y, w, h), _ = self.composition(number)
            image = self.art[number]
            result = Image.new('RGBA', (w, h))
            if self.cinematic:
                shadow = Image.new('RGBA', image.size, (0, 0, 0, 0))
                shadow.putalpha(image.getchannel('A').point(lambda a: round(a*.22)))
                result.alpha_composite(shadow, ((w-image.width)//2+round(w*.018), (h-image.height)//2+round(h*.018)))
            result.alpha_composite(image, ((w-image.width)//2, (h-image.height)//2))
            result.putalpha(result.getchannel('A').point(lambda a: round(a*opacity)))
            frame.paste(result, (x, y), result)
        opacity = min(1., max(0., (self.duration-t)/.45))
        if current > 0 and progress < 1:
            draw_art(current-1, (1-progress)*opacity)
        draw_art(current, progress*opacity)

    def art_crossing(self, current):
        if current <= 0:
            return 0.
        gap = (self.art_starts[current+1]-self.art_starts[current]
               if current+1 < len(self.art_starts) else self.art_starts[current]-self.art_starts[current-1])
        return min(20., max(1., gap*.9))

    def background(self, index, t, veil=True):
        scene = self.plan['scenes'][max(0, index)]
        if self.artwork_mode in ('fullscreen', 'verse') and self.art_starts:
            current = max(0, bisect.bisect_right(self.art_starts,t)-1)
            frame = self.art[current].convert('RGB')
            if current > 0:
                blend = min(1., max(0., (t-self.art_starts[current])/self.art_crossing(current)))
                if blend < 1:
                    previous = self.art[current-1].convert('RGB')
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
            ink=rgb(PALETTES[scene['palette']][2])
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

    def _paint_early_entrances(self,frame,t):
        for index,arrival in enumerate(self.arrivals):
            if arrival is None or not arrival.start <= t < self.starts[index]:
                continue
            if index not in self._arrival_compositors:
                entrance,_ = self.effect_pairs[index]
                child = Compositor([self.data[index]],dict(self.plan,scenes=[self.plan['scenes'][index]],word_layouts=[self.plan['word_layouts'][index]] if self.plan.get('word_layouts') else None),
                    self.width,self.height,self.duration,custom_font=self.custom_font,cinematic=self.cinematic,
                    particle_intensity=self.particle_intensity,particle_speed=self.particle_speed,
                    entrance_effect=entrance,exit_effect='none',text_animation=self.text_animations[index],**self.typography)
                child.arrivals = [arrival]
                child.word_effect_pairs=[self.word_effect_pairs[index]]
                child.word_animations=[self.word_animations[index]]
                child.text_animations=[self.text_animations[index]]
                child.starts = [arrival.start]
                child.ends = [self.effect_end_times[index]]
                child.line_lanes,child.lane_count = [0],1
                child.reading_band = self.reading_band
                child.default_text_box = self.line_box(index)
                child.line_regions = [self.line_box(index)]
                child._reading_size = self.reading_size()
                self._arrival_compositors[index] = child
            layer = self._arrival_compositors[index].frame(t,text_only=True)
            frame.paste(layer,(0,0),layer)

    def rises_into_place(self, index, position, particle_entry):
        """Words that slide up from below during the staggered entrance."""
        motion = self.word_animations[index][position]
        if particle_entry or self.plan.get('word_layouts') or motion in ('fade', 'none'):
            return False
        if motion == 'slide':
            return SLIDE_DIRECTIONS[position % len(SLIDE_DIRECTIONS)][1] > 0
        return self.plan['scenes'][index]['mode'] == 'stack'

    def word_arrival(self, index, position, count, t):
        """Stagger words inside the line's arrival window; the last one still lands before the vocal."""
        arrival = self.arrivals[index]
        if arrival.finish <= arrival.start:
            return 1. if t >= arrival.start else 0.
        raw = max(0., min(1., (t-arrival.start)/(arrival.finish-arrival.start)))
        step = min(.16, .55/max(1, count-1)) if count > 1 else 0.
        return max(0., min(1., (raw-step*position)/max(.2, 1-step*(count-1))))

    def growth_extent(self, index, family, word):
        """How far grown lettering reaches above and below a word, as fractions of the font size."""
        effect = self.effect_catalog['entrance'].get(self.effect_pairs[index][0])
        if effect is None or effect.trajectory != 'grow' or self.effect_intensity(effect) <= 0:
            return 0., 0.
        extents = self.__dict__.setdefault('_growth_extents', {})
        key = (effect.id, family, self.effect_intensity(effect))
        if key not in extents:
            if effect.family == 'petals':
                from botanical_growth import grown_sprite
            else:
                from material_growth import grown_sprite
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

    def prepare(self, index):
        scene, line = self.plan['scenes'][index], self.data[index]
        text_animation = self.text_animations[index]
        self.text_box = self.line_box(index)
        _, _, w, h = self.text_box
        particle_entry = self.effect_pairs[index][0] in self.effect_catalog['entrance'] and self.effect_intensity(self.effect_pairs[index][0])>0
        if self.plan.get('word_layouts'):
            from free_typography import build_layout
            scene_colors=dict(scene,colors=PALETTES[scene['palette']][2:])
            botanical=self.effect_catalog['entrance'].get(self.effect_pairs[index][0]) is not None and self.effect_catalog['entrance'][self.effect_pairs[index][0]].family=='petals'
            self.layout=build_layout(line,self.plan['word_layouts'][index],scene_colors,w,h,
                lambda size:font_at(scene['font'],size,self.custom_font),self.typography['font_scale'],botanical)
            self.cache_index=index;self.effect_cache.clear()
            return
        fit = self.fit_line(index, w, h)
        base = self.reading_size()
        if fit['size'] > base*SIZE_SPREAD[1]:
            fit = self.fit_line(index, w, h, start=round(base*SIZE_SPREAD[1]))
        elif fit['size'] < base*SIZE_SPREAD[0]:
            x0, y0, _, _ = self.text_box
            w2, h2 = min(self.width*.94, max(w, w*base/max(1, fit['size']))), min(self.height*.9, max(h, h*1.15))
            x2 = round(min(max(0, x0+w/2-w2/2), self.width-w2)); y2 = round(min(max(0, y0+h/2-h2/2), self.height-h2))
            self.text_box = (x2, y2, round(w2), round(h2))
            _, _, w, h = self.text_box
            fit = self.fit_line(index, w, h, floor=round(base*SIZE_SPREAD[0]))
        style, family, size, rows, font, gap, pitch, above = (fit[key] for key in ('style', 'family', 'size', 'rows', 'font', 'gap', 'pitch', 'above'))
        def display(word):
            return word.upper()
        top = (h - len(rows)*pitch) / 2 + size*above
        center = (self.text_box[0]+w/2)/self.width
        align = 'left' if center < 1/3 else 'right' if center > 2/3 else 'center'
        ink, accent = PALETTES[scene['palette']][2:]
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
                    sprite = sprite.rotate((-1 if i % 2 else 1)*1.1,
                                           resample=Image.Resampling.BICUBIC, expand=False)
                    if backdrop is not None:
                        backdrop = backdrop.rotate((-1 if i % 2 else 1)*1.1, resample=Image.Resampling.BICUBIC, expand=False)
                boundaries = [0]+[max(0,min(sprite.width,round(pad+font.getlength(label[:k])))) for k in range(1,len(label))]+[sprite.width]
                words.append(dict(index=i, row=r, x=x-pad, y=top+r*pitch,
                                  glyph_spans=list(zip(boundaries,boundaries[1:])),
                                  sprite=sprite, glyph_mask=glyph_mask, boxed=boxed, start=word['start'], length=length,
                                  backdrop=(rgb(fill), rgb(ink if fill == accent else accent), backdrop) if backdrop is not None else None))
                x += length + gap
        self.layout = dict(words=words, size=size, gap=gap)
        self.cache_index = index
        self.effect_cache.clear()

    def _paint_exit_tails(self, frame, index, t):
        active = [previous for previous in range(index)
                  if self.ends[previous] <= t < self.effect_end_times[previous]]
        self._tail_compositors = {key:value for key,value in self._tail_compositors.items() if key in active}
        for previous in active:
            if previous not in self._tail_compositors:
                entrance, exit_effect = self.effect_pairs[previous]
                child_plan = dict(self.plan, scenes=[dict(self.plan['scenes'][previous])],word_layouts=[self.plan['word_layouts'][previous]] if self.plan.get('word_layouts') else None)
                child = Compositor([self.data[previous]], child_plan, self.width, self.height,
                    self.duration, custom_font=self.custom_font, lead_in=0., cinematic=self.cinematic,
                    type_effect='none', particle_intensity=self.particle_intensity,
                    particle_speed=self.particle_speed, entrance_effect=entrance, exit_effect=exit_effect,
                    text_animation=self.text_animations[previous],**self.typography)
                child.arrivals = [self.arrivals[previous]]
                child.word_effect_pairs=[self.word_effect_pairs[previous]]
                child.word_animations=[self.word_animations[previous]]
                child.text_animations=[self.text_animations[previous]]
                child.line_lanes,child.lane_count = [0],1
                child.reading_band = self.reading_band
                child.default_text_box = self.line_box(previous)
                child.line_regions = [self.line_box(previous)]
                child._reading_size = self.reading_size()
                child.ends = [self.effect_end_times[previous]]
                self._tail_compositors[previous] = child
            tail = self._tail_compositors[previous].frame(t, text_only=True)
            frame.paste(tail,(0,0),tail)

    def frame(self, t, *, text_only=False):
        image = self._frame(t, text_only=text_only)
        if self.instrument_stage is not None and not text_only:
            image = self.instrument_stage.paint(image, t)
        return image

    def _frame(self, t, *, text_only=False):
        if self.realtime is not None and not text_only:
            return self.realtime.frame(t)
        index = bisect.bisect_right(self.starts, t) - 1
        frame = Image.new('RGBA',(self.width,self.height)) if text_only else self.background(index,t)
        if index < 0 or t >= self.ends[index]:
            if not text_only:
                self.illustration(frame,index,t)
                self._paint_exit_tails(frame,index,t)
                self._paint_early_entrances(frame,t)
            return frame
        if self.cache_index != index:
            self.prepare(index)
        scene = self.plan['scenes'][index]
        tx, ty, w, h = self.text_box
        energy, mode = scene['energy'], scene['mode']
        entrance, exit_effect = self.effect_pairs[index]
        text_animation = self.text_animations[index]
        full_screen = entrance != 'none' or exit_effect != 'none'
        if full_screen:
            mode = 'letters'
        if text_animation == 'slide':
            mode = 'slide'
        elif text_animation in ('fade','none','highlight','karaoke'):
            mode = 'letters'
        fade_end = self.effect_end_times[index] if exit_effect != 'none' and self.effect_intensity(exit_effect) > 0 else self.ends[index]
        exit_start = self.exit_starts[index]
        fade_end-exit_start
        line_fade=min(1.,max(0.,(self.effect_end_times[index]-t)/self.exit_lengths[index]))
        fade=line_fade
        line_entrance,line_exit=self.effect_pairs[index]
        camera = 1.
        if mode == 'zoom':
            camera = 1. + (.12 + energy*.10) * (1-word_progress(t, self.cues[index], self.starts[index], self.lead_in))


        if not text_only:
            self.illustration(frame,index,t)
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
        ease((t - self.starts[index]) / .18)
        for item in self.layout['words']:
            word = self.data[index]['words'][item['index']]
            entrance,exit_effect=line_entrance,'none'
            text_animation=self.word_animations[index][item['index']]
            particle_in = entrance in self.effect_catalog['entrance'] and self.effect_intensity(entrance) > 0
            mode = 'letters' if particle_in or self.plan.get('word_layouts') else scene['mode']
            if text_animation == 'slide':mode = 'slide'
            elif text_animation in ('fade','none'):mode = 'letters'
            if particle_in:
                progress = self.arrivals[index].progress(t)
            else:
                progress = self.word_arrival(index, item['index'], len(self.layout['words']), t)
            if text_animation == 'none' and not particle_in:progress = 1. if t >= self.arrivals[index].start else 0.
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
            sprite = item['sprite']
            overlay = None
            box_fraction = 0.
            if text_animation in ('highlight','karaoke') and progress >= 1:
                fraction = 1. if text_animation == 'highlight' and word['start']<=t<word['end'] else 0.
                if text_animation == 'karaoke':
                    fraction = max(0., min(1., (t-word['start']) / max(.001, word['end']-word['start'])))
                if self.plan.get('word_layouts') and t>=word['end']:fraction=0.
                highlight_color = item.get('highlight_color',rgb(PALETTES[scene['palette']][0] if item['boxed'] else HIGHLIGHT_COLORS.get(scene['palette'],PALETTES[scene['palette']][3])))
                held = self.effect_catalog['entrance'].get(entrance)
                if item.get('backdrop'):
                    box_fraction = fraction
                elif held is not None and self.effect_intensity(held) > 0 and (held.trajectory == 'grow' or getattr(held, 'hold', 'solid') == 'particles'):
                    overlay = highlight_overlay(sprite.size, highlight_color, fraction, item['glyph_mask'])
                else:
                    sprite = highlight_word(sprite,highlight_color,fraction,glyph_mask=item['glyph_mask'])
            if abs(scale-1) > .005:
                sprite = sprite.resize((max(1, round(sprite.width*scale)), max(1, round(sprite.height*scale))), Image.Resampling.BICUBIC)
                if overlay is not None:
                    overlay = overlay.resize(sprite.size, Image.Resampling.BICUBIC)
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
            paint_word(text_layer, sprite, x+tx if full_screen else x, y+ty if full_screen else y, progress, 1., t-self.arrivals[index].start, item['index'], 'none', energy, spans, intensity=self.effect_intensity(entrance), speed=self.effect_speed(entrance),
                       entrance_effect=entrance, exit_effect=exit_effect, effect_catalog=self.effect_catalog, cache=self.effect_cache)
            if overlay is not None:
                text_layer.alpha_composite(overlay, (round(x+tx if full_screen else x), round(y+ty if full_screen else y)))
        if mode == 'marquee':
            font = font_at(scene['font'], max(10, round(h*.065)), self.custom_font)
            text = '  /  ' * 24
            span = max(1, math.ceil(font.getlength(text)))
            offset = -((t-self.starts[index]) * w * (.025+energy*.035)) % span - span
            draw = ImageDraw.Draw(text_layer)
            ink = rgb(PALETTES[scene['palette']][2])
            for k in range(math.ceil(w/span)+2):
                draw.text((offset+k*span, h*.88), text, font=font, fill=(*ink, round(70*fade)))
        if camera != 1:
            enlarged = text_layer.resize((round(w*camera), round(h*camera)), Image.Resampling.BICUBIC)
            text_layer = ImageOps.fit(enlarged, (w, h), centering=(.5, .5))
        if line_fade<1.:
            if line_exit in self.effect_catalog['exit'] and self.effect_intensity(line_exit)>0:
                from particle_motion import paint_transition
                bounds=text_layer.getchannel('A').getbbox()
                exiting=Image.new('RGBA',text_layer.size)
                if bounds:
                    paint_transition(exiting,text_layer.crop(bounds),bounds[0],bounds[1],'exit',1-line_fade,
                        self.effect_catalog['exit'][line_exit],index,self.effect_intensity(line_exit),energy,self.effect_cache)
                text_layer=exiting
            else:
                text_layer.putalpha(text_layer.getchannel('A').point(lambda a:round(a*line_fade)))
        overlay_frame = frame.convert('RGBA')
        overlay_frame.alpha_composite(text_layer, (0, 0) if full_screen else (tx, ty))
        frame = overlay_frame if text_only else overlay_frame.convert('RGB')
        return frame


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
        from kinetic_particles_3d import close_particle_renderer
        close_particle_renderer()
        from stage_3d import close_stage
        close_stage()


def tighten_line_starts(data):
    """Aligners stretch a line's first word back over the silence before it. Start it near its sung length.

    The song's own seconds-per-character rate (from non-initial words) bounds the first word; ends never move.
    Applying it twice changes nothing.
    """
    from statistics import median
    import string
    rates = [(w['end']-w['start'])/max(1, len(w['text'].strip())) for line in data for w in line['words'][1:] if w['end'] > w['start']]
    if not rates:
        return data
    rate = median(rates)
    for line in data:
        word = line['words'][0]
        if word.get('onset'):
            continue
        limit = max(.35, rate*len(word['text'].strip(string.punctuation+' '))*1.6)
        if word['end']-word['start'] > limit:
            word['start'] = round(word['end']-limit, 3)
    return data


def render_compositor(data,plan,duration,args):
    return Compositor(
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
        instruments=getattr(args, 'instrument_pictures', None), **typography_options(vars(args)))


def _render_video(audio, output, data, plan, duration, args):
    import tempfile
    compositor = render_compositor(data,plan,duration,args)
    if getattr(args, 'entrance_effect', None) == 'ai' and compositor.particle_intensity > 0:
        from effect_director import ensure_line_effects
        emit('direction', 0, message='AI choosing effects for each line')
        plan = ensure_line_effects(data, plan, compositor, vars(args), Path(output).parent)
        compositor = render_compositor(data,plan,duration,args)
    if compositor.typography['reading_flow'] == 'mixed':
        from scene_mix import ensure_scenes
        emit('direction', 0, message='AI choosing a scene effect for each song section')
        plan = ensure_scenes(data, plan, vars(args), Path(output).parent)
        compositor = render_compositor(data,plan,duration,args)
    pictures = getattr(args, 'stage_pictures', 'ai-painted')
    has_stage = compositor.typography['reading_flow'] == 'stage' or getattr(compositor.realtime, 'stage', None) is not None
    if has_stage and pictures != 'keywords':
        if pictures == 'off':
            plan = dict(plan, ornaments=[], pictures='off')
        else:
            from ornament_director import ensure_ornaments
            emit('direction', 0, message='AI choosing the small animated pictures for each block')
            plan = ensure_ornaments(data, plan, compositor, dict(vars(args), ornament_images=pictures == 'ai-painted'), Path(output).parent)
        compositor = render_compositor(data,plan,duration,args)
    if getattr(args, 'instruments_found', None) and getattr(args, 'instruments', 'auto') != 'off':
        from instrument_stage import instrument_pictures
        emit('direction', 0, message='Painting the instruments heard in the song')
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
                   '-framerate', str(args.fps), '-i', 'pipe:0', '-ss', str(start), '-i', str(audio),
                   '-map', '0:v:0', '-map', '1:a:0', '-t', str(span), *encoding,
                   '-force_key_frames', 'expr:gte(t,n_forced*1)',
                   *(BT709_OUTPUT if getattr(args, 'color', 'bt709') == 'bt709' else []),
                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(target)]
        emit('render', 0, message='Compositing frames and encoding video')
        print(f'Rendering {"cinematic" if compositor.cinematic else "editorial"} typography with {args.encoder}...', flush=True)
        with (Path(temp)/'ffmpeg.log').open('w+b') as log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
            try:
                count = math.ceil(span*args.fps)
                from parallel_render import frame_batches,worker_count
                from generation_queue import has_pending,ReplacementsPending
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
                    log.seek(0)
                    raise ValueError('FFmpeg: ' + log.read().decode(errors='replace'))
            except BrokenPipeError as exc:
                process.wait()
                log.seek(0)
                raise ValueError('FFmpeg: ' + log.read().decode(errors='replace')) from exc
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if process.stdin and not process.stdin.closed:
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
        if output.name=='video.mp4' and output.exists():
            from video_versions import archive_video
            archive_video(output)
        target.replace(output)
        from video_versions import write_render_metadata
        write_render_metadata(output, compositor.artwork_revisions, start, end)
        emit('render', 1, message='Video encoding complete')
