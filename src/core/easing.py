"""Easing curves shared by the renderers and effects.

Modules used to define their own `ease` and `smooth`, and the same name meant different curves in different files
(cubic ease-out in the compositor and cinema, smoothstep in the scene mix). Each curve now
has one definition and a name that says which it is; modules import it under their own local name.
All of them clamp their input to 0..1 first.
"""

import numpy as np


def smoothstep(value):
    """3v^2 - 2v^3 for one number: slow, faster, slow."""
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def smoothstep_array(value):
    """smoothstep() over a NumPy array (or a number), element by element."""
    value = np.clip(value, 0, 1)
    return value * value * (3 - 2 * value)


def cubic_out(value):
    """Fast start, soft landing: 1 - (1 - v)^3."""
    value = max(0.0, min(1.0, value))
    return 1 - (1 - value) ** 3
