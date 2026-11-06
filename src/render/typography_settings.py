"""Validated typography settings shared by Studio, previews and rendering."""

import json
import math
from pathlib import Path
import os

KINETIC_TEXT_SCALE = 3.0

WORD_ANIMATIONS = ('directed', 'highlight', 'karaoke', 'slide', 'fade', 'mask-rise', 'cartoon-pop', 'none')
READING_FLOWS = ('realtime', 'preview', 'stage', 'mixed', 'cinema')
BACKDROP_KINDS = ('outline', 'filled', 'vertical', 'echo', 'giant')
GLOW_INSTRUMENTS = ('drums', 'other', 'bass')
CAMERA_MODES = ('pan', 'still')
BEAT_EFFECTS = ('none', 'dim', 'lights')  # what the beat does besides the shake
BEAT_SCOPES = ('chorus', 'song')
KINETIC_DEFAULTS = dict(
    camera='pan',
    pan_speed=0.05,
    backdrop_rate=0.6,
    backdrops=list(BACKDROP_KINDS),
    traces=True,
    geometry=0.8,
    frames=0.1,
    glows=list(GLOW_INSTRUMENTS),
    glow_words=0.15,
    glow_strength=0.55,
    glitch=True,
    text_pulse=0.0,
    word_shapes=0.0,
    drum_reactivity=0.8,
    background_shake=0.8,
    shake_all=False,
    beat_dim=0.0,
    chorus_fx=0.75,
    scenes=None,
    scene_settings=None,
    fade=True,
    beat_effect=None,
    beat_scope=None,
    beat_confetti=None,
    beat_intensity=None,
    confetti_intensity=0.85,
    beat_blur=0.0,
    match_art_colors=False,
    overlay_text=True,
)


def effect_speeds(value):
    """Per-effect particle speeds {effect id: 0.2..3}; effects without one use the global speed."""
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError('Invalid per-effect speeds') from exc
    value = value or {}
    if not isinstance(value, dict):
        raise ValueError('Invalid per-effect speeds')
    result = {}
    for key, speed in value.items():
        speed = number(speed, 'Each effect speed must be between 0.2 and 3')
        if (
            not isinstance(key, str)
            or not key.replace('-', '').isalnum()
            or not math.isfinite(speed)
            or not 0.2 <= speed <= 3
        ):
            raise ValueError('Each effect speed must be between 0.2 and 3')
        result[key] = speed
    return result


def number(value, message):
    """float(value), or ValueError(message) for anything that is not a number (null, a list, text), so bad settings
    get the same friendly message as out-of-range ones."""
    if isinstance(value, bool):
        raise ValueError(message)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(message) from None


def effect_intensities(value):
    """Per-effect letter-effect intensities {effect id: 0..2}; effects without one use the global intensity."""
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError('Invalid per-effect intensities') from exc
    value = value or {}
    if not isinstance(value, dict):
        raise ValueError('Invalid per-effect intensities')
    result = {}
    for key, amount in value.items():
        amount = number(amount, 'Each effect intensity must be between 0 and 2')
        if (
            not isinstance(key, str)
            or not key.replace('-', '').isalnum()
            or not math.isfinite(amount)
            or not 0 <= amount <= 2
        ):
            raise ValueError('Each effect intensity must be between 0 and 2')
        result[key] = amount
    return result


