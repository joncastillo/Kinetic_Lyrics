"""What the compositor expects from a lyric engine (realtime, stage_3d, cinema, scene_mix).

The compositor builds one engine for the reading flow (Compositor._choose_engine) and hands it itself, so the engine
can read the song (data, plan, timing, effects) and the artwork (art, art_starts, background(), illustration(),
scenery()). The preview flow has no engine: the compositor draws it. These protocols are documentation and a check
for tests; nothing inherits from them.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class LyricEngine(Protocol):
    def plan(self):
        """Prepare everything that does not depend on time (layouts, routes); safe to call more than once."""

    def frame(self, t):
        """The finished RGB frame at time t, artwork included."""


@runtime_checkable
class WispEngine(LyricEngine, Protocol):
    """An engine whose wisp the scene mix can carry across a change of scene."""

    def wisp_runs(self):
        """[(start, end)] time of each run of the wisp."""

    def wisp_screen(self, number, when, t):
        """Screen pixel of run `number`'s wisp head where it was at time `when`, filmed by the camera at time t."""
