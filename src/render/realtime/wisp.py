"""The wisp: underlines and a thread through the hero words, drawn as bands, plus the duet.

Route geometry is shared with the 3D wisp through render/thread_path.py. The duet and band
tuning are separate: here the duet covers the busiest run of whole lines, while the 3D stage
times one visit inside a ribbon run."""

import bisect
import math
from PIL import Image, ImageDraw, ImageFilter
from core.easing import smoothstep as smooth
from core.color import hex_rgb
from render.thread_path import THREAD_LIFE, monotone_keys, sample_thread, thread_distance
from render.realtime.common import (
    BANDS,
    BAND_ALPHA,
    BAND_UNIT,
    DUET_COLORS,
    DUET_EASE,
    DUET_SHARE,
    STRAND_STEP,
    THREAD_LEAD,
    UNDERLINE_LINGER,
    add_piece,
    direction,
    group_by_color,
    mix_rgb,
    recolor,
    strand_normals,
    thread_curve,
)
from render.realtime.layout import role_font


class FlowWisp:
    def paint_traces(self, layer, t, base, visible):
        """Glowing underlines beneath sung words, and one continuous wisp whose head travels from hero
        word to hero word ahead of the singing (THREAD_LEAD early, and at a new line before it starts).
        It keeps one colour, except during the duet, when a second wisp braids with it. Its tail follows
        THREAD_LIFE seconds behind, so it is erased just as smoothly."""
        trace = Image.new('RGBA', layer.size)
        draw = ImageDraw.Draw(trace)
        for index, _ in visible:
            shift = self.shift(index, base)
            for word in self.lines[index]['layout'].words:
                if word.start > t or t >= word.end + UNDERLINE_LINGER or word.role == 'function':
                    continue
                ascent = role_font(word.role, word.size).getmetrics()[0]
                fraction = smooth((t - word.start) / max(0.15, word.end - word.start))
                fade = 1 - smooth((t - word.end) / UNDERLINE_LINGER)
                y = word.y + shift[1] + ascent * 1.08
                x0 = word.x + shift[0]
                x1 = x0 + word.width * fraction
                weight = max(2, round(word.size * 0.035))
                draw.line((x0, y, x1, y), fill=(*word.color, round(230 * fade)), width=weight)
                draw.ellipse(
                    (x1 - weight * 1.6, y - weight * 1.6, x1 + weight * 1.6, y + weight * 1.6),
                    fill=(255, 255, 255, round(240 * fade)),
                )
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
        thread = self.thread_path()
        head = thread_distance(thread['keys'], t)
        if head is None:
            return
        tail = thread_distance(thread['keys'], t - THREAD_LIFE) or 0.0
        samples = sample_thread(thread['pieces'], tail, head, STRAND_STEP)
        if len(samples) < 2:
            return
        color, duet_color, partner_color = self.wisp_colors()
        together = self.duet_strength(t)
        main = mix_rgb(color, duet_color, together)
        fade = 1.0  # the run ends off screen: the head has flown out, and the tail follows it out
        if together <= 0:
            wisps = [(recolor(samples, main), tail, 1.0)]
        else:
            # The partner peels away from the wisp where the duet began; the two braid around each
            # other, and merge back into one as it leaves.
            joined = thread_distance(thread['keys'], self.duet_window()[0]) or tail
            unit = self.c.height * BAND_UNIT
            normals = strand_normals(samples)

            def braided(side, chosen):
                points = []
                for (x, y, distance, _), normal in zip(samples, normals):
                    swing = side * together * unit * 5 * math.sin(distance / (unit * 22) + t * 1.7)
                    swing *= smooth((distance - joined) / (unit * 20))
                    points.append((x + normal[0] * swing, y + normal[1] * swing, distance, chosen))
                return points

            partner = [p for p in braided(-1, mix_rgb(color, partner_color, together)) if p[2] >= joined]
            wisps = [(braided(1, main), tail, 1.0)]
            if len(partner) >= 2:
                wisps.append((partner, max(tail, joined), together))
        for points, start, strength in wisps:
            strength *= fade
            self.paint_bands(draw, fill_layer, points, start, head, t, base, min(1.0, strength))
            if any(start <= t < end for start, end in self.veils):
                continue  # the scene mix is carrying the wisp across a change of scene
            x, y = points[-1][0] - base[0], points[-1][1] - base[1]
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(255, 255, 255, round(230 * min(1.0, strength))))

    def paint_bands(self, draw, fill_layer, samples, tail, head, t, base, strength=1.0):
        """The thread as a few thick translucent bands, like the PSP waves: each swells and narrows in its
        own slow wave, overlaps brighten, a thin crest catches the light, and all pinch together at the
        moving head and at the tail."""
        unit = self.c.height * BAND_UNIT
        normals = strand_normals(samples)
        bands = Image.new('RGBA', fill_layer.size)
        for band in range(BANDS):
            centre = band - (BANDS - 1) / 2
            upper, lower = [], []
            for (x, y, distance, color), normal in zip(samples, normals):
                pinch = smooth(min(head - distance, distance - tail) / (unit * 12))
                phase = distance / (unit * 14) + t * 0.5 + band * 1.7
                middle = (centre * 1.4 + math.sin(phase) * 1.2) * unit * pinch
                half = (1.1 + 0.8 * math.sin(phase * 0.6 + band)) * unit * pinch
                px, py = x - base[0], y - base[1]
                upper.append((px + normal[0] * (middle - half), py + normal[1] * (middle - half), color))
                lower.append((px + normal[0] * (middle + half), py + normal[1] * (middle + half), color))
            # Drawn opaque as one small quad per step (a closed loop stays a ring, never a filled disc), then
            # made translucent as a whole so the quads' shared edges do not show.
            band_layer = Image.new('RGBA', fill_layer.size)
            band_draw = ImageDraw.Draw(band_layer)
            for (color, top), (_, bottom) in zip(group_by_color(upper), group_by_color(lower)):
                band_draw.polygon(top + bottom[::-1], fill=(*color, round(BAND_ALPHA * strength)))
                band_draw.line(top, fill=(*color, round(150 * strength)), width=2, joint='curve')
            bands.alpha_composite(band_layer)
        box = bands.getbbox()
        if box:
            box = (max(0, box[0] - 4), max(0, box[1] - 4), min(bands.width, box[2] + 4), min(bands.height, box[3] + 4))
            fill_layer.alpha_composite(bands.crop(box).filter(ImageFilter.GaussianBlur(1.1)), box[:2])

    wisp_exits = True  # at the end of its run the wisp flies off the screen itself; the scene mix need not carry it

    def wisp_runs(self):
        """(start, end) time of the wisp's one run, for the scene mix's hand-over."""
        if not self.options['traces']:
            return []
        times = self.thread_path()['keys'][0]
        return [(times[0], times[-1])] if times else []

    def wisp_screen(self, number, when, t):
        """Screen pixel of the wisp where it was at time `when`, with the camera at time t."""
        thread = self.thread_path()
        head = thread_distance(thread['keys'], when)
        if head is None:
            return None
        samples = sample_thread(thread['pieces'], max(0.0, head - 1.0), head, STRAND_STEP)
        if not samples:
            return None
        center = self.path.at(t)
        return samples[-1][0] - (center[0] - self.c.width / 2), samples[-1][1] - (center[1] - self.c.height / 2)

    def thread_path(self):
        """The whole thread on the canvas: a smooth path through each hero word, with the distance its head
        has reached as each is sung. It turns continuously and keeps one cruising speed (see flow_path)."""
        if getattr(self, '_thread', None) is not None:
            return self._thread
        stops = []
        for number, line in enumerate(self.plan()):
            if not self.shown(number):  # in a scene mix the wisp visits only this scene's own lines
                continue
            for word in line['layout'].words:
                if word.role == 'hero':
                    ascent = role_font(word.role, word.size).getmetrics()[0]
                    top = word.y + line['offset'][1] + ascent * 0.08
                    bottom = word.y + line['offset'][1] + ascent * 1.02
                    stops.append(
                        dict(
                            word=word,
                            line=number,
                            line_start=line['start'],
                            anchor=(word.x + line['offset'][0] + word.width / 2, (top + bottom) / 2),
                        )
                    )
        stops.sort(key=lambda stop: stop['word'].start)
        times = []
        for number, stop in enumerate(stops):
            # Ahead of the singing: early at every hero word, and at a new line before the line begins.
            due = stop['word'].start
            if not number or stops[number - 1]['line'] != stop['line']:
                due = min(due, stop['line_start'])
            due -= THREAD_LEAD
            times.append(max(due, times[-1] + 0.05) if times else due)
        for number, stop in enumerate(stops):
            stop['arrive'] = stop['leave'] = (
                direction(stops[number - 1]['anchor'], stop['anchor']) if number else (1.0, 0.0)
            )
        rates = sorted(
            math.dist(stops[n]['anchor'], stops[n + 1]['anchor']) / (times[n + 1] - times[n])
            for n in range(len(stops) - 1)
        )
        cruise = rates[len(rates) // 2] if rates else 0.0
        pieces, distances, total = [], [], 0.0
        for number, stop in enumerate(stops):
            if number:
                wanted = cruise * (times[number] - times[number - 1])
                curve = thread_curve(stops[number - 1], stop, wanted, 1 if number % 2 else -1)
                total = add_piece(pieces, curve, self.wisp_colors()[0], total)
            distances.append(total)
        if stops:  # it never parks: past its last word it keeps going the way it was heading, off the screen
            last = stops[-1]
            heading = last['arrive']
            reach = math.hypot(self.c.width, self.c.height) * 0.85
            speed = max(cruise, reach / 1.4)  # out of the frame within about a second and a half
            out = dict(
                anchor=(last['anchor'][0] + heading[0] * reach, last['anchor'][1] + heading[1] * reach),
                arrive=heading,
                leave=heading,
            )
            total = add_piece(pieces, thread_curve(last, out, reach, 1), self.wisp_colors()[0], total)
            distances.append(total)
            times.append(times[-1] + reach / speed)
        self._thread = dict(pieces=pieces, keys=monotone_keys(times, distances))
        return self._thread

    def wisp_colors(self):
        """(the wisp's colour for the whole song, its colour during the duet, the second wisp's colour)."""
        if getattr(self, '_wisp_colors', None) is None:
            heroes = [w for line in self.plan() for w in line['layout'].words if w.role == 'hero']
            base = tuple(heroes[0].color) if heroes else hex_rgb(DUET_COLORS[1])
            # The duet colours are the two most unlike the song's colour, so the change reads clearly.
            duet = sorted(
                (hex_rgb(c) for c in getattr(self.c, 'art_duet', None) or DUET_COLORS),
                key=lambda c: -sum((a - b) ** 2 for a, b in zip(c, base)),
            )
            self._wisp_colors = (base, duet[0], duet[1])
        return self._wisp_colors

    def duet_window(self):
        """(start, end) of the one stretch where a second wisp plays alongside the first, or None.

        About DUET_SHARE of the sung song, on whole lines: the stretch with the densest instrument
        onsets, favouring a chorus, and later in the song when the music gives no other reason.
        """
        if getattr(self, '_duet', False) is not False:
            return self._duet
        data = self.c.data
        starts = [line['words'][0]['start'] for line in data]
        ends = [line['words'][-1]['end'] for line in data]
        self._duet = None
        if len(data) < 3 or not self.options['traces']:
            return None
        target = (ends[-1] - starts[0]) * DUET_SHARE
        if target < 3 * DUET_EASE:
            return None
        onsets = sorted(time for stem in ('drums', 'bass', 'other') for time, _ in (self.rhythm.get(stem) or []))
        chorus = [
            any(name in str(line.get('section_label', '')).lower() for name in ('chorus', 'refrain')) for line in data
        ]
        best = None
        for first in range(len(data)):
            last = next((k for k in range(first, len(data)) if ends[k] - starts[first] >= target * 0.8), None)
            if last is None:
                break
            span = ends[last] - starts[first]
            count = bisect.bisect_right(onsets, ends[last]) - bisect.bisect_left(onsets, starts[first])
            middle = (starts[first] + ends[last]) / 2
            late = 1 - abs((middle - starts[0]) / max(1e-6, ends[-1] - starts[0]) - 0.7)
            score = (count / span, sum(chorus[first : last + 1]) / (last - first + 1), late)
            if best is None or score > best[0]:
                best = (score, (starts[first], ends[last]))
        self._duet = best[1] if best else None
        return self._duet

    def duet_strength(self, t):
        """0 outside the duet, easing to 1 as the second wisp arrives and back to 0 as it leaves."""
        window = self.duet_window()
        if window is None:
            return 0.0
        start, end = window
        return smooth((t - start) / DUET_EASE) * (1 - smooth((t - end) / DUET_EASE))
