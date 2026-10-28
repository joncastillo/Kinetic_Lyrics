"""A camera path through one stitched collage of every illustration.

The camera follows a smooth curve at a constant speed for the whole song: no braking, no
acceleration. The curve turns at each scene change (right, rising, falling, diagonal), and
each illustration is placed exactly where the camera travels while it is current, with
feathered edges so neighbouring pictures blend into one image. Only tiles under the camera
are scaled, keeping memory small in every render worker.
"""
import bisect
import math

from PIL import Image, ImageFilter, ImageOps

DIRECTIONS = ((1, 0), (1, .55), (1, -.5), (.6, .8), (1, 0), (.65, -.75), (1, .3))
FEATHER = .16
SCENE_FADE = .75
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
        self.feather = round(min(width, height)*FEATHER)
        self.tiles, self.spans = [], list(spans)
        for source, (start, end) in zip(paths, spans):
            centers = [path.at(start+(end-start)*k/12) for k in range(13)]
            xs, ys = [p[0] for p in centers], [p[1] for p in centers]
            left, top = min(xs)-width/2-self.feather, min(ys)-height/2-self.feather
            right, bottom = max(xs)+width/2+self.feather, max(ys)+height/2+self.feather
            self.tiles.append(dict(path=source, x=round(left), y=round(top), width=round(right-left), height=round(bottom-top)))
        self._scaled = {}

    def tile_image(self, index):
        """Scaled picture with feathered alpha edges, cached for the few tiles under the camera."""
        if index not in self._scaled:
            if len(self._scaled) >= 3:
                self._scaled.pop(next(iter(self._scaled)))
            spec = self.tiles[index]
            with Image.open(spec['path']) as source:
                image = ImageOps.fit(source.convert('RGB'), (spec['width'], spec['height']), Image.Resampling.LANCZOS).convert('RGBA')
            mask = Image.new('L', image.size, 0)
            mask.paste(255, (self.feather, self.feather, image.width-self.feather, image.height-self.feather))
            image.putalpha(mask.filter(ImageFilter.BoxBlur(self.feather/2)))
            self._scaled[index] = image
        return self._scaled[index]

    def current(self, t):
        return max(0, bisect.bisect_right([start for start, _ in self.spans], t)-1)

    def view(self, left, top, width, height, t):
        """What the camera sees: neighbouring pictures underneath, the current scene on top,
        crossfading into the next scene around each change."""
        view = Image.new('RGBA', (width, height), CANVAS+(255,))
        active = self.current(t)
        incoming = active+1 if active+1 < len(self.tiles) and self.spans[active+1][0]-t < SCENE_FADE else None
        outgoing = active-1 if active and t-self.spans[active][0] < SCENE_FADE else None
        order = [i for i in range(len(self.tiles)) if i not in (active, incoming, outgoing)]
        layers = [(i, 1.) for i in order]
        if outgoing is not None:
            layers += [(outgoing, 1.), (active, .5+.5*smooth((t-self.spans[active][0])/SCENE_FADE))]
        elif incoming is not None:
            layers += [(active, 1.), (incoming, .5-.5*smooth((self.spans[incoming][0]-t)/SCENE_FADE))]
        else:
            layers.append((active, 1.))
        for index, opacity in layers:
            spec = self.tiles[index]
            if spec['x'] >= left+width or spec['x']+spec['width'] <= left or spec['y'] >= top+height or spec['y']+spec['height'] <= top:
                continue
            region = (max(left, spec['x'])-spec['x'], max(top, spec['y'])-spec['y'],
                      min(left+width, spec['x']+spec['width'])-spec['x'], min(top+height, spec['y']+spec['height'])-spec['y'])
            piece = self.tile_image(index).crop(region)
            if opacity < 1:
                piece.putalpha(piece.getchannel('A').point(lambda a: round(a*opacity)))
            view.alpha_composite(piece, (region[0]+spec['x']-left, region[1]+spec['y']-top))
        return view


def smooth(value):
    value = max(0., min(1., value))
    return value*value*(3-2*value)
