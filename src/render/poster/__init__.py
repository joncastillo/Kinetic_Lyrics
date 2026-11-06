"""Poster scenes: each lyric line becomes one full-frame typographic composition over the artwork.

Two layouts, after the bold title-card work of motion designers:

* "stack": the line's words are rows of one justified block, every row stretched to the same width. The word
  being sung swells into the tall, heavy row while the others squash flat, so the block trades proportions
  row to row as the line is sung, on a hard offset extrusion. Rows slam in from alternate sides when the line
  arrives and fold away when it leaves.
* "wall": the sung word repeats across the frame in marquee rows sliding in opposite directions, alternating
  heavy fill and hairline outline, with the middle row in the accent colour. On each new word the rows roll
  over like a slot machine. The whole line runs along the bottom in a pill strip so it can always be read.

Every frame is a pure function of time.

One module per scene. PAINTERS maps a layout name (`layout` in assets/scenes/*.json) to its painter.
Helpers are in common.py, shared methods in shared.py."""

import bisect
import random
from render.poster.common import LEAD, PALETTES, rows_of
from render.poster.shared import PosterShared
from render.poster.stack import StackScene
from render.poster.wall import WallScene
from render.poster.seal import SealScene
from render.poster.grid import GridScene
from render.poster.blink import BlinkScene
from render.poster.tour import TourScene
from render.poster.spiral import SpiralScene
from render.poster.drum import DrumScene
from render.poster.recede import RecedeScene
from render.poster.horizon import HorizonScene
from render.poster.fold import FoldScene
from render.poster.ribbon import RibbonScene
from render.poster.dive import DiveScene
from render.poster.halftone import HalftoneScene
from render.poster.search import SearchScene
from render.poster.mobile import MobileScene
from render.poster.stamp import StampScene
from render.poster.register import RegisterScene
from render.poster.drop import DropScene

PAINTERS = {
    'stack': 'paint_stack',
    'wall': 'paint_wall',
    'seal': 'paint_seal',
    'grid': 'paint_grid',
    'blink': 'paint_blink',
    'tour': 'paint_tour',
    'spiral': 'paint_spiral',
    'drum': 'paint_drum',
    'recede': 'paint_recede',
    'horizon': 'paint_horizon',
    'fold': 'paint_fold',
    'ribbon': 'paint_ribbon',
    'dive': 'paint_dive',
    'halftone': 'paint_halftone',
    'search': 'paint_search',
    'mobile': 'paint_mobile',
    'stamp': 'paint_stamp',
    'register': 'paint_register',
    'drop': 'paint_drop',
}  # anything else uses paint_stack


class PosterTypography(
    PosterShared,
    StackScene,
    WallScene,
    SealScene,
    GridScene,
    BlinkScene,
    TourScene,
    SpiralScene,
    DrumScene,
    RecedeScene,
    HorizonScene,
    FoldScene,
    RibbonScene,
    DiveScene,
    HalftoneScene,
    SearchScene,
    MobileScene,
    StampScene,
    RegisterScene,
    DropScene,
):
    def __init__(self, compositor, melody=None, speed=1.0, rhythm=None, options=None, only=None, layouts=None):
        self.c = compositor
        self.only = frozenset(only) if only is not None else None
        self.layouts = layouts or {}
        self.lines = None
        self.veils = []

    def plan(self):
        if self.lines is not None:
            return self.lines
        c = self.c
        lines = []
        indices = [i for i in range(len(c.data)) if self.only is None or i in self.only]
        for n, index in enumerate(indices):
            line = c.data[index]
            words = [w for w in line['words'] if w['text'].strip()]
            if not words:
                continue
            rng = random.Random(index * 7919 + len(words))
            start = words[0]['start'] - LEAD
            following = c.data[index + 1]['words'][0]['start'] - LEAD if index + 1 < len(c.data) else c.duration
            end = max(words[-1]['end'] + 0.4, min(following + 0.12, words[-1]['end'] + 2.5))
            linger = 0.0
            if self.layouts.get(index) == 'drop' and index + 1 < len(
                c.data
            ):  # its pile stays until the next line's first block knocks it away
                linger = max(0.0, following + 0.95 - end)
                end += linger
            lines.append(
                dict(
                    index=index,
                    words=words,
                    rows=rows_of(words),
                    start=start,
                    end=end,
                    layout=self.layouts.get(index, 'stack'),
                    palette=PALETTES[(index * 2 + n) % len(PALETTES)],
                    side=1 if n % 2 else -1,
                    seed=rng.random(),
                    linger=linger,
                )
            )
        self.lines = lines
        self.starts = [line['start'] for line in lines]
        return lines

    def wisp_runs(self):
        return []

    def frame(self, t):
        c = self.c
        self.plan()
        index = max(0, sum(1 for line in c.data if line['words'][0]['start'] <= t) - 1)
        screen = c.background(index, t, veil=False).convert('RGBA')
        c.illustration(screen, index, t)
        k = bisect.bisect_right(self.starts, t) - 1
        for number in (k - 1, k):
            if 0 <= number < len(self.lines) and self.lines[number]['start'] <= t < self.lines[number]['end']:
                line = self.lines[number]
                getattr(self, PAINTERS.get(line['layout'], 'paint_stack'))(screen, line, t)
        return screen.convert('RGB')
