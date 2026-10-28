"""Animated instruments that play along with their own separated stems.

Each instrument the analysis confidently heard (see instrument_analysis.py) gets a painted picture and
appears near a lower corner only while it plays, fading in and out at the edges of its stretches. Its
motion comes from its stem: a drum squashes as procedural sticks strike it on every hit, a trombone
slides back and forth with the pitch, guitars and basses rock and their strings shiver on each pluck,
keys bob, wind instruments tilt with the melody and bowed strings sway under a moving bow. Every pose is
a pure function of time, so parallel render workers agree exactly.
"""
import bisect
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FADE = .7
SUBJECTS = {
    'drum kit': 'snare drum with two crossed drumsticks resting on it, seen slightly from above',
    'bass guitar': 'electric bass guitar lying diagonally, the whole instrument',
    'double bass': 'upright double bass, the whole instrument',
    'electric guitar': 'electric guitar lying diagonally, the whole instrument',
    'acoustic guitar': 'acoustic guitar lying diagonally, the whole instrument',
    'ukulele': 'ukulele, the whole instrument',
    'piano': 'small upright piano seen from the front',
    'organ': 'small church organ with pipes',
    'synthesizer': 'keyboard synthesizer seen from above at an angle',
    'trombone': 'brass trombone seen from the side, slide pointing left',
    'trumpet': 'brass trumpet seen from the side, bell pointing right',
    'saxophone': 'golden saxophone seen from the side',
    'flute': 'silver flute lying diagonally',
    'clarinet': 'black clarinet lying diagonally',
    'harmonica': 'harmonica seen from the front at an angle',
    'accordion': 'accordion, slightly opened',
    'violin': 'violin with its bow, seen from the front at an angle',
    'cello': 'cello, the whole instrument, seen from the front',
    'harp': 'golden concert harp',
}


def instrument_pictures(instruments, folder, options):
    """Paint a picture for each instrument (cached); instruments without one are dropped."""
    if not instruments:
        return []
    from ornament_director import icon_prompt, paint_icons
    prompts = [icon_prompt(SUBJECTS.get(item['name'], item['name']), '', options.get('style_prompt', '')) for item in instruments]
    paths = paint_icons(prompts, [item['name'] for item in instruments], folder, options, kind='video.instruments')
    return [dict(item, image=str(path)) for item, path in zip(instruments, paths) if path is not None]


def _smooth(value):
    value = max(0., min(1., value))
    return value*value*(3-2*value)


