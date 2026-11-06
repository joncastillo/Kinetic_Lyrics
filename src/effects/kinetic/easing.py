"""Easing curves for kinetic type. All map 0 -> 0 and 1 -> 1 exactly, so rest poses are exact."""
import math


def clamp(value, low=0., high=1.):
    return low if value < low else high if value > high else value


def window(value, start, end):
    """0 before `start`, 1 after `end`, linear between."""
    return clamp((value-start)/max(1e-6, end-start))


def smooth(q):
    q = clamp(q)
    return q*q*(3-2*q)


def smoother(q):
    q = clamp(q)
    return q*q*q*(q*(q*6-15)+10)


def expo_out(q):
    q = clamp(q)
    return (1-2**(-10*q))/(1-2**-10)


def circ_in_out(q):
    q = clamp(q)
    if q < .5:
        return (1-math.sqrt(1-(2*q)**2))/2
    return (math.sqrt(1-(-2*q+2)**2)+1)/2


def back_out(q, overshoot=1.70158):
    q = clamp(q)
    c3 = overshoot+1
    return 1+c3*(q-1)**3+overshoot*(q-1)**2


def spring(q, frequency=7., damping=.35):
    """A damped spring from 0 to 1 that lands exactly on 1 at q=1 (the tail is blended out)."""
    q = clamp(q)
    if q >= 1:
        return 1.
    raw = 1-math.exp(-q*frequency*damping*2.2)*math.cos(q*frequency)
    tail = smoother((q-.75)/.25) if q > .75 else 0.
    return raw*(1-tail)+tail


def keyframes(q, keys, ease=None):
    """Pose-to-pose interpolation through [(time, value or tuple), ...], eased between keys (in-out circ by
    default: hold, snap, hold - the motion-graphics look)."""
    ease = ease or circ_in_out
    q = clamp(q)
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if q <= t1:
            f = ease(window(q, t0, t1))
            if isinstance(v0, tuple):
                return tuple(a+(b-a)*f for a, b in zip(v0, v1))
            return v0+(v1-v0)*f
    return keys[-1][1]


def pulse(q):
    """0 -> 1 -> 0 hump."""
    q = clamp(q)
    return math.sin(math.pi*q)
