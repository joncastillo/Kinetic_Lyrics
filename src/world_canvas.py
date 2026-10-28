"""A camera path through one continuous collage of every illustration.

The camera follows a smooth curve at a constant speed for the whole song: no braking, no
acceleration. The curve turns at each scene change (right, rising, falling, diagonal), and
each illustration is laid where the camera travels while it is current. Every canvas point
shows the picture whose stretch of path is nearest, with a soft seam where two pictures
meet, so the background is one continuous image the camera glides across, never a fade.
Only tiles under the camera are scaled, keeping memory small in every render worker.
"""
import bisect
import math

import numpy as np
from PIL import Image, ImageOps

DIRECTIONS = ((1, 0), (1, .55), (1, -.5), (.6, .8), (1, 0), (.65, -.75), (1, .3))
SEAM = .3
CANVAS = (6, 9, 16)


class CameraPath:
    """Arc-length parametrised Catmull-Rom curve, so the camera moves at one constant speed."""

    def __init__(self, spans, speed, duration):
        points = [(0., 0.)]
        for index, (start, end) in enumerate(spans):
            dx, dy = DIRECTIONS[index % len(DIRECTIONS)]
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


class WorldCanvas:
    def __init__(self, paths, spans, width, height, path):
        self.W, self.H = width, height
        self.seam = width*SEAM
        margin = round(self.seam)
        self.tiles = []
        for source, (start, end) in zip(paths, spans):
            centers = [path.at(start+(end-start)*k/16) for k in range(17)]
            xs, ys = [p[0] for p in centers], [p[1] for p in centers]
            left, top = min(xs)-width/2-margin, min(ys)-height/2-margin
            right, bottom = max(xs)+width/2+margin, max(ys)+height/2+margin
            self.tiles.append(dict(path=source, x=round(left), y=round(top), width=round(right-left), height=round(bottom-top),
                                   centers=np.array(centers)))
        self._scaled = {}

    def tile_image(self, index):
        if index not in self._scaled:
            if len(self._scaled) >= 3:
                self._scaled.pop(next(iter(self._scaled)))
            spec = self.tiles[index]
            with Image.open(spec['path']) as source:
                self._scaled[index] = ImageOps.fit(source.convert('RGB'), (spec['width'], spec['height']), Image.Resampling.LANCZOS)
        return self._scaled[index]

    def view(self, left, top, width, height):
        """Canvas pixels in the rectangle: each point from the picture whose path is nearest, blended softly at seams."""
        touching = [i for i, spec in enumerate(self.tiles)
                    if spec['x'] < left+width and spec['x']+spec['width'] > left and spec['y'] < top+height and spec['y']+spec['height'] > top]
        view = Image.new('RGB', (width, height), CANVAS)
        if not touching:
            return view.convert('RGBA')
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
        nearest = np.min(distances, axis=0)
        with np.errstate(invalid='ignore'):
            weights = [np.where(np.isfinite(d), np.clip(1-(d-nearest)/self.seam, 0, 1), 0.) for d in distances]
        total = np.zeros_like(nearest)
        for index, weight in zip(touching, weights):
            total = total+weight
            share = np.divide(weight, total, out=np.zeros_like(weight), where=total > 0)
            if not share.any():
                continue
            spec = self.tiles[index]
            region = (max(left, spec['x'])-spec['x'], max(top, spec['y'])-spec['y'],
                      min(left+width, spec['x']+spec['width'])-spec['x'], min(top+height, spec['y']+spec['height'])-spec['y'])
            piece = Image.new('RGB', (width, height), CANVAS)
            piece.paste(self.tile_image(index).crop(region), (region[0]+spec['x']-left, region[1]+spec['y']-top))
            mask = Image.fromarray((share*255).astype('uint8'), 'L').resize((width, height), Image.Resampling.BILINEAR)
            view = Image.composite(piece, view, mask)
        return view.convert('RGBA')
