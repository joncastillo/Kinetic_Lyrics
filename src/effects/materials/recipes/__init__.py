"""The material entrances and exits. Each recipe paints one frame of its effect from progress t alone.

Entrances run t = 0 (nothing) to 1 (the finished word, which is also the held image); exits run
t = 0 (the word as it was) to 1 (gone). Shared simulation pieces live in effects/materials/fx.py.

The painters live in one module per family; importing this package registers them all."""

from effects.materials.recipes.registry import RECIPES, recipe  # noqa: F401
from effects.materials.recipes.common import silk_letter_spans, silk_strokes, supersampled  # noqa: F401

# Registration happens on import, in this order.
from effects.materials.recipes import stone  # noqa: F401
from effects.materials.recipes import fire  # noqa: F401
from effects.materials.recipes import frost  # noqa: F401
from effects.materials.recipes import silk  # noqa: F401
from effects.materials.recipes import glass  # noqa: F401
from effects.materials.recipes import ornament  # noqa: F401
import effects.growth.garden  # noqa: E402,F401  (registers the succulent garden and meadow grass recipes)
