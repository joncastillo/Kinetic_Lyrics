"""Reviewed scene motion descriptions and the controls implemented by each renderer."""

import math
import re


def slider(key, label, default=1.0, low=0.0, high=2.0, step=0.05):
    return dict(key=key, label=label, type='range', default=default, min=low, max=high, step=step)


def choice(key, label, options):
    return dict(key=key, label=label, type='select', default='auto', options=['auto', *options])


COLOR = dict(key='accent', label='Accent color (blank uses scene palette)', type='color', default='')
VARIANT = slider('variant', 'Variation seed offset', 0, 0, 20, 1)
SIZE = slider('size', 'Type size multiplier', 1.0, 0.65, 1.35)
SPEED = slider('speed', 'Entrance speed multiplier', 1.0, 0.25, 3.0)

# Entries describe the actual painters, rather than inferring motion from the recipe name.
POSTERS = {
    'stack': (
        'Rows reveal whole letters behind alternating wipes.',
        'Rows roll shut, bottom row first.',
        [slider('swelling', 'Sung row height', 2.6, 1.0, 4.0), SIZE],
    ),
    'wall': (
        'Marquee rows unfold; each word changes with a staggered split-flap turn.',
        'Rows fold shut; the caption pill closes.',
        [slider('motion', 'Marquee speed', 1.0, 0.0, 3.0)],
    ),
    'seal': (
        'Badge spins and grows in; the central word stamps with overshoot.',
        'Badge accelerates its spin and shrinks away.',
        [
            slider('motion', 'Ring rotation speed', 1.0, 0.0, 3.0),
            SIZE,
            choice('shape', 'Badge shape', ['round', 'scalloped', 'sawtooth']),
        ],
    ),
    'grid': (
        'Rules sweep in and words glide along them; sung cells fill with color.',
        'Words slide sideways and rules retract.',
        [slider('motion', 'Perspective tilt', 1.0, 0.0, 1.5)],
    ),
    'blink': (
        'Colored word bands slam sideways with squash; the final band joins in two halves.',
        'The band collapses vertically and the caption closes.',
        [slider('motion', 'Band tilt', 1.0, 0.0, 2.0)],
    ),
    'tour': (
        'Fixed pairs: Pop extrude, Elastic stretch, Dot stamp, Echo cascade, Echo chain, Page peel.',
        'Camera pulls back while turning; the block shrinks and spins away.',
        [slider('travel_speed', 'Camera travel speed', 1.0, 0.5, 2.0)],
    ),
    'spiral': (
        'Spiral grows outward; the sung word stamps into its eye.',
        'Spiral winds back into its center.',
        [slider('motion', 'Spiral rotation speed', 1.0, 0.0, 3.0)],
    ),
    'drum': (
        'Drum swings in; rows rotate to bring the sung word forward.',
        'Drum spins away and contracts.',
        [slider('motion', 'Outer row rotation speed', 1.0, 0.0, 3.0)],
    ),
    'recede': (
        'Word plates slam in at the front and push older words into depth.',
        'The stack rushes into the distance.',
        [SIZE],
    ),
    'horizon': (
        'Letters rise from behind the horizon with a landing squash.',
        'Words sink behind the horizon in sequence.',
        [slider('horizon', 'Horizon height (fraction from top)', 0.66, 0.45, 0.8)],
    ),
    'fold': (
        'A pleated strip unfolds; the sung pleat slaps flat.',
        'The strip folds shut.',
        [slider('fold_angle', 'Resting pleat angle (degrees)', 46.0, 15.0, 70.0, 1)],
    ),
    'ribbon': (
        'Ribbon slides in and glides to each sung word.',
        'Ribbon twists shut edge-on.',
        [slider('motion', 'Ribbon breathing speed', 1.0, 0.0, 3.0)],
    ),
    'dive': (
        'First word grows in; later words wait inside the preceding letter counter.',
        'Camera dives through the letter counter.',
        [slider('dive_curve', 'Dive acceleration (higher starts later)', 3.0, 1.5, 5.0, 0.1)],
    ),
    'halftone': (
        'Dots grow across the line; sung words bloom into solid glyphs.',
        'Dots shrink across the line and solid glyphs fade.',
        [
            slider('motion', 'Bloom ripple strength', 1.0, 0.0, 2.0),
            choice('alignment', 'Word arrangement', ['center', 'left', 'stepped']),
        ],
    ),
    'search': (
        'Puzzle letters drop in; a marker sweeps over each sung word.',
        'The grid drops away.',
        [slider('marker_speed', 'Marker sweep speed', 1.0, 0.5, 2.0)],
    ),
    'mobile': (
        'Word tiles drop on threads; sung words lower and swing.',
        'Threads reel the words up out of frame.',
        [slider('motion', 'Swing strength', 1.0, 0.0, 1.5)],
    ),
    'stamp': (
        'Stamps press down with squash, spreading ink and splatter.',
        'Stamps sweep sideways in sequence.',
        [slider('imperfection', 'Ink wear and irregular tilt', 1.0, 0.0, 2.0), SIZE],
    ),
    'register': (
        'Color plates gather into near-register; sung words split then snap into register.',
        'Words drop away last-first, with a slight plate split and shear.',
        [slider('imperfection', 'Resting plate misalignment', 1.0, 0.0, 3.0)],
    ),
    'drop': (
        'Word blocks fall or tumble onto shelves, squashing on impact.',
        'Blocks topple onto a pile; the next line knocks the pile away.',
        [slider('motion', 'Impact camera shake', 1.0, 0.0, 2.0)],
    ),
}