def kinetic_options(value):
    """Real-time effect controls with defaults; unknown keys are rejected."""
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError('Invalid kinetic effect settings') from exc
    value = value or {}
    if isinstance(value, dict):
        value = {k: v for k, v in value.items() if k != 'thread_shapes'}
    if not isinstance(value, dict) or set(value) - set(KINETIC_DEFAULTS):
        raise ValueError('Invalid kinetic effect settings')
    result = dict(KINETIC_DEFAULTS, **value)
    from direction.scene_controls import scene_settings

    result['scene_settings'] = scene_settings(result['scene_settings'])
    beat_settings(result)
    for key, low, high in (
        ('pan_speed', 0.0, 0.15),
        ('backdrop_rate', 0.0, 1.0),
        ('geometry', 0.0, 1.0),
        ('frames', 0.0, 1.0),
        ('glow_strength', 0.0, 1.0),
        ('text_pulse', 0.0, 1.0),
        ('glow_words', 0.0, 1.0),
        ('word_shapes', 0.0, 1.0),
        ('drum_reactivity', 0.0, 1.0),
        ('background_shake', 0.0, 1.0),
        ('beat_dim', 0.0, 1.0),
        ('chorus_fx', 0.0, 1.0),
        ('confetti_intensity', 0.0, 1.0),
        ('beat_blur', 0.0, 1.0),
    ):
        value = number(result[key], f'Kinetic setting {key} must be a number')
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Kinetic setting {key} is out of range')
        result[key] = value
    for key, allowed in (('backdrops', BACKDROP_KINDS), ('glows', GLOW_INSTRUMENTS)):
        if not isinstance(result[key], list) or any(item not in allowed for item in result[key]):
            raise ValueError(f'Invalid kinetic setting {key}')
    if result['camera'] not in CAMERA_MODES:
        raise ValueError('Invalid kinetic setting camera')
    if result['scenes'] is None:
        from direction.scene_catalog import scene_catalog

        result['scenes'] = list(scene_catalog())
    elif (
        not isinstance(result['scenes'], list)
        or not result['scenes']
        or any(not isinstance(s, str) for s in result['scenes'])
    ):
        raise ValueError('Tick at least one scene effect')
    else:
        from direction.scene_catalog import scene_catalog

        known = scene_catalog()
        result['scenes'] = [s for s in dict.fromkeys(result['scenes']) if s in known] or list(known)
    for key in ('traces', 'glitch', 'fade', 'shake_all', 'beat_confetti', 'match_art_colors', 'overlay_text'):
        if type(result[key]) is not bool:
            raise ValueError(f'Kinetic setting {key} must be on or off')
    pass
    pass
    pass
    return result


def beat_settings(result):
    """Fill the beat options (effect, scope, confetti, intensity) in place. Settings saved before they existed
    carry the older controls instead: chorus lights and confetti (chorus_fx), a dim slider and "shake all song"."""
    legacy_fx = number(result.get('chorus_fx') or 0.0, 'Kinetic setting chorus_fx must be a number')
    legacy_dim = number(result.get('beat_dim') or 0.0, 'Kinetic setting beat_dim must be a number')
    if result.get('beat_effect') is None:
        result['beat_effect'] = 'lights' if legacy_fx > 0 else 'dim' if legacy_dim > 0 else 'none'
    if result['beat_effect'] not in BEAT_EFFECTS:
        raise ValueError('Invalid kinetic setting beat_effect')
    if result.get('beat_intensity') is None:
        result['beat_intensity'] = (
            legacy_fx if result['beat_effect'] == 'lights' else legacy_dim if result['beat_effect'] == 'dim' else 0.75
        )
    if result.get('beat_scope') is None:
        result['beat_scope'] = 'song' if result.get('shake_all') else 'chorus'
    if result['beat_scope'] not in BEAT_SCOPES:
        raise ValueError('Invalid kinetic setting beat_scope')
    if result.get('beat_confetti') is None:
        result['beat_confetti'] = legacy_fx > 0
    intensity = number(result['beat_intensity'], 'Kinetic setting beat_intensity must be a number')
    if not math.isfinite(intensity) or not 0 <= intensity <= 1:
        raise ValueError('Kinetic setting beat_intensity is out of range')
    result['beat_intensity'] = intensity
    # The older keys follow the new ones, so anything still reading them agrees.
    result['shake_all'] = result['beat_scope'] == 'song'
    result['beat_dim'] = intensity if result['beat_effect'] == 'dim' else 0.0
    result['chorus_fx'] = intensity if result['beat_effect'] == 'lights' else 0.0
    return result


