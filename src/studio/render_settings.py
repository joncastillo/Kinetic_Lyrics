"""The render settings a Studio job runs with, checked in one place for a new job and for a rerender."""

from effects.particles.catalog import discover_effects, parse_pool, validate_choice
from render.text_effects import EFFECTS, TEXT_ANIMATIONS
from render.typography_settings import number, typography_options

STAGE_PICTURES = ('ai-painted', 'ai-library', 'keywords', 'off')
AUDIO_MODES = ('original', 'karaoke')
DEPTH_MODELS = ('depth-anything', 'megasam')   # what hides scene lyrics standing on the land (scene_text.occlusion)
DEFAULTS = dict(
    type_effect='mixed',
    particle_intensity=1.0,
    particle_speed=1.0,
    text_animation='directed',
    audio_mode='original',
    entrance_effect='legacy',
    exit_effect='legacy',
    stage_pictures='ai-painted',
    depth_model='depth-anything',
)


def render_settings(values, previous=None, defaults=None):
    """The letter effects, particles, word animation, audio mode, 3D stage pictures and typography in `values`
    (a form or a JSON request), each falling back to `previous` (the job's saved config), then to the defaults.
    Raises ValueError for anything invalid. A choice or pool given in `values` is checked strictly; one carried
    over from `previous` was checked when it was saved."""
    previous = previous or {}
    defaults = dict(DEFAULTS, **(defaults or {}))

    def pick(key):
        return values[key] if key in values else previous.get(key, defaults[key])

    settings = dict(
        type_effect=pick('type_effect'),
        text_animation=pick('text_animation'),
        audio_mode=pick('audio_mode'),
        entrance_effect=pick('entrance_effect'),
        exit_effect=pick('exit_effect'),
        stage_pictures=values.get('stage_pictures') or previous.get('stage_pictures') or defaults['stage_pictures'],
        depth_model=values.get('depth_model') or previous.get('depth_model') or defaults['depth_model'],
    )
    settings['particle_intensity'] = number(pick('particle_intensity'), 'Particle density must be a number from 0 to 2')
    settings['particle_speed'] = number(pick('particle_speed'), 'Particle speed must be a number from 0.2 to 3')
    if settings['type_effect'] not in EFFECTS:
        raise ValueError('Invalid typography effect')
    if not 0 <= settings['particle_intensity'] <= 2:
        raise ValueError('Particle density must be between 0 and 2')
    if not 0.2 <= settings['particle_speed'] <= 3:
        raise ValueError('Particle speed must be between 0.2 and 3')
    if settings['text_animation'] not in TEXT_ANIMATIONS:
        raise ValueError('Invalid word animation')
    if settings['audio_mode'] not in AUDIO_MODES:
        raise ValueError('Invalid audio mode')
    if settings['stage_pictures'] not in STAGE_PICTURES:
        raise ValueError('Invalid 3D stage picture setting')
    if settings['depth_model'] not in DEPTH_MODELS:
        raise ValueError('Invalid scene lyrics depth model')
    catalog = discover_effects()
    for phase in ('entrance', 'exit'):
        if phase + '_effect' in values:
            validate_choice(settings[phase + '_effect'], phase, catalog)
        settings[phase + '_pool'] = parse_pool(
            values.get(phase + '_pool', previous.get(phase + '_pool')), phase, catalog, strict=phase + '_pool' in values
        )
    settings.update(typography_options(dict(previous, **values)))
    return settings
