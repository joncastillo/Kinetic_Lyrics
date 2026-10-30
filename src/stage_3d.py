"""Lyric blocks set in a 3D world, filmed by a gliding camera (ModernGL, headless).

Lines that are sung together form a squarish justified block (see lyric_blocks). Every
block stands somewhere in a 3D space, turned a little towards or away from the viewer.
The camera never stops: it cruises across the current block while it is sung, then
speeds up along an arc to the next one, pulling back on the way so earlier blocks (which
stay where they were written) come back into view. A flat screen aligned backdrop
joins adjacent paintings only at a narrow moving seam, without folded surfaces.
Words fly into their slots as they are sung (flipping up, swinging in, rising or
dropping), hero words are extruded with a few stacked layers, some words keep moving
(a letter wave, a beat pulse, a slow tilt), and themed words get a small animated
picture, sometimes in place of their letter O. The block's particle effect grows only on
its top row (effects tagged "top", such as maple trees, need the open space above it);
the other rows stay plain ink with one accent word. When the block director has run, each
block's entry motion, accent colour and picture are the AI's matched choice for that block.
As in the 2D flow, translucent bands flow from hero word to hero word (here through 3D
space, between blocks) and outlined shapes drift and turn on strong bass notes, at depths
around the blocks so they shift with parallax. Words and pictures share one invisible
rectangle: a picture beside a word takes its own slot in the justified row. A scene can
set its blocks in the "contrast" layout instead: thin and heavy words side by side, one
heavy display word whose every letter has fine woven grain in colors sampled from the
illustration, drawn by a shader so the texture drifts gently inside the letters), and the last word set
vertically close beside the rows; every letter springs in with an elastic bounce, and the camera zooms in and
rolls into a tilt. Which side, which way the vertical word reads, how the fonts pair, the
tilt and the zoom vary from block to block. A scene effect
can own the block's particle effects (`crowns`, such as maple and oak for the tree canopy);
the block director then picks one of them per block. When the video mixes scenes, `only` limits
the stage to the lines of the song sections it films. Every frame is a pure function of time, so renders split
across processes exactly.
"""
from __future__ import annotations

import bisect
from collections import OrderedDict
import colorsys
from functools import lru_cache
import math
from pathlib import Path
import random
import threading

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import glyph_art
from lyric_blocks import TARGET_RATIO, group_lines, layout_block
from realtime_typography import (BACKDROP_COLORS, CURL_TIME, FUNCTION_WORDS, HEAD_FADE, TRACE_TIME, SHAPE_LIFE, SHAPES, THREAD_LIFE, assign_roles, bare, curl_route, hex_rgb,
                                  dying_tail, loop_duration, swash_route,
                                  insert_thread_loop, monotone_keys, overshoot, role_font, sample_thread, settle_keys, smooth, thread_distance)

FOV = 38.
BLOCK_WIDTH = 4.
FILL_WIDTH, FILL_HEIGHT = .74, .72
REFERENCE = 200
OVERSAMPLE = 1.25
FONT_LIMITS = (16, 440)
MOVE, MOVE_LEAD = 1.8, 1.1
# The ribbon's route is rounded over this many seconds of travel either side of each point, so a loop spliced
# in at an angle (or any other corner) turns smoothly instead of making the wisp bounce back in one frame.
ROUND_TIME = .15
# The wisps' swim is measured across the route's direction over this many seconds of travel either way, so on
# a tight turn the swim swings across the route gradually instead of flipping sides within a frame.
TURN_TIME = .35
CRUISE = .14
DEPTHS = (-1.2, .6)
VIEW_TILT = .55
ENTRY, ENTRY_LEAD, LETTER_STAGGER = .38, .08, .035
PARTICLE_ENTRY, GROW_ENTRY = .6, 1.4
EFFECT_FONT = 280
GROW_ROOM, EFFECT_ROOM = .9, .25
ACCENT = (239, 76, 84)
STAGE_FONTS = {'thin': ('segoeuil.ttf', 'calibril.ttf', 'DejaVuSans-ExtraLight.ttf'),
               'heavy': ('ariblk.ttf', 'seguibl.ttf', 'DejaVuSans-Bold.ttf'),
               'sweet': ('GILSANUB.TTF', 'ROCKEB.TTF', 'seguibl.ttf', 'DejaVuSans-Bold.ttf')}
COLUMN_GAP, COLUMN_LIMIT = .018, .32
BOUNCE_ENTRY, BOUNCE_STAGGER = .55, .045
ROLL_RANGE, ZOOM_RANGE = (5., 12.), (.9, .96)
CONTRAST_LEADING = .42
HOP, SWAY = .07, 3.
PATTERNS = 5
ENTRANCES = ('flip', 'swing', 'rise', 'drop')
MOTIONS = ('wave', 'pulse', 'tilt')
OLD_BLOCK, DIM_TIME = .45, 1.
DRAW_REACH = 3.
EXTRUDE_LAYERS, EXTRUDE_DEPTH = 7, .07
ORNAMENT_SIZE, FLOAT_SIZE = 1.12, .9
SLOT_PICTURE = 1.45  # a picture beside a word is drawn larger than its slot, overlapping its neighbours a little
BACKDROP_TINT = .62
MOTES = 36
SHAPE_DEPTHS = (-3.2, -.6)
SHAPE_REACH = 1.5
BANDS, BAND_WIDTH, BAND_STEP, BAND_OPACITY = 3, .05, .09, .42
DUET_LENGTH = (12., 18.)  # how long the partner's one visit lasts
# Shares of the visit: flying in, trailing the main wisp, joining it, the helix, and leaving.
DUET_ENTER, DUET_FOLLOW, DUET_JOIN, DUET_HELIX, DUET_LEAVE = .15, .32, .12, (.55, .74), .85
RIBBON_DEPTH, RIBBON_SWING, RIBBON_REACH = -.12, 1.6, 28.
TEXTURE_LIMIT = 220

VERTEX = '''
#version 330
uniform mat4 mvp;
uniform vec4 uv_rect;
out vec2 uv;
const vec2 corners[6] = vec2[](vec2(-.5, -.5), vec2(.5, -.5), vec2(.5, .5), vec2(-.5, -.5), vec2(.5, .5), vec2(-.5, .5));
void main() {
    vec2 corner = corners[gl_VertexID];
    uv = uv_rect.xy+vec2(corner.x+.5, .5-corner.y)*uv_rect.zw;
    gl_Position = mvp*vec4(corner, 0., 1.);
}
'''
FRAGMENT = '''
#version 330
uniform sampler2D image;
uniform float opacity;
uniform vec3 tint;
in vec2 uv;
out vec4 color;
void main() {
    vec4 texel = texture(image, uv);
    color = vec4(texel.rgb*tint, texel.a)*opacity;
}
'''

STRIP_VERTEX = '''
#version 330
uniform mat4 mvp;
in vec3 position;
in float across;
in vec3 color;
out float v;
out vec3 tint;
void main() {
    v = across;
    tint = color;
    gl_Position = mvp*vec4(position, 1.);
}
'''
STRIP_FRAGMENT = '''
#version 330
uniform sampler2D image;
uniform float opacity;
in float v;
in vec3 tint;
out vec4 color;
void main() {
    vec4 texel = texture(image, vec2(.5, v));
    color = vec4(texel.rgb*tint, texel.a)*opacity;
}
'''

FILL_FRAGMENT = '''
#version 330
uniform sampler2D image;
uniform float opacity;
uniform float time;
uniform float seed;
uniform vec2 origin;
uniform vec2 span;
uniform vec3 deep;
uniform vec3 middle;
uniform vec3 light;
uniform int pattern;
uniform float angle;
uniform float speed;
in vec2 uv;
out vec4 color;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7)))*43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f*f*(3.-2.*f);
    return mix(mix(hash(i), hash(i+vec2(1., 0.)), u.x), mix(hash(i+vec2(0., 1.)), hash(i+vec2(1., 1.)), u.x), u.y);
}
float fbm(vec2 p) {
    float value = 0., amplitude = .5;
    for (int k = 0; k < 5; k++) { value += amplitude*noise(p); p = p*2.03+vec2(1.7, 9.2); amplitude *= .5; }
    return value;
}

void main() {
    vec4 texel = texture(image, uv);
    vec2 p = origin+vec2(uv.x, 1.-uv.y)*span+vec2(seed*7.31, seed*3.17);
    vec2 along = vec2(cos(angle), sin(angle));
    float drift = time*speed*.018;
    float weave = dot(p, along)*(.8+float(pattern)*.17);
    float grain = noise(p*vec2(11., 16.)+along*drift);
    float thread = sin(weave*24.+(grain-.5)*.9+drift);
    float fibre = smoothstep(.84, .98, thread);
    float shade = .5+.15*(noise(p*3.2+vec2(drift, 0.))-.5);
    vec3 ink = mix(deep, middle, shade);
    ink = mix(ink, light, fibre*.18);
    color = vec4(ink*texel.r, texel.a)*opacity;
}
'''

_LOCAL = threading.local()


def ease(value):
    value = max(0., min(1., value))
    return 4*value**3 if value < .5 else 1-(-2*value+2)**3/2


def normalized(vector):
    vector = np.asarray(vector, dtype=float)
    return vector/(np.linalg.norm(vector) or 1.)


def perspective(fov, aspect, near=.05, far=400.):
    f = 1/math.tan(math.radians(fov)/2)
    return np.array([[f/aspect, 0, 0, 0], [0, f, 0, 0],
                     [0, 0, (far+near)/(near-far), 2*far*near/(near-far)], [0, 0, -1, 0]])


def look_at(eye, target, up=(0., 1., 0.)):
    forward = normalized(np.subtract(target, eye))
    side = normalized(np.cross(forward, up))
    upward = np.cross(side, forward)
    view = np.identity(4)
    view[0, :3], view[1, :3], view[2, :3] = side, upward, -forward
    view[:3, 3] = -view[:3, :3]@np.asarray(eye, dtype=float)
    return view


def rotation(yaw=0., pitch=0., roll=0.):
    """4x4 rotation from degrees: yaw about y, pitch about x, roll about z."""
    a, b, c = (math.radians(v) for v in (yaw, pitch, roll))
    ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    matrix = np.identity(4)
    matrix[:3, :3] = ry@rx@rz
    return matrix


def translation(x=0., y=0., z=0.):
    matrix = np.identity(4)
    matrix[:3, 3] = (x, y, z)
    return matrix


def scaling(x, y):
    return np.diag((x, y, 1., 1.))


