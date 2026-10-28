"""Headless ModernGL 3D particles with instancing, perspective and HDR bloom."""
from pathlib import Path
from project_paths import PROJECT_ROOT
import threading
from PIL import Image

_LOCAL=threading.local()
EFFECTS=('sparks','dust','trails','fragments','orbits','confetti')

class ParticleRenderer:
    def __init__(self,size):
        try:
            import moderngl
        except ImportError as exc:
            raise RuntimeError('3D particles require ModernGL. Install requirements.txt.') from exc
        self.size=tuple(size);self.closed=False;self.resources=[]
        try:
            self.ctx=moderngl.create_context(standalone=True,require=330)
            self.renderer=self.ctx.info['GL_RENDERER']
            print('3D particles: ModernGL / '+self.renderer,flush=True)
            shaders=PROJECT_ROOT/'shaders'
            read=lambda name:(shaders/name).read_text(encoding='utf-8-sig')
            self.program=self.track(self.ctx.program(vertex_shader=read('particles.vert'),fragment_shader=read('particles.frag')))
            self.vao=self.track(self.ctx.vertex_array(self.program,[]))
            self.blur=self.track(self.ctx.program(vertex_shader=read('fullscreen.vert'),fragment_shader=read('bloom.frag')))
            self.blur_vao=self.track(self.ctx.vertex_array(self.blur,[]))
            self.composite=self.track(self.ctx.program(vertex_shader=read('fullscreen.vert'),fragment_shader=read('composite.frag')))
            self.composite_vao=self.track(self.ctx.vertex_array(self.composite,[]))
            self.hdr=self.texture(self.size,'f2');self.target=self.track(self.ctx.framebuffer([self.hdr]))
            half=(max(1,size[0]//2),max(1,size[1]//2))
            self.blur_a=self.texture(half,'f2');self.blur_b=self.texture(half,'f2')
            self.fbo_a=self.track(self.ctx.framebuffer([self.blur_a]));self.fbo_b=self.track(self.ctx.framebuffer([self.blur_b]))
            self.output=self.texture(self.size,'f1');self.final=self.track(self.ctx.framebuffer([self.output]))
            self.program['resolution'].value=tuple(map(float,size))
            self.blur['source'].value=0;self.composite['source'].value=0;self.composite['glow'].value=1
        except Exception:
            self.close()
            raise

    def track(self,obj):
        self.resources.append(obj);return obj

    def texture(self,size,dtype):
        import moderngl
        obj=self.track(self.ctx.texture(size,4,dtype=dtype))
        obj.filter=(moderngl.LINEAR,moderngl.LINEAR);obj.repeat_x=obj.repeat_y=False
        return obj

    def render(self,anchors,elapsed,duration,effect,ink,accent,seed,intensity,speed=1.):
        import moderngl
        if self.closed:raise RuntimeError('Particle renderer is closed')
        if effect not in EFFECTS:raise ValueError('Unknown 3D particle preset')
        if not anchors or intensity<=0:return Image.new('RGBA',self.size)
        anchors=list(anchors[:16]);p=self.program
        p['anchors'].value=anchors+[anchors[-1]]*(16-len(anchors))
        p['anchor_count'].value=len(anchors);p['time'].value=float(elapsed*speed)
        p['duration'].value=float(duration);p['scene_seed'].value=float(seed)
        p['effect'].value=EFFECTS.index(effect)
        p['ink'].value=tuple(c/255 for c in ink);p['accent'].value=tuple(c/255 for c in accent)
        self.target.use();self.ctx.viewport=(0,0,*self.size);self.target.clear()
        self.ctx.enable(moderngl.BLEND);self.ctx.blend_func=(moderngl.ONE,moderngl.ONE)
        counts=dict(sparks=1000,dust=1800,trails=4096,fragments=650,orbits=1200,confetti=800)
        count=round(counts[effect]*min(2.,intensity))
        self.vao.render(moderngl.TRIANGLES,vertices=6,instances=count)
        self.ctx.disable(moderngl.BLEND)
        half=self.blur_a.size;self.ctx.viewport=(0,0,*half)
        self.fbo_a.use();self.hdr.use(0);self.blur['direction'].value=(1/self.size[0],0.)
        self.blur_vao.render(moderngl.TRIANGLES,vertices=3)
        self.fbo_b.use();self.blur_a.use(0);self.blur['direction'].value=(0.,1/half[1])
        self.blur_vao.render(moderngl.TRIANGLES,vertices=3)
        self.final.use();self.ctx.viewport=(0,0,*self.size);self.hdr.use(0);self.blur_b.use(1)
        self.composite_vao.render(moderngl.TRIANGLES,vertices=3)
        data=self.final.read(components=4,alignment=1)
        return Image.frombytes('RGBA',self.size,data).transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    def close(self):
        if self.closed:return
        self.closed=True
        for resource in reversed(self.resources):
            resource.release()
        self.resources.clear()
        if hasattr(self,'ctx'):self.ctx.release()


def render_particles(size,*args):
    renderer=getattr(_LOCAL,'renderer',None)
    if renderer is None or renderer.size!=tuple(size) or renderer.closed:
        if renderer is not None:renderer.close()
        renderer=_LOCAL.renderer=ParticleRenderer(size)
    return renderer.render(*args)


def close_particle_renderer():
    renderer=getattr(_LOCAL,'renderer',None)
    if renderer is not None:
        renderer.close();_LOCAL.renderer=None
