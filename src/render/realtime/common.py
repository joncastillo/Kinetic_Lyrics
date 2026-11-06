"""Shared constants and drawing helpers for the flow."""
import json
import math
from pathlib import Path
from PIL import ImageChops

FUNCTION_WORDS = frozenset('''
a an and are as at be but by for from i if in is it its me my of on or our so than that the their them they this to
too up us was we were what when where which who will with you your i'm don't can't won't im
ang ng sa mga at ay ko ka na ni si kay ito iyan iyon ako ikaw siya kami tayo kayo sila ka'y ko'y
'''.split())
ROLE_FONTS = {'function': ('cour.ttf', 'georgiai.ttf', 'DejaVuSansMono.ttf'),
              'content': ('ariblk.ttf', 'seguibl.ttf', 'DejaVuSans-Bold.ttf'),
              'hero': ('impact.ttf', 'bahnschrift.ttf', 'DejaVuSansCondensed-Bold.ttf')}
ROLE_SCALE = {'function': .6, 'content': 1., 'hero': 2.2}
HOT_COLORS = ('#FF3D7F', '#FFD23F')
BACKDROP_COLORS = ('#FF3D7F', '#4CC9FF', '#FFD23F')
MARGIN, MIN_WIDTH, MIN_HEIGHT, LEAD_WIDTH = .04, .42, .3, .55
LINE_LINGER = 1.5
BACKDROP_FADE, UNDERLINE_LINGER = .8, .6
BANDS = 3
BAND_UNIT = .014
BAND_ALPHA = 46
STRAND_STEP = 6.
HALO_CACHE = 96  # knockout halos kept per renderer: enough for every word on screen
# The wisp leads the singing: its head reaches each hero word this many seconds early, and the
# first hero word of a line this long before the line starts.
THREAD_LEAD = .8
# Once per song a second wisp joins the first and they braid together for about this share of
# the song; that is the only time the wisps change colour.
DUET_SHARE = .2
DUET_EASE = 1.2
DUET_COLORS = ('#FF3D7F', '#4CC9FF', '#FFD23F', '#8A6BFF')
INSTRUMENT_GLOWS = {'drums': ('#FF3D7F', .18),
                    'other': ('#FFD23F', .3),
                    'bass': ('#8A6BFF', .4)}
WORD_SHAPE_FILL, WORD_SHAPE_FADE = 60, .6
MIN_SHAPE_CONTRAST = 3.
MIN_GLOW_CONTRAST = 1.5
SHAPE_COLORS = ('#FF3D7F', '#4CC9FF', '#FFD23F', '#8A6BFF', '#F2F2F2', '#16243F', '#3B1230', '#0E3B43')
FRAME_RETRACT = .9
SHAPES = ('triangle', 'square', 'hexagon')
SHAPE_LIFE = 3.2
LINE_FRAMES = ('ellipse', 'frame', 'hexagon', 'diamond')
ROW_LEADING = .12  # gap between the rows of one line, as a share of its base size
LINE_GAP = .05  # clear space between separate lines on the canvas, as a share of the screen height
HIDE_TIME = .5
TRACE_TIME = (1.5, 6.)  # seconds the wisp may take round a traced shape
CURL_TIME = (1.2, 4.)
BASE_SCALE = .75
OLDER_LINES, DIM_TIME, FADE_TIME = .5, .8, 1.2
STILL_HOLD = 6.
STILL_EXIT = .8
PARTICLE_ENTRY = .6
DISPLAY_ROLES = ('content', 'hero')  # roles that take the font the user chose; function words keep their contrast
_chosen_font = None
def overshoot(value):
    value = max(0., min(1., value))-1
    return 1+2.4*value**3+1.4*value**2


def shape_outline(kind, left, top, right, bottom, pad):
    """Closed outline of a shape fitted around a box, starting at its left-middle point."""
    cx, cy = (left+right)/2, (top+bottom)/2
    rx, ry = (right-left)/2+pad, (bottom-top)/2+pad
    if kind == 'ellipse':
        rx, ry = rx*1.12, ry*1.25
        return [(cx+rx*math.cos(a), cy+ry*math.sin(a)) for a in (math.pi+2*math.pi*k/72 for k in range(73))]
    if kind == 'frame':
        corners = [(cx-rx, cy), (cx-rx, cy-ry), (cx+rx, cy-ry), (cx+rx, cy+ry), (cx-rx, cy+ry)]
    elif kind == 'hexagon':
        corners = [(cx+rx*1.08*math.cos(a), cy+ry*1.15*math.sin(a)) for a in (math.pi+math.pi/3*k for k in range(6))]
    else:
        corners = [(cx-rx*1.25, cy), (cx, cy-ry*1.4), (cx+rx*1.25, cy), (cx, cy+ry*1.4)]
    return rounded(corners, cy)


def rounded(corners, cy, passes=4):
    """Corner-cut a closed polygon into a smooth loop that starts at its left-middle point."""
    ring = list(corners)
    for _ in range(passes):
        ring = [point for a, b in zip(ring, ring[1:]+ring[:1])
                for point in ((.75*a[0]+.25*b[0], .75*a[1]+.25*b[1]), (.25*a[0]+.75*b[0], .25*a[1]+.75*b[1]))]
    start = min(range(len(ring)), key=lambda i: (round(ring[i][0]), abs(ring[i][1]-cy)))
    ring = ring[start:]+ring[:start]
    return ring+[ring[0]]


