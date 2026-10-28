"""Discover declarative typography effects without a hand-maintained registry."""

from dataclasses import dataclass, fields
from itertools import zip_longest
import json
import math
from pathlib import Path
from project_paths import PROJECT_ROOT
import re
import warnings


EFFECT_ROOT = PROJECT_ROOT/"particles"
PHASES = ("entrance", "exit")
FAMILIES = (
    "glass",
    "dust",
    "sparks",
    "ribbons",
    "pixels",
    "petals",
    "snow",
    "smoke",
    "bubbles",
    "ink",
    "vortex",
    "magnetic",
    "letters",
    "ornament",
    "trees",
    "cinematic",
    "material",
)
# "top" marks effects that grow above the word (trees, ornaments), so a block uses them
# only on its top row, where nothing sits above.
PLACEMENTS = ("any", "top")
PATHS = ("radial", "left", "right", "up", "down", "spiral", "wave", "fan", "grow")


@dataclass(frozen=True)
class Effect:
    id: str
    name: str
    family: str
    trajectory: str = "radial"
    spread: float = 1.8
    gravity: float = 0.6
    spin: float = 1.0
    twist: float = 0.0
    stagger: float = 0.15
    density: float = 1.0
    hold: str = "solid"
    description: str = ""
    base_color: str = "ink"
    placement: str = "any"


def read_effect(path):
    """The filename is the persistent ID; recipes cannot execute Python code."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    metadata_path=path.parent.parent/'descriptions.json'
    if 'description' not in data and metadata_path.is_file():
        metadata=json.loads(metadata_path.read_text(encoding='utf-8-sig'))
        data['description']=metadata.get(path.parent.name,{}).get(path.stem,'')
    colors_path=path.parent.parent/'colors.json'
    if path.parent.name=='entrance' and 'base_color' not in data and colors_path.is_file():
        data['base_color']=json.loads(colors_path.read_text(encoding='utf-8-sig')).get(path.stem,'ink')
    allowed = {field.name for field in fields(Effect)} - {"id"}
    if not isinstance(data, dict) or data.keys() - allowed:
        raise ValueError("Unknown effect fields")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", path.stem):
        raise ValueError("Use a lowercase, hyphenated filename")
    effect = Effect(id=path.stem, **data)
    if (
        not isinstance(effect.name, str)
        or not effect.name.strip()
        or len(effect.name) > 80
    ):
        raise ValueError("Effect name must contain 1 to 80 characters")
    if not isinstance(effect.description,str) or len(effect.description.split())>10:
        raise ValueError('Effect description must contain at most 10 words')
    if effect.family not in FAMILIES or effect.trajectory not in PATHS:
        raise ValueError("Unknown particle family or trajectory")
    if effect.placement not in PLACEMENTS:
        raise ValueError("placement must be any or top")
    if effect.hold not in ("solid", "particles"):
        raise ValueError("hold must be solid or particles")
    if effect.hold == "particles" and effect.family != "petals" and effect.trajectory != "grow":
        raise ValueError("Particle lettering currently requires the petals family")
    limits = dict(
        spread=(0.1, 5.0),
        gravity=(-3.0, 3.0),
        spin=(-4.0, 4.0),
        twist=(-6.0, 6.0),
        stagger=(0.0, 0.8),
        density=(0.2, 2.0),
    )
    for key, (low, high) in limits.items():
        value = getattr(effect, key)
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError(f"{key} must be finite and between {low} and {high}")
    return effect


def discover_effects(root=None):
    """Rescan on job/API boundaries, never in the per-frame rendering loop."""
    curated = root is None
    root = EFFECT_ROOT if root is None else Path(root)
    catalog = {phase: {} for phase in PHASES}
    for phase in PHASES:
        for path in sorted((root / phase).glob("*.json")):
            try:
                effect = read_effect(path)
            except (OSError, ValueError, TypeError) as exc:
                warnings.warn(f"Skipping particle effect {path}: {exc}", stacklevel=2)
                continue
            if curated:
                allowed=(effect.family in ('glass','letters','ornament','trees','cinematic','material') or effect.id in
                         ('petals-breeze-lettering','petals-spiral-lettering','petals-wind-lettering','petals-grow-lettering','ink-bloom-lettering','thread-stitch-lettering')) if phase=='entrance' else effect.family in ('glass','petals','smoke','cinematic','material')
                if not allowed:continue
            catalog[phase][effect.id] = effect
    return catalog


def catalog_choices(catalog=None):
    catalog = discover_effects() if catalog is None else catalog
    return {
        phase: [
            dict(id=effect.id, name=effect.name, family=effect.family, hold=effect.hold, description=effect.description,
                 base_color=effect.base_color, placement=effect.placement)
            for effect in effects.values()
        ]
        for phase, effects in catalog.items()
    }


def validate_choice(value, phase, catalog):
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{phase.title()} effect must be an effect ID")
    if value not in (None, "legacy", "none", "mixed", "ai") and value not in catalog[phase]:
        raise ValueError(f"Unknown {phase} effect: {value}")
    return value


LEGACY = {
    "shatter": ("none", "glass-shatter"),
    "fragments": ("glass-assemble", "glass-impact"),
    "dust": ("dust-coalesce", "dust-dissolve"),
    "sparks": ("sparks-ignite", "sparks-burst"),
    "trails": ("ribbons-weave", "ribbons-unravel"),
    "orbits": ("vortex-orbit", "vortex-release"),
    "confetti": ("petals-gather", "petals-scatter"),
}


def parse_pool(value, phase, catalog, strict=True):
    """None enables all recipes; an empty list deliberately enables none."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValueError(f"Invalid {phase} effect selection") from exc
    if (
        not isinstance(value, list)
        or len(value) > 1000
        or any(not isinstance(item, str) for item in value)
    ):
        raise ValueError(
            f"{phase.title()} effect selection must be a list of effect IDs"
        )
    result = []
    for item in value:
        if item not in catalog[phase]:
            if strict:
                raise ValueError(f"Unknown {phase} effect: {item}")
            continue
        if item not in result:
            result.append(item)
    return result


def resolve_effect(value, phase, catalog, index=0, legacy="none", pool=None):
    if value in (None, "legacy"):
        if legacy == "mixed":
            value = "mixed"
        elif legacy in LEGACY:
            value = LEGACY[legacy][PHASES.index(phase)]
        else:
            return "none"
    if value == "mixed":
        enabled = set(catalog[phase] if pool is None else pool)
        groups = [
            [
                effect.id
                for effect in catalog[phase].values()
                if effect.family == family and effect.id in enabled
            ]
            for family in FAMILIES
        ]
        pool = [
            effect
            for group in zip_longest(*groups)
            for effect in group
            if effect is not None
        ]
        return pool[index % len(pool)] if pool else "none"
    if value not in ("none", "melt", "slime", "liquid") and value not in catalog[phase]:
        warnings.warn(
            f"Missing {phase} effect {value!r}; using clean typography.", stacklevel=2
        )
        return "none"
    return value
