"""Colour notation shared by direction, rendering and effects: '#RRGGBB' text and (r, g, b) tuples of 0-255."""


def hex_rgb(value):
    """(r, g, b) from '#RRGGBB' or 'RRGGBB'."""
    value = value.lstrip('#')
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def rgb_hex(rgb):
    """'#RRGGBB' from (r, g, b); values are rounded and kept within 0-255."""
    return '#%02X%02X%02X' % tuple(int(round(max(0, min(255, v)))) for v in rgb[:3])