def inside(polygon, point):
    """Even-odd test: is the point inside the closed polygon?"""
    x, y = point
    result = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:]+polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0+(y-y0)*(x1-x0)/(y1-y0):
            result = not result
    return result


def direction(a, b):
    length = math.hypot(b[0]-a[0], b[1]-a[1]) or 1.
    return (b[0]-a[0])/length, (b[1]-a[1])/length


def polyline_length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def thread_curve(previous, stop, wanted, side, most=2.5):
    """Cubic curve between two thread stops, leaving and arriving along their directions, bowed sideways
    until it is about `wanted` long (never more than `most` times the straight distance)."""
    a, b = previous['anchor'], stop['anchor']
    span = math.dist(a, b) or 1.
    normal = ((a[1]-b[1])/span*side, (b[0]-a[0])/span*side)

    def curve(bow):
        reach = span*.45
        c1 = (a[0]+previous['leave'][0]*reach+normal[0]*bow, a[1]+previous['leave'][1]*reach+normal[1]*bow)
        c2 = (b[0]-stop['arrive'][0]*reach+normal[0]*bow, b[1]-stop['arrive'][1]*reach+normal[1]*bow)
        return [((1-u)**3*a[0]+3*(1-u)**2*u*c1[0]+3*(1-u)*u*u*c2[0]+u**3*b[0],
                 (1-u)**3*a[1]+3*(1-u)**2*u*c1[1]+3*(1-u)*u*u*c2[1]+u**3*b[1]) for u in (k/48 for k in range(49))]
    target = min(wanted, span*most)
    low, high = 0., span*2
    if polyline_length(curve(0.)) >= target:
        return curve(0.)
    for _ in range(18):
        middle = (low+high)/2
        low, high = (middle, high) if polyline_length(curve(middle)) < target else (low, middle)
    return curve(low)


def add_piece(pieces, points, color, total):
    length = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(points, points[1:]))
    if length > 1e-6:
        pieces.append(dict(points=points, color=color, start=total, end=total+length))
    return total+length


def strand_normals(samples):
    normals = []
    for i in range(len(samples)):
        a, b = samples[max(0, i-1)], samples[min(len(samples)-1, i+1)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = math.hypot(dx, dy) or 1.
        normals.append((-dy/length, dx/length))
    return normals


def mix_rgb(a, b, amount):
    return tuple(round(x+(y-x)*amount) for x, y in zip(a, b))


def recolor(samples, color):
    return [(x, y, distance, color) for x, y, distance, _ in samples]


def group_by_color(points):
    """Consecutive runs of points sharing a colour, overlapping by one point so runs join up."""
    runs, current, color = [], [], None
    for x, y, c in points:
        if c != color and current:
            runs.append((color, current+[(x, y)]))
            current = []
        color = c
        current.append((x, y))
    if len(current) >= 2:
        runs.append((color, current))
    return runs


def trace_outline(draw, points, start, end, color, width, alpha=210):
    """Draw the part of a closed outline between two fractions of its perimeter, with a bright head
    while it is still drawing on, so shapes are traced in and erased rather than faded."""
    if end <= start:
        return
    lengths = [0.]
    for a, b in zip(points, points[1:]):
        lengths.append(lengths[-1]+math.hypot(b[0]-a[0], b[1]-a[1]))
    def at(distance):
        for (a, b), first, last in zip(zip(points, points[1:]), lengths, lengths[1:]):
            if distance <= last:
                u = (distance-first)/max(1e-6, last-first)
                return a[0]+(b[0]-a[0])*u, a[1]+(b[1]-a[1])*u
        return points[-1]
    total = lengths[-1]
    begin, finish = total*start, total*end
    path = [at(begin)]+[p for p, d in zip(points, lengths) if begin < d < finish]+[at(finish)]
    draw.line(path, fill=(*color, alpha), width=width, joint='curve')


def paste_lighter(mask, sprite, x, y):
    """Merge a greyscale sprite into a mask at (x, y), keeping the brighter value, clipped to the mask."""
    box = (max(0, -x), max(0, -y), min(sprite.width, mask.width-x), min(sprite.height, mask.height-y))
    if box[2] > box[0] and box[3] > box[1]:
        at = (max(0, x), max(0, y), max(0, x)+box[2]-box[0], max(0, y)+box[3]-box[1])
        mask.paste(ImageChops.lighter(mask.crop(at), sprite.crop(box)), at[:2])


def paste_clipped(layer, sprite, x, y):
    box = (max(0, -x), max(0, -y), min(sprite.width, layer.width-x), min(sprite.height, layer.height-y))
    if box[2] > box[0] and box[3] > box[1]:
        layer.alpha_composite(sprite.crop(box), (max(0, x), max(0, y)))


def melody_for(folder):
    """Cached melody features from a project folder, if present."""
    try:
        return json.loads((Path(folder)/'video.melody.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
