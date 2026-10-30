"""Image operations that keep small, transparent artwork clean.

Pillow rotates RGBA images without premultiplying alpha, so the colour of fully transparent
pixels (black in our atlases and word sprites) bleeds into every edge as a dark halo.
`turn` rotates premultiplied instead. Pillow also draws lines without antialiasing; `Strokes`
draws them several times larger and reduces the result, which smooths diagonal stems.
"""
from PIL import Image, ImageDraw

SUPERSAMPLE = 4
# Strokes are already smooth at three times the size; four costs more on large branch areas.
STROKE_SUPERSAMPLE = 3


def turn(image, angle, resample=Image.Resampling.BICUBIC, expand=True):
    """`image.rotate(angle)` without dark fringes on RGBA images."""
    if not angle % 360:
        return image.copy()
    if image.mode != 'RGBA':
        return image.rotate(angle, resample, expand=expand)
    return image.convert('RGBa').rotate(angle, resample, expand=expand).convert('RGBA')


def reduce_sprite(source, size, angle=0., squash=1.):
    """`source` fitted into a `size` square, squashed horizontally then rotated, resampled once at the end.

    The work is done at SUPERSAMPLE times the final size, so a photograph shrunk to a few pixels
    keeps its shape and colour instead of being softened by several small resizes.
    """
    work = max(2, round(size*SUPERSAMPLE))
    scale = work/max(source.width, source.height)
    image = source.resize((max(1, round(source.width*scale*squash)), max(1, round(source.height*scale))),
                          Image.Resampling.LANCZOS)
    image = turn(image, angle)
    return image.resize((max(1, round(image.width/SUPERSAMPLE)), max(1, round(image.height/SUPERSAMPLE))),
                        Image.Resampling.LANCZOS)


class Strokes:
    """Antialiased lines for one layer. Call `line` like ImageDraw.line, then `paint` once.

    Lines render in `order` passes (then call order), so a stem's shadow, body and highlight
    can be given as passes 0, 1, 2 and every segment's highlight stays on top of the next
    segment's shadow. Only the area the lines cover is supersampled.
    """

    def __init__(self):
        self.lines = []

    def line(self, xy, fill, width=1, order=0):
        self.lines.append((order, len(self.lines), tuple(float(v) for v in xy), fill, max(1, width)))

    def paint(self, layer):
        if not self.lines:
            return
        pad = max(line[4] for line in self.lines)+2
        xs = [v for line in self.lines for v in line[2][0::2]]
        ys = [v for line in self.lines for v in line[2][1::2]]
        left, top = max(0, int(min(xs)-pad)), max(0, int(min(ys)-pad))
        right, bottom = min(layer.width, int(max(xs)+pad)+1), min(layer.height, int(max(ys)+pad)+1)
        if right <= left or bottom <= top:
            return
        s = STROKE_SUPERSAMPLE
        canvas = Image.new('RGBA', ((right-left)*s, (bottom-top)*s))
        draw = ImageDraw.Draw(canvas)
        for _, _, (x0, y0, x1, y1), fill, width in sorted(self.lines):
            a, b = ((x0-left+.5)*s, (y0-top+.5)*s), ((x1-left+.5)*s, (y1-top+.5)*s)
            draw.line((a, b), fill=fill, width=round(width*s))
            # A round end where the next segment of the curve starts, so joints have no notches.
            if width > 1:
                r = width*s/2
                draw.ellipse((b[0]-r, b[1]-r, b[0]+r, b[1]+r), fill=fill)
        layer.alpha_composite(canvas.resize((right-left, bottom-top), Image.Resampling.BOX), (left, top))
