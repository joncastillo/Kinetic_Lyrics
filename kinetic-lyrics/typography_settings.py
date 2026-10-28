"""Validated typography settings shared by Studio, previews and rendering."""
import json
import math
from pathlib import Path
import os

KINETIC_TEXT_SCALE = 3.

WORD_ANIMATIONS = ('directed','highlight','karaoke','slide','fade','none')
READING_FLOWS = ('realtime','preview')
BACKDROP_KINDS = ('outline','filled','vertical','echo','giant')
GLOW_INSTRUMENTS = ('drums','other','bass')
KINETIC_DEFAULTS = dict(pan_speed=.05,backdrop_rate=.6,backdrops=list(BACKDROP_KINDS),traces=True,
                        geometry=.8,frames=.1,glows=[],glow_strength=.55,glitch=True,text_pulse=.1,thread_shapes=.8)


def effect_speeds(value):
    """Per-effect particle speeds {effect id: 0.2..3}; effects without one use the global speed."""
    if isinstance(value,str):
        try:value=json.loads(value) if value.strip() else {}
        except json.JSONDecodeError as exc:raise ValueError('Invalid per-effect speeds') from exc
    value=value or {}
    if not isinstance(value,dict):raise ValueError('Invalid per-effect speeds')
    result={}
    for key,speed in value.items():
        speed=float(speed)
        if not isinstance(key,str) or not key.replace('-','').isalnum() or not math.isfinite(speed) or not .2<=speed<=3:
            raise ValueError('Each effect speed must be between 0.2 and 3')
        result[key]=speed
    return result


def kinetic_options(value):
    """Real-time effect controls with defaults; unknown keys are rejected."""
    if isinstance(value,str):
        try:value=json.loads(value) if value.strip() else {}
        except json.JSONDecodeError as exc:raise ValueError('Invalid kinetic effect settings') from exc
    value=value or {}
    if not isinstance(value,dict) or set(value)-set(KINETIC_DEFAULTS):
        raise ValueError('Invalid kinetic effect settings')
    result=dict(KINETIC_DEFAULTS,**value)
    for key,low,high in (('pan_speed',0.,.15),('backdrop_rate',0.,1.),('geometry',0.,1.),('frames',0.,1.),('glow_strength',0.,1.),('text_pulse',0.,1.),('thread_shapes',0.,1.)):
        number=float(result[key])
        if not math.isfinite(number) or not low<=number<=high:raise ValueError(f'Kinetic setting {key} is out of range')
        result[key]=number
    for key,allowed in (('backdrops',BACKDROP_KINDS),('glows',GLOW_INSTRUMENTS)):
        if not isinstance(result[key],list) or any(item not in allowed for item in result[key]):
            raise ValueError(f'Invalid kinetic setting {key}')
    for key in ('traces','glitch'):
        if type(result[key]) is not bool:raise ValueError(f'Kinetic setting {key} must be on or off')
    return result
LETTERING_STYLES = ('swiss','poster','outline','cutout','neon','extrude','split')
FONT_FAMILIES = ('auto','arial','segoe','georgia','impact')
FONT_STYLES = ('auto','regular','bold','italic')


def typography_options(values):
    family = values.get('font_family','auto')
    style = values.get('font_style','auto')
    scale = float(values.get('font_scale',1.25))
    if family not in FONT_FAMILIES or style not in FONT_STYLES:
        raise ValueError('Choose an available font and style')
    if not math.isfinite(scale) or not .6 <= scale <= 2.:
        raise ValueError('Font size must be between 60 and 200 percent')
    pool = values.get('text_pool')
    if isinstance(pool,str):
        try:pool=json.loads(pool)
        except json.JSONDecodeError as exc:raise ValueError('Invalid word animation set') from exc
    if pool is None:pool=list(WORD_ANIMATIONS)
    if not isinstance(pool,list) or any(choice not in WORD_ANIMATIONS for choice in pool):
        raise ValueError('Invalid word animation set')
    styles = values.get('lettering_styles')
    if isinstance(styles,str):
        try:styles=json.loads(styles)
        except json.JSONDecodeError as exc:raise ValueError('Invalid text style set') from exc
    if not styles:styles=list(LETTERING_STYLES)
    if not isinstance(styles,list) or any(choice not in LETTERING_STYLES for choice in styles):
        raise ValueError('Invalid text style set')
    flow = values.get('reading_flow','realtime') or 'realtime'
    if flow not in READING_FLOWS:
        raise ValueError('Choose real-time or preview reading flow')
    return dict(font_family=family,font_style=style,font_scale=scale,text_pool=list(dict.fromkeys(pool)),reading_flow=flow,
                kinetic=kinetic_options(values.get('kinetic')),effect_speeds=effect_speeds(values.get('effect_speeds')),
                lettering_styles=[choice for choice in LETTERING_STYLES if choice in styles])


def selected_word_animation(choice,pool,index):
    return (pool[index%len(pool)] if pool else 'none') if choice=='mixed' else choice


def selected_font(family,style):
    if family=='auto' and style=='auto':return None
    family='segoe' if family=='auto' else family
    style='bold' if style=='auto' else style
    stems={'arial':('arial.ttf','arialbd.ttf','ariali.ttf'),
           'segoe':('segoeui.ttf','segoeuib.ttf','segoeuii.ttf'),
           'georgia':('georgia.ttf','georgiab.ttf','georgiai.ttf'),
           'impact':('impact.ttf','impact.ttf','impact.ttf')}
    return Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/stems[family][('regular','bold','italic').index(style)]
