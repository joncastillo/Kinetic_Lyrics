"""Drum-pulsed spotlights and occasional lyric-shaped accents for choruses."""

import bisect
import math
import random
import re

from PIL import Image, ImageDraw, ImageFilter

from audio.rhythm import pulse
from direction.song_structure import sections_for


COLORS = ((255, 210, 84), (69, 208, 255), (255, 87, 159), (173, 135, 255), (244, 246, 255))
PARTICLE_LIFE = 2.15
# Pairs of corners the spotlights shine from, in turn: top, bottom, and the two diagonals.
LAYOUTS = (('tl', 'tr'), ('bl', 'br'), ('tl', 'br'), ('bl', 'tr'))
BAR = 4  # kicks per change of corners
LAYOUT_SECONDS = 3.  # change of corners when a chorus has no drums
LAYOUT_FADE = .35  # seconds the lights cross-fade between pairs
CONFETTI = .85  # default confetti opacity; set apart from the lights or dim intensity
BLUR_REACH = .012  # blur radius on a full-strength kick, as a share of the screen's short side


def motif_for(text):
    words = text.casefold()
    choices = (
        ('heart', ('love', 'heart', 'kiss', 'romance', 'mahal', 'puso', 'pag-ibig', 'ibig')),
        ('leaf', ('leaf', 'leaves', 'tree', 'forest', 'wind', 'dahon', 'puno', 'hangin')),
        ('flower', ('flower', 'bloom', 'rose', 'blossom', 'bulaklak', 'rosas')),
        ('petal', ('petal', 'spring', 'garden', 'talulot', 'hardin')),
        ('star', ('star', 'sky', 'night', 'dream', 'moon', 'bituin', 'langit', 'gabi', 'panaginip')),
        ('confetti', ('dance', 'party', 'celebrate', 'celebration', 'festival', 'sayaw', 'piyesta')),
    )
    # Whole words only (a plural 's' allowed): 'street' is not a tree, 'window' is not wind, 'start' is not a star.
    return next((kind for kind, tokens in choices
                 if any(re.search(r'(?<![\w-])'+re.escape(token)+r's?(?![\w-])', words) for token in tokens)), 'none')


def chorus_windows(data):
    """Use explicit chorus/refrain labels; cap the tail at the next section."""
    sections = sections_for(data)
    result = []
    for number, section in enumerate(sections):
        if section['role'] not in ('chorus', 'refrain'):
            continue
        start = data[section['start']]['words'][0]['start']
        end = data[section['end']-1]['words'][-1]['end']+.7
        if number+1 < len(sections):
            end = min(end, data[sections[number+1]['start']]['words'][0]['start'])
        if end > start:
            lyrics = ' '.join(data[i]['text'] for i in range(section['start'], section['end']))
            result.append((start, end, section['start'], motif_for(lyrics)))
    return result


def confetti_pieces(strength):
    """How many pieces each burst throws, relative to the default: the slider's low half thins the showers, the
    default keeps them as they were, and the top of the range fills the screen (four times the pieces at 100%)."""
    if strength <= CONFETTI:
        return max(.15, (strength/CONFETTI)**2)
    return 1.+3.*((strength-CONFETTI)/(1.-CONFETTI))**2