QUIET_SCENES = {
    'editorial': (
        'Editorial',
        'Short, left-aligned phrases rise softly beside a fine rule.',
        'The phrase fades and lifts a few pixels.',
    ),
    'focus': (
        'Quiet focus',
        'Centered serif phrases resolve from soft focus with a slight push-in.',
        'Type gently defocuses and fades.',
    ),
    'baseline': (
        'Baseline reveal',
        'Words rise through a shared baseline mask, following the vocal.',
        'The line sinks below its baseline masks.',
    ),
    'caption': (
        'Gallery caption',
        'A fine rule extends and a small lower-left caption fades in.',
        'Caption fades as the rule retracts.',
    ),
}


def scene_tags(scene):
    if scene['camera'] == 'cinema' or scene['layout'] in QUIET_SCENES:
        return ['minimalist', 'professional', 'cinematic'] + (
            ['editorial'] if scene['layout'] in ('editorial', 'caption') else []
        )
    if scene['camera'] == 'blocks':
        style = {
            'tree-canopy': ['organic'],
            'crystal-and-coral': ['organic', 'geometric'],
            'golden-ornament': ['ornamental'],
            'lace-and-paper': ['textured', 'ornamental'],
            'sweet-contrast': ['textured', 'editorial'],
            'plain-blocks': ['geometric', 'professional'],
        }
        return ['3d', 'typographic', *style.get(scene['id'], ['geometric'])]
    if scene['camera'] in ('pan', 'still'):
        return ['kinetic', 'typographic', 'cinematic']
    layout = scene['layout']
    tags = ['bold', 'typographic']
    tags += ['textured'] if layout in ('stamp', 'register', 'halftone') else ['geometric']
    tags += ['playful'] if layout in ('blink', 'mobile', 'stamp', 'drop', 'search', 'seal') else ['kinetic']
    if layout in ('grid', 'recede', 'horizon'):
        tags.append('editorial')
    return tags


