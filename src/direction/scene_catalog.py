"""Scene effects: the curated looks a video's song sections are filmed in.

Each scene is a small JSON recipe in assets/scenes/. Its `camera` picks the renderer: "pan" (the
real-time panning canvas, with flowing bands and a wisp tracing shapes), "still" (the real-time
still camera, lines built inside shapes), "blocks" (the 3D stage) "cinema" (spotlight: one
short phrase at a time in hairline and heavy type over the artwork), "poster" (each line one full-frame
typographic composition: a proportion-swapping word "stack" or a marquee word "wall"). A blocks scene lists
preferred particle effects (`particles`); the AI can choose any selected entrance, except
Tree canopy, which is restricted to its tree effects. A blocks scene's `layout` is
"justified" (rows of equal width, the default) or "contrast" (thin and heavy words, one
word with a flowing textured fill, the last word set vertically, the camera zoomed and
tilted). Pan and still scenes keep the user's per-line entrance effects, so `particles`
is null for them. The filename, without .json, is the scene's ID.
"""

import json
import re
import warnings

from core.paths import ASSET_ROOT

SCENE_ROOT = ASSET_ROOT / 'scenes'
CAMERAS = ('pan', 'still', 'blocks', 'cinema', 'poster')
LAYOUTS = ('justified', 'contrast')
POSTER_LAYOUTS = (
    'stack',
    'wall',
    'seal',
    'grid',
    'blink',
    'tour',
    'spiral',
    'drum',
    'recede',
    'horizon',
    'fold',
    'ribbon',
    'dive',
    'halftone',
    'search',
    'mobile',
    'stamp',
    'register',
    'drop',
    'editorial',
    'focus',
    'baseline',
    'caption',
)  # poster scenes: proportion-swapping word stack, or a marquee word wall


def read_scene(path, entrances=None):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or set(data) - {'name', 'description', 'camera', 'particles', 'layout'}:
        raise ValueError('Unknown scene fields')
    if not re.fullmatch(r'[a-z][a-z0-9-]*', path.stem):
        raise ValueError('Use a lowercase, hyphenated filename')
    if not isinstance(data.get('name'), str) or not 0 < len(data['name'].strip()) <= 60:
        raise ValueError('Scene name must contain 1 to 60 characters')
    if not isinstance(data.get('description', ''), str) or len(data.get('description', '').split()) > 25:
        raise ValueError('Scene description must contain at most 25 words')
    if data.get('camera') not in CAMERAS:
        raise ValueError('camera must be pan, still, blocks, cinema or poster')
    particles = data.get('particles')
    if data['camera'] == 'blocks':
        if not isinstance(particles, list) or any(not isinstance(p, str) for p in particles):
            raise ValueError('A blocks scene lists its particle effects (an empty list for plain blocks)')
        if entrances is not None and any(p not in entrances for p in particles):
            raise ValueError('Unknown particle effect in scene')
    elif particles is not None:
        raise ValueError('Only blocks scenes list particle effects; leave particles null for other cameras')
    if data['camera'] == 'poster':
        layout = data.get('layout', 'stack')
        if layout not in POSTER_LAYOUTS:
            raise ValueError('Choose an available poster layout')
    else:
        layout = data.get('layout', 'justified')
        if layout not in LAYOUTS or (layout != 'justified' and data['camera'] != 'blocks'):
            raise ValueError('layout must be justified or contrast, and only blocks scenes take a layout')
    return dict(
        id=path.stem,
        name=data['name'],
        description=data.get('description', ''),
        camera=data['camera'],
        particles=list(particles) if particles is not None else None,
        layout=layout,
    )


def scene_catalog():
    """{id: scene} for every valid recipe in assets/scenes/, skipping invalid ones with a warning."""
    from effects.particles.catalog import discover_effects

    entrances = discover_effects()['entrance']
    catalog = {}
    for path in sorted(SCENE_ROOT.glob('*.json')):
        try:
            from direction.scene_controls import scene_details, scene_tags

            scene = read_scene(path, entrances)
            catalog[path.stem] = dict(scene, **scene_details(scene, entrances), tags=scene_tags(scene))
        except (OSError, ValueError, TypeError) as exc:
            warnings.warn(f'Skipping scene {path}: {exc}', stacklevel=2)
    return catalog
