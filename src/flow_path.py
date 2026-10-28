"""The flowing band's path: always turning, never cornering, braking or stopping (like the PSP waves).

The band passes through each hero word as it is sung. Its path is a smooth spline through
those words whose direction carries straight on through every word, so it never turns a
corner. Where the next word is far off in time, the path weaves gentle S-curves on the way,
just enough that the whole band can travel at one steady cruising speed. Each wave is at
most half as tall as it is long, so the band always turns gently; when gentle waves cannot
make up the length, the band arrives a little early instead of braking: its head cruises
at one steady speed and only eases faster or slower within a narrow range (never below
three quarters of it) to stay near each word as it is sung. The weaving fades to nothing
at each word, so every join stays smooth. The band flows in a little before the first word
and flows on past the last one instead of stopping there. Where the words are far apart in
time (another scene is playing in between), the band ends and later starts a new run, so
it never has to crawl through the gap. Works in 2D (the
panning canvas) and 3D (the stage), where the weaving stays in the plane of the blocks.
"""
import math

import numpy as np

SAMPLES = 48
LEAD = 2.5
CRUISE_MARGIN = 1.15
MAX_WAVES = 6
LOBE = .5
STEP = 1/30
SLOWEST, FASTEST, EASE, LOOKAHEAD = .75, 1.35, .5, 1.2
BREAK = 4.


def unit(vector):
    length = float(np.linalg.norm(vector))
    return vector/length if length > 1e-9 else vector*0


def length_of(points):
    return float(np.sum(np.linalg.norm(np.diff(points, axis=0), axis=1)))


def hermite(a, b, start, end, chord, samples):
    """The smooth curve from a to b leaving along `start` and arriving along `end`."""
    u = np.linspace(0., 1., samples+1)[:, None]
    return (2*u**3-3*u**2+1)*a+(u**3-2*u**2+u)*start*chord+(-2*u**3+3*u**2)*b+(u**3-u**2)*end*chord


def build_flows(times, points, colors, amplitude, normals=None, lines=None):
    """Separate runs of the band wherever another scene plays in between (the stops' `lines` are not next
    to each other) or a gap between words is over BREAK times the usual gap, all at one shared cruising
    speed; each run is a build_flow result."""
    if not times:
        return []
    gaps = sorted(b-a for a, b in zip(times, times[1:]))
    usual = gaps[len(gaps)//2] if gaps else 1.
    apart = lambda i: times[i]-times[i-1] > BREAK*usual or (lines is not None and lines[i]-lines[i-1] > 1)  # noqa: E731
    rates = sorted(float(np.linalg.norm(np.subtract(b, a)))/max(1e-3, t1-t0)
                   for i, (a, b, t0, t1) in enumerate(zip(points, points[1:], times, times[1:]), 1) if not apart(i))
    cruise = rates[len(rates)//2]*CRUISE_MARGIN if rates else None
    runs, start = [], 0
    for i in range(1, len(times)+1):
        if i == len(times) or apart(i):
            part = slice(start, i)
            runs.append(build_flow(times[part], points[part], colors[part], amplitude,
                                   normals[part] if normals is not None else None, cruise))
            start = i
    return [run for run in runs if run['pieces']]


def build_flow(times, points, colors, amplitude, normals=None, cruise=None):
    """Pieces of the band's path (dict(points, color, start, end), distances along it) and the timing keys
    that bring its head to each point at its time. `amplitude` caps how far the weaving swings sideways;
    `normals` (3D only) give the plane each stop's weaving stays in."""
    from realtime_typography import monotone_keys
    points = [np.asarray(p, dtype=float) for p in points]
    times = list(times)
    if not points or (len(points) < 2 and not cruise):
        return dict(pieces=[], keys=monotone_keys(times, [0.]*len(times)))
    if len(points) > 1:
        rates = sorted(np.linalg.norm(b-a)/max(1e-3, t1-t0) for a, b, t0, t1 in zip(points, points[1:], times, times[1:]))
        cruise = cruise or rates[len(rates)//2]*CRUISE_MARGIN
        first, last = unit(points[1]-points[0]), unit(points[-1]-points[-2])
    else:
        first = last = np.eye(len(points[0]))[0]
    points = [points[0]-first*cruise*LEAD]+points+[points[-1]+last*cruise*LEAD]
    times = [times[0]-LEAD]+times+[times[-1]+LEAD]
    colors = [colors[0]]+list(colors)+[colors[-1]]
    if normals is not None:
        normals = [normals[0]]+list(normals)+[normals[-1]]
    count = len(points)
    tangents = [unit(points[min(count-1, i+1)]-points[max(0, i-1)]) for i in range(count)]
    pieces, distances, total = [], [0.], 0.
    for i in range(count-1):
        a, b = points[i], points[i+1]
        chord = float(np.linalg.norm(b-a)) or 1e-6
        wanted = cruise*(times[i+1]-times[i])
        if len(a) == 2:
            side = unit(np.array([a[1]-b[1], b[0]-a[0]]))
        else:
            plane = unit((normals[i]+normals[i+1])/2) if normals is not None else np.array([0., 0., 1.])
            side = unit(np.cross(b-a, plane))
        curve = hermite(a, b, tangents[i], tangents[i+1], chord, SAMPLES)
        for waves in range(1, MAX_WAVES+1):
            if length_of(curve) >= wanted:
                break
            u = np.linspace(0., 1., SAMPLES*waves+1)[:, None]
            base = hermite(a, b, tangents[i], tangents[i+1], chord, SAMPLES*waves)
            shape = np.sin(np.pi*u)**2*np.sin(np.pi*waves*u)*(1 if i % 2 else -1)
            low, high = 0., min(amplitude, LOBE*chord/waves)
            for _ in range(24):
                middle = (low+high)/2
                low, high = (middle, high) if length_of(base+shape*side*middle) < wanted else (low, middle)
            curve = base+shape*side*low
        length = length_of(curve)
        pieces.append(dict(points=[tuple(p) for p in curve], color=colors[i+1], start=total, end=total+length))
        total += length
        distances.append(total)
    return dict(pieces=pieces, keys=steady(times, distances))


def steady(times, distances):
    """Timing keys for a head that cruises along the path: it steers towards where the word timings put it
    a moment ahead, but its speed stays within SLOWEST..FASTEST of the cruise and changes by at most EASE
    of the cruise per second, so it never brakes, stops or lurches. Planned once for the whole path."""
    from realtime_typography import monotone_keys, thread_distance
    target = monotone_keys(times, distances)
    cruise = distances[-1]/max(1e-6, times[-1]-times[0])
    grid, positions = [times[0]], [0.]
    speed = cruise
    while grid[-1] < times[-1] and positions[-1] < distances[-1]:
        t = grid[-1]
        wanted = (thread_distance(target, min(times[-1], t+LOOKAHEAD))-positions[-1])/LOOKAHEAD
        wanted = min(FASTEST*cruise, max(SLOWEST*cruise, wanted))
        speed += max(-EASE*cruise*STEP, min(EASE*cruise*STEP, wanted-speed))
        grid.append(t+STEP)
        positions.append(min(distances[-1], positions[-1]+speed*STEP))
    return monotone_keys(grid, positions)
