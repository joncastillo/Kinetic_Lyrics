"""Wisp path geometry: keyframed routes, sampling, loops and the dying tail.

Used by both wisps (render/realtime/wisp.py, render/stage_3d/wisp.py), flow_path and
wisp_forms. Each wisp keeps its own duet and band tuning.
"""

import bisect
import math

from core.easing import smoothstep as smooth

THREAD_LIFE = 30.0
DIE_TIME, HEAD_FADE = 4.0, 0.8  # when a wisp's run ends: its tail fades back to the head; the head dims out


def dying_tail(keys, t, reach=math.inf):
    """Where the ribbon's tail is: THREAD_LIFE behind the head (and no more than `reach` behind it). Once the
    run ends and its wisp dies, the tail slowly fades back from its end to where the head stopped."""
    head = thread_distance(keys, t) or 0.0
    tail = max(thread_distance(keys, t - THREAD_LIFE) or 0.0, head - reach)
    end = keys[0][-1] if keys[0] else t
    if t <= end:
        return tail
    last = thread_distance(keys, end) or 0.0
    stopped = max(thread_distance(keys, end - THREAD_LIFE) or 0.0, last - reach)
    return max(tail, stopped + (last - stopped) * smooth((t - end) / DIE_TIME))


def loop_duration(keys, length, limits):
    """How long the head takes over an extra loop of `length`: about as long as it would take at its cruising
    pace, within limits, so it eases round instead of whipping through (and its tail does the same later)."""
    times, distances, _ = keys
    cruise = (distances[-1] - distances[0]) / max(1e-6, times[-1] - times[0]) if len(times) > 1 else 0.0
    return min(limits[1], max(limits[0], length / cruise if cruise > 1e-6 else limits[0]))


def curl_route(x, y, radius, lean=1.0, steps=40):
    """A graceful loop-de-loop for the thread: it rises from (x, y), swings once round a slightly tilted
    teardrop and carries on from where it started, so the ribbon itself draws the flourish."""
    points = []
    for k in range(steps + 1):
        a = k / steps
        theta = math.pi / 2 - lean * a * math.tau
        r = radius * (1 + 0.28 * math.sin(math.pi * a))
        drift = radius * 0.35 * math.sin(math.pi * a) * lean
        points.append((x + drift + r * math.cos(theta), y - radius + r * math.sin(theta)))
    points[-1] = (x, y)
    return points


def swash_route(x, y, cx, cy, rx, ry, tilt=-0.12, steps=56):
    """A calligraphic swash round a word: an open, tilted oval that swells and thins like a pen stroke,
    starting and ending where the thread meets it."""
    start = math.atan2((y - cy) / max(ry, 1e-6), (x - cx) / max(rx, 1e-6))
    points = [(x, y)]
    for k in range(steps + 1):
        a = k / steps
        theta = start + a * math.tau * 1.08
        swell = 1 + 0.12 * math.sin(a * math.pi * 2 + 0.6)
        px, py = rx * swell * math.cos(theta), ry * swell * math.sin(theta)
        points.append((cx + px * math.cos(tilt) - py * math.sin(tilt), cy + px * math.sin(tilt) + py * math.cos(tilt)))
    points.append((x, y))
    return points


def insert_thread_loop(pieces, distance, loop, color, shape=True):
    """Splice a closed route into the flowing path so its head and tail trace it. With shape=False the
    ribbon itself draws the route (a curl or swash) instead of revealing a filled shape."""
    result = []
    inserted = False
    for piece in pieces:
        points = piece['points']
        if not inserted and distance <= piece['start']:
            result.append(dict(points=loop, color=color, shape=shape))
            inserted = True
        if not inserted and piece['start'] < distance < piece['end']:
            remaining = distance - piece['start']
            for index, (a, b) in enumerate(zip(points, points[1:])):
                span = math.dist(a, b)
                if remaining <= span:
                    u = remaining / max(span, 1e-9)
                    knot = tuple(a[k] + (b[k] - a[k]) * u for k in range(len(a)))
                    result.extend(
                        (
                            dict(points=points[: index + 1] + [knot], color=piece['color']),
                            dict(points=loop, color=color, shape=shape),
                            dict(points=[knot] + points[index + 1 :], color=piece['color']),
                        )
                    )
                    inserted = True
                    break
                remaining -= span
            if inserted:
                continue
        result.append(dict(points=points, color=piece['color']))
    if not inserted:
        return 0.0
    travelled = 0.0
    for piece in result:
        piece['start'] = travelled
        travelled += sum(math.dist(a, b) for a, b in zip(piece['points'], piece['points'][1:]))
        piece['end'] = travelled
    pieces[:] = result
    return sum(math.dist(a, b) for a, b in zip(loop, loop[1:]))


