"""Headless GL: shaders, matrices and a per-thread context that draws quads and strips."""

from __future__ import annotations
from collections import OrderedDict
import math
import threading
import numpy as np
from PIL import Image
from render.stage_3d.common import TEXTURE_LIMIT, normalized

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
    if (texel.a < .01) discard;
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
    if (texel.a < .01) discard;
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
    if (pattern == 5) {
        float x = origin.x + uv.x*span.x;
        float scan = fract(time*.18+seed*.035)*(span.x+2.)-1.;
        float reflection = exp(-pow((x-scan)/.32, 2.));
        float brushing = .025*sin((origin.y+uv.y*span.y)*180.);
        float rim = clamp(length(vec2(dFdx(texel.a),dFdy(texel.a)))*12.,0.,1.);
        ink = mix(deep,middle,.76+brushing);
        ink = mix(ink,light,clamp(reflection*.82+rim*.28,0.,1.));
    }
    color = vec4(ink*texel.r, texel.a)*opacity;
}
'''
_LOCAL = threading.local()


def perspective(fov, aspect, near=0.05, far=400.0):
    f = 1 / math.tan(math.radians(fov) / 2)
    return np.array(
        [
            [f / aspect, 0, 0, 0],
            [0, f, 0, 0],
            [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
            [0, 0, -1, 0],
        ]
    )


def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    forward = normalized(np.subtract(target, eye))
    side = normalized(np.cross(forward, up))
    upward = np.cross(side, forward)
    view = np.identity(4)
    view[0, :3], view[1, :3], view[2, :3] = side, upward, -forward
    view[:3, 3] = -view[:3, :3] @ np.asarray(eye, dtype=float)
    return view


def rotation(yaw=0.0, pitch=0.0, roll=0.0):
    """4x4 rotation from degrees: yaw about y, pitch about x, roll about z."""
    a, b, c = (math.radians(v) for v in (yaw, pitch, roll))
    ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    matrix = np.identity(4)
    matrix[:3, :3] = ry @ rx @ rz
    return matrix


def translation(x=0.0, y=0.0, z=0.0):
    matrix = np.identity(4)
    matrix[:3, 3] = (x, y, z)
    return matrix


def scaling(x, y):
    return np.diag((x, y, 1.0, 1.0))


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
        from render.stage_3d.sculpture import VERTEX as SIDE_VERTEX, FRAGMENT as SIDE_FRAGMENT

        self.side_program = self.ctx.program(vertex_shader=SIDE_VERTEX, fragment_shader=SIDE_FRAGMENT)
        self.meshes = OrderedDict()
        samples = min(4, self.ctx.max_samples)
        self.msaa = self.ctx.framebuffer(
            [self.ctx.renderbuffer(self.size, 4, samples=samples)],
            self.ctx.depth_renderbuffer(self.size, samples=samples),
        )
        self.output = self.ctx.framebuffer(
            [self.ctx.renderbuffer(self.size, 4)], self.ctx.depth_renderbuffer(self.size)
        )
        self.textures = OrderedDict()
        self.transients = []

    def upload(self, image):
        pixels = np.asarray(image.convert('RGBA'), dtype=np.float32)
        pixels[..., :3] *= pixels[..., 3:] / 255
        texture = self.ctx.texture(image.size, 4, pixels.round().astype(np.uint8).tobytes())
        texture.build_mipmaps()
        texture.filter = (self.moderngl.LINEAR_MIPMAP_LINEAR, self.moderngl.LINEAR)
        texture.anisotropy = 8.0
        texture.repeat_x = texture.repeat_y = False
        return texture

    def texture(self, key, image):
        """A cached, mipmapped, premultiplied texture; `image` may be a callable that makes it."""
        from render.scene_fonts import current_font

        key = (current_font(), key)
        if key in self.textures:
            self.textures.move_to_end(key)
            return self.textures[key]
        texture = self.textures[key] = self.upload(image() if callable(image) else image)
        while len(self.textures) > TEXTURE_LIMIT:
            self.textures.popitem(last=False)[1].release()
        return texture

    def transient(self, image):
        """A texture for this frame only, such as a particle effect still in motion."""
        texture = self.upload(image)
        self.transients.append(texture)
        return texture

    def begin(self):
        self.msaa.use()
        self.ctx.viewport = (0, 0, *self.size)
        self.msaa.clear(0.0, 0.0, 0.0, 1.0)
        self.ctx.enable(self.moderngl.BLEND)
        self.ctx.blend_func = (self.moderngl.ONE, self.moderngl.ONE_MINUS_SRC_ALPHA)
        self.ctx.disable(self.moderngl.DEPTH_TEST)

    def side_mesh(self, key, mask):
        from render.scene_fonts import current_font
        from render.stage_3d.sculpture import side_vertices

        key = (current_font(), key)
        if key not in self.meshes:
            vertices = side_vertices(mask())
            if not len(vertices):
                return None
            buffer = self.ctx.buffer(vertices.tobytes())
            vao = self.ctx.vertex_array(self.side_program, [(buffer, '3f 3f', 'position', 'normal')])
            self.meshes[key] = (vao, buffer)
            while len(self.meshes) > 128:
                old_vao, old_buffer = self.meshes.popitem(last=False)[1]
                old_vao.release()
                old_buffer.release()
        self.meshes.move_to_end(key)
        return self.meshes[key][0]

    def sides(self, vao, mvp, model, opacity, tint, eye, time):
        program = self.side_program
        program['mvp'].write(np.ascontiguousarray(mvp.T, dtype='f4').tobytes())
        program['model'].write(np.ascontiguousarray(model.T, dtype='f4').tobytes())
        normal = np.linalg.inv(model[:3, :3]).T
        program['normal_matrix'].write(np.ascontiguousarray(normal.T, dtype='f4').tobytes())
        program['opacity'].value = float(opacity)
        program['tint'].value = tuple(float(v) for v in tint)
        program['eye'].value = tuple(float(v) for v in eye)
        program['time'].value = float(time)
        vao.render(self.moderngl.TRIANGLES)

    def quad(self, texture, mvp, opacity=1.0, tint=(1.0, 1.0, 1.0), uv=(0.0, 0.0, 1.0, 1.0)):
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
        program['uv_rect'].value = (0.0, 0.0, 1.0, 1.0)
        for name in ('deep', 'middle', 'light'):
            program[name].value = tuple(v / 255 for v in fill[name])
        for name in ('time', 'seed', 'angle', 'speed'):
            program[name].value = float(fill[name])
        program['pattern'].value = int(fill['pattern'])
        for name in ('origin', 'span'):
            program[name].value = tuple(float(v) for v in fill[name])
        self.fill_vao.render(self.moderngl.TRIANGLES, vertices=6)

    def strip(self, texture, mvp, vertices, opacity=1.0):
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
        for vao, buffer in self.meshes.values():
            vao.release()
            buffer.release()
        self.meshes.clear()
        for texture in self.textures.values():
            texture.release()
        self.textures.clear()
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
