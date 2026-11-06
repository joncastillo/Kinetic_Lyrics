"""Real-time kinetic typography over one full-frame illustration at a time.

The typography camera glides at a constant speed from the first frame to the last. Each
line is written onto its path ahead of the camera as it is sung, sized so it stays fully
on screen until its last word, then drifts away. Background illustrations remain screen
aligned so adjacent paintings cannot overlap. Words use a role-based font mix (small typewriter function words, heavy content
words, huge condensed hero words); hero words form through the line's particle entrance;
melody drives colour and pace. A per-line backdrop (marquee, echo, giant word...) adds
variety. Every frame is a pure function of time, so renders split across processes exactly.
When the video mixes scenes, `only` limits the drawn lines (and the thread between hero words)
to the song sections this scene films; the canvas and camera still span the whole song.

planning.py builds the plan, words.py paints lines, wisp.py draws the wisp, layout.py sets out
words and lines, and common.py holds shared constants and helpers.
"""
import math
from PIL import Image
from core.easing import smoothstep as smooth
from render.realtime.common import BACKDROP_FADE
from render.realtime.layout import use_display_font
from render.realtime.planning import LinePlanning
from render.realtime.words import LinePainting
from render.realtime.wisp import FlowWisp
from render.realtime.common import BACKDROP_COLORS, CURL_TIME, FUNCTION_WORDS, TRACE_TIME, SHAPE_LIFE, SHAPES, overshoot, melody_for, THREAD_LEAD, DUET_EASE  # noqa: F401 - re-exported
from render.realtime.layout import assign_roles, bare, role_font  # noqa: F401 - re-exported
from core.color import hex_rgb  # noqa: F401 - re-exported


class RealtimeTypography(LinePlanning, LinePainting, FlowWisp):
    def __init__(self, compositor, melody=None, speed=1., rhythm=None, options=None, only=None, large=()):
        from render.typography_settings import kinetic_options
        self.c = compositor
        use_display_font(getattr(compositor, 'custom_font', None))
        self.only = frozenset(only) if only is not None else None
        self.large = frozenset(large)
        self.options = kinetic_options(options)
        self.rhythm = rhythm or {}
        self.melody = melody.get('lines') if isinstance(melody, dict) else None
        self.speed = max(.2, speed)
        self.lines = self.path = self.world = self.mattes = None
        self.veils = []  # (start, end) times when the scene mix carries the wisp instead (see wisp_screen)
        self.still = self.options['camera'] == 'still'
        self.shapes = None

    def frame(self, t):
        c = self.c
        self.plan()
        center = self.path.at(t)
        left, top = center[0]-c.width/2, center[1]-c.height/2
        base = (math.floor(left), math.floor(top))
        fraction = (left-base[0], top-base[1])
        signals = self.instrument_signals(t)
        scenery = None
        if self.world:
            screen = self.world.view(base[0], base[1], c.width+2, c.height+2)
            if self.mattes:
                scenery = screen.copy()
                scenery.putalpha(self.mattes.view(base[0], base[1], c.width+2, c.height+2))
        else:
            scenery = c.scenery(t)
            index = max(0, sum(1 for line in c.data if line['words'][0]['start'] <= t)-1)
            screen = c.background(index, t, veil=False).convert('RGBA')
            c.illustration(screen, index, t)
        chorus_hit = self.c.chorus_fx.active(t) is not None
        shaking = self.c.chorus_fx.beat_active(t) is not None  # choruses, or the whole song
        if shaking and (self.options['background_shake'] > 0 or self.options['beat_dim'] > 0):
            # The same four-on-the-floor kicks that the words react to (the drum track holds one pulse per
            # beat): in the chorus sections, or all through the song with "Shake all song".
            from render.drum_typography import shake_background
            screen = shake_background(screen, signals['drums'].hit, self.options['background_shake'],
                                      self.options['beat_dim'])
        # The painting is fixed to the screen; only the camera-borne layer (words, traces, backdrops) takes the
        # camera's sub-pixel offset. Shifting the painting too made it creep a fraction and snap back a whole pixel
        # on slow pans, a slight, dizzying shake.
        canvas = Image.new('RGBA', (c.width+2, c.height+2))
        c.effect_cache['backdrop'] = screen  # the frame's artwork, for effects that show it through the letters
        visible = self.visible(t)
        if visible:
            newest = visible[0][0]
            handover = smooth((t-self.lines[newest]['start'])/BACKDROP_FADE)
            if newest and handover < 1 and self.shown(newest-1):
                self.paint_backdrop(canvas, newest-1, t, fraction, 1-handover)
            self.paint_backdrop(canvas, newest, t, fraction)
        if self.options['traces']:  # 'geometry' drives the 3D stage's traced shapes; in 2D it must not switch the wisp on
            self.paint_traces(canvas, t, base, visible)
        for index, opacity in visible:
            if self.still and t >= self.lines[index]['exit'][0]:
                self.paint_exit(canvas, index, t, base)
                continue
            if self.still:  # on the panning canvas the wisp traces the frames instead (see trace_shape)
                self.paint_frame(canvas, index, t, opacity, base)
            self.paint_line(canvas, index, t, opacity, base, impact=chorus_hit and index == newest, signals=signals)
        if scenery is not None:
            canvas.alpha_composite(scenery)
        shifted = canvas.transform((c.width, c.height), Image.Transform.AFFINE, (1, 0, fraction[0], 0, 1, fraction[1]),
                                   resample=Image.Resampling.BILINEAR)
        screen.alpha_composite(shifted)
        return screen.convert('RGB')