def scene_details(scene, effects=None):
    camera = scene['camera']
    if camera == 'poster':
        if scene['layout'] in QUIET_SCENES:
            _, entry, exit_ = QUIET_SCENES[scene['layout']]
            return dict(
                entry=entry,
                exit=exit_,
                selection='Built-in restrained motion; global entrance and exit selections are ignored.',
                controls=[
                    dict(COLOR, label='Highlight color (blank uses warm white)'),
                    SIZE,
                    dict(SPEED, label='Transition speed multiplier'),
                    slider('motion', 'Motion distance', 1.0, 0.0, 2.0),
                    slider('tracking', 'Letter spacing (em)', 0.015, 0.0, 0.15, 0.005),
                ],
            )
        entry, exit_, controls = POSTERS[scene['layout']]
        variants = [VARIANT] if scene['layout'] not in ('fold', 'ribbon', 'dive', 'mobile') else []
        return dict(
            entry=entry,
            exit=exit_,
            selection='Built-in motion; global entrance and exit selections are ignored.',
            controls=[COLOR, *variants, *controls],
        )
    if camera == 'cinema':
        return dict(
            entry='Hairline settle, blurred slide, oversized zoom or mirrored flip.',
            exit='Blur and grow, mirrored flip, or blurred sideways slide.',
            selection='Built-in phrase motion; global entrance and exit selections are ignored.',
            controls=[
                dict(COLOR, label='Text color (blank uses global text color)'),
                SIZE,
                SPEED,
                slider('push', 'Holding text push-in', 1.0, 0.0, 2.0),
            ],
        )
    if camera == 'blocks':
        preferred = scene['particles']
        effects = effects or {}
        names = [effects[p].name if p in effects else p.replace('-', ' ').title() for p in preferred]
        particles = (
            (
                'Restricted to the selected tree effects from: '
                if scene['id'] == 'tree-canopy'
                else 'Selected entrances; preferred top-row effects: '
            )
            + ', '.join(names)
            if preferred
            else 'Selected entrances can decorate the top row.'
        )
        return dict(
            entry=('Elastic letter bounce. ' if scene['layout'] == 'contrast' else 'Flip, swing, rise, drop or pop. ')
            + particles,
            exit='Earlier blocks remain in the world, dimming as the camera moves to the next block.',
            selection='Global exit selections are ignored. Particle intensity and selected entrances apply.',
            controls=[
                COLOR,
                VARIANT,
                slider('motion', 'Camera cruising motion', 1.0, 0.0, 2.0),
                slider('geometry', 'Drifting geometry', 0.8, 0.0, 1.0),
            ],
        )
    return dict(
        entry='Selected per-word entrance effects and directed word motion.',
        exit='Finished lines stay on the canvas, dim and drift out of view.'
        if camera == 'pan'
        else 'Selected per-word exit effects.',
        selection='Global entrances apply; global exits are ignored by the panning camera.'
        if camera == 'pan'
        else 'Global entrance and exit selections apply.',
        controls=[
            COLOR,
            SIZE,
            SPEED,
            slider('pan_speed', 'Camera speed (frame widths / second)', 0.05, 0.0, 0.15, 0.005),
            slider('backdrop_rate', 'Backdrop frequency', 0.6, 0.0, 1.0),
        ],
    )


def scene_settings(value):
    """Validate sparse overrides; defaults stay inherited and existing projects keep their exact look."""
    from direction.scene_catalog import scene_catalog

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('Scene settings must be an object')
    if not value:
        return {}
    catalog = scene_catalog()
    result = {}
    for scene_id, settings in value.items():
        if scene_id not in catalog or not isinstance(settings, dict):
            raise ValueError('Choose an available scene to configure')
        specs = {s['key']: s for s in catalog[scene_id]['controls']}
        if set(settings) - set(specs):
            raise ValueError(f'Unsupported setting for scene {scene_id}')
        clean = {}
        for key, raw in settings.items():
            spec = specs[key]
            if spec['type'] == 'select':
                if not isinstance(raw, str) or raw not in spec['options']:
                    raise ValueError(f'Choose an available {key} for scene {scene_id}')
                if raw != 'auto':
                    clean[key] = raw
                continue
            if spec['type'] == 'color':
                if not isinstance(raw, str) or (raw and not re.fullmatch(r'#[0-9a-fA-F]{6}', raw)):
                    raise ValueError('Scene colors must be #RRGGBB or blank')
                if raw:
                    clean[key] = raw.lower()
                continue
            if (
                isinstance(raw, bool)
                or not isinstance(raw, (int, float))
                or not math.isfinite(raw)
                or not spec['min'] <= raw <= spec['max']
            ):
                raise ValueError(f'Scene setting {key} is out of range')
            if key == 'variant' and raw != int(raw):
                raise ValueError('Scene variation must be a whole number')
            clean[key] = int(raw) if key == 'variant' else float(raw)
        if clean:
            result[scene_id] = clean
    return result
