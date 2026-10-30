"""Deterministic cloth surfaces for the silk lettering entrance.

Each letter starts as a separate, continuous sheet.  Its centre follows a curved wind path while the
free end lags under gravity.  Travelling air waves bend the sheet, and a varying roll twists its cross
sections.  A fold front then draws successive sections onto the letter's stroke route.  The free and
settled surfaces are blended in material coordinates, so a point never jumps to a different place on
the cloth between frames.
"""
import math

import numpy as np
from scipy.ndimage import gaussian_filter

from effects.materials.fx import sm, smooth

ROWS, COLS = 96, 30
CAMERA_DISTANCE = 8.0

FLIGHTS = (
    (-1.65, -.35, .32),
    (1.45, -1.15, -.42),
    (-.65, 1.55, .48),
    (1.65, .52, -.28),
    (-1.25, -1.25, .38),
    (.5, 1.65, -.42),
)


def letter_route(F, lo, hi):
    """Resample the skeleton of one glyph as a smooth centreline with local stroke widths."""
    from effects.materials.recipes import silk_strokes

    def build():
        strokes = silk_strokes(F, lo, hi)
        if len(strokes) < 2:
            return None
        xy = np.array([(x, y) for x, y, _, _ in strokes], dtype=float)/F.u
        half = np.array([w for _, _, w, _ in strokes], dtype=float)/F.u
        drawn = np.array([d for _, _, _, d in strokes], dtype=bool)
        arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        if arc[-1] < .01:
            return None
        distance = np.linspace(0., arc[-1], ROWS)
        points = np.stack([np.interp(distance, arc, xy[:, c]) for c in range(2)], -1)
        segment = np.clip(np.searchsorted(arc, distance, side='right')-1, 0, len(drawn)-2)
        on = drawn[segment+1]
        on[0] = True
        points = gaussian_filter(points, (1., 0.), mode='nearest')
        tangent = gaussian_filter(np.gradient(points, axis=0), (2., 0.), mode='nearest')
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-8)
        normal = np.stack((-tangent[:, 1], tangent[:, 0]), -1)
        width = np.maximum(gaussian_filter(np.interp(distance, arc, half), 2.)*1.08, .035)
        return dict(points=points, normal=normal, half=width, on=on, length=arc[-1])

    return F.memo(('silk-route-v2', int(lo), int(hi)), build)


def word_cloth(F):
    """One flight path and one target surface per visible letter."""
    from effects.materials.recipes import silk_letter_spans

    def build():
        spans = silk_letter_spans(F)
        letters = []
        for index, (left, right) in enumerate(spans):
            lo = (spans[index-1][1]+left)/2 if index else left-F.u*.35
            hi = (right+spans[index+1][0])/2 if index+1 < len(spans) else right+F.u*.35
            route = letter_route(F, lo, hi)
            if route is None:
                continue
            glyph = F.ink[:, max(0, int(lo)):min(F.W, int(hi))]
            ys, xs = np.nonzero(glyph > .35)
            if not len(xs):
                continue
            centre = np.array(((xs.mean()+lo)/F.u, ys.mean()/F.u))
            offset_x, offset_y, bend = FLIGHTS[index % len(FLIGHTS)]
            phase = index*1.37+F.seed*.021
            letters.append(dict(index=index, route=route, centre=centre,
                                start=centre+np.array((offset_x, offset_y)), bend=bend, phase=phase,
                                length=1.65+.15*(index % 3), width=.98+.08*(index % 2)))
        return dict(letters=letters, spans=spans)

    return F.memo('silk-cloth-v2', build)


def grid_normals(points):
    along = np.gradient(points, axis=0)
    across = np.gradient(points, axis=1)
    normal = np.cross(along, across)
    normal /= np.maximum(np.linalg.norm(normal, axis=-1, keepdims=True), 1e-8)
    tangent = along/np.maximum(np.linalg.norm(along, axis=-1, keepdims=True), 1e-8)
    return normal, tangent


