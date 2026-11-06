"""The wisp: bands along the ribbon, its head and motes, the music driving it, and the
partner's one visit.

Route geometry comes from render/thread_path.py, shared with the 2D wisp."""
from __future__ import annotations
import bisect
import math
import random
import numpy as np
from render.realtime import smooth
from render.thread_path import HEAD_FADE, dying_tail, thread_distance
from render.stage_3d.common import BANDS, BAND_STEP, BAND_WIDTH, DUET_ENTER, DUET_FOLLOW, DUET_HELIX, DUET_JOIN, DUET_LEAVE, DUET_LENGTH, RIBBON_REACH, normalized, route_point, shifted, steady_tangent
from render.stage_3d.gl import look_at


class StageWisp:
    def ribbon_bands(self, t, eye):
        """Translucent bands from the thread's tail to its head, each swelling and narrowing in its own slow
        wave and pinching together at both ends, turned to face the camera: one vertex row per sample."""
        if not self.options['traces'] and self.options['geometry'] <= 0:
            return []
        return [band for run in self.ribbon for band in self.run_bands(run, t, eye)]

    def ribbon_heads(self, t, eye):
        """The main wisp's head at the leading end of the ribbon, and the partner's while it visits."""
        if not self.options['traces'] and self.options['geometry'] <= 0:
            return []
        if any(start <= t < end for start, end in self.veils):
            return []
        result = []
        energy, _, tune = self.pulse(t)
        presence = self.partner_presence(t)
        glow = self.duet_glow(t)
        for number, run in enumerate(self.ribbon):
            alive = 1-smooth((t-run['keys'][0][-1])/HEAD_FADE)
            if alive <= .001:
                continue
            head = self.head_at(number, t)
            if head is None:
                continue
            point, tangent = head
            side = normalized(np.cross(tangent, eye-point))
            up = normalized(np.cross(side, tangent))
            for wisp, opacity in ((0, alive), (1, presence*alive)):
                if opacity <= .001:
                    continue
                position = point+self.wisp_offset(wisp, t, t, side, up, tangent, energy)
                result.append((position, opacity, shifted((1., .96, .82), (tune-.5)*.16+wisp*.28+glow)))
        return result

    def music(self):
        """Hits from the drums and bass, and the sung pitch rank of each word, prepared once."""
        if getattr(self, '_music', None) is None:
            hits = sorted(h for stem in ('drums', 'bass') for h in (self.rhythm.get(stem) or []))
            times = np.array([h[0] for h in hits]) if hits else np.zeros(0)
            strengths = np.array([h[1] for h in hits]) if hits else np.zeros(0)
            tune = []
            for index, line in enumerate(self.c.data):
                features = self.melody[index] if self.melody and index < len(self.melody) else None  # a stale melody can be shorter
                for number, word in enumerate(line['words']):
                    rank = (features[number] or {}).get('pitch_rank') if features and number < len(features) else None
                    if rank is not None:
                        tune.append((word['start'], rank))
            tune.sort()
            self._music = dict(times=times, strengths=strengths, tune_times=[a for a, _ in tune], tune=[b for _, b in tune])
        return self._music

    def pulse(self, t):
        """(soft hit glow, continuous motion clock, pitch rank of the vocal melody)."""
        music = self.music()
        before = music['times'] <= t
        ages = t-music['times'][before]
        strengths = music['strengths'][before]
        energy = float(np.sum(strengths*np.minimum(1., np.maximum(0., ages)/.16)*np.exp(-ages/.55)))
        clock = t*.7
        index = bisect.bisect_right(music['tune_times'], t)-1
        if index < 0:
            tune = .5
        else:  # glide from the previous word's pitch to this one's over a moment
            here = music['tune'][index]
            previous = music['tune'][index-1] if index else here
            tune = previous+(here-previous)*smooth((t-music['tune_times'][index])/.4)
        return min(1.5, energy), clock, tune

    def duet_windows(self):
        """The partner's one visit (DUET_LENGTH long, in the second half of the song), starting and ending on
        vocal notes or rhythm hits within an active ribbon run; empty when no run is long enough there."""
        if getattr(self, '_duet_windows', None) is not None:
            return self._duet_windows
        music = self.music()
        hits = [(float(t), float(s)) for t, s in zip(music['times'], music['strengths']) if s >= .55]
        notes = music['tune_times']
        events = []
        for i, note in enumerate(notes):
            change = abs(music['tune'][i]-music['tune'][i-1]) if i else 0.
            accent = max((strength for time, strength in hits if abs(time-note) <= .22), default=0.)
            if change >= .07 or accent >= .6:
                events.append((float(note), change+accent*.5))
        if not events:
            events = hits
        shortest, longest = DUET_LENGTH
        middle = getattr(getattr(self, 'c', None), 'duration', 0.)/2
        windows = []
        for run in self.ribbon:
            first, last = run['keys'][0][0], run['keys'][0][-1]
            local = [(time, strength) for time, strength in events if max(first+.6, middle) <= time <= last-shortest]
            for start, strength in local:
                if strength < .08:
                    continue
                ends = [time for time, _ in events if start+shortest <= time <= min(last, start+longest)]
                if not ends:
                    ends = [time for time, _ in hits if start+shortest <= time <= min(last, start+longest)]
                if ends:
                    windows = [(start, ends[0])]
                    break
            if windows:
                break
        self._duet_windows = windows
        return windows

    def visit(self, when):
        """The partner's visit covering time `when`: (start, end, the side it flies in from), or None."""
        windows = self.duet_windows()
        k = bisect.bisect_right([start for start, _ in windows], when)-1
        if k >= 0 and when <= windows[k][1]:
            return windows[k][0], windows[k][1], 1. if k % 2 == 0 else -1.
        return None

    def partner_presence(self, t):
        """How visible the partner is: it fades in far off as it arrives and out far off as it leaves."""
        visit = self.visit(t)
        if visit is None:
            return 0.
        start, end, _ = visit
        u = (t-start)/max(1e-6, end-start)
        return smooth(u/.12)*smooth((1-u)/.12)

    @staticmethod
    def solo(when):
        """The main wisp's lazy swim round the path when it is alone, in (side, up, forward) BAND_WIDTHs."""
        return np.array([2.4*math.cos(1.1*when)+.5*math.sin(1.7*when+.3), 1.9*math.sin(1.1*when), 0.])

    def chase(self, when):
        """Main and partner offsets from the path at `when`, in (side, up, forward) units of BAND_WIDTH, and how
        fully they are together (0 when the main wisp is alone, 1 mid-chase). The partner is None off a visit."""
        solo = self.solo(when)
        visit = self.visit(when)
        if visit is None:
            return solo, None, 0.
        start, end, from_side = visit
        u, tau = (when-start)/max(1e-6, end-start), when-start
        entering = smooth(u/DUET_ENTER)
        joining = smooth((u-DUET_FOLLOW)/DUET_JOIN)
        leaving = smooth((u-DUET_LEAVE)/(1-DUET_LEAVE))
        helix = smooth((u-DUET_HELIX[0])/.06)*smooth((DUET_HELIX[1]-u)/.06)
        # Trailing: behind the main wisp, echoing the swim it made a moment earlier, slowly closing the gap.
        follow = self.solo(when-1.2)+np.array([0., 0., -7.+3.5*smooth((u-DUET_ENTER)/(DUET_FOLLOW-DUET_ENTER))])
        # Joined: round and round each other on a wandering figure, swapping the lead; tighter in the helix.
        theta = 1.3*tau+2.2*math.sin(.37*tau)+3.2*tau*helix
        radius = (3.2+1.4*math.sin(.8*tau+1.))*(1-.65*helix)
        chase = radius*np.array([math.cos(theta), .8*math.sin(theta), .6*math.sin(2*theta+.5)])
        arrive, depart = np.array([16*from_side, 9., -24.]), np.array([-18*from_side, 12., 16.])
        partner = follow+(chase-follow)*joining
        partner = arrive+(partner-arrive)*entering
        partner = partner+(depart-partner)*leaving
        together = joining*(1-leaving)
        return solo+(-.55*chase-solo)*together, partner, together

    def duet_glow(self, when):
        """A hue drift that ripples through both wisps, their tails and motes while they are together."""
        return .35*self.chase(when)[2]*math.sin(1.7*when)

    def wisp_offset(self, wisp, when, now, side, up, tangent, energy=0.):
        """Where a wisp was relative to the path at time `when` (the head's time, or for a point on a tail the
        time the head passed it). Tails flick with a wave running down them, livelier on hits."""
        main, partner, _ = self.chase(when)
        offset = partner if wisp and partner is not None else main
        age = max(0., now-when)
        flick = min(1., age/.6)*(.45+.35*min(1.5, energy))
        offset = offset+flick*np.array([math.sin(9*age+3.1*when), .6*math.cos(7*age+2.3*when), 0.])
        return (side*offset[0]+up*offset[1]+tangent*offset[2])*BAND_WIDTH

    def head_times(self, number, distances):
        """When the run's head passed each distance along its path (the inverse of its timing keys)."""
        run = self.ribbon[number]
        if '_clock' not in run:
            times = run['keys'][0]
            grid = np.arange(times[0], times[-1]+1/60, 1/60)
            run['_clock'] = (np.maximum.accumulate([thread_distance(run['keys'], x) or 0. for x in grid]), grid)
        travelled, grid = run['_clock']
        return np.interp(distances, travelled, grid)

    def run_bands(self, run, t, eye):
        head = thread_distance(run['keys'], t)
        if head is None:
            return []
        number = next(k for k, other in enumerate(self.ribbon) if other is run)
        tail = dying_tail(run['keys'], t, RIBBON_REACH)
        samples, groups, travelled = [], [], 0.
        for (p, q), color, paint in zip(run['segments'], run['colors'], run['paint']):
            length = float(np.linalg.norm(q-p))
            start, travelled = travelled, travelled+length
            if not paint:
                if len(samples) >= 2:
                    groups.append(samples)
                samples = []
                continue
            if travelled <= tail or start >= head or length < 1e-6:
                continue
            marks = [max(tail, start)]+[d for d in np.arange(math.ceil(start/BAND_STEP)*BAND_STEP, travelled, BAND_STEP)
                                        if tail < d < head]+[min(head, travelled)]
            for distance in marks:
                if not samples or distance > samples[-1][1]+1e-6:
                    samples.append((p+(q-p)*((distance-start)/length), distance, np.array(color)/255))
        if len(samples) >= 2:
            groups.append(samples)
        energy, clock, tune = self.pulse(t)
        presence = self.partner_presence(t)
        visit = self.visit(t)
        bands = []
        for samples in groups:
            whens = self.head_times(number, [distance for _, distance, _ in samples])
            tangents = [steady_tangent(run, distance) for _, distance, _ in samples]
            for wisp in (0, 1):
                opacity = 1. if wisp == 0 else presence
                if opacity <= .001:
                    continue
                # The partner's tail only reaches back to where it flew in.
                chosen = [k for k in range(len(samples)) if wisp == 0 or whens[k] >= visit[0]]
                if len(chosen) < 2:
                    continue
                begin, finish = samples[chosen[0]][1], samples[chosen[-1]][1]
                for band in range(BANDS if wisp == 0 else BANDS-1):
                    rows = []
                    for k in chosen:
                        point, distance, color = samples[k]
                        tangent = tangents[k]
                        side = normalized(np.cross(tangent, eye-point))
                        up = normalized(np.cross(side, tangent))
                        pinch = smooth(min(finish-distance, distance-begin)/(BAND_WIDTH*14))
                        phase = distance/(BAND_WIDTH*16)+clock+band*1.7
                        centre = point+self.wisp_offset(wisp, whens[k], t, side, up, tangent, energy)
                        offset = ((band-(BANDS-1)/2)*1.2+math.sin(phase)*1.)*BAND_WIDTH*pinch*.8
                        width = (1.+.8*math.sin(phase*.6+band))*BAND_WIDTH*1.7*pinch
                        tint = shifted(color, (tune-.5)*.18+wisp*.2+self.duet_glow(whens[k]))
                        rows.append((*(centre+side*(offset-width/2)), 0., *tint))
                        rows.append((*(centre+side*(offset+width/2)), 1., *tint))
                    if len(rows) >= 4:
                        bands.append((np.array(rows), opacity))
        return bands

    def wisp_particles(self, t):
        """Glowing motes streaming from the wisp heads, bursting on every hit and pouring off both wisps in
        shifting colours while they chase, with sparks wherever the two pass close: [(position, size, opacity,
        colour)]. Each mote's path is solved from its birth time."""
        if not self.options['traces']:
            return []
        energy, clock, tune = self.pulse(t)
        music = self.music()
        result = []
        for number, run in enumerate(self.ribbon):
            if t > run['keys'][0][-1]+1.2 or t < run['keys'][0][0]:
                continue
            colour = np.array(run['colors'][0] if run['colors'] else (255, 255, 255))/255
            for k in range(36):  # motes born over the last 1.2 s
                born = math.floor(t*30)/30-k/30
                age = t-born
                if born < run['keys'][0][0]:
                    break
                head = self.head_at(number, born)
                if head is None:
                    continue
                point, tangent = head
                hits = music['times'][(music['times'] <= born) & (music['times'] > born-1/30)]
                together = self.chase(born)[2]
                burst = (5 if len(hits) else 1)+round(3*together)
                b_energy = self.pulse(born)[0]
                presence = self.partner_presence(born)
                side = normalized(np.cross(tangent, np.array([0., 0., 1.])))
                up = normalized(np.cross(side, tangent))
                for j in range(burst*2):
                    rng = random.Random(round(born*30)*97+j*13+number)
                    wisp = j % 2
                    if wisp and presence <= .001:
                        continue
                    origin = point+self.wisp_offset(wisp, born, born, side, up, tangent, b_energy)
                    velocity = np.array([rng.uniform(-1, 1), rng.uniform(-.4, 1.), rng.uniform(-1, 1)])*(.3+.9*(burst > 1))
                    position = origin+velocity*age-np.array([0., .12, 0.])*age*age
                    fade = (1-smooth(age/1.2))*smooth(age/.05)
                    tint = shifted(colour*.6+.4, (tune-.5)*.18+wisp*.2+self.duet_glow(born)+together*rng.uniform(-.25, .25))
                    result.append((position, BAND_WIDTH*(2.6 if burst > 1 else 1.5)*(1-.5*age),
                                   fade*(presence if wisp else 1.), tint))
            # Wherever the two wisps pass close, a spark flares.
            head = self.head_at(number, t)
            if head is not None and self.partner_presence(t) > .6:
                point, tangent = head
                side = normalized(np.cross(tangent, np.array([0., 0., 1.])))
                up = normalized(np.cross(side, tangent))
                gap = np.linalg.norm(self.wisp_offset(0, t, t, side, up, tangent)-self.wisp_offset(1, t, t, side, up, tangent))
                if gap < BAND_WIDTH*2.2:
                    middle = point+(self.wisp_offset(0, t, t, side, up, tangent)+self.wisp_offset(1, t, t, side, up, tangent))/2
                    result.append((middle, BAND_WIDTH*5, .9*(1-gap/(BAND_WIDTH*2.2)), (1., 1., 1.)))
        return result

    def head_at(self, number, t):
        """Position and steady direction of a ribbon run's head at time t, cached per stage (an lru_cache on the
        method would keep every stage, and its compositor's artwork, alive in one module-wide cache)."""
        cache = self.__dict__.setdefault('_heads', {})
        key = (number, t)
        if key not in cache:
            if len(cache) >= 4096:
                cache.clear()
            cache[key] = self._head_at(number, t)
        return cache[key]

    def _head_at(self, number, t):
        run = self.ribbon[number]
        head = thread_distance(run['keys'], t)
        if head is None or not run['segments']:
            return None
        return route_point(run, head), steady_tangent(run, head)

    def wisp_runs(self):
        """(start, end) time of each ribbon run's main wisp."""
        self.plan()
        if not self.options['traces'] and self.options['geometry'] <= 0:
            return []
        return [(run['keys'][0][0], run['keys'][0][-1]) if run['keys'][0] else (math.inf, -math.inf) for run in self.ribbon]

    def wisp_screen(self, number, when, t):
        """Screen pixel of run `number`'s main wisp where it was at time `when`, filmed by the camera at time t."""
        head = self.head_at(number, when)
        if head is None:
            return None
        point, tangent = head
        eye, target, _, up = self.camera(t)
        side = normalized(np.cross(tangent, eye-point))
        lift = normalized(np.cross(side, tangent))
        position = point+self.wisp_offset(0, when, when, side, lift, tangent, self.pulse(when)[0])
        clip = self.projection@look_at(eye, target, up)@np.array([*position, 1.])
        if clip[3] <= 1e-6:
            return None
        return (clip[0]/clip[3]+1)/2*self.c.width, (1-clip[1]/clip[3])/2*self.c.height
