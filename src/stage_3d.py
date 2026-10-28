"""Lyric blocks set in a 3D world, filmed by a gliding camera (ModernGL, headless).

Lines that are sung together form a squarish justified block (see lyric_blocks). Every
block stands somewhere in a 3D space, turned a little towards or away from the viewer.
The camera never stops: it cruises across the current block while it is sung, then
speeds up along an arc to the next one, pulling back on the way so earlier blocks (which
stay where they were written) come back into view. Behind everything lies one continuous
collage of every illustration, stitched along the camera's path like the 2D panning
canvas and bent like a sheet of curved paper: gentle folds fixed in the world, shaded on
their slopes, that turn and shift with parallax as the camera glides past.
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
heavy display word filled with a slowly flowing marbled texture in the accent's tones (drawn
by a shader, so the texture keeps moving inside the letters), and the last word set
vertically close beside the rows; every letter springs in with an elastic bounce, and the camera zooms in and
rolls into a tilt. Which side, which way the vertical word reads, how the fonts pair, the
tilt and the zoom vary from block to block. A scene effect
can own the block's particle effects (`crowns`, such as maple and oak for the tree canopy);
the block director then picks one of them per block. When the video mixes scenes, `only` limits
the stage to the lines of the song sections it films. Illustrations hang far behind as planes
that shift with parallax. Every frame is a pure function of time, so renders split
across processes exactly.
"""
from __future__ import annotations

import bisect
from collections import OrderedDict
import colorsys
from functools import lru_cache
import math
import random
import threading

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import glyph_art
from lyric_blocks import TARGET_RATIO, group_lines, layout_block
from realtime_typography import (BACKDROP_COLORS, FUNCTION_WORDS, SHAPE_LIFE, SHAPES, THREAD_LIFE, assign_roles, bare, hex_rgb,
                                  monotone_keys, overshoot, role_font, smooth, thread_distance)

FOV = 38.
BLOCK_WIDTH = 4.
FILL_WIDTH, FILL_HEIGHT = .74, .72
REFERENCE = 200
OVERSAMPLE = 1.25
FONT_LIMITS = (16, 440)
MOVE, MOVE_LEAD = 1.3, .9
HOLD_DOLLY, CRUISE = .06, .14
ARC_LIFT, ARC_PULL = .12, .55
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
ENTRANCES = ('flip', 'swing', 'rise', 'drop')
MOTIONS = ('wave', 'pulse', 'tilt')
OLD_BLOCK, DIM_TIME = .45, 1.
DRAW_REACH = 3.
EXTRUDE_LAYERS, EXTRUDE_DEPTH = 7, .07
ORNAMENT_SIZE, FLOAT_SIZE = 1.12, .9
BACKDROP_DEPTH, BACKDROP_TINT = 8., .62
CHUNK, CHUNK_LIMIT = 1024, 16
PAPER_STRIPS, PAPER_DEPTH, PAPER_FOLD, PAPER_SHADE = 14, 1.1, .16, .55
MOTES = 36
SHAPE_DEPTHS = (-3.2, -.6)
SHAPE_REACH = 1.5
BANDS, BAND_WIDTH, BAND_STEP, BAND_OPACITY = 3, .05, .09, .42
RIBBON_DEPTH, RIBBON_BOW, RIBBON_REACH = -.12, .35, 28.
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
    vec2 q = vec2(fbm(p*1.1+vec2(0., time*.16)), fbm(p*1.1+vec2(5.2, 1.3)-vec2(time*.12, 0.)));
    float n = fbm(p*1.4+2.2*q+vec2(time*.05, -time*.04));
    vec3 ink = mix(deep, middle, smoothstep(.25, .62, n));
    ink = mix(ink, light, smoothstep(.6, .9, n)*.85);
    float band = abs(fract((p.x*.55+p.y*.3)*.35-time*.12)-.5);
    ink += light*(1.-smoothstep(.0, .06, band))*.22;
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
        for name in ('time', 'seed'):
            program[name].value = float(fill[name])
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


def texture_tones(accent):
    """Three related tones for the textured word: a deep shade, the accent (softened), and a light tint."""
    h, s, v = colorsys.rgb_to_hsv(*(c/255 for c in accent))
    tone = lambda s, v: tuple(round(c*255) for c in colorsys.hsv_to_rgb(h, s, v))  # noqa: E731
    return dict(deep=tone(min(1., s*1.05), v*.32), middle=tone(min(.78, s), min(1., v*.95)), light=tone(s*.28, 1.))


def elastic(value):
    """0 to 1 with a springy overshoot that settles: letters pop in and wobble into place."""
    value = max(0., min(1., value))
    return 1-math.exp(-6*value)*math.cos(value*math.pi*3.2)