class GLStage:
    """One headless OpenGL context per process: textured quads, 4x MSAA, RGB readback."""

    def __init__(self, size):
        try:
            import moderngl
        except ImportError as exc:
            raise RuntimeError('The 3D stage requires ModernGL. Install requirements.txt.') from exc
        self.moderngl, self.size = moderngl, tuple(size)
        self.ctx = moderngl.create_context(standalone=True, require=330)
        self.program = self.ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
        self.vao = self.ctx.vertex_array(self.program, [])
        self.strip_program = self.ctx.program(vertex_shader=STRIP_VERTEX, fragment_shader=STRIP_FRAGMENT)
        self.fill_program = self.ctx.program(vertex_shader=VERTEX, fragment_shader=FILL_FRAGMENT)
        self.fill_vao = self.ctx.vertex_array(self.fill_program, [])
        samples = min(4, self.ctx.max_samples)
        self.msaa = self.ctx.framebuffer([self.ctx.renderbuffer(self.size, 4, samples=samples)])
        self.output = self.ctx.framebuffer([self.ctx.renderbuffer(self.size, 4)])
        self.textures = OrderedDict()
        self.chunks = OrderedDict()
        self.transients = []

    def upload(self, image):
        pixels = np.asarray(image.convert('RGBA'), dtype=np.float32)
        pixels[..., :3] *= pixels[..., 3:]/255
        texture = self.ctx.texture(image.size, 4, pixels.round().astype(np.uint8).tobytes())
        texture.build_mipmaps()
        texture.filter = (self.moderngl.LINEAR_MIPMAP_LINEAR, self.moderngl.LINEAR)
        texture.anisotropy = 8.
        texture.repeat_x = texture.repeat_y = False
        return texture

    def texture(self, key, image):
        """A cached, mipmapped, premultiplied texture; `image` may be a callable that makes it."""
        if key in self.textures:
            self.textures.move_to_end(key)
            return self.textures[key]
        texture = self.textures[key] = self.upload(image() if callable(image) else image)
        while len(self.textures) > TEXTURE_LIMIT:
            self.textures.popitem(last=False)[1].release()
        return texture

    def chunk(self, key, image):
        """A cached piece of the backdrop collage; a few are kept, so long songs stay small in GPU memory."""
        if key in self.chunks:
            self.chunks.move_to_end(key)
            return self.chunks[key]
        texture = self.chunks[key] = self.upload(image())
        while len(self.chunks) > CHUNK_LIMIT:
            self.chunks.popitem(last=False)[1].release()
        return texture

    def transient(self, image):
        """A texture for this frame only, such as a particle effect still in motion."""
        texture = self.upload(image)
        self.transients.append(texture)
        return texture

    def begin(self):
        self.msaa.use()
        self.ctx.viewport = (0, 0, *self.size)
        self.msaa.clear(0., 0., 0., 1.)
        self.ctx.enable(self.moderngl.BLEND)
        self.ctx.blend_func = (self.moderngl.ONE, self.moderngl.ONE_MINUS_SRC_ALPHA)

    def quad(self, texture, mvp, opacity=1., tint=(1., 1., 1.), uv=(0., 0., 1., 1.)):
        texture.use(0)
        self.program['mvp'].write(np.ascontiguousarray(mvp.T, dtype='f4').tobytes())
        self.program['opacity'].value = float(opacity)
        self.program['tint'].value = tuple(float(v) for v in tint)
        self.program['uv_rect'].value = tuple(float(v) for v in uv)
        self.vao.render(self.moderngl.TRIANGLES, vertices=6)

    def fill(self, texture, mvp, opacity, fill):
        """A glyph quad (white letters over a dark halo) filled with the flowing marbled texture: `fill` holds
        the three tones, the time, a seed and where this quad sits in the word, in cap heights."""
        texture.use(0)
        program = self.fill_program
        program['mvp'].write(np.ascontiguousarray(mvp.T, dtype='f4').tobytes())
        program['opacity'].value = float(opacity)
        program['uv_rect'].value = (0., 0., 1., 1.)
        for name in ('deep', 'middle', 'light'):
            program[name].value = tuple(v/255 for v in fill[name])
        for name in ('time', 'seed', 'angle', 'speed'):
            program[name].value = float(fill[name])
        program['pattern'].value = int(fill['pattern'])
        for name in ('origin', 'span'):
            program[name].value = tuple(float(v) for v in fill[name])
        self.fill_vao.render(self.moderngl.TRIANGLES, vertices=6)

    def strip(self, texture, mvp, vertices, opacity=1.):
        """A continuous band: rows of (x, y, z, across, r, g, b) drawn as one triangle strip."""
        buffer = self.ctx.buffer(np.ascontiguousarray(vertices, dtype='f4').tobytes())
        vao = self.ctx.vertex_array(self.strip_program, [(buffer, '3f 1f 3f', 'position', 'across', 'color')])
        texture.use(0)
        self.strip_program['mvp'].write(np.ascontiguousarray(mvp.T, dtype='f4').tobytes())
        self.strip_program['opacity'].value = float(opacity)
        vao.render(self.moderngl.TRIANGLE_STRIP)
        vao.release()
        buffer.release()

    def read(self):
        self.ctx.copy_framebuffer(self.output, self.msaa)
        data = self.output.read(components=3, alignment=1)
        for texture in self.transients:
            texture.release()
        self.transients.clear()
        return Image.frombytes('RGB', self.size, data).transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    def close(self):
        for texture in [*self.textures.values(), *self.chunks.values()]:
            texture.release()
        self.textures.clear()
        self.chunks.clear()
        self.ctx.release()


def gl_stage(size):
    stage = getattr(_LOCAL, 'stage', None)
    if stage is None or stage.size != tuple(size):
        if stage is not None:
            stage.close()
        stage = _LOCAL.stage = GLStage(size)
    return stage


def close_stage():
    stage = getattr(_LOCAL, 'stage', None)
    if stage is not None:
        stage.close()
        _LOCAL.stage = None


@lru_cache(maxsize=256)
def stage_font(name, size):
    """The stage's extra faces (thin, heavy, sweet), or the real-time role fonts."""
    if name not in STAGE_FONTS:
        return role_font(name, size)
    for file in STAGE_FONTS[name]:
        for folder in ('', 'C:/Windows/Fonts/'):
            try:
                return ImageFont.truetype(folder+file, size)
            except OSError:
                continue
    return role_font('content', size)


def text_sprite(text, role, size, color):
    """Text drawn with its baseline at (pad, pad+ascent) over a soft dark halo; returns (image, pad, ascent)."""
    font = stage_font(role, size)
    ascent, descent = font.getmetrics()
    pad = max(6, round(size*.14))
    width = max(1, math.ceil(font.getlength(text)))
    shape = Image.new('L', (width+pad*2, ascent+descent+pad*2))
    ImageDraw.Draw(shape).text((pad, pad+ascent), text, font=font, fill=255, anchor='ls')
    halo = shape.filter(ImageFilter.GaussianBlur(max(2, size*.07))).point(lambda a: min(255, round(a*1.4)))
    image = Image.new('RGBA', shape.size, (0, 0, 0, 0))
    image.putalpha(halo.point(lambda a: round(a*.55)))
    image.alpha_composite(Image.merge('RGBA', (*Image.new('RGB', shape.size, color).split(), shape)))
    return image, pad, ascent


def letter_fills(accent, count, rng):
    """Subtle woven grain with a shared scene color and independent, slow letter drift."""
    patterns = list(range(PATTERNS))
    rng.shuffle(patterns)
    fills = []
    for k in range(count):
        fills.append(dict(texture_tones(accent), pattern=patterns[k % PATTERNS],
                          angle=rng.uniform(0., math.pi), speed=rng.uniform(.4, .8)*rng.choice((-1, 1)),
                          seed=rng.uniform(0., 50.)))
    return fills


def texture_tones(accent):
    """Three close tones of the scene accent, with no unrelated white or hue shift."""
    h, s, v = colorsys.rgb_to_hsv(*(c/255 for c in accent))
    tone = lambda s, v: tuple(round(c*255) for c in colorsys.hsv_to_rgb(h, s, v))  # noqa: E731
    return dict(deep=tone(s, v*.78), middle=tone(s*.95, v*.9), light=tone(s*.85, min(1., v*1.04)))


def elastic(value):
    """0 to 1 with a springy overshoot that settles: letters pop in and wobble into place."""
    value = max(0., min(1., value))
    return 1-math.exp(-6*value)*math.cos(value*math.pi*3.2)


ORNAMENTS = ('ring', 'halo', 'orbit', 'sparkle')


