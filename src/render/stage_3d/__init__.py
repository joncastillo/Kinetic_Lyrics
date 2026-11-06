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

planning.py builds the plan, wisp.py draws the wisp and duet, drawing.py builds each frame's
items and gl.py draws them. common.py holds shared constants and helpers.
"""
from __future__ import annotations
import math
import numpy as np
from render.stage_3d.common import BAND_OPACITY, BAND_WIDTH, BLOCK_WIDTH, BOUNCE_ENTRY, BOUNCE_STAGGER, DRAW_REACH, ENTRY, FILL_WIDTH, FOV, GROW_ENTRY, LETTER_STAGGER, OVERSAMPLE, PARTICLE_ENTRY, band_image, gradient, soft_dot
from render.stage_3d.gl import gl_stage, look_at, perspective, scaling
from render.stage_3d.planning import StagePlanning
from render.stage_3d.wisp import StageWisp
from render.stage_3d.drawing import StageDrawing
from render.stage_3d.common import MOVE  # noqa: F401 - re-exported
from render.stage_3d.gl import close_stage  # noqa: F401 - re-exported


class Stage3D(StagePlanning, StageWisp, StageDrawing):
    def __init__(self, compositor, melody=None, rhythm=None, seed=None, only=None, breaks=(), crowns=None, layouts=None):
        from render.typography_settings import kinetic_options
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