def shape_image(kind, filled, size=256):
    """A white outlined (and maybe translucent filled) shape, tinted by the shape's colour when drawn."""
    image = Image.new('RGBA', (size*2, size*2))
    draw = ImageDraw.Draw(image)
    sides = {'ring': 72, 'circle': 72, 'triangle': 3, 'square': 4, 'hexagon': 6}[kind]
    r = size*.9
    points = [(size+r*math.cos(2*math.pi*k/sides-math.pi/2), size+r*math.sin(2*math.pi*k/sides-math.pi/2)) for k in range(sides)]
    if filled and kind != 'ring':
        draw.polygon(points, fill=(255, 255, 255, 70))
    draw.line(points+points[:2], fill=(255, 255, 255, 235), width=round(size*.035), joint='curve')
    return image.resize((size, size), Image.Resampling.LANCZOS)


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
            palette = [hex_rgb(v) for v in PALETTES[scene['palette']]]
            words = self.block_words(members, palette)
            accent = hex_rgb(directed['accent']) if directed and directed.get('accent') else ACCENT
            style = self.contrast_style(words, rng, accent) if self.layouts.get(members[0]) == 'contrast' else None
            arrange = (lambda pictured=None: self.arrange_contrast(words, members, style, pictured)) if style else \
                (lambda pictured=None: self.arrange(words, members, pictured))
            height = arrange()
            effect = self.block_effect(members, number, directed)
            self.crown(words, effect)
            self.choose_accent(words, palette[2], accent, style)
            self.choose_motion(words, rng, (directed or {}).get('ornament') if direction is not None else False)
            pictured = next((w for w in words if w['ornament'] and w['letter'] is None), None)
            if pictured is not None:
                height = arrange(pictured)
                self.crown(words, effect)
                self.choose_accent(words, palette[2], accent, style)
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
            sweet.update(font='sweet', sweet=True, text=sweet['text'].lower(), fill=texture_tones(accent))
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

    def block_effect(self, members, number=0, directed=None):
        """The block's particle entrance. In a scene that owns particle effects: the one the block director
        picked, or the scene's effects in turn. Otherwise a top-only effect if any of its lines has one,
        else the first line's."""
        c = self.c
        if getattr(c, 'particle_intensity', 0) <= 0:
            return None
        if self.crowns is not None:
            owned = [e for e in self.crowns.get(members[0]) or [] if e in c.effect_catalog['entrance']]
            if not owned:
                return None
            pick = (directed or {}).get('particle')
            return c.effect_catalog['entrance'][pick if pick in owned else owned[number % len(owned)]]
        recipes = [c.effect_catalog['entrance'].get(c.effect_pairs[index][0]) for index in members]
        recipes = [recipe for recipe in recipes if recipe is not None]
        return next((r for r in recipes if r.placement == 'top'), recipes[0] if recipes else None)

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
            word = next((w for w in words if (w['line'], w['index']) == (spec.get('line'), spec.get('word')) and not w['effect']
                         and not w.get('vertical') and not w.get('sweet')), None)
            if word is None:
                return
            word['ornament'] = dict(kind=spec.get('library') if spec.get('source') == 'library' or not spec.get('image') else None,
                                    image=spec.get('image'), motion=spec.get('motion'))
            if not word['ornament']['kind'] and not word['ornament']['image']:
                word['ornament'] = None
                return
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
        """One collage of every full-screen illustration, stitched along where the camera looks (as the 2D
        panning canvas is), on a plane behind all the blocks; None without full-screen artwork."""
        c = self.c
        paths = list(getattr(c, 'illustration_paths', None) or [])
        if not paths or c.artwork_mode not in ('fullscreen', 'verse'):
            return None
        from world_canvas import WorldCanvas
        starts = list(getattr(c, 'art_starts', None) or [0.])[:len(paths)]
        spans = [(start, starts[n+1] if n+1 < len(starts) else c.duration) for n, start in enumerate(starts)]
        self.backdrop_z = DEPTHS[0]-BACKDROP_DEPTH
        distance = float(np.median([b['distance'] for b in self.blocks]))+DEPTHS[0]+BACKDROP_DEPTH
        footprint = 2*distance*math.tan(math.radians(FOV)/2)*self.aspect
        self.backdrop_scale = c.width*1.15/footprint
        stage = self

        class Path:
            def at(self, t):
                eye, target, _, _ = stage.camera(t)
                return target[0]*stage.backdrop_scale, -target[1]*stage.backdrop_scale
        return WorldCanvas([str(p) for p in paths], spans, c.width, c.height, Path())

    def backdrop_items(self, gl, eye, view):
        """The part of the collage the camera sees this frame, on curved paper. The collage is cut into fixed
        square chunks (made once, kept on the GPU); each chunk is drawn as thin vertical strips that follow
        the folds, each showing its own slice of the chunk, darker where the paper turns away."""
        half = math.tan(math.radians(FOV)/2)
        corners = []
        for x in (-1, 1):
            for y in (-1, 1):
                direction = -view[2, :3]+view[0, :3]*x*half*self.aspect*1.1+view[1, :3]*y*half*1.1
                if direction[2] >= -1e-3:
                    return []
                corners.append(eye+direction*(self.backdrop_z-PAPER_DEPTH*1.5-eye[2])/direction[2])
        scale = self.backdrop_scale
        xs, ys = [p[0]*scale for p in corners], [-p[1]*scale for p in corners]
        columns = range(math.floor(min(xs)/CHUNK), math.floor(max(xs)/CHUNK)+1)
        rows = range(math.floor(min(ys)/CHUNK), math.floor(max(ys)/CHUNK)+1)
        if len(columns)*len(rows) > CHUNK_LIMIT:
            return []
        fold = lambda x: self.backdrop_z+PAPER_DEPTH*(math.sin(x*PAPER_FOLD+.7)+.45*math.sin(x*PAPER_FOLD*2.3+1.9))  # noqa: E731
        size = CHUNK/scale
        strips = []
        for column in columns:
            for row in rows:
                texture = gl.chunk(('paper', column, row), lambda column=column, row=row:
                                   self.world.view(column*CHUNK, row*CHUNK, CHUNK, CHUNK).convert('RGB'))
                x0, middle = column*size, -(row+.5)*size
                for k in range(PAPER_STRIPS):
                    a, b = x0+size*k/PAPER_STRIPS, x0+size*(k+1)/PAPER_STRIPS
                    za, zb = fold(a), fold(b)
                    model = np.identity(4)
                    model[:3, 0] = (b-a, 0., zb-za)
                    model[:3, 1] = (0., size, 0.)
                    model[:3, 2] = normalized((za-zb, 0., b-a))
                    model[:3, 3] = ((a+b)/2, middle, (za+zb)/2)
                    light = BACKDROP_TINT*(1-PAPER_SHADE*min(1., abs(zb-za)/(b-a)))*(1+.12*(za < zb))
                    strips.append((model, texture, (light,)*3, (k/PAPER_STRIPS, 0., 1/PAPER_STRIPS, 1.)))
        return strips

    def plan_shapes(self):
        """Outlined or translucent shapes around the blocks on strong bass notes (or block starts without
        bass), on screen for about the `geometry` share of the stage's time, in the block's own colours."""
        blocks = self.blocks
        span = sum(b['hold'][1]-b['hold'][0] for b in blocks)
        count = round(self.options['geometry']*span/SHAPE_LIFE)
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
            shapes.append(dict(start=time, block=number, kind=rng.choice(SHAPES), filled=rng.random() < .4, color=color,
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
            fade = smooth(age/.8)*(1-smooth((age-SHAPE_LIFE+1.)/1.))
            if fade <= .01:
                continue
            block = self.blocks[shape['block']]
            x, y, z = (p+d*age for p, d in zip(shape['position'], shape['drift']))
            size = shape['size']*(1+.08*age/SHAPE_LIFE)
            texture = gl.texture(('shape', shape['kind'], shape['filled']), lambda shape=shape: shape_image(shape['kind'], shape['filled']))
            model = (block['placement']@translation(x, y, z)@rotation(*shape['tilt'], roll=shape['spin']*age)@scaling(size, size))
            items.append((model, texture, .75*fade, tuple(v/255 for v in shape['color'])))
        return items

    def plan_ribbon(self):
        """The bands' path through the world: a smooth curve just behind each hero word, bowed out of the
        block plane between words, reached as each is sung (the same timing as the 2D thread)."""
        stops = []
        for block in self.blocks:
            for word in block['words']:
                if word['role'] == 'hero':
                    local = np.array([word['x']+word['width']/2, word['baseline']+word['cap']/2, RIBBON_DEPTH, 1.])
                    stops.append((word['start'], (block['placement']@word['frame']@local)[:3], word['color'], block['placement'][:3, 2]))
        if len(stops) < 2:
            return None
        stops.sort(key=lambda stop: stop[0])
        times = []
        for stop in stops:
            times.append(max(stop[0], times[-1]+.05) if times else stop[0])
        points, colors, distances, total = [], [], [0.], 0.
        for (_, a, _, normal_a), (_, b, color, normal_b) in zip(stops, stops[1:]):
            bow = (normal_a+normal_b)/2*min(1.5, np.linalg.norm(b-a))*RIBBON_BOW
            curve = [(1-u)**2*a+2*(1-u)*u*((a+b)/2+bow)+u*u*b for u in (k/24 for k in range(25))]
            for p, q in zip(curve, curve[1:]):
                points.append((p, q))
                colors.append(color)
                total += float(np.linalg.norm(q-p))
            distances.append(total)
        return dict(segments=points, colors=colors, keys=monotone_keys(times, distances))

    def ribbon_bands(self, t, eye):
        """Translucent bands from the thread's tail to its head, each swelling and narrowing in its own slow
        wave and pinching together at both ends, turned to face the camera: one vertex row per sample."""
        if not self.options['traces'] or not self.ribbon:
            return []
        head = thread_distance(self.ribbon['keys'], t)
        if head is None:
            return []
        tail = max(thread_distance(self.ribbon['keys'], t-THREAD_LIFE) or 0., head-RIBBON_REACH)
        samples, travelled = [], 0.
        for (p, q), color in zip(self.ribbon['segments'], self.ribbon['colors']):
            length = float(np.linalg.norm(q-p))
            start, travelled = travelled, travelled+length
            if travelled <= tail or start >= head or length < 1e-6:
                continue
            marks = [max(tail, start)]+[d for d in np.arange(math.ceil(start/BAND_STEP)*BAND_STEP, travelled, BAND_STEP)
                                        if tail < d < head]+[min(head, travelled)]
            for distance in marks:
                if not samples or distance > samples[-1][1]+1e-6:
                    samples.append((p+(q-p)*((distance-start)/length), distance, np.array(color)/255))
        if len(samples) < 2:
            return []
        bands = []
        for band in range(BANDS):
            rows = []
            for number, (point, distance, color) in enumerate(samples):
                before, after = samples[max(0, number-1)][0], samples[min(len(samples)-1, number+1)][0]
                side = normalized(np.cross(after-before, eye-point))
                pinch = smooth(min(head-distance, distance-tail)/(BAND_WIDTH*14))
                phase = distance/(BAND_WIDTH*16)+t*.5+band*1.7
                offset = ((band-(BANDS-1)/2)*1.4+math.sin(phase)*1.2)*BAND_WIDTH*pinch
                width = (1.1+.8*math.sin(phase*.6+band))*BAND_WIDTH*2*pinch
                rows.append((*(point+side*(offset-width/2)), 0., *color))
                rows.append((*(point+side*(offset+width/2)), 1., *color))
            bands.append(np.array(rows))
        return bands

    # Camera.

    def hold_pose(self, block, t):
        start, end = block['hold']
        u = (t-start)/max(1e-3, end-start)
        middle = (block['start']+block['end'])/2
        target = block['focus']+block['cruise']*(t-middle)
        eye = target+block['view']*block['distance']*(1-HOLD_DOLLY*u)+block['side']*.1*math.sin(t*.4)*block['drift']
        return eye, target

    def camera(self, t):
        blocks = self.plan()
        number = max(0, bisect.bisect_right([b['move'] for b in blocks], t)-1)
        block = blocks[number]
        eye, target = self.hold_pose(block, t)
        if number and t < block['move']+MOVE:
            u = ease((t-block['move'])/MOVE)
            old_eye, old_target = self.hold_pose(blocks[number-1], t)
            travel = np.linalg.norm(target-old_target)
            arc = math.sin(math.pi*u)
            eye = old_eye+(eye-old_eye)*u+np.array([0., 1., 0.])*arc*travel*ARC_LIFT
            eye = eye+normalized(eye-target)*arc*travel*ARC_PULL
            target = old_target+(target-old_target)*u
        roll = block['roll']
        if number and t < block['move']+MOVE:
            roll = blocks[number-1]['roll']+(roll-blocks[number-1]['roll'])*ease((t-block['move'])/MOVE)
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
            for model, texture, light, uv in self.backdrop_items(gl, eye, view) or []:
                gl.quad(texture, camera@model, 1., light, uv)
        band = gl.texture('band', band_image)
        for rows in self.ribbon_bands(t, eye):
            gl.strip(band, camera, rows, BAND_OPACITY)
        items = self.shape_items(gl, t)
        beat = self.beat(t)
        dot = gl.texture('dot', soft_dot)
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
                if t >= word['start']-ENTRY_LEAD:
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
        progress = min(1., (t-word['start']+ENTRY_LEAD)/length)
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
                             c.particle_intensity, .6, c.effect_cache, glyph_spans=list(zip(edges, edges[1:])))
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
        sweet = bool(word.get('sweet'))
        items = []
        for number, text in pieces:
            if number is not None and (number == word['letter'] or not text.strip()):
                continue
            offset = font.getlength(word['text'][:number])*k if number is not None else 0.
            delay = (number or 0)*stagger
            progress = min(1., (t-word['start']+ENTRY_LEAD-delay)/entry)
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
                fill = dict(word['fill'], time=t, seed=word['line']*13+word['index'],
                            origin=((offset-pad*k)/word['cap'], -(height-ascent-pad)*k/word['cap']),
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