LETTERING_STYLES = ('swiss', 'poster', 'outline', 'cutout', 'neon', 'extrude', 'split')
# Openly licensed display fonts bundled in assets/fonts: (regular, bold, italic) files.
DISPLAY_FONTS = {
    'anton': ('Anton-Regular.ttf',) * 3,
    'archivo-black': ('ArchivoBlack-Regular.ttf',) * 3,
    'alfa-slab': ('AlfaSlabOne-Regular.ttf',) * 3,
    'big-shoulders': ('BigShouldersDisplay[wght].ttf',) * 3,
    'league-gothic': ('LeagueGothic[wdth].ttf',) * 3,
    'dela-gothic': ('DelaGothicOne-Regular.ttf',) * 3,
    'bowlby': ('BowlbyOne-Regular.ttf',) * 3,
    'unbounded': ('Unbounded[wght].ttf',) * 3,
    'rubik-mono': ('RubikMonoOne-Regular.ttf',) * 3,
    'syne': ('Syne[wght].ttf',) * 3,
    'bricolage': ('BricolageGrotesque[opsz,wdth,wght].ttf',) * 3,
    'bungee': ('Bungee-Regular.ttf',) * 3,
    'bungee-shade': ('BungeeShade-Regular.ttf',) * 3,
    'monoton': ('Monoton-Regular.ttf',) * 3,
    'shrikhand': ('Shrikhand-Regular.ttf',) * 3,
    'chango': ('Chango-Regular.ttf',) * 3,
    'bagel': ('BagelFatOne-Regular.ttf',) * 3,
    'titan': ('TitanOne-Regular.ttf',) * 3,
    'rammetto': ('RammettoOne-Regular.ttf',) * 3,
    'righteous': ('Righteous-Regular.ttf',) * 3,
    'tilt-warp': ('TiltWarp[XROT,YROT].ttf',) * 3,
    'climate-crisis': ('ClimateCrisis[YEAR].ttf',) * 3,
    'sixtyfour': ('Sixtyfour[BLED,SCAN].ttf',) * 3,
    'fraunces': ('Fraunces[SOFT,WONK,opsz,wght].ttf',) * 3,
    'abril': ('AbrilFatface-Regular.ttf',) * 3,
    'gloock': ('Gloock-Regular.ttf',) * 3,
    'dm-serif': ('DMSerifDisplay-Regular.ttf', 'DMSerifDisplay-Regular.ttf', 'DMSerifDisplay-Italic.ttf'),
}
FONT_FAMILIES = ('auto', 'arial', 'segoe', 'georgia', 'impact', *DISPLAY_FONTS)
FONT_STYLES = ('auto', 'regular', 'bold', 'italic')


def typography_options(values):
    family = values.get('font_family', 'auto')
    style = values.get('font_style', 'auto')
    scale = float(values.get('font_scale', 1.25))
    if family not in FONT_FAMILIES or style not in FONT_STYLES:
        raise ValueError('Choose an available font and style')
    if not math.isfinite(scale) or not 0.6 <= scale <= 2.0:
        raise ValueError('Font size must be between 60 and 200 percent')
    pool = values.get('text_pool')
    if isinstance(pool, str):
        try:
            pool = json.loads(pool)
        except json.JSONDecodeError as exc:
            raise ValueError('Invalid word animation set') from exc
    if pool is None:
        pool = list(WORD_ANIMATIONS)
    if not isinstance(pool, list) or any(choice not in WORD_ANIMATIONS for choice in pool):
        raise ValueError('Invalid word animation set')
    styles = values.get('lettering_styles')
    if isinstance(styles, str):
        try:
            styles = json.loads(styles)
        except json.JSONDecodeError as exc:
            raise ValueError('Invalid text style set') from exc
    if not styles:
        styles = list(LETTERING_STYLES)
    if not isinstance(styles, list) or any(choice not in LETTERING_STYLES for choice in styles):
        raise ValueError('Invalid text style set')
    flow = values.get('reading_flow', 'realtime') or 'realtime'
    if flow not in READING_FLOWS:
        raise ValueError('Choose the real-time, preview, 3D stage, scene mix or cinema reading flow')
    instructions = values.get('instructions') or ''
    if not isinstance(instructions, str) or len(instructions) > 2000:
        raise ValueError('Special instructions must be text of at most 2000 characters')
    return dict(
        instructions=instructions.strip(),
        font_family=family,
        font_style=style,
        font_scale=scale,
        text_pool=list(dict.fromkeys(pool)),
        reading_flow=flow,
        kinetic=kinetic_options(values.get('kinetic')),
        effect_speeds=effect_speeds(values.get('effect_speeds')),
        effect_intensities=effect_intensities(values.get('effect_intensities')),
        lettering_styles=[choice for choice in LETTERING_STYLES if choice in styles],
    )


def selected_word_animation(choice, pool, index):
    return (pool[index % len(pool)] if pool else 'none') if choice == 'mixed' else choice


def selected_font(family, style):
    if family == 'auto' and style == 'auto':
        return None
    family = 'segoe' if family == 'auto' else family
    style = 'bold' if style == 'auto' else style
    if family in DISPLAY_FONTS:
        from core.fonts import FONTS_DIR

        return FONTS_DIR / DISPLAY_FONTS[family][('regular', 'bold', 'italic').index(style)]
    stems = {
        'arial': ('arial.ttf', 'arialbd.ttf', 'ariali.ttf'),
        'segoe': ('segoeui.ttf', 'segoeuib.ttf', 'segoeuii.ttf'),
        'georgia': ('georgia.ttf', 'georgiab.ttf', 'georgiai.ttf'),
        'impact': ('impact.ttf', 'impact.ttf', 'impact.ttf'),
    }
    return (
        Path(os.environ.get('WINDIR', 'C:/Windows'))
        / 'Fonts'
        / stems[family][('regular', 'bold', 'italic').index(style)]
    )
