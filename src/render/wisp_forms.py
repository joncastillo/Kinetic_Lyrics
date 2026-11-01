"""Small lyric-shaped heads for the travelling typography ribbon."""

import math
import re


FORMS = (
    ('jet', ('jet', 'fighter plane', 'fighter jet', 'eroplano de kombate')),
    ('airplane', ('airplane', 'aeroplane', 'aircraft', 'plane', 'flight', 'flying', 'eroplano', 'lipad')),
    ('comet', ('comet', 'meteor', 'shooting star', 'rocket', 'kometa', 'bulalakaw')),
    ('ball', ('ball', 'soccer', 'basketball', 'football', 'sphere', 'bola')),
    ('bird', ('bird', 'wings', 'sparrow', 'ibon', 'pakpak')),
    ('heart', ('heart', 'love', 'puso', 'mahal', 'pag-ibig')),
    ('leaf', ('leaf', 'leaves', 'forest', 'tree', 'dahon', 'puno')),
    ('star', ('star', 'stars', 'bituin', 'constellation')),
    ('drop', ('rain', 'tears', 'water', 'ulan', 'luha', 'tubig')),
)


def form_for(word, line=''):
    """Prefer the hero word; use its lyric line when the hero itself is abstract."""
    for text in (word, line):
        cleaned = ' '.join(re.findall(r'\w+', text.casefold()))
        for kind, keywords in FORMS:
            if any(re.search(r'(?<!\w)'+re.escape(key)+r'(?!\w)', cleaned) for key in keywords):
                return kind
    return 'orb'


def forms_at(forms, t, blend=.32):
    """Crossfade forms around a lyric cue; no frame history is needed."""
    if not forms:
        return [('orb', 1.)]
    index = max((i for i, (when, _) in enumerate(forms) if when <= t+blend/2), default=0)
    if index == 0:
        return [(forms[0][1], 1.)]
    when, kind = forms[index]
    u = max(0., min(1., (t-when+blend/2)/blend))
    u = u*u*(3-2*u)
    prior = forms[index-1][1]
    return [(prior, 1-u), (kind, u)] if prior != kind else [(kind, 1.)]


def heading_at(pieces, distance, look=18.):
    """Average the route across a short arc so icons bank through bends smoothly."""
    from render.realtime import sample_thread

    end = pieces[-1]['end'] if pieces else 0.
    a, b = max(0., distance-look), min(end, distance+look)
    points = sample_thread(pieces, a, b, max(1., b-a))
    if len(points) < 2:
        return 0.
    return math.atan2(points[-1][1]-points[0][1], points[-1][0]-points[0][0])


def paint_head(draw, x, y, angle, kind, alpha, size, phase=0.):
    """Draw one legible flat icon facing its direction of travel."""
    alpha = max(0, min(255, round(alpha)))
    if alpha <= 0:
        return
    c, s = math.cos(angle), math.sin(angle)
    def point(px, py):
        return x+size*(px*c-py*s), y+size*(px*s+py*c)
    def polygon(points, color):
        draw.polygon([point(*p) for p in points], fill=(*color, alpha))
    white = (255, 255, 250)
    if kind == 'orb':
        # A will-o'-the-wisp, not a solid disc: a flickering flame that trails away from its direction of travel,
        # a pale blue-green halo around a small bright core. The trace layer's blur turns it into soft light.
        flicker = .82+.18*math.sin(phase*11.3)+.08*math.sin(phase*23.7)
        sway = .1*math.sin(phase*7.1)
        def flame(scale, color, opacity):
            tail = 1.55*flicker*scale
            points = [(math.cos(theta)*.5*scale, math.sin(theta)*.5*scale)
                      for theta in (math.tau*k/16 for k in range(-4, 5))]  # the rounded front half
            points += [(-.35*scale, .42*scale), (-tail*.7, (.2+sway)*scale), (-tail, sway*scale),
                       (-tail*.7, (-.2+sway)*scale), (-.35*scale, -.42*scale)]
            draw.polygon([point(*p) for p in points], fill=(*color, max(0, min(255, round(alpha*opacity)))))
        flame(1.25, (150, 236, 222), .38)
        flame(.85, (214, 252, 240), .7)
        draw.ellipse((x-size*.2, y-size*.2, x+size*.2, y+size*.2), fill=(*white, alpha))
    elif kind == 'ball':
        draw.ellipse((x-size*.65, y-size*.65, x+size*.65, y+size*.65), fill=(*white, alpha))
        spin = phase*3
        for offset in (-.22, .22):
            a, b = point(offset*math.cos(spin)-.33, -.4), point(offset*math.cos(spin)+.33, .4)
            draw.line((a, b), fill=(70, 130, 190, alpha), width=max(1, round(size*.1)))
    elif kind == 'airplane':
        polygon(((1.15, 0), (.1, -.19), (-.68, -.88), (-.94, -.73), (-.49, -.05),
                 (-1.03, -.04), (-1.03, .04), (-.49, .05), (-.94, .73),
                 (-.68, .88), (.1, .19)), white)
        polygon(((1.08, 0), (.33, -.11), (.33, .11)), (88, 221, 255))
    elif kind == 'jet':
        polygon(((1.2, 0), (-.36, -.24), (-.76, -.87), (-.99, -.85), (-.68, -.08),
                 (-1.02, -.07), (-1.02, .07), (-.68, .08), (-.99, .85),
                 (-.76, .87), (-.36, .24)), white)
        polygon(((-1.02, -.12), (-1.45, 0), (-1.02, .12)), (255, 140, 82))
    elif kind == 'comet':
        polygon(((-2.1, -.38), (-.1, -.28), (.38, 0), (-.1, .28), (-2.1, .38),
                 (-1.25, 0)), (89, 204, 255))
        draw.ellipse((x-size*.5, y-size*.5, x+size*.5, y+size*.5), fill=(*white, alpha))
    elif kind == 'bird':
        wing = .55+.18*math.sin(phase*8)
        polygon(((1.1, 0), (-.2, -.16), (-.95, -wing), (-.52, .02),
                 (-.95, wing), (-.2, .16)), white)
    elif kind == 'heart':
        points = []
        for k in range(20):
            theta = math.tau*k/20
            hx = 16*math.sin(theta)**3/18
            hy = -(13*math.cos(theta)-5*math.cos(2*theta)-2*math.cos(3*theta)-math.cos(4*theta))/18
            points.append((hx*.75, hy*.75))
        polygon(points, (255, 111, 156))
    elif kind == 'leaf':
        polygon(((1., 0), (.12, -.53), (-1., 0), (.12, .53)), (160, 240, 172))
        draw.line((point(-.8, 0), point(.8, 0)), fill=(*white, alpha), width=1)
    elif kind == 'star':
        polygon([(math.cos(k*math.pi/5)*(1. if k % 2 == 0 else .42),
                  math.sin(k*math.pi/5)*(1. if k % 2 == 0 else .42)) for k in range(10)],
                (255, 225, 132))
    else:  # drop
        polygon(((.95, 0), (-.16, -.63), (-.68, -.4), (-.95, 0),
                 (-.68, .4), (-.16, .63)), (118, 218, 255))