class ChorusFX:
    """The beat effects: coloured lights pulsing on the kicks, and lyric-shaped confetti thrown on the strong ones,
    in the choruses or (whole_song) all through the song. `strength` is the lights' intensity."""

    def __init__(self, data, drums=None, strength=.75, lights=True, confetti=True, whole_song=False,
                 confetti_strength=CONFETTI, blur=0.):
        self.choruses = chorus_windows(data) if data else []
        self.drums = drums or []
        self.strength = strength
        self.lights_on = lights and strength > 0
        self.confetti_strength = confetti_strength
        self.blur = blur
        if whole_song and data:
            end = max(line['words'][-1]['end'] for line in data)+2.
            song = motif_for(' '.join(line['text'] for line in data))
            self.scope = [(0., max(end, max((w for w, _ in self.drums), default=0.)+1.), -1, song)]
        else:
            self.scope = list(self.choruses)
        # Kept for callers that only ask about choruses.
        self.windows = self.choruses if (self.lights_on or confetti) else []
        self.bursts = []
        if confetti and confetti_strength > 0:
            pieces = confetti_pieces(confetti_strength)
            every = 1 if confetti_strength >= .95 else 2 if confetti_strength >= .85 else 4  # kicks per burst
            fallback = motif_for(' '.join(line['text'] for line in data)) if data else 'none'
            fallback = 'confetti' if fallback == 'none' else fallback
            for start, end, section, motif in self.choruses:  # every chorus opens with a burst
                self.bursts.append((start, section*100003+7, 1., round(18*pieces), motif if motif != 'none' else fallback))
            for index, (when, weight) in enumerate(self.drums):
                window = next((w for w in self.scope if w[0] <= when < w[1]), None)
                if window is None or weight < .68 or index % every:
                    continue
                chorus = next((c for c in self.choruses if c[0] <= when < c[1]), None)
                motif = (chorus or window)[3]
                self.bursts.append((when, index*7919+101, weight, round(4*pieces), motif if motif != 'none' else fallback))
        self.bursts.sort()
        self.times = [burst[0] for burst in self.bursts]

    def active(self, t):
        """The chorus playing at `t`, as (start, end), or None."""
        return next(((start, end) for start, end, _, _ in self.choruses if start <= t < end), None)

    def beat_active(self, t):
        """The stretch where the beat effects run at `t` (a chorus, or the whole song), or None."""
        return next(((start, end) for start, end, _, _ in self.scope if start <= t < end), None)

    def paint(self, frame, t):
        window = self.beat_active(t)
        end = bisect.bisect_right(self.times, t)
        recent = self.bursts[max(0, end-16):end]
        flying = any(t-when <= PARTICLE_LIFE for when, *_ in recent)
        blur = 0.
        if window is not None and self.blur > 0:
            # A soft blur over the whole screen on each kick, clearing before the next one.
            blur = self.blur*pulse(self.drums, t, .12).level*min(frame.size)*BLUR_REACH
        if not flying and blur < .4 and (window is None or not self.lights_on):
            return frame
        width, height = frame.size
        result = frame.convert('RGBA')
        if blur >= .4:
            result = result.filter(ImageFilter.GaussianBlur(blur))
        energy = 0.
        if window is not None and self.lights_on:
            drum = pulse(self.drums, t, .23).level
            entrance = math.exp(-(t-window[0])*2.8)
            energy = self.strength*(.35+.65*max(drum, entrance))
        if energy > .03:
            # The lights move to another pair of corners every bar, cross-fading from the pair before.
            layout, previous, mix = self.layout_at(window, t)
            if mix < 1 and previous != layout:
                result.alpha_composite(self.lights((width, height), t, energy*(1-mix), previous))
            result.alpha_composite(self.lights((width, height), t, energy*(mix if previous != layout else 1.), layout))
        confetti = Image.new('RGBA', (width, height))
        draw = ImageDraw.Draw(confetti)
        for when, seed, weight, count, motif in recent:
            age = t-when
            if age <= PARTICLE_LIFE:
                self.paint_burst(draw, width, height, age, seed, count, min(1., self.confetti_strength/CONFETTI)*(.45+.55*weight), motif)
        if confetti.getbbox():
            half = (max(1, width//2), max(1, height//2))
            glow = confetti.resize(half, Image.Resampling.BILINEAR)
            glow = glow.filter(ImageFilter.GaussianBlur(max(2, min(half)*.01)))
            glow = glow.resize((width, height), Image.Resampling.BILINEAR)
            glow.putalpha(glow.getchannel('A').point(lambda a: round(a*.85)))
            result.alpha_composite(glow)
        result.alpha_composite(confetti)
        return result

    def layout_at(self, window, t):
        """(pair of corners now, pair before, cross-fade 0..1) for the chorus that opened at window[0]. The pair
        changes every BAR drum hits (a bar of four kicks), or every LAYOUT_SECONDS when the chorus has no drums."""
        start, end = window
        kicks = [when for when, _ in self.drums if start <= when < end]
        if kicks:
            changes = [kicks[k] for k in range(BAR, len(kicks), BAR)]
        else:
            changes = [start+k*LAYOUT_SECONDS for k in range(1, int((end-start)/LAYOUT_SECONDS)+1)]
        number = bisect.bisect_right(changes, t)
        offset = int(start*7) % len(LAYOUTS)  # each chorus opens on a different pair
        layout = LAYOUTS[(number+offset) % len(LAYOUTS)]
        if number == 0:
            return layout, layout, 1.
        previous = LAYOUTS[(number-1+offset) % len(LAYOUTS)]
        mix = min(1., (t-changes[number-1])/LAYOUT_FADE)
        return layout, previous, mix*mix*(3-2*mix)

    @staticmethod
    def lights(size, t, energy, layout=('tl', 'tr')):
        """Two coloured spotlight beams with soft glows, from the corners in `layout`, angled across the frame."""
        width, height = size
        small = (max(1, width//4), max(1, height//4))
        w, h = small
        result = Image.new('RGBA', small)
        sway = math.sin(t*1.7)*w*.11
        alpha = round(min(255, 92*energy))
        glow = round(min(255, 145*energy))
        r = w*.22
        for corner, (beam, halo) in zip(layout, ((((73, 202, 255), (76, 205, 255))), ((255, 83, 158), (255, 201, 89)))):
            # Drawn from the top-left corner, then flipped into place.
            light = Image.new('RGBA', small)
            draw = ImageDraw.Draw(light)
            lean = sway if corner in ('tl', 'br') else -sway
            draw.polygon(((0, 0), (w*.29, 0), (w*.72+lean, h), (w*.6+lean, h)), fill=(*beam, alpha))
            draw.ellipse((w*.09-r, -r*.7, w*.09+r, r*1.3), fill=(*halo, glow))
            if corner[0] == 'b':
                light = light.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            if corner[1] == 'r':
                light = light.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            result.alpha_composite(light)
        return result.filter(ImageFilter.GaussianBlur(max(2, round(w*.025)))).resize(size, Image.Resampling.BILINEAR)

    @staticmethod
    def paint_burst(draw, width, height, age, seed, count, strength, motif):
        rng = random.Random(seed)
        fade = max(0., min(1., (PARTICLE_LIFE-age)/.55))
        for number in range(count):
            # Every third piece leaves a side cannon; the rest rise from anywhere along the bottom, in any direction,
            # and the fastest climb past the top of the frame, so a burst fills the whole picture.
            side = -1 if number % 2 else 1
            cannon = number % 3 == 0
            origin_x = width*(.04 if side > 0 else .96) if cannon else width*rng.uniform(.02, .98)
            speed_x = side*width*rng.uniform(.12, .5) if cannon else width*rng.uniform(-.45, .45)
            speed_y = -height*rng.uniform(.3, 1.25)
            x = origin_x+speed_x*age+math.sin(age*5+number)*width*.012
            y = height*rng.uniform(.78, .86)+speed_y*age+height*.43*age*age
            if not (-15 < x < width+15 and -15 < y < height+15):
                continue
            size = max(2., min(width, height)*rng.uniform(.009, .021))
            angle = age*rng.uniform(3., 8.)+number*.73
            dx, dy = math.cos(angle)*size, math.sin(angle)*size
            nx, ny = -dy*.36, dx*.36
            color = COLORS[number % len(COLORS)]
            alpha = round(210*fade*strength)
            if motif == 'heart':
                points = []
                for k in range(20):
                    theta = math.tau*k/20
                    hx = 16*math.sin(theta)**3/17
                    hy = -(13*math.cos(theta)-5*math.cos(2*theta)-2*math.cos(3*theta)-math.cos(4*theta))/17
                    points.append((x+size*(hx*math.cos(angle)-hy*math.sin(angle)),
                                   y+size*(hx*math.sin(angle)+hy*math.cos(angle))))
                draw.polygon(points, fill=(*color, alpha))
            elif motif == 'star':
                points = [(x+math.cos(angle+k*math.pi/5)*size*(1. if k % 2 == 0 else .43),
                           y+math.sin(angle+k*math.pi/5)*size*(1. if k % 2 == 0 else .43))
                          for k in range(10)]
                draw.polygon(points, fill=(*color, alpha))
            elif motif == 'flower':
                for k in range(5):
                    theta = angle+k*math.tau/5
                    px, py = x+math.cos(theta)*size*.55, y+math.sin(theta)*size*.55
                    draw.ellipse((px-size*.38, py-size*.38, px+size*.38, py+size*.38), fill=(*color, alpha))
                draw.ellipse((x-size*.24, y-size*.24, x+size*.24, y+size*.24),
                             fill=(255, 226, 111, alpha))
            elif motif in ('leaf', 'petal'):
                bend = math.sin(age*7+number)*size*.35
                tip = (x+dx+bend, y+dy)
                back = (x-dx, y-dy)
                draw.polygon((tip, (x+nx*1.4, y+ny*1.4), back,
                              (x-nx*1.4, y-ny*1.4)), fill=(*color, alpha))
                if motif == 'leaf':
                    draw.line((back, tip), fill=(245, 255, 229, round(alpha*.55)), width=1)
            else:
                draw.polygon(((x-dx-nx, y-dy-ny), (x+dx-nx, y+dy-ny),
                              (x+dx+nx, y+dy+ny), (x-dx+nx, y-dy+ny)), fill=(*color, alpha))
