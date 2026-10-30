"""Portable storage defaults, preserving an existing Studio installation."""
import os
from pathlib import Path

SRC_ROOT=Path(__file__).resolve().parents[1]
PROJECT_ROOT=SRC_ROOT.parent
UI_ROOT=SRC_ROOT/'frontend'


def ollama_models_dir():
    override=os.environ.get('OLLAMA_MODELS')
    return Path(override).expanduser() if override else Path.home()/'.ollama'/'models'


def default_model_cache():
    override=os.environ.get('KINETIC_LYRICS_MODEL_CACHE')
    return Path(override).expanduser() if override else ollama_models_dir()


def studio_output(here,name='lyric-studio'):
    override=os.environ.get('KINETIC_LYRICS_OUTPUT')
    if override:return Path(override).expanduser().resolve()
    legacy=here.parent/'output'/name
    return legacy if legacy.is_dir() else here/'output'/name
