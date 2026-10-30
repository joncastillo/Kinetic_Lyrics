"""A camera path through one continuous collage of every illustration.

The camera follows a smooth curve at a constant speed for the whole song: no braking, no
acceleration. The curve turns at each scene change (right, rising, falling, diagonal), and
each illustration is laid where the camera travels while it is current. Every canvas point
shows the picture whose stretch of path is nearest, with a soft seam where two pictures
meet, so the background is one continuous image the camera glides across, never a fade.
Only tiles under the camera are scaled, keeping memory small in every render worker.

The pictures are a distant layer. During its verse each picture drifts slower than the camera, just
enough that it is never enlarged more than MAX_ZOOM beyond filling the screen (stretching a picture
across a whole verse of camera travel blows it up into an unrecognisable blur). The pictures are laid
a screen apart, and at each verse change the background glides across to the next one, so at most two
pictures share the screen, meeting along a narrow wandering seam rather than overlapping like ghosts.
"""
import bisect
import math

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageOps

DIRECTIONS = ((1, 0), (1, .55), (1, -.5), (.6, .8), (1, 0), (.65, -.75), (1, .3))
# Greenscreen scenery keeps its horizon level, so the camera only travels along it.
ALONG_HORIZON = ((1, 0),)
SEAM = .012  # feather only the boundary between neighboring pictures
GLIDE = 1.6  # seconds the background takes to glide across to the next verse's picture
MAX_ZOOM = 1.4  # how far beyond exactly filling the screen a picture may be enlarged
CANVAS = (6, 9, 16)


def _smooth(value):
    value = np.clip(value, 0, 1)
    return value*value*(3-2*value)


class CameraPath:
    """Arc-length parametrised Catmull-Rom curve, so the camera moves at one constant speed."""

    def __init__(self, spans, speed, duration, directions=DIRECTIONS):
        points = [(0., 0.)]
        for index, (start, end) in enumerate(spans):
            dx, dy = directions[index % len(directions)]
            norm = math.hypot(dx, dy)
            length = speed*max(.5, end-start)
            points.append((points[-1][0]+dx/norm*length, points[-1][1]+dy/norm*length))
        padded = [points[0]]+points+[points[-1]]
        self.samples = []
        for i in range(1, len(padded)-2):
            p0, p1, p2, p3 = padded[i-1:i+3]
            for step in range(24):
                u = step/24
                self.samples.append(tuple(.5*(2*b+(-a+c)*u+(2*a-5*b+4*c-d)*u*u+(-a+3*b-3*c+d)*u**3)
                                          for a, b, c, d in zip(p0, p1, p2, p3)))
        self.samples.append(points[-1])
        self.lengths = [0.]
        for a, b in zip(self.samples, self.samples[1:]):
            self.lengths.append(self.lengths[-1]+math.hypot(b[0]-a[0], b[1]-a[1]))
        self.speed = self.lengths[-1]/max(1e-6, duration)

    def at(self, t):
        distance = min(self.lengths[-1], max(0., self.speed*t))
        i = min(len(self.samples)-1, max(1, bisect.bisect_left(self.lengths, distance)))
        span = self.lengths[i]-self.lengths[i-1] or 1.
        u = (distance-self.lengths[i-1])/span
        a, b = self.samples[i-1], self.samples[i]
        return a[0]+(b[0]-a[0])*u, a[1]+(b[1]-a[1])*u


def open_rgb(path):
    with Image.open(path) as source:
        return source.convert('RGB')


