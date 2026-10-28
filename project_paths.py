"""Portable storage defaults, preserving an existing Studio installation."""
import os
from pathlib import Path


def default_model_cache():
    override=os.environ.get('KINETIC_LYRICS_MODEL_CACHE')
    if override:return Path(override).expanduser()
    existing=Path('D:/AI_Models')
    if os.name=='nt' and existing.is_dir():return existing
    return Path.home()/'.cache'/'kinetic-lyrics'


def studio_output(here,name='lyric-studio'):
    override=os.environ.get('KINETIC_LYRICS_OUTPUT')
    if override:return Path(override).expanduser().resolve()
    legacy=here.parent/'output'/name
    return legacy if legacy.is_dir() else here/'output'/name
