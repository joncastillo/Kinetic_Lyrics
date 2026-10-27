"""Validated typography settings shared by Studio, previews and rendering."""
import json
import math
from pathlib import Path
import os

KINETIC_TEXT_SCALE = 3.

WORD_ANIMATIONS = ('directed','highlight','karaoke','slide','fade','none')
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
    return dict(font_family=family,font_style=style,font_scale=scale,text_pool=list(dict.fromkeys(pool)))


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