class WorldCanvas:
    """`load` turns a path into the tile picture. An 'L' canvas holds greenscreen mattes: at seams it keeps
    whatever either picture covers, so lyrics never show through scenery while two pictures blend."""

    def __init__(self, paths, spans, width, height, path, reach=1., bleed=0., load=open_rgb, mode='RGB'):
        """`reach` is how many screens' worth of canvas the camera looks at directly (more than one for a 3D
        camera that moves closer and further), and every picture covers it. `bleed` (in screens) extends each
        picture with mirrored edges for what an oblique camera glimpses at the far edge of its view."""
        self.W, self.H = width, height
        self.load, self.mode = load, mode
        self.fill = CANVAS if mode == 'RGB' else 0
        self.seam = width*SEAM
        width, height = width*reach, height*reach
        self.path, self.spans = path, spans[:len(paths)]
        margin = round(self.seam+bleed*self.W)
        self.drift, self.base, self.tiles = [], [], []
        end = np.zeros(2)
        for index, (source, (start, stop)) in enumerate(zip(paths, self.spans)):
            local = np.array([path.at(start+(stop-start)*k/16) for k in range(17)])-np.array(path.at(start))
            with Image.open(source) as image:
                iw, ih = image.size
            fill = max(width/iw, height/ih)
            rate = 1.
            for axis, screen, size in ((0, width, iw), (1, height, ih)):
                extent = np.ptp(local[:, axis])
                if extent > 1e-6:
                    rate = min(rate, max(0., MAX_ZOOM*fill*size-screen)/extent)
            if index:
                heading = np.array(path.at(start+min(GLIDE, (stop-start)/2)))-np.array(path.at(self.spans[index-1][0]))
                heading = heading/max(1e-6, np.linalg.norm(heading)) if np.linalg.norm(heading) > 1e-6 else np.array((1., 0.))
                crossing = 1/max(abs(heading[0])/width, abs(heading[1])/height)  # one screen along the heading
                base = end+heading*crossing
            else:
                base = np.zeros(2)
            centers = base+local*rate
            end = centers[-1]
            self.drift.append(rate)
            self.base.append(base)
            core = (np.ptp(centers[:, 0])+width, np.ptp(centers[:, 1])+height)
            left, top = centers[:, 0].min()-width/2-margin, centers[:, 1].min()-height/2-margin
            self.tiles.append(dict(path=source, x=round(left), y=round(top), width=round(core[0])+2*margin,
                                   height=round(core[1])+2*margin, margin=margin, centers=centers))
        self._scaled = {}

    def _resting(self, index, t):
        start = self.spans[index][0]
        offset = np.array(self.path.at(t))-np.array(self.path.at(start))
        return self.base[index]+offset*self.drift[index]

    def at(self, t):
        """Canvas position the backdrop is centred on at time t: drifting slowly within a verse, gliding
        across to the next picture when the verse changes."""
        starts = [start for start, _ in self.spans]
        index = max(0, bisect.bisect_right(starts, t)-1)
        here = self._resting(index, t)
        if index and t < starts[index]+GLIDE:
            u = _smooth((t-starts[index])/GLIDE)
            there = self._resting(index-1, starts[index])
            here = there+(here-there)*u
        return float(here[0]), float(here[1])

    def tile_image(self, index):
        if index not in self._scaled:
            if len(self._scaled) >= 3:
                self._scaled.pop(next(iter(self._scaled)))
            spec = self.tiles[index]
            m = spec['margin']
            # Cover only what the camera can see; the seam margins mirror the picture's own edges.
            core = ImageOps.fit(self.load(spec['path']), (spec['width']-2*m, spec['height']-2*m), Image.Resampling.LANCZOS)
            pixels = np.asarray(core)
            while m > 0:  # mirror repeatedly when the bleed is wider than the picture itself
                step = min(m, pixels.shape[0]-1, pixels.shape[1]-1)
                pixels = np.pad(pixels, ((step, step), (step, step))+((0, 0),)*(pixels.ndim-2), mode='symmetric')
                m -= step
            self._scaled[index] = Image.fromarray(pixels)
        return self._scaled[index]

    def view(self, left, top, width, height):
        """Canvas pixels in the rectangle: each point from the picture whose path is nearest, blended softly at seams."""
        touching = [i for i, spec in enumerate(self.tiles)
                    if spec['x'] < left+width and spec['x']+spec['width'] > left and spec['y'] < top+height and spec['y']+spec['height'] > top]
        view = Image.new(self.mode, (width, height), self.fill)
        if not touching:
            return view.convert('RGBA') if self.mode == 'RGB' else view
        grid_w, grid_h = max(2, width//8), max(2, height//8)
        xs = left+(np.arange(grid_w)+.5)*width/grid_w
        ys = top+(np.arange(grid_h)+.5)*height/grid_h
        gx, gy = np.meshgrid(xs, ys)
        distances = []
        for index in touching:
            spec = self.tiles[index]
            centers = spec['centers']
            d = np.min(np.hypot(gx[..., None]-centers[:, 0], gy[..., None]-centers[:, 1]), axis=-1)
            inside = (gx >= spec['x']) & (gx < spec['x']+spec['width']) & (gy >= spec['y']) & (gy < spec['y']+spec['height'])
            distances.append(np.where(inside, d, np.inf))
        # Pick one painting at each point, then feather that ownership mask in image space. Blending
        # distance scores directly makes a shallow distance gradient mix whole paintings together.
        distances = [d+self.seam*.8*np.sin(gx*.0041+index*1.7)*np.cos(gy*.0053+index*2.3)
                     for d, index in zip(distances, touching)]
        scores = np.stack(distances)
        owner = np.argmin(scores, axis=0)
        valid = np.isfinite(np.min(scores, axis=0))
        total = np.zeros((height, width), dtype='float32')
        for slot, index in enumerate(touching):
            mask = Image.fromarray(((owner == slot) & valid).astype('uint8')*255, 'L')
            mask = mask.resize((width, height), Image.Resampling.NEAREST).filter(ImageFilter.GaussianBlur(self.seam))
            weight = np.asarray(mask, dtype='float32')/255
            total = total+weight
            share = np.divide(weight, total, out=np.zeros_like(weight), where=total > 0)
            if not share.any():
                continue
            spec = self.tiles[index]
            region = (max(left, spec['x'])-spec['x'], max(top, spec['y'])-spec['y'],
                      min(left+width, spec['x']+spec['width'])-spec['x'], min(top+height, spec['y']+spec['height'])-spec['y'])
            piece = Image.new(self.mode, (width, height), self.fill)
            piece.paste(self.tile_image(index).crop(region), (region[0]+spec['x']-left, region[1]+spec['y']-top))
            mask = Image.fromarray((share*255).astype('uint8'), 'L')
            if self.mode == 'L':
                view = ImageChops.lighter(view, ImageChops.multiply(piece, mask.point(lambda v: 255 if v else 0)))
            else:
                view = Image.composite(piece, view, mask)
        return view.convert('RGBA') if self.mode == 'RGB' else view