@lru_cache(maxsize=256)
def ornament_image(kind, step, size=256):
    """A floating line ornament drawn on by `step`/24: a ring, a double halo of beads, an orbit with its
    travelling bead, or a four-point sparkle; thin luminous strokes with a soft glow."""
    from PIL import ImageFilter
    image = Image.new('L', (size, size))
    draw = ImageDraw.Draw(image)
    c, r, w = size/2, size*.42, max(2, size//80)
    sweep = 360*step/24
    if kind == 'ring':
        draw.arc((c-r, c-r, c+r, c+r), -90, -90+sweep, fill=255, width=w)
    elif kind == 'halo':
        draw.arc((c-r, c-r, c+r, c+r), -90, -90+sweep, fill=255, width=w)
        inner = r*.78
        draw.arc((c-inner, c-inner, c+inner, c+inner), 90, 90+sweep*.85, fill=170, width=max(1, w//2))
        for k in range(int(12*step/24)):
            a = math.radians(-90+k*30)
            bx, by = c+math.cos(a)*r*.89, c+math.sin(a)*r*.89
            draw.ellipse((bx-w*1.3, by-w*1.3, bx+w*1.3, by+w*1.3), fill=230)
    elif kind == 'orbit':
        box = (c-r, c-r*.45, c+r, c+r*.45)
        draw.arc(box, -90, -90+sweep, fill=210, width=max(1, w//2*2))
        a = math.radians(-90+sweep)
        bx, by = c+math.cos(a)*r, c+math.sin(a)*r*.45
        draw.ellipse((bx-w*2.4, by-w*2.4, bx+w*2.4, by+w*2.4), fill=255)
    else:
        reach = r*step/24
        for angle in (0, 90, 180, 270):
            a = math.radians(angle)
            tip = (c+math.cos(a)*reach, c+math.sin(a)*reach)
            side = (math.cos(a+math.pi/2)*w*1.6, math.sin(a+math.pi/2)*w*1.6)
            draw.polygon([(c+side[0], c+side[1]), tip, (c-side[0], c-side[1])], fill=255)
        draw.ellipse((c-w*2, c-w*2, c+w*2, c+w*2), fill=255)
    glow = image.filter(ImageFilter.GaussianBlur(size/40))
    alpha = Image.eval(Image.merge('L', (image,)), lambda v: v)
    combined = Image.fromarray(np.clip(np.asarray(alpha, dtype=float)+np.asarray(glow, dtype=float)*1.4, 0, 255).astype('uint8'))
    result = Image.new('RGBA', (size, size), (255, 255, 255, 0))
    result.putalpha(combined)
    return result


def shape_image(kind, filled=True, size=128, progress=1.):
    """The portion of a solid shape swept out by the traveling dot; no perimeter stroke."""
    image = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(image)
    sides = {'triangle': 3, 'square': 4, 'hexagon': 6}[kind]
    centre, radius = size/2, size*.47
    points = [(centre+radius*math.cos(math.pi+2*math.pi*k/sides),
               centre-radius*math.sin(math.pi+2*math.pi*k/sides)) for k in range(sides+1)]
    progress = max(0., min(1., progress))
    count = min(sides-1, int(progress*sides))
    fraction = progress*sides-count
    a, b = points[count], points[count+1]
    tip = (a[0]+(b[0]-a[0])*fraction, a[1]+(b[1]-a[1])*fraction)
    if progress > 0:
        draw.polygon([(centre, centre)]+points[:count+1]+[tip], fill=(255, 255, 255, 255))
    return image


def shifted(color, amount):
    """An RGB colour (0..1) with its hue turned by `amount` of a full turn."""
    h, l, s = colorsys.rgb_to_hls(*(float(v) for v in color[:3]))
    return colorsys.hls_to_rgb((h+amount) % 1., l, s)


def band_image(width=8, height=64):
    """A band across its width: soft translucent body with a thin bright crest along one edge."""
    column = Image.new('L', (1, height))
    for y in range(height):
        u = y/(height-1)
        body = math.sin(math.pi*u)**.6*120
        crest = 255*math.exp(-((u-.18)/.04)**2)
        column.putpixel((0, y), round(min(255, body+crest*.8)))
    image = Image.new('RGBA', (width, height), (255, 255, 255, 0))
    image.putalpha(column.resize((width, height)))
    return image


def gradient(top, bottom, height=256):
    column = Image.new('RGB', (1, height))
    for y in range(height):
        u = y/(height-1)
        column.putpixel((0, y), tuple(round(a+(b-a)*u) for a, b in zip(top, bottom)))
    return column.resize((4, height))


def soft_dot(size=64):
    dot = Image.new('L', (size, size))
    ImageDraw.Draw(dot).ellipse((size*.3, size*.3, size*.7, size*.7), fill=255)
    dot = dot.filter(ImageFilter.GaussianBlur(size*.1))
    image = Image.new('RGBA', (size, size), (255, 248, 230, 0))
    image.putalpha(dot)
    return image



def route_table(run):
    """Cached (segment starts, ends, cumulative distances, cruising speed) for looking up points on a run."""
    if '_route' not in run:
        starts = np.array([p for p, _ in run['segments']], dtype=float)
        ends = np.array([q for _, q in run['segments']], dtype=float)
        edges = np.concatenate([[0.], np.cumsum(np.linalg.norm(ends-starts, axis=1))])
        times, distances, _ = run['keys']
        cruise = (distances[-1]-distances[0])/max(1e-6, times[-1]-times[0]) if len(times) > 1 else 0.
        run['_route'] = (starts, ends, edges, cruise)
    return run['_route']


def route_point(run, distance):
    """The point `distance` along the run's route."""
    starts, ends, edges, _ = route_table(run)
    k = int(np.clip(np.searchsorted(edges, distance, side='right')-1, 0, len(starts)-1))
    span = edges[k+1]-edges[k]
    return starts[k]+(ends[k]-starts[k])*(0. if span <= 1e-9 else min(1., max(0., (distance-edges[k])/span)))


def steady_tangent(run, distance):
    """The route's direction at `distance`, measured from TURN_TIME of travel behind to TURN_TIME ahead."""
    starts, ends, edges, cruise = route_table(run)
    reach = max(1e-3, cruise*TURN_TIME)
    chord = route_point(run, min(edges[-1], distance+reach))-route_point(run, max(0., distance-reach))
    if np.linalg.norm(chord) > 1e-6:
        return normalized(chord)
    k = int(np.clip(np.searchsorted(edges, distance, side='right')-1, 0, len(starts)-1))
    return normalized(ends[k]-starts[k])

def rounded_run(run):
    """The run's route resampled evenly and averaged along its length over ROUND_TIME of travel either side,
    which rounds every corner (a spliced-in loop's entry and exit included). Timing keys and fill distances
    are remapped to the rounded lengths, so the head still passes each point at the time it was planned."""
    segments = run['segments']
    times, distances, _ = run['keys']
    if len(segments) < 2 or len(times) < 2:
        return run
    starts = np.array([p for p, _ in segments], dtype=float)
    ends = np.array([q for _, q in segments], dtype=float)
    lengths = np.linalg.norm(ends-starts, axis=1)
    edges = np.concatenate([[0.], np.cumsum(lengths)])
    total = edges[-1]
    cruise = (distances[-1]-distances[0])/max(1e-6, times[-1]-times[0])
    radius = cruise*ROUND_TIME
    if total <= 0 or radius <= 0:
        return run
    step = radius/3
    grid = np.linspace(0., total, max(2, int(total/step)+1))
    which = np.clip(np.searchsorted(edges, grid, side='right')-1, 0, len(segments)-1)
    u = np.clip((grid-edges[which])/np.maximum(lengths[which], 1e-9), 0., 1.)[:, None]
    points = starts[which]+(ends[which]-starts[which])*u
    reach = max(1, round(radius/(grid[1]-grid[0])))
    rounded = points
    for _ in range(2):  # two passes weight neighbours as a triangle, so even the acceleration turns smoothly
        padded = np.concatenate([np.repeat(rounded[:1], reach, 0), rounded, np.repeat(rounded[-1:], reach, 0)])
        summed = np.concatenate([np.zeros((1, points.shape[1])), np.cumsum(padded, axis=0)])
        rounded = (summed[2*reach+1:]-summed[:-2*reach-1])/(2*reach+1)
    rounded[0], rounded[-1] = points[0], points[-1]  # the route still starts and ends where it did
    remapped = np.concatenate([[0.], np.cumsum(np.linalg.norm(np.diff(rounded, axis=0), axis=1))])
    remap = lambda d: float(np.interp(d, grid, remapped))  # noqa: E731
    pieces = which[:-1]
    fills = [dict(fill, start_distance=remap(fill['start_distance']), end_distance=remap(fill['end_distance']))
             for fill in run['shape_fills']]
    return dict(run, segments=list(zip(rounded[:-1], rounded[1:])), colors=[run['colors'][k] for k in pieces],
                paint=[run['paint'][k] for k in pieces], keys=settle_keys(monotone_keys(list(times), [remap(d) for d in distances])),
                shape_fills=fills)

class Stage3D:
    def __init__(self, compositor, melody=None, rhythm=None, seed=None, only=None, breaks=(), crowns=None, layouts=None):
        from typography_settings import kinetic_options
        self.c = compositor
        self.only = frozenset(only) if only is not None else None
        self.breaks = set(breaks)
        self.crowns = crowns
        self.layouts = layouts or {}
        self.options = kinetic_options((getattr(compositor, 'typography', None) or {}).get('kinetic'))
        self.melody = melody.get('lines') if isinstance(melody, dict) else None
        self.rhythm = rhythm or {}
        self.seed = getattr(compositor, 'layout_seed', 42) if seed is None else seed
        self.blocks = None
        self.art_tones = {}
        self.veils = []  # (start, end) times when the scene mix carries the wisp instead (see wisp_screen)
        width, height = compositor.width, compositor.height
        self.aspect = width/height
        self.ppu = width*FILL_WIDTH/BLOCK_WIDTH*OVERSAMPLE
        self.projection = perspective(FOV, self.aspect)

    # Planning: blocks, words, places in the world, camera shots.

    def art_breaks(self):
        """Line indices where a new illustration starts, so a block never straddles two pictures."""
        c, breaks = self.c, set()
        cues = [line['words'][0]['start'] for line in c.data]
        lead = getattr(c, 'lead_in', 0.)
        for start in list(getattr(c, 'art_starts', None) or [])[1:]:
            for index, cue in enumerate(cues):
                if abs(cue-start) < 1e-6 or abs(max(0., cue-lead)-start) < 1e-6:
                    breaks.add(index)
                    break
        return breaks

    def plan(self):
        if self.blocks is not None:
            return self.blocks
        from kinetic_director import PALETTES
        c = self.c
        self.blocks = []
        center = np.zeros(3)
        previous_extent = 0.
        groups = group_lines(c.data, self.art_breaks() | self.breaks)
        groups = [g for g in ([i for i in group if self.only is None or i in self.only] for group in groups) if g]
        direction = self.directions()
        for number, members in enumerate(groups):
            rng = random.Random(self.seed*7919+number*104729)
            directed = direction.get(members[0]) if direction is not None else None
            scene = c.plan['scenes'][members[0]]
            palette = [hex_rgb(v) for v in c.scene_palette(scene)]
            words = self.block_words(members, palette)
            accent = self.artwork_accent(words[0]['start'], palette[3])
            style = self.contrast_style(words, rng, accent) if self.layouts.get(members[0]) == 'contrast' else None
            arrange = (lambda pictured=None: self.arrange_contrast(words, members, style, pictured)) if style else \
                (lambda pictured=None: self.arrange(words, members, pictured))
            height = arrange()
            effect = self.block_effect(members, number, directed)
            self.crown(words, effect)
            self.choose_accent(words, palette[2], accent, style)
            self.follow_instructions(words)
            ornament = (directed or {}).get('ornament') if direction is not None else None
            no_pictures = self.c.plan.get('pictures') == 'off'  # the setting turns off keyword pictures too
            self.choose_motion(words, rng, None if no_pictures else ornament if direction is not None else False)
            pictured = next((w for w in words if w['ornament'] and w['letter'] is None), None)
            if pictured is not None:
                height = arrange(pictured)
                self.crown(words, effect)
                self.choose_accent(words, palette[2], accent, style)
                self.follow_instructions(words)
            room = (GROW_ROOM if effect.trajectory == 'grow' else EFFECT_ROOM)*REFERENCE*words[0]['scale'] if effect else 0.
            extent = max(BLOCK_WIDTH, height+room)
            if number:
                heading = self.heading(number, rng)
                center = center+heading*(1.1*(previous_extent+extent)/2+.7)
                center[2] = rng.uniform(*DEPTHS)
            previous_extent = extent
            tilt = 1.6 if rng.random() < .2 else 1.
            yaw, pitch, roll = rng.uniform(-24, 24)*tilt, rng.uniform(-10, 10)*tilt, rng.uniform(-4, 4)
            placement = translation(*center)@rotation(yaw, pitch, roll)
            normal = placement[:3, :3]@np.array([0., 0., 1.])
            view = normalized(normal*VIEW_TILT+np.array([0., 0., 1.])*(1-VIEW_TILT))
            half = math.tan(math.radians(FOV)/2)
            angle = math.radians(abs(style['roll'])) if style else 0.  # the tilted block's bounding box must fit
            wide = BLOCK_WIDTH*math.cos(angle)+(height+room)*math.sin(angle)
            tall = BLOCK_WIDTH*math.sin(angle)+(height+room)*math.cos(angle)
            distance = max(tall/2/half/FILL_HEIGHT, wide/2/(half*self.aspect)/FILL_WIDTH)*(style['zoom'] if style else 1.)
            focus = (placement@np.array([0., room/2, 0., 1.]))[:3]
            margin = .9*min(distance*half*self.aspect-wide/2, distance*half-tall/2)
            self.blocks.append(dict(lines=members, words=words, height=height, center=center, focus=focus, placement=placement,
                                    view=view, distance=distance, side=normalized(np.cross([0., 1., 0.], view)),
                                    start=min(w['start'] for w in words), end=max(w['end'] for w in words),
                                    palette=palette, entrance=rng.choice(ENTRANCES), motes=self.motes(rng, height),
                                    drift=rng.choice((-1., 1.)), accent=accent, layout='contrast' if style else 'justified', margin=max(0., margin),
                                    roll=style['roll'] if style else 0., zoom=style['zoom'] if style else 1.))
            if directed and directed.get('entrance') in ENTRANCES:
                self.blocks[-1]['entrance'] = directed['entrance']
        for number, block in enumerate(self.blocks):
            required = block['distance']*1.06
            if number == 0:
                block['camera_distance'] = required*1.08
            else:
                previous = self.blocks[number-1]['camera_distance']
                phase = number % 5
                scale = (1.16, 1.12, 1., .84, .9)[phase-1]
                block['camera_distance'] = max(required, min(required*1.65, previous*scale))
            block['shot_roll'] = (0., 0., 7., -6., 0., 5.)[number % 6]+block['roll']*.25
            block['move'] = block['start']-MOVE_LEAD if number else -math.inf
            following = self.blocks[number+1]['start']-MOVE_LEAD if number+1 < len(self.blocks) else self.c.duration
            block['hold'] = (max(0., block['start']-MOVE_LEAD), max(block['start']+1., following))
            ahead = self.blocks[number+1]['focus'] if number+1 < len(self.blocks) else block['focus']+self.heading(number+1, random.Random(number))
            reach = max(.5, (block['end']-block['start'])/2+MOVE_LEAD)
            block['cruise'] = normalized((ahead-block['focus'])*np.array([1., 1., 0.]))*min(CRUISE, block['margin']/reach)
        self.world = self.plan_world()
        self.shapes = self.plan_shapes()
        self.ribbon = self.plan_ribbon()
        return self.blocks

    def artwork_accent(self, time, fallback):
        """Pick a readable backdrop hue while keeping purple out of textured lettering."""
        c = self.c
        if c.artwork_mode not in ('fullscreen', 'verse') or not getattr(c, 'art', None) or not c.art_starts:
            return fallback
        slot = max(0, min(len(c.art)-1, bisect.bisect_right(c.art_starts, time)-1))
        if slot not in self.art_tones:
            swatches = c.art[slot].convert('RGB').resize((96, 54), Image.Resampling.BILINEAR).quantize(colors=12)
            colors = swatches.convert('RGB').getcolors() or []
            choices = []
            for count, color in colors:
                h, s, v = colorsys.rgb_to_hsv(*(component/255 for component in color))
                if s >= .14 and .25 <= v <= .96 and not .69 <= h <= .96:
                    choices.append((count*(.2+s)*(.5+v), h, s, v))
            if choices:
                _, h, s, v = max(choices)
                rgb = colorsys.hsv_to_rgb(h, min(.55, max(.26, s)), max(.78, min(.94, v*1.35)))
                self.art_tones[slot] = tuple(round(component*255) for component in rgb)
            else:
                self.art_tones[slot] = fallback
        return self.art_tones[slot]

    def heading(self, number, rng):
        """Direction from one block to the next: right, rising, falling or diving, never straight back."""
        options = ((1., 0., 0.), (1., -.55, 0.), (1., .5, 0.), (.35, -1., 0.), (.8, .25, 0.), (.55, .8, 0.), (1., -.25, 0.))
        return normalized(options[(number*3+rng.randrange(len(options))) % len(options)])

    def block_words(self, members, palette):
        c, words = self.c, []
        ink, accent = palette[2], palette[3]
        for index in members:
            line = c.data[index]
            features = self.melody[index] if self.melody and index < len(self.melody) else None
            roles = assign_roles(line, features, c.plan['scenes'][index].get('emphasis', -1))
            for k, (word, role) in enumerate(zip(line['words'], roles)):
                text = word['text'].strip()
                upper = role != 'function' or bare(text) not in FUNCTION_WORDS
                words.append(dict(text=text.upper() if upper else text.lower(), bare=bare(text), role=role, font='content' if role == 'function' else role, line=index,
                                  index=k, start=word['start'], end=word['end'],
                                  color=accent if role == 'hero' else ink if role == 'content' else tuple(round(v*.86) for v in ink)))
        return words

    def contrast_style(self, words, rng, accent):
        """The contrast layout's choices for one block: the vertical word (the last word that is not a short
        function word), the textured word (a hero word), how thin and heavy fonts pair, and the camera's tilt."""
        content = [w for w in words if w['role'] != 'function' and len(w['bare']) > 2] or words
        vertical = content[-1]
        heroes = [w for w in words if w['role'] == 'hero' and w is not vertical]
        sweet = (heroes or [w for w in content if w is not vertical] or [None])[0]
        pairing = rng.choice(('roles', 'lines'))
        for word in words:
            line = sorted({w['line'] for w in words}).index(word['line'])
            thin = word['role'] == 'function' if pairing == 'roles' else line % 2 == 0 and word['role'] != 'hero'
            word.update(font='thin' if thin else 'heavy', text=word['text'].upper(), bouncy=True)
        vertical.update(font='heavy', vertical=True)
        if sweet is not None:
            sweet.update(font='sweet', sweet=True, text=sweet['text'].lower(), fills=letter_fills(accent, len(sweet['text']), rng))
        return dict(vertical=vertical, side=rng.choice((-1, 1)), reads=rng.choice(('up', 'down')),
                    roll=rng.choice((-1, 1))*rng.uniform(*ROLL_RANGE), zoom=rng.uniform(*ZOOM_RANGE))

    def arrange_contrast(self, words, members, style, pictured=None):
        """Rows of the other words beside a column holding the vertical word, which runs the block's full height."""
        vertical = style['vertical']
        rest = [w for w in words if w is not vertical]
        font = stage_font(vertical['font'], REFERENCE)
        length, cap = max(1., font.getlength(vertical['text'])), -font.getbbox('H', anchor='ls')[1]
        column = .2*BLOCK_WIDTH
        for _ in range(4):
            width = BLOCK_WIDTH-column-COLUMN_GAP*BLOCK_WIDTH
            left = -BLOCK_WIDTH/2+(column+COLUMN_GAP*BLOCK_WIDTH if style['side'] < 0 else 0.)
            height = self.arrange(rest, members, pictured, width, left, CONTRAST_LEADING)
            wanted = min(COLUMN_LIMIT*BLOCK_WIDTH, cap*height/length)
            if abs(wanted-column) < 1e-3:
                break
            column = wanted
        scale = column/cap
        span = length*scale
        edge = -BLOCK_WIDTH/2 if style['side'] < 0 else BLOCK_WIDTH/2-column
        if style['reads'] == 'up':
            frame = translation(edge+column, -span/2)@rotation(roll=90)
        else:
            frame = translation(edge, span/2)@rotation(roll=-90)
        vertical.update(row=-1, scale=scale, cap=column, width=span, x=0., baseline=0., slot=None, frame=frame)
        return height

    def arrange(self, words, members, pictured=None, width=BLOCK_WIDTH, left=-BLOCK_WIDTH/2, leading=None):
        """Set the words as a justified block (with a square slot for the picture beside `pictured`) of the
        given width from `left`; returns the block height. Each word gets its row, size and baseline position."""
        sizes, slot = [], None
        lengths = [sum(1 for w in words if w['line'] == i) for i in members]
        for word in words:
            font = stage_font(word['font'], REFERENCE)
            cap = -font.getbbox('H', anchor='ls')[1]
            sizes.append((max(1., font.getlength(word['text'])), cap))
            if word is pictured:
                slot = len(sizes)
                sizes.append((cap*1.15, cap))
                lengths[members.index(word['line'])] += 1
        layout = layout_block(sizes, TARGET_RATIO/self.aspect*width/BLOCK_WIDTH, width, [n for n in lengths if n],
                              *(() if leading is None else (leading,)))
        height = layout['height']
        caps = {}
        for size, place in zip(sizes, layout['words']):
            caps[place['row']] = max(caps.get(place['row'], 0.), size[1]*place['scale'])
        places = [place for number, place in enumerate(layout['words']) if number != slot]
        measured = [size for number, size in enumerate(sizes) if number != slot]
        for word, size, place in zip(words, measured, places):
            cap = caps[place['row']]
            word.update(row=place['row'], scale=place['scale'], cap=cap, width=size[0]*place['scale'],
                        x=place['x']+left, baseline=height/2-(place['y']+cap), slot=None, frame=np.identity(4))
        if pictured is not None:
            place = layout['words'][slot]
            cap = caps[place['row']]
            size = min(cap*1.1, sizes[slot][0]*place['scale'])
            pictured['slot'] = (place['x']+left+sizes[slot][0]*place['scale']/2, height/2-(place['y']+cap)+cap/2, size)
        return height

    def crown(self, words, effect):
        """The block's particle effect grows on its top row only, never on the word carrying a picture."""
        for word in words:
            word['effect'] = effect if word['row'] == 0 and not word.get('ornament') else None

    def follow_instructions(self, words):
        """Special instructions typed for the renderer: the words they name take that effect and colour."""
        for word in words:
            directive = getattr(self.c, 'word_directives', {}).get((word['line'], word['index']), {})
            if directive.get('effect'):
                word['effect'] = self.c.effect_catalog['entrance'].get(directive['effect'], word['effect'])
            if directive.get('color'):
                word['color'] = tuple(directive['color'])

    def block_effect(self, members, number=0, directed=None):
        """The block's particle entrance. In a scene that owns particle effects: the one the block director
        picked, or the scene's effects in turn. Otherwise a top-only effect if any of its lines has one,
        else the first line's."""
        c = self.c
        if getattr(c, 'particle_intensity', 0) <= 0:
            return None
        if self.crowns is not None:
            owned = self.owned_effects(members[0])
            if not owned:
                return None
            pick = (directed or {}).get('particle')
            preferred = [e for e in (self.crowns or {}).get(members[0]) or [] if e in owned]
            fallback = preferred or owned
            return c.effect_catalog['entrance'][pick if pick in owned else fallback[number % len(fallback)]]
        recipes = [c.effect_catalog['entrance'].get(c.effect_pairs[index][0]) for index in members]
        recipes = [recipe for recipe in recipes if recipe is not None]
        return next((r for r in recipes if r.placement == 'top'), recipes[0] if recipes else None)

    def owned_effects(self, line):
        """Allowed entrances for a scene block; tree canopy alone is restricted to tree effects."""
        c = self.c
        pool = getattr(c, 'entrance_pool', None)
        flow = next((f for f in c.plan.get('scene_flows', []) if f['start'] <= line < f['end']), None)
        tree = flow is not None and flow['scene'] == 'tree-canopy'
        choices = (self.crowns or {}).get(line) or [] if tree else c.effect_catalog['entrance']
        return [e for e in choices
                if e in c.effect_catalog['entrance'] and (pool is None or e in pool)]

    def choose_accent(self, words, ink, color=ACCENT, style=None):
        """All words in ink except one accent below the top row: the first hero there, else the longest-held word.
        In the contrast layout the vertical word carries the accent."""
        if style is not None:
            for word in words:
                word['color'] = color if word is style['vertical'] else ink
            return
        below = [w for w in words if w['row'] > 0] or words
        accent = next((w for w in below if w['role'] == 'hero'), None) or max(below, key=lambda w: w['end']-w['start'])
        for word in words:
            word['color'] = color if word is accent else ink if word['role'] != 'function' else tuple(round(v*.86) for v in ink)

    def directions(self):
        """The block director's choices by each block's first line, or None when it has not run."""
        directed = self.c.plan.get('stage_direction')
        if not isinstance(directed, list):
            return None
        return {entry['lines'][0]: entry for entry in directed if entry and entry.get('lines')}

    def choose_motion(self, words, rng, directed=False):
        """Some words keep moving after they land, and one word per block may get a picture: the one the
        block director chose (`directed`, None for no picture), or with `directed` False the first word
        matching a keyword picture."""
        for word in words:
            word['motion'] = rng.choice(MOTIONS) if word['role'] == 'hero' and not word['effect'] and rng.random() < .6 else None
            if word.get('sweet'):
                word['motion'] = 'bounce'
            elif word.get('bouncy') and word['motion'] == 'tilt':
                word['motion'] = None
            word['ornament'] = word['letter'] = None
        if directed is None:
            return
        if directed is not False:
            spec = directed
            word = next((w for w in words if (w['line'], w['index']) == (spec.get('line'), spec.get('word'))
                         and not w.get('vertical') and not w.get('sweet')), None)
            if word is None:
                return
            word['ornament'] = dict(kind=spec.get('library') if spec.get('source') == 'library' or not spec.get('image') else None,
                                    image=spec.get('image'), motion=spec.get('motion'))
            if not word['ornament']['kind'] and not word['ornament']['image']:
                word['ornament'] = None
                return
            word['effect'] = None
            letter = word['text'].upper().find('O') if spec.get('placement') == 'letter' else -1
            word['letter'] = letter if letter >= 0 else None
        else:
            themed = [w for w in words if glyph_art.theme(w['bare']) and not w['effect'] and not w.get('vertical') and not w.get('sweet')]
            themed.sort(key=lambda w: (glyph_art.replaces_letter(glyph_art.theme(w['bare']), w['text']) is None,
                                       w['bare'] != glyph_art.theme(w['bare']), w['role'] != 'hero', w['start']))
            if not themed:
                return
            word = themed[0]
            kind = glyph_art.theme(word['bare'])
            word['ornament'] = dict(kind=kind, image=None, motion=None)
            word['letter'] = glyph_art.replaces_letter(kind, word['text'])
        if word['letter'] is not None and word['motion'] == 'tilt':
            word['motion'] = 'wave'

    def motes(self, rng, height):
        return [(rng.uniform(-1.4, 1.4)*BLOCK_WIDTH/2, rng.uniform(-1.6, 1.6)*height/2, rng.uniform(-3., 1.2),
                 rng.uniform(.025, .07), rng.uniform(0, math.tau), rng.uniform(.4, 1.2)) for _ in range(MOTES)]

    def plan_world(self):
        """Whether the screen aligned artwork backdrop is active behind the 3D lettering."""
        c = self.c
        paths = list(getattr(c, 'illustration_paths', None) or [])
        if not paths or c.artwork_mode not in ('fullscreen', 'verse'):
            return None
        return [str(p) for p in paths]

    def backdrop(self, gl, t):
        # The shared compositor stitches adjacent paintings at one narrow seam. The flat texture
        # sits behind the perspective lettering, so no folded 3D surfaces can double-expose it.
        starts = self.c.art_starts
        current = max(0, min(len(self.c.art)-1, bisect.bisect_right(starts, t)-1))
        if current and t < starts[current]+self.c.art_crossing(current):
            texture = gl.transient(self.c.background(0, t, veil=False).convert('RGBA'))
        else:
            texture = gl.texture(('backdrop', current), lambda: self.c.art[current].convert('RGBA'))
        gl.quad(texture, scaling(2., 2.), 1., (BACKDROP_TINT,)*3)

    def plan_shapes(self):
        """Outlined or translucent shapes around the blocks on strong bass notes (or block starts without
        bass), on screen for about the `geometry` share of the stage's time, in the block's own colours."""
        blocks = self.blocks
        span = sum(b['hold'][1]-b['hold'][0] for b in blocks)
        count = round(self.options['geometry']*span/(SHAPE_LIFE*1.7))
        moments = [time for time, strength in (self.rhythm.get('bass') or []) if strength >= .6]
        moments = [m for m in moments if any(b['hold'][0] <= m < b['hold'][1] for b in blocks)] or [b['start'] for b in blocks]
        spacing = span/max(1, count)
        shapes, last = [], -math.inf
        for time in moments:
            if len(shapes) >= count:
                break
            if time-last < spacing:
                continue
            last = time
            rng = random.Random(round(time*1000))
            number = max(0, bisect.bisect_right([b['hold'][0] for b in blocks], time)-1)
            block = blocks[number]
            angle = rng.uniform(0, math.tau)
            x = math.cos(angle)*BLOCK_WIDTH/2*rng.uniform(.6, SHAPE_REACH)
            y = math.sin(angle)*block['height']/2*rng.uniform(.8, SHAPE_REACH*1.4)
            color = block['accent'] if rng.random() < .5 else hex_rgb(rng.choice(BACKDROP_COLORS))
            mode = ('glide', 'word', 'glide', 'loop', 'word', 'glide')[len(shapes) % 6]
            shapes.append(dict(start=time, block=number, kind=rng.choice(SHAPES), ornament=rng.choice(ORNAMENTS), mode=mode,
                               filled=True, color=color,
                               position=(x, y, rng.uniform(*SHAPE_DEPTHS)), size=rng.uniform(.35, 1.1),
                               spin=rng.uniform(-25, 25), tilt=(rng.uniform(-35, 35), rng.uniform(-35, 35)),
                               drift=(rng.uniform(-.06, .06), rng.uniform(-.06, .06), rng.uniform(-.04, .04))))
        return shapes

    def shape_items(self, gl, t):
        items = []
        for shape in self.shapes:
            age = t-shape['start']
            if not 0 <= age < SHAPE_LIFE:
                continue
            fade = smooth(age/.6)*(1-smooth((age-SHAPE_LIFE+1.2)/1.2))
            if fade <= .01:
                continue
            block = self.blocks[shape['block']]
            x, y, z = (p+d*age for p, d in zip(shape['position'], shape['drift']))
            size = shape['size']*(.85+.25*smooth(age/SHAPE_LIFE))  # swells gently as it draws itself on
            step = max(1, min(24, round(24*smooth(age/1.1))))
            kind = shape.get('ornament', 'ring')
            texture = gl.texture(('ornament-line', kind, step), lambda kind=kind, step=step: ornament_image(kind, step))
            model = (block['placement']@translation(x, y, z)@rotation(shape['tilt'][0]*.4, shape['tilt'][1]*.4,
                     roll=shape['spin']*.5*age)@scaling(size, size))
            items.append((model, texture, .6*fade, tuple(min(1., v/255*.6+.4) for v in shape['color'])))
        return items

    def plan_ribbon(self):
        """The bands' path through the world: from block to block, just behind each block's first hero word
        as it is sung, turning continuously at one cruising speed and weaving in the blocks' planes (see
        flow_path). One stop per block keeps the distances and times between stops even, so the band can
        sweep on without braking."""
        stops = []
        for block in self.blocks:
            word = next((w for w in block['words'] if w['role'] == 'hero'), block['words'][0])
            local = np.array([word['x']+word['width']/2, word['baseline']+word['cap']/2, RIBBON_DEPTH, 1.])
            stops.append((word['start'], (block['placement']@word['frame']@local)[:3], block['accent'], block['placement'][:3, 2],
                          block['lines'][0], block['lines'][-1]))
        stops.sort(key=lambda stop: stop[0])
        times = []
        for stop in stops:
            times.append(max(stop[0], times[-1]+.05) if times else stop[0])
        from flow_path import build_flows
        runs, runs_of, label = [], [], 0
        for n, stop in enumerate(stops):
            label += 0 if not n else 1 if stop[4] == stops[n-1][5]+1 else 2
            runs_of.append(label)
        painted_words = set()
        for flow in build_flows(times, [stop[1] for stop in stops], [stop[2] for stop in stops], amplitude=RIBBON_SWING,
                                normals=[stop[3] for stop in stops], lines=runs_of):
            if self.options['geometry'] > 0:
                for shape in self.shapes:
                    if shape['mode'] == 'glide':
                        continue
                    moment = shape['start']
                    keys = flow['keys']
                    if not keys[0] or not keys[0][0]+.5 < moment < keys[0][-1]-1.2:
                        continue
                    distance = thread_distance(keys, moment)
                    if distance is None or distance <= .01 or distance >= flow['pieces'][-1]['end']:
                        continue
                    point = sample_thread(flow['pieces'], distance-.01, distance, 1.)[-1]
                    origin = np.array(point[:3])
                    block = self.blocks[shape['block']]
                    permanent = shape['mode'] == 'word'
                    if permanent:
                        choices = [w for w in block['words'] if w['role'] == 'hero' and w['start'] <= moment+.5
                                   and (w['line'], w['index']) not in painted_words]
                        if not choices:
                            continue
                        word = min(choices, key=lambda w: abs(w['start']-moment))
                        painted_words.add((word['line'], word['index']))
                        frame = block['placement']@word['frame']
                        cx, cy = word['x']+word['width']/2, word['baseline']+word['cap']/2
                        rx, ry = word['width']/2+word['cap']*.65, word['cap']*1.1
                        local = np.linalg.inv(frame)@np.array([*origin, 1.])
                        flat = swash_route(local[0], local[1], cx, cy, rx, ry, tilt=.12)
                        route = [tuple((frame@np.array([px, py, RIBBON_DEPTH-.04, 1.]))[:3]) for px, py in flat]
                        route[0] = route[-1] = tuple(origin)
                        color = block['accent']
                    else:
                        right, up = block['placement'][:3, 0], block['placement'][:3, 1]
                        flat = curl_route(0., 0., shape['size']*.2, 1. if round(moment*10) % 2 else -1.)
                        route = [tuple(origin+px*right-py*up) for px, py in flat]  # the curl is drawn with y down
                        color = point[-1]
                    # The ribbon itself draws the curl or swash; no filled shape is revealed behind it.
                    length = insert_thread_loop(flow['pieces'], distance, route, color, shape=False)
                    clock, distances, _ = keys
                    duration = loop_duration(keys, length, (2.2, TRACE_TIME[1]) if permanent else CURL_TIME)
                    flow['keys'] = monotone_keys(clock, [d+length*smooth((time-moment)/duration)
                                                         for time, d in zip(clock, distances)])
            segments, colors, paint = [], [], []
            for piece in flow['pieces']:
                points = [np.array(p) for p in piece['points']]
                segments.extend(zip(points, points[1:]))
                colors.extend([piece['color']]*(len(points)-1))
                paint.extend([not piece.get('shape', False)]*(len(points)-1))
            runs.append(rounded_run(dict(segments=segments, colors=colors, paint=paint, keys=flow['keys'],
                                         shape_fills=flow.get('shape_fills', []))))
        return runs

    def shape_fill_items(self, gl, t):
        """Reveal each solid polygon only as the white ribbon head traces its route."""
        items = []
        for run in self.ribbon:
            head = thread_distance(run['keys'], t)
            if head is None:
                continue
            for shape in run['shape_fills']:
                start, end = shape['start_distance'], shape['end_distance']
                if head <= start or (not shape['permanent'] and t >= shape['time']+SHAPE_LIFE):
                    continue
                progress = min(1., (head-start)/max(1e-6, end-start))
                step = max(1, round(progress*40))
                texture = gl.texture(('shape-fill', shape['kind'], step),
                                     lambda shape=shape, step=step: shape_image(shape['kind'], progress=step/40))
                model = np.identity(4)
                model[:3, 0] = shape['right']*shape['rx']*2.15
                model[:3, 1] = shape['up']*shape['ry']*2.15
                model[:3, 2] = normalized(np.cross(shape['right'], shape['up']))
                model[:3, 3] = shape['centre']
                fade = 1. if shape['permanent'] else 1-smooth((t-shape['time']-SHAPE_LIFE+.8)/.8)
                alpha = .4 if shape['permanent'] else .5
                items.append((model, texture, alpha*smooth(progress)*fade, tuple(v/255 for v in shape['color'])))
        return items

    def ribbon_bands(self, t, eye):
        """Translucent bands from the thread's tail to its head, each swelling and narrowing in its own slow
        wave and pinching together at both ends, turned to face the camera: one vertex row per sample."""
        if not self.options['traces'] and self.options['geometry'] <= 0:
            return []
        return [band for run in self.ribbon for band in self.run_bands(run, t, eye)]

    def ribbon_heads(self, t, eye):
        """The main wisp's head at the leading end of the ribbon, and the partner's while it visits."""
        if not self.options['traces'] and self.options['geometry'] <= 0:
            return []
        if any(start <= t < end for start, end in self.veils):
            return []
        result = []
        energy, _, tune = self.pulse(t)
        presence = self.partner_presence(t)
        glow = self.duet_glow(t)
        for number, run in enumerate(self.ribbon):
            alive = 1-smooth((t-run['keys'][0][-1])/HEAD_FADE)
            if alive <= .001:
                continue
            head = self.head_at(number, t)
            if head is None:
                continue
            point, tangent = head
            side = normalized(np.cross(tangent, eye-point))
            up = normalized(np.cross(side, tangent))
            for wisp, opacity in ((0, alive), (1, presence*alive)):
                if opacity <= .001:
                    continue
                position = point+self.wisp_offset(wisp, t, t, side, up, tangent, energy)
                result.append((position, opacity, shifted((1., .96, .82), (tune-.5)*.16+wisp*.28+glow)))
        return result

    # The two wisps. The main one swims alone along the path. Once, between the middle and the end of the song,
    # a partner flies in from far behind, trails the main wisp for a while, closes in and joins it: the two chase
    # round each other like birds in a flock, twisting into a tight helix, throwing off motes and colour, until
    # the partner peels away and leaves; the main one carries on. Every offset is a function of the time the head
    # was there, so each tail traces its wisp's own flight.

    def music(self):
        """Hits from the drums and bass, and the sung pitch rank of each word, prepared once."""
        if getattr(self, '_music', None) is None:
            hits = sorted(h for stem in ('drums', 'bass') for h in (self.rhythm.get(stem) or []))
            times = np.array([h[0] for h in hits]) if hits else np.zeros(0)
            strengths = np.array([h[1] for h in hits]) if hits else np.zeros(0)
            tune = []
            for index, line in enumerate(self.c.data):
                features = (self.melody or [None]*len(self.c.data))[index] if self.melody else None
                for number, word in enumerate(line['words']):
                    rank = (features[number] or {}).get('pitch_rank') if features and number < len(features) else None
                    if rank is not None:
                        tune.append((word['start'], rank))
            tune.sort()
            self._music = dict(times=times, strengths=strengths, tune_times=[a for a, _ in tune], tune=[b for _, b in tune])
        return self._music

    def pulse(self, t):
        """(soft hit glow, continuous motion clock, pitch rank of the vocal melody)."""
        music = self.music()
        before = music['times'] <= t
        ages = t-music['times'][before]
        strengths = music['strengths'][before]
        energy = float(np.sum(strengths*np.minimum(1., np.maximum(0., ages)/.16)*np.exp(-ages/.55)))
        clock = t*.7
        index = bisect.bisect_right(music['tune_times'], t)-1
        if index < 0:
            tune = .5
        else:  # glide from the previous word's pitch to this one's over a moment
            here = music['tune'][index]
            previous = music['tune'][index-1] if index else here
            tune = previous+(here-previous)*smooth((t-music['tune_times'][index])/.4)
        return min(1.5, energy), clock, tune

    def duet_windows(self):
        """The partner's one visit (DUET_LENGTH long, in the second half of the song), starting and ending on
        vocal notes or rhythm hits within an active ribbon run; empty when no run is long enough there."""
        if getattr(self, '_duet_windows', None) is not None:
            return self._duet_windows
        music = self.music()
        hits = [(float(t), float(s)) for t, s in zip(music['times'], music['strengths']) if s >= .55]
        notes = music['tune_times']
        events = []
        for i, note in enumerate(notes):
            change = abs(music['tune'][i]-music['tune'][i-1]) if i else 0.
            accent = max((strength for time, strength in hits if abs(time-note) <= .22), default=0.)
            if change >= .07 or accent >= .6:
                events.append((float(note), change+accent*.5))
        if not events:
            events = hits
        shortest, longest = DUET_LENGTH
        middle = getattr(getattr(self, 'c', None), 'duration', 0.)/2
        windows = []
        for run in self.ribbon:
            first, last = run['keys'][0][0], run['keys'][0][-1]
            local = [(time, strength) for time, strength in events if max(first+.6, middle) <= time <= last-shortest]
            for start, strength in local:
                if strength < .08:
                    continue
                ends = [time for time, _ in events if start+shortest <= time <= min(last, start+longest)]
                if not ends:
                    ends = [time for time, _ in hits if start+shortest <= time <= min(last, start+longest)]
                if ends:
                    windows = [(start, ends[0])]
                    break
            if windows:
                break
        self._duet_windows = windows
        return windows

    def visit(self, when):
        """The partner's visit covering time `when`: (start, end, the side it flies in from), or None."""
        windows = self.duet_windows()
        k = bisect.bisect_right([start for start, _ in windows], when)-1
        if k >= 0 and when <= windows[k][1]:
            return windows[k][0], windows[k][1], 1. if k % 2 == 0 else -1.
        return None

    def partner_presence(self, t):
        """How visible the partner is: it fades in far off as it arrives and out far off as it leaves."""
        visit = self.visit(t)
        if visit is None:
            return 0.
        start, end, _ = visit
        u = (t-start)/max(1e-6, end-start)
        return smooth(u/.12)*smooth((1-u)/.12)

    @staticmethod
    def solo(when):
        """The main wisp's lazy swim round the path when it is alone, in (side, up, forward) BAND_WIDTHs."""
        return np.array([2.4*math.cos(1.1*when)+.5*math.sin(1.7*when+.3), 1.9*math.sin(1.1*when), 0.])

    def chase(self, when):
        """Main and partner offsets from the path at `when`, in (side, up, forward) units of BAND_WIDTH, and how
        fully they are together (0 when the main wisp is alone, 1 mid-chase). The partner is None off a visit."""
        solo = self.solo(when)
        visit = self.visit(when)
        if visit is None:
            return solo, None, 0.
        start, end, from_side = visit
        u, tau = (when-start)/max(1e-6, end-start), when-start
        entering = smooth(u/DUET_ENTER)
        joining = smooth((u-DUET_FOLLOW)/DUET_JOIN)
        leaving = smooth((u-DUET_LEAVE)/(1-DUET_LEAVE))
        helix = smooth((u-DUET_HELIX[0])/.06)*smooth((DUET_HELIX[1]-u)/.06)
        # Trailing: behind the main wisp, echoing the swim it made a moment earlier, slowly closing the gap.
        follow = self.solo(when-1.2)+np.array([0., 0., -7.+3.5*smooth((u-DUET_ENTER)/(DUET_FOLLOW-DUET_ENTER))])
        # Joined: round and round each other on a wandering figure, swapping the lead; tighter in the helix.
        theta = 1.3*tau+2.2*math.sin(.37*tau)+3.2*tau*helix
        radius = (3.2+1.4*math.sin(.8*tau+1.))*(1-.65*helix)
        chase = radius*np.array([math.cos(theta), .8*math.sin(theta), .6*math.sin(2*theta+.5)])
        arrive, depart = np.array([16*from_side, 9., -24.]), np.array([-18*from_side, 12., 16.])
        partner = follow+(chase-follow)*joining
        partner = arrive+(partner-arrive)*entering
        partner = partner+(depart-partner)*leaving
        together = joining*(1-leaving)
        return solo+(-.55*chase-solo)*together, partner, together

    def duet_glow(self, when):
        """A hue drift that ripples through both wisps, their tails and motes while they are together."""
        return .35*self.chase(when)[2]*math.sin(1.7*when)

    def wisp_offset(self, wisp, when, now, side, up, tangent, energy=0.):
        """Where a wisp was relative to the path at time `when` (the head's time, or for a point on a tail the
        time the head passed it). Tails flick with a wave running down them, livelier on hits."""
        main, partner, _ = self.chase(when)
        offset = partner if wisp and partner is not None else main
        age = max(0., now-when)
        flick = min(1., age/.6)*(.45+.35*min(1.5, energy))
        offset = offset+flick*np.array([math.sin(9*age+3.1*when), .6*math.cos(7*age+2.3*when), 0.])
        return (side*offset[0]+up*offset[1]+tangent*offset[2])*BAND_WIDTH

    def head_times(self, number, distances):
        """When the run's head passed each distance along its path (the inverse of its timing keys)."""
        run = self.ribbon[number]
        if '_clock' not in run:
            times = run['keys'][0]
            grid = np.arange(times[0], times[-1]+1/60, 1/60)
            run['_clock'] = (np.maximum.accumulate([thread_distance(run['keys'], x) or 0. for x in grid]), grid)
        travelled, grid = run['_clock']
        return np.interp(distances, travelled, grid)

    def run_bands(self, run, t, eye):
        head = thread_distance(run['keys'], t)
        if head is None:
            return []
        number = next(k for k, other in enumerate(self.ribbon) if other is run)
        tail = dying_tail(run['keys'], t, RIBBON_REACH)
        samples, groups, travelled = [], [], 0.
        for (p, q), color, paint in zip(run['segments'], run['colors'], run['paint']):
            length = float(np.linalg.norm(q-p))
            start, travelled = travelled, travelled+length
            if not paint:
                if len(samples) >= 2:
                    groups.append(samples)
                samples = []
                continue
            if travelled <= tail or start >= head or length < 1e-6:
                continue
            marks = [max(tail, start)]+[d for d in np.arange(math.ceil(start/BAND_STEP)*BAND_STEP, travelled, BAND_STEP)
                                        if tail < d < head]+[min(head, travelled)]
            for distance in marks:
                if not samples or distance > samples[-1][1]+1e-6:
                    samples.append((p+(q-p)*((distance-start)/length), distance, np.array(color)/255))
        if len(samples) >= 2:
            groups.append(samples)
        energy, clock, tune = self.pulse(t)
        presence = self.partner_presence(t)
        visit = self.visit(t)
        bands = []
        for samples in groups:
            whens = self.head_times(number, [distance for _, distance, _ in samples])
            tangents = [steady_tangent(run, distance) for _, distance, _ in samples]
            for wisp in (0, 1):
                opacity = 1. if wisp == 0 else presence
                if opacity <= .001:
                    continue
                # The partner's tail only reaches back to where it flew in.
                chosen = [k for k in range(len(samples)) if wisp == 0 or whens[k] >= visit[0]]
                if len(chosen) < 2:
                    continue
                begin, finish = samples[chosen[0]][1], samples[chosen[-1]][1]
                for band in range(BANDS if wisp == 0 else BANDS-1):
                    rows = []
                    for k in chosen:
                        point, distance, color = samples[k]
                        tangent = tangents[k]
                        side = normalized(np.cross(tangent, eye-point))
                        up = normalized(np.cross(side, tangent))
                        pinch = smooth(min(finish-distance, distance-begin)/(BAND_WIDTH*14))
                        phase = distance/(BAND_WIDTH*16)+clock+band*1.7
                        centre = point+self.wisp_offset(wisp, whens[k], t, side, up, tangent, energy)
                        offset = ((band-(BANDS-1)/2)*1.2+math.sin(phase)*1.)*BAND_WIDTH*pinch*.8
                        width = (1.+.8*math.sin(phase*.6+band))*BAND_WIDTH*1.7*pinch
                        tint = shifted(color, (tune-.5)*.18+wisp*.2+self.duet_glow(whens[k]))
                        rows.append((*(centre+side*(offset-width/2)), 0., *tint))
                        rows.append((*(centre+side*(offset+width/2)), 1., *tint))
                    if len(rows) >= 4:
                        bands.append((np.array(rows), opacity))
        return bands

    def wisp_particles(self, t):
        """Glowing motes streaming from the wisp heads, bursting on every hit and pouring off both wisps in
        shifting colours while they chase, with sparks wherever the two pass close: [(position, size, opacity,
        colour)]. Each mote's path is solved from its birth time."""
        if not self.options['traces']:
            return []
        energy, clock, tune = self.pulse(t)
        music = self.music()
        result = []
        for number, run in enumerate(self.ribbon):
            if t > run['keys'][0][-1]+1.2 or t < run['keys'][0][0]:
                continue
            colour = np.array(run['colors'][0] if run['colors'] else (255, 255, 255))/255
            for k in range(36):  # motes born over the last 1.2 s
                born = math.floor(t*30)/30-k/30
                age = t-born
                if born < run['keys'][0][0]:
                    break
                head = self.head_at(number, born)
                if head is None:
                    continue
                point, tangent = head
                hits = music['times'][(music['times'] <= born) & (music['times'] > born-1/30)]
                together = self.chase(born)[2]
                burst = (5 if len(hits) else 1)+round(3*together)
                b_energy = self.pulse(born)[0]
                presence = self.partner_presence(born)
                side = normalized(np.cross(tangent, np.array([0., 0., 1.])))
                up = normalized(np.cross(side, tangent))
                for j in range(burst*2):
                    rng = random.Random(round(born*30)*97+j*13+number)
                    wisp = j % 2
                    if wisp and presence <= .001:
                        continue
                    origin = point+self.wisp_offset(wisp, born, born, side, up, tangent, b_energy)
                    velocity = np.array([rng.uniform(-1, 1), rng.uniform(-.4, 1.), rng.uniform(-1, 1)])*(.3+.9*(burst > 1))
                    position = origin+velocity*age-np.array([0., .12, 0.])*age*age
                    fade = (1-smooth(age/1.2))*smooth(age/.05)
                    tint = shifted(colour*.6+.4, (tune-.5)*.18+wisp*.2+self.duet_glow(born)+together*rng.uniform(-.25, .25))
                    result.append((position, BAND_WIDTH*(2.6 if burst > 1 else 1.5)*(1-.5*age),
                                   fade*(presence if wisp else 1.), tint))
            # Wherever the two wisps pass close, a spark flares.
            head = self.head_at(number, t)
            if head is not None and self.partner_presence(t) > .6:
                point, tangent = head
                side = normalized(np.cross(tangent, np.array([0., 0., 1.])))
                up = normalized(np.cross(side, tangent))
                gap = np.linalg.norm(self.wisp_offset(0, t, t, side, up, tangent)-self.wisp_offset(1, t, t, side, up, tangent))
                if gap < BAND_WIDTH*2.2:
                    middle = point+(self.wisp_offset(0, t, t, side, up, tangent)+self.wisp_offset(1, t, t, side, up, tangent))/2
                    result.append((middle, BAND_WIDTH*5, .9*(1-gap/(BAND_WIDTH*2.2)), (1., 1., 1.)))
        return result

    @lru_cache(maxsize=4096)
    def head_at(self, number, t):
        """Position and steady direction of a ribbon run's head at time t."""
        run = self.ribbon[number]
        head = thread_distance(run['keys'], t)
        if head is None or not run['segments']:
            return None
        return route_point(run, head), steady_tangent(run, head)

    # Hand-over to the scene mix, which carries the wisp across a change of scene.

    def wisp_runs(self):
        """(start, end) time of each ribbon run's main wisp."""
        self.plan()
        if not self.options['traces'] and self.options['geometry'] <= 0:
            return []
        return [(run['keys'][0][0], run['keys'][0][-1]) if run['keys'][0] else (math.inf, -math.inf) for run in self.ribbon]

    def wisp_screen(self, number, when, t):
        """Screen pixel of run `number`'s main wisp where it was at time `when`, filmed by the camera at time t."""
        head = self.head_at(number, when)
        if head is None:
            return None
        point, tangent = head
        eye, target, _, up = self.camera(t)
        side = normalized(np.cross(tangent, eye-point))
        lift = normalized(np.cross(side, tangent))
        position = point+self.wisp_offset(0, when, when, side, lift, tangent, self.pulse(when)[0])
        clip = self.projection@look_at(eye, target, up)@np.array([*position, 1.])
        if clip[3] <= 1e-6:
            return None
        return (clip[0]/clip[3]+1)/2*self.c.width, (1-clip[1]/clip[3])/2*self.c.height

    # Camera.

    def hold_pose(self, block, t):
        middle = (block['start']+block['end'])/2
        target = block['focus']+block['cruise']*(t-middle)
        eye = target+block['view']*block['camera_distance']
        return eye, target

    def camera(self, t):
        blocks = self.plan()
        number = max(0, bisect.bisect_right([b['move'] for b in blocks], t)-1)
        block = blocks[number]
        eye, target = self.hold_pose(block, t)
        roll = block['shot_roll']
        if number and t < block['move']+MOVE:
            # Blend from the old shot to the new one while both keep drifting, with an eased weight: the glide
            # leaves at the old shot's own velocity and arrives at the new one's, so nothing on screen (the wisp
            # least of all) lurches when a glide starts or stops.
            u = smooth(max(0., min(1., (t-block['move'])/MOVE)))
            old_eye, old_target = self.hold_pose(blocks[number-1], t)
            eye = old_eye+(eye-old_eye)*u
            target = old_target+(target-old_target)*u
            roll = blocks[number-1]['shot_roll']+(roll-blocks[number-1]['shot_roll'])*u
        forward = normalized(target-eye)
        angle = math.radians(roll)
        up = np.array([0., 1., 0.])
        up = up*math.cos(angle)+np.cross(forward, up)*math.sin(angle)+forward*np.dot(forward, up)*(1-math.cos(angle))
        return eye, target, number, up

    # Drawing.

    def beat(self, t):
        drums = self.rhythm.get('drums')
        if not drums:
            return 0.
        from rhythm import envelope
        return envelope(drums, t, .18)

    def block_opacity(self, number, current, t):
        """Earlier blocks stay where they were written, dimmed once the next block starts."""
        if number >= current:
            return 1.
        return 1-(1-OLD_BLOCK)*smooth((t-self.blocks[number+1]['start'])/DIM_TIME)

    def frame(self, t):
        c = self.c
        blocks = self.plan()
        gl = gl_stage((c.width, c.height))
        eye, target, current, up = self.camera(t)
        view = look_at(eye, target, up)
        camera = self.projection@view
        gl.begin()
        palette = blocks[current]['palette']
        sky = gl.texture(('sky', palette[0], palette[1]), lambda: gradient(tuple(round(v*.7) for v in palette[0]), palette[1]))
        gl.quad(sky, scaling(2., 2.))
        if self.world is not None:
            self.backdrop(gl, t)
        for model, texture, opacity, tint in self.shape_fill_items(gl, t):
            gl.quad(texture, camera@model, opacity, tint)
        band = gl.texture('band', band_image)
        for rows, opacity in self.ribbon_bands(t, eye):
            gl.strip(band, camera, rows, BAND_OPACITY*opacity)
        items = []
        beat = self.beat(t)
        dot = gl.texture('dot', soft_dot)
        for position, opacity, tint in self.ribbon_heads(t, eye):
            items.append((self.billboard(position, view, BAND_WIDTH*4), dot, .95*opacity, tint))
        for position, size, opacity, tint in self.wisp_particles(t):
            items.append((self.billboard(position, view, size), dot, opacity, tuple(tint)))
        reach = DRAW_REACH*blocks[current]['distance']
        for number in range(len(blocks)):
            block = blocks[number]
            if number > current+1 or np.linalg.norm(block['center']-target) > reach:
                continue
            opacity = self.block_opacity(number, current, t)
            for x, y, z, size, phase, speed in block['motes']:
                twinkle = .5+.5*math.sin(t*speed*2+phase)
                position = block['placement']@np.array([x+math.sin(t*.2*speed+phase)*.15, y+math.cos(t*.17*speed+phase)*.12, z, 1.])
                items.append((self.billboard(position[:3], view, size*(.7+.3*twinkle)), dot, .45*twinkle*opacity, (1., 1., 1.)))
            for word in block['words']:
                if word['effect']:
                    recipe = word['effect']
                    lead = (GROW_ENTRY if recipe.trajectory == 'grow' else PARTICLE_ENTRY)/c.effect_speed(recipe.id)
                else:
                    entry, stagger = (BOUNCE_ENTRY, BOUNCE_STAGGER) if word.get('bouncy') else (ENTRY, LETTER_STAGGER)
                    letters = word['motion'] in ('wave', 'bounce') or word['letter'] is not None or word.get('bouncy')
                    lead = entry+(len(word['text'])-1)*stagger if letters else entry
                if t >= word['start']-lead:
                    items.extend(self.word_items(gl, block, word, t, opacity, beat))
        depth = lambda item: (view@item[0]@np.array([0., 0., 0., 1.]))[2]
        for item in sorted(items, key=depth):
            if len(item) > 4:
                gl.fill(item[1], camera@item[0], item[2], item[4])
            else:
                gl.quad(item[1], camera@item[0], item[2], item[3])
        return gl.read()

    def billboard(self, position, view, size):
        model = np.identity(4)
        model[:3, :3] = view[:3, :3].T*size
        model[:3, 3] = position
        return model

    def entrance(self, block, word, progress, anchor_x):
        """Local transform of a landing word (or letter) about its baseline anchor."""
        cap = word['cap']
        settled = overshoot(progress)
        if word.get('bouncy'):
            s = max(.01, elastic(progress))
            return translation(0, (1-smooth(progress))*cap*.7)@np.diag((s, s, 1., 1.))
        kind = 'pop' if word['role'] == 'hero' and block['entrance'] in ('rise',) else block['entrance']
        if kind == 'flip':
            return rotation(pitch=-95*(1-smooth(progress)))
        if kind == 'swing':
            return translation(-anchor_x)@rotation(yaw=85*(1-smooth(progress)))@translation(anchor_x)
        if kind == 'drop':
            return translation(0, (1-settled)*cap*1.4)
        if kind == 'pop':
            s = max(.01, settled)
            return translation(0, 0, (1-smooth(progress))*-cap*2)@np.diag((s, s, 1., 1.))
        return translation(0, -(1-settled)*cap*.6, (1-smooth(progress))*-cap*3)

    def effect_items(self, gl, block, word, t, opacity):
        """A top-row word forming through the block's particle effect, drawn flat and turned gently in 3D."""
        c, recipe = self.c, word['effect']
        length = (GROW_ENTRY if recipe.trajectory == 'grow' else PARTICLE_ENTRY)/c.effect_speed(recipe.id)
        progress = min(1., (t-word['start']+length)/length)
        if progress <= 0:
            return []
        size = max(FONT_LIMITS[0], min(EFFECT_FONT, round(REFERENCE*word['scale']*self.ppu)))
        k = REFERENCE*word['scale']/size
        font = stage_font(word['font'], size)
        ascent, descent = font.getmetrics()
        pad = max(6, round(size*.14))
        side, top, bottom = round(size*.6), round(size*1.1), round(size*.5)

        def draw():
            from particle_motion import paint_transition
            sprite = Image.new('RGBA', (math.ceil(font.getlength(word['text']))+pad*2, ascent+descent+pad*2))
            ImageDraw.Draw(sprite).text((pad, pad+ascent), word['text'], font=font, fill=word['color'], anchor='ls')
            edges = [0]+[pad+round(font.getlength(word['text'][:n])) for n in range(1, len(word['text']))]+[sprite.width]
            layer = Image.new('RGBA', (sprite.width+side*2, sprite.height+top+bottom))
            paint_transition(layer, sprite, side, top, 'entrance', 1-progress, recipe, word['line']*31+word['index'],
                             c.effect_intensity(recipe), .6, c.effect_cache, glyph_spans=list(zip(edges, edges[1:])))
            return layer
        if progress >= 1:
            texture = gl.texture(('effect', word['text'], recipe.id, size, word['color'], word['line'], word['index']), draw)
        else:
            texture = gl.transient(draw())
        width, height = texture.size
        middle = font.getlength(word['text'])*k/2
        sway = rotation(yaw=math.sin(t*.7+word['index'])*5*smooth(max(0., t-word['start'])/2))
        model = (block['placement']@word['frame']@translation(word['x']+middle, word['baseline'], 0.)@sway
                 @translation((width/2-side-pad)*k-middle, (top+pad+ascent-height/2)*k, 0.)@scaling(width*k, height*k))
        return [(model, texture, opacity, (1., 1., 1.))]

    def word_items(self, gl, block, word, t, opacity, beat):
        if word['effect']:
            return self.effect_items(gl, block, word, t, opacity)
        size = max(FONT_LIMITS[0], min(FONT_LIMITS[1], round(REFERENCE*word['scale']*self.ppu)))
        k = REFERENCE*word['scale']/size
        letters = word['motion'] in ('wave', 'bounce') or word['letter'] is not None or word.get('bouncy')
        pieces = list(enumerate(word['text'])) if letters else [(None, word['text'])]
        font = stage_font(word['font'], size)
        entry, stagger = (BOUNCE_ENTRY, BOUNCE_STAGGER) if word.get('bouncy') else (ENTRY, LETTER_STAGGER)
        lead = entry+(len(word['text'])-1)*stagger if letters else entry
        sweet = bool(word.get('sweet'))
        items = []
        for number, text in pieces:
            if number is not None and (number == word['letter'] or not text.strip()):
                continue
            offset = font.getlength(word['text'][:number])*k if number is not None else 0.
            delay = (number or 0)*stagger
            progress = min(1., (t-word['start']+lead-delay)/entry)
            if progress <= 0:
                continue
            color = (255, 255, 255) if sweet else word['color']
            key = ('word', text, word['font'], size, color)
            sprite = gl.texture(key, lambda text=text, color=color: text_sprite(text, word['font'], size, color)[0])
            pad = max(6, round(size*.14))
            ascent = font.getmetrics()[0]
            width, height = sprite.size
            relative = np.array([(width/2-pad)*k, (ascent+pad-height/2)*k])
            glyph_width = font.getlength(text)*k
            anchor = np.array([word['x']+offset+glyph_width/2, word['baseline']])
            local = self.motion(word, t, beat, number, anchor_x=glyph_width/2)
            local = local@self.entrance(block, word, progress, glyph_width/2)
            alpha = smooth(progress*2.2)*opacity
            base = (block['placement']@word['frame']@translation(*anchor, 0.)@local
                    @translation(relative[0]-glyph_width/2, relative[1], 0.))
            if sweet:
                fill = dict(word['fills'][(number or 0) % len(word['fills'])], time=t,
                            origin=(-pad*k/word['cap'], -(height-ascent-pad)*k/word['cap']),
                            span=(width*k/word['cap'], height*k/word['cap']))
                items.append((base@scaling(width*k, height*k), sprite, alpha, (1., 1., 1.), fill))
                continue
            if word['role'] == 'hero':
                depth = EXTRUDE_DEPTH*word['cap']
                for layer in range(EXTRUDE_LAYERS, 0, -1):
                    shade = .22+.25*(1-layer/EXTRUDE_LAYERS)
                    items.append((base@translation(0, 0, -depth*layer/EXTRUDE_LAYERS)@scaling(width*k, height*k), sprite, alpha,
                                  (shade, shade, shade*1.1)))
            items.append((base@scaling(width*k, height*k), sprite, alpha, (1., 1., 1.)))
        if word['ornament']:
            items.extend(self.ornament_items(gl, block, word, font, k, t, opacity, beat))
        return items

    def motion(self, word, t, beat, letter, anchor_x):
        """Continuing movement of a landed word: a travelling letter wave, a beat pulse or a slow 3D tilt."""
        cap, age = word['cap'], max(0., t-word['start'])
        settle = smooth(age/.6)
        if word['motion'] == 'wave' and letter is not None:
            return translation(0, math.sin(t*4.2-letter*.7)*cap*.09*settle)
        if word['motion'] == 'bounce' and letter is not None:
            hop = abs(math.sin(t*3.2-letter*.55))
            return translation(0, hop*cap*HOP*settle)@rotation(roll=math.sin(t*3.2-letter*.55)*SWAY*settle)
        if word['motion'] == 'pulse':
            s = 1+.09*beat*settle+.03*math.sin(t*3.1)*settle
            return translation(0, cap/2)@np.diag((s, s, 1., 1.))@translation(0, -cap/2)
        if word['motion'] == 'tilt':
            return rotation(yaw=math.sin(t*1.3+word['index'])*16*settle, pitch=math.sin(t*.9)*6*settle)
        return np.identity(4)

    def ornament_items(self, gl, block, word, font, k, t, opacity, beat):
        cap = word['cap']
        progress = min(1., (t-word['start']+ENTRY_LEAD)/(ENTRY*1.6))
        grow = max(0., overshoot(progress))
        if word['letter'] is not None:
            letter = word['text'][word['letter']]
            middle = word['x']+(font.getlength(word['text'][:word['letter']])+font.getlength(letter)/2)*k
            center, size = np.array([middle, word['baseline']+cap/2, 0.]), cap*ORNAMENT_SIZE
            if word['motion'] == 'wave':
                center[1] += math.sin(t*4.2-word['letter']*.7)*cap*.09*smooth(max(0., t-word['start'])/.6)
        else:
            x, y, size = word['slot']
            size *= SLOT_PICTURE
            center = np.array([x, y+math.sin(t*1.7)*cap*.05, cap*.15])
        items = []
        for key, image, pose in glyph_art.ornament_layers(word['ornament'], t, beat):
            texture = gl.texture(('ornament',)+tuple(key), image)
            scale = size*pose['scale']*grow
            if scale <= 1e-4:
                continue
            model = (block['placement']@word['frame']@translation(*(center+np.array([pose['dx'], pose['dy'], pose['dz']])*size))
                     @rotation(roll=pose['angle'])@scaling(scale, scale))
            items.append((model, texture, pose['alpha']*opacity*smooth(progress*2), (1., 1., 1.)))
        return items