def sheet(F, t, cloth, k):
    """A deforming satin surface in pixels, sampled at an arbitrary entrance progress."""
    letter = cloth['letters'][k]
    if t <= 0:
        return None
    route = letter['route']
    s = np.linspace(0., 1., ROWS)[:, None]
    w = np.linspace(-1., 1., COLS)[None, :]
    phase = letter['phase']

    # A curved carrying wind moves the sheet toward the glyph.  The trailing end lags and hangs lower;
    # its acceleration is proportional to gravity until the arriving stroke begins to support it.
    arrival = sm(t, .015, .78)
    start, end = letter['start'], letter['centre']
    chord = end-start
    heading = chord/max(np.linalg.norm(chord), 1e-8)
    sideways = np.array((-heading[1], heading[0]))
    centre = start+chord*arrival+sideways*letter['bend']*math.sin(math.pi*arrival)
    trailing = (1-s)**1.7
    gravity = .26*(.35+arrival)*trailing
    # Wind pulses travel down the length of the sheet.  Their phase advances through several folds
    # during flight, so a nearby frame has a visibly different contour rather than a translated copy.
    pulse = math.tau*(s*1.12-t*2.05)+phase
    gust = (.15*np.sin(pulse)
            +.055*np.sin(math.tau*(s*2.2-t*2.9)-phase*.61))*(.35+.65*trailing)
    fold_front = .31+.17*s
    gathered = smooth(t-fold_front, 0., .46)
    free_axis = (s-.5)*letter['length']
    free_xy = centre+free_axis[..., None]*heading+gust[..., None]*sideways
    free_xy = np.broadcast_to(free_xy, (ROWS, COLS, 2)).copy()
    free_xy[..., 1] += gravity

    # Roll each cross section about the lengthwise thread.  This makes real front/back turns and changes
    # the silhouette, unlike a brightness wave painted onto a flat rectangle.
    edge = .78+.22*np.sin(np.pi*s)**.7
    edge = edge+.11*np.sin(math.tau*(s*1.65-t*2.25)+phase)*w
    lateral = w*letter['width']*.5*edge
    roll = .88*np.sin(math.tau*(s*.85-t*1.7)+phase)+.29*np.sin(math.tau*(s*1.55-t*2.45)-phase)
    free_xy += lateral[..., None]*sideways*np.cos(roll)[..., None]
    free_z = lateral*np.sin(roll)
    free_z += .15*np.sin(math.tau*(s*1.3+w*.78-t*1.9)+phase)
    free_z += .055*np.sin(math.tau*(s*2.4-w*1.3-t*2.7)-phase*.5)
    # The long free edges lag behind the pressure wave, then lift and fall.  The displacement is largest
    # away from the supported leading edge, giving the sheet an actual flapping silhouette in projection.
    edge_flap = .19*np.abs(w)**1.8*(.3+.7*trailing)*np.sin(pulse-1.0)
    free_z += edge_flap
    free_xy += (edge_flap*.45)[..., None]*sideways

    # As the fold front reaches a section of cloth, its centre follows the actual stroke centreline.
    # Width contracts in projection while the excess cloth rises into rounded transverse pleats.
    target_xy = route['points'][:, None, :]+route['normal'][:, None, :]*(w*route['half'][:, None])[..., None]
    pleat = np.sin(math.tau*(w*1.35+s*.36)+phase)
    target_z = .10*pleat+.045*np.sin(math.tau*(w*2.5-s*.62)+phase*.7)
    morph = gathered[..., None]
    xy = free_xy*(1-morph)+target_xy*morph
    z = free_z*(1-gathered)+target_z*gathered

    # The shallow camera gives the turned edge a little parallax without enlarging the fabric wildly.
    scale = CAMERA_DISTANCE/np.maximum(CAMERA_DISTANCE*.6, CAMERA_DISTANCE-z)
    camera = np.array((F.cx/F.u, F.cy/F.u))
    points = np.empty((ROWS, COLS, 3))
    points[..., :2] = (camera+(xy-camera)*scale[..., None])*F.u
    points[..., 2] = z*F.u
    cavity = np.clip(-np.gradient(np.gradient(z, axis=1), axis=1)*2.5, 0, 1)
    visible = (1-sm(t, .70, .96)*(1-route['on'][:, None]))*sm(t, 0, .07)
    visible = np.broadcast_to(visible, (ROWS, COLS))
    arc = np.broadcast_to(s*route['length'], (ROWS, COLS))
    across = np.broadcast_to(w, (ROWS, COLS))
    density = np.broadcast_to(gathered, (ROWS, COLS))
    return dict(points=points, visible=visible, arc=arc, w=across, cavity=cavity, density=density)
