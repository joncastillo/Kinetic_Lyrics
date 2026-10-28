"""Scene effects: the curated looks a video's song sections are filmed in.

Each scene is a small JSON recipe in scenes/. Its `camera` picks the renderer: "pan" (the
real-time panning canvas, with flowing bands and drifting shapes), "still" (the real-time
still camera, lines built inside shapes) or "blocks" (the 3D stage). A blocks scene owns a
few particle effects (`particles`), such as the maple and oak trees of the tree canopy;
inside that scene the AI picks one of them for each block. Pan and still scenes keep the
user's per-line entrance effects, so `particles` is null for them. The filename, without
.json, is the scene's ID.
"""
from functools import lru_cache
import json
import re
import warnings

from project_paths import PROJECT_ROOT

SCENE_ROOT = PROJECT_ROOT/'scenes'
CAMERAS = ('pan', 'still', 'blocks')


def read_scene(path, entrances=None):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or set(data)-{'name', 'description', 'camera', 'particles'}:
        raise ValueError('Unknown scene fields')
    if not re.fullmatch(r'[a-z][a-z0-9-]*', path.stem):
        raise ValueError('Use a lowercase, hyphenated filename')
    if not isinstance(data.get('name'), str) or not 0 < len(data['name'].strip()) <= 60:
        raise ValueError('Scene name must contain 1 to 60 characters')
    if not isinstance(data.get('description', ''), str) or len(data.get('description', '').split()) > 25:
        raise ValueError('Scene description must contain at most 25 words')
    if data.get('camera') not in CAMERAS:
        raise ValueError('camera must be pan, still or blocks')
    particles = data.get('particles')
    if data['camera'] == 'blocks':
        if not isinstance(particles, list) or any(not isinstance(p, str) for p in particles):
            raise ValueError('A blocks scene lists its particle effects (an empty list for plain blocks)')
        if entrances is not None and any(p not in entrances for p in particles):
            raise ValueError('Unknown particle effect in scene')
    elif particles is not None:
        raise ValueError('Pan and still scenes use the per-line entrance effects; leave particles null')
    return dict(id=path.stem, name=data['name'], description=data.get('description', ''), camera=data['camera'],
                particles=list(particles) if particles is not None else None)


@lru_cache(maxsize=1)
def scene_catalog():
    """{id: scene} for every valid recipe in scenes/, skipping invalid ones with a warning."""
    from particle_catalog import discover_effects
    entrances = discover_effects()['entrance']
    catalog = {}
    for path in sorted(SCENE_ROOT.glob('*.json')):
        try:
            catalog[path.stem] = read_scene(path, entrances)
        except (OSError, ValueError, TypeError) as exc:
            warnings.warn(f'Skipping scene {path}: {exc}', stacklevel=2)
    return catalog