def sample_thread(pieces, tail, head, step):
    """Evenly spaced (x, y, distance, colour) points along the thread, starting exactly at `tail` and
    ending exactly at `head` so both ends move every frame instead of in whole steps."""
    samples = []
    for piece in pieces:
        if piece['end'] <= tail or piece['start'] >= head:
            continue
        travelled = piece['start']
        for a, b in zip(piece['points'], piece['points'][1:]):
            length = math.dist(a, b)
            if length < 1e-6:
                continue
            first = max(tail, travelled)
            last = min(head, travelled + length)
            if first > last:
                travelled += length
                continue
            marks = [first, last]
            distance = math.ceil(first / step) * step
            while distance <= last:
                marks.append(distance)
                distance += step
            for distance in sorted(set(marks)):
                if not samples or distance > samples[-1][2] + 1e-6:
                    u = (distance - travelled) / length
                    position = tuple(a[k] + (b[k] - a[k]) * u for k in range(len(a)))
                    samples.append((*position, distance, piece['color']))
            travelled += length
    return samples


def monotone_keys(times, distances):
    """Monotone cubic (PCHIP) slopes through (time, distance) keys: the thread keeps moving forward, at a
    steady pace between keys, and its speed changes smoothly at each one instead of jumping."""
    deltas = [(d1 - d0) / (t1 - t0) for t0, t1, d0, d1 in zip(times, times[1:], distances, distances[1:])]
    if not deltas:
        return times, distances, [0.0] * len(times)
    slopes = [deltas[0]]
    for k in range(1, len(deltas)):
        h0, h1, a, b = times[k] - times[k - 1], times[k + 1] - times[k], deltas[k - 1], deltas[k]
        if a <= 0 or b <= 0:
            slopes.append(0.0)
        else:
            w1, w2 = 2 * h1 + h0, h1 + 2 * h0
            slopes.append((w1 + w2) / (w1 / a + w2 / b))
    slopes.append(deltas[-1])
    return times, distances, slopes


def settle_keys(keys, seconds=1.0):
    """The same timing with its last `seconds` replaced by a gentle braking stop: the head's speed eases from
    what it was to nothing (its acceleration changing smoothly too), instead of halting dead at the end."""
    times, distances, _ = keys
    if len(times) < 2:
        return keys
    end = times[-1]
    start = max(times[0], end - seconds)
    window = end - start
    if window <= 1e-3:
        return keys
    d0 = thread_distance(keys, start)
    v0 = (
        (d0 - thread_distance(keys, start - 1e-3)) / 1e-3
        if start - 1e-3 >= times[0]
        else (distances[1] - distances[0]) / max(1e-6, times[1] - times[0])
    )
    kept = [(t, d) for t, d in zip(times, distances) if t < start - 1e-6]
    braking = [(start + window * k / 12, d0 + v0 * window * (s - s**3 + s**4 / 2)) for k in range(13) for s in [k / 12]]
    clock, travelled = zip(*(kept + braking))
    return monotone_keys(list(clock), list(travelled))


def thread_distance(keys, t):
    """How far along the thread its head is at time t, or None before the first hero word."""
    times, distances, slopes = keys
    if not times or t < times[0]:
        return None
    if t >= times[-1]:
        return distances[-1]
    i = bisect.bisect_right(times, t) - 1
    h = times[i + 1] - times[i]
    u = (t - times[i]) / h
    return (
        (2 * u**3 - 3 * u * u + 1) * distances[i]
        + (u**3 - 2 * u * u + u) * h * slopes[i]
        + (-2 * u**3 + 3 * u * u) * distances[i + 1]
        + (u**3 - u * u) * h * slopes[i + 1]
    )