class InstrumentStage:
    def __init__(self, instruments, rhythm, width, height):
        from glyph_art import cutout
        self.width, self.height = width, height
        self.size = round(height*.24)
        self.items = []
        for slot, item in enumerate(instruments[:3]):
            picture = cutout(item['image']).copy()
            picture.thumbnail((self.size, self.size), Image.Resampling.LANCZOS)
            hits = sorted((rhythm or {}).get(item['stem']) or [])
            pitch = item.get('pitch')
            voiced = [p for p in pitch or [] if p is not None]
            low, high = (np.percentile(voiced, 10), np.percentile(voiced, 90)) if len(voiced) > 10 else (0., 1.)
            anchor = ((.11, .84), (.89, .84), (.89, .2))[slot]
            self.items.append(dict(item, picture=picture, hits=hits, hit_times=[h[0] for h in hits], low=low,
                                   high=max(low+1, high), anchor=anchor, flip=slot == 1))

    def presence(self, item, t):
        best = 0.
        for start, end in item['spans']:
            best = max(best, _smooth((t-start)/FADE)*_smooth((end-t)/FADE))
        return best

    def level(self, item, t):
        values = item.get('level') or []
        index = int(t/.05)
        return values[index] if 0 <= index < len(values) else 0.

    def pitch(self, item, t):
        """The most recent voiced pitch (normalised 0..1 over the instrument's range), smoothed over a moment."""
        values = item.get('pitch') or []
        index = min(len(values)-1, int(t/.05))
        total = weight = 0.
        for k in range(max(0, index-6), index+1):
            if values[k] is not None:
                w = 1+k-index+6
                total += values[k]*w
                weight += w
        if not weight:
            return .5
        return max(0., min(1., (total/weight-item['low'])/(item['high']-item['low'])))

    def hit(self, item, t):
        """Decaying envelope of recent hits, and the index and age of the latest one."""
        times = item['hit_times']
        last = bisect.bisect_right(times, t)-1
        envelope = 0.
        for k in range(max(0, last-6), last+1):
            age = t-times[k]
            envelope += item['hits'][k][1]*math.exp(-age/.12)
        return min(1.5, envelope), last, (t-times[last] if last >= 0 else 9.)

    def pose(self, item, t):
        motion = item['motion']
        level = self.level(item, t)
        envelope, last, age = self.hit(item, t)
        pose = dict(dx=0., dy=0., angle=0., sx=1., sy=1., extra=None)
        s = self.size
        if motion == 'drum':
            pose.update(sy=1-.07*envelope, sx=1+.035*envelope, dy=.02*s*envelope, extra=('sticks', last, age))
        elif motion == 'slide':
            p = self.pitch(item, t)
            pose.update(dx=(.5-p)*.28*s, angle=-4*(p-.5)+2*envelope, sx=1+.03*envelope)
        elif motion == 'blow':
            p = self.pitch(item, t)
            pose.update(angle=10*(p-.5)+2*math.sin(t*1.6)*level, sx=1+.04*envelope, sy=1+.04*envelope)
        elif motion in ('strum', 'pluck'):
            pose.update(angle=-5*envelope+1.5*math.sin(t*1.3), dx=math.sin(t*95)*.012*s*min(1., envelope+level*.3))
        elif motion == 'keys':
            pose.update(dy=.035*s*envelope, sy=1-.04*envelope)
        elif motion == 'bow':
            pose.update(angle=4*math.sin(t*2.1)*level, extra=('bow', level, t))
        return pose, envelope

    def paint(self, frame, t):
        layer = None
        for item in self.items:
            present = self.presence(item, t)
            if present <= .01:
                continue
            layer = layer or Image.new('RGBA', frame.size)
            pose, envelope = self.pose(item, t)
            picture = item['picture']
            if item['flip']:
                picture = picture.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            w = max(2, round(picture.width*pose['sx']))
            h = max(2, round(picture.height*pose['sy']))
            sprite = picture.resize((w, h), Image.Resampling.BICUBIC).rotate(pose['angle'], Image.Resampling.BICUBIC, expand=True)
            cx = item['anchor'][0]*self.width+pose['dx']
            cy = item['anchor'][1]*self.height+pose['dy']
            glow = Image.new('RGBA', (sprite.width+40, sprite.height+40))
            ImageDraw.Draw(glow).ellipse((20, sprite.height*.55+20, sprite.width+20, sprite.height+30),
                                         fill=(0, 0, 0, round(90*present)))
            glow = glow.filter(ImageFilter.GaussianBlur(9))
            layer.alpha_composite(glow, (round(cx-glow.width/2), round(cy-glow.height/2)))
            if envelope > .05:
                halo = Image.new('RGBA', sprite.size)
                ImageDraw.Draw(halo).ellipse((0, 0, sprite.width, sprite.height), fill=(255, 220, 160, round(70*min(1, envelope)*present)))
                layer.alpha_composite(halo.filter(ImageFilter.GaussianBlur(sprite.width/6)),
                                      (round(cx-sprite.width/2), round(cy-sprite.height/2)))
            faded = sprite.copy()
            faded.putalpha(sprite.getchannel('A').point(lambda a, k=present: round(a*k)))
            layer.alpha_composite(faded, (round(cx-sprite.width/2), round(cy-sprite.height/2)))
            if pose['extra']:
                self.paint_extra(layer, pose['extra'], cx, cy, picture.size, present)
        if layer is not None:
            frame = frame.convert('RGBA')
            frame.alpha_composite(layer)
        return frame

    def paint_extra(self, layer, extra, cx, cy, size, present):
        draw = ImageDraw.Draw(layer)
        w, h = size
        alpha = round(255*present)
        if extra[0] == 'sticks':
            _, last, age = extra
            for side in (-1, 1):  # the sticks alternate: each hit is struck by the other hand
                striking = last >= 0 and (last % 2 == (0 if side < 0 else 1))
                swing = math.exp(-age/.07) if striking else 0.
                pivot = (cx+side*w*.55, cy-h*.5)
                raised = (cx+side*w*.28, cy-h*.82)
                struck = (cx+side*w*.1, cy-h*.18)
                tip = (raised[0]+(struck[0]-raised[0])*swing, raised[1]+(struck[1]-raised[1])*swing)
                draw.line((pivot, tip), fill=(120, 74, 40, alpha), width=max(3, round(w*.045)))
                draw.line(((pivot[0]-1, pivot[1]-1), (tip[0]-1, tip[1]-1)), fill=(210, 160, 100, alpha), width=max(1, round(w*.015)))
                r = max(2, w*.03)
                draw.ellipse((tip[0]-r, tip[1]-r, tip[0]+r, tip[1]+r), fill=(236, 214, 170, alpha))
        elif extra[0] == 'bow':
            _, level, t = extra
            reach = w*.3*math.sin(t*2.4)*(.3+.7*level)  # the bow travels back and forth while it plays
            y = cy+h*.1
            draw.line((cx-w*.45+reach, y-h*.12, cx+w*.45+reach, y+h*.05), fill=(90, 60, 36, alpha), width=max(2, round(w*.02)))
            draw.line((cx-w*.45+reach, y-h*.14, cx+w*.45+reach, y+h*.03), fill=(236, 230, 210, round(alpha*.8)), width=1)
