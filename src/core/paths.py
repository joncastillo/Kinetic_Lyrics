"""Portable storage defaults, preserving an existing Studio installation."""
import json
import os
from pathlib import Path

SRC_ROOT=Path(__file__).resolve().parents[1]
PROJECT_ROOT=SRC_ROOT.parent
ASSET_ROOT=PROJECT_ROOT/'assets'
UI_ROOT=SRC_ROOT/'frontend'


def ollama_models_dir():
    override=os.environ.get('OLLAMA_MODELS')
    return Path(override).expanduser() if override else Path.home()/'.ollama'/'models'


def default_model_cache():
    override=os.environ.get('KINETIC_LYRICS_MODEL_CACHE')
    return Path(override).expanduser() if override else ollama_models_dir()


SETTINGS=PROJECT_ROOT/'.runtime'/'studio-settings.json'


def documents_folder():
    """The user's Documents, asked of Windows so a folder redirected to OneDrive or another drive is found."""
    if os.name=='nt':
        import ctypes
        path=ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None,5,None,0,path)==0 and path.value:  # 5: CSIDL_PERSONAL
            return Path(path.value)
    return Path.home()/'Documents'


def saved_projects_folder():
    try:
        return str(json.loads(SETTINGS.read_text(encoding='utf-8')).get('projects_folder') or '')
    except (OSError,ValueError,AttributeError):
        return ''


def save_projects_folder(value):
    """Keep the folder new projects go in (Settings); '' goes back to the default. The folder is made now, so one that
    cannot be used is refused here rather than at the next start. Returns the folder saved, or ''."""
    value=str(value or '').strip()
    if value:
        folder=Path(value).expanduser()
        if not folder.is_absolute():
            raise ValueError('Give the whole path of the folder, for example D:\\Kinetic Lyrics')
        try:
            folder.mkdir(parents=True,exist_ok=True)
            probe=folder/'.kinetic-write-test'
            probe.write_text('x',encoding='utf-8');probe.unlink()
        except OSError as exc:
            raise ValueError(f'That folder cannot be used: {exc}') from exc
        value=str(folder.resolve())
    SETTINGS.parent.mkdir(parents=True,exist_ok=True)
    SETTINGS.write_text(json.dumps(dict(projects_folder=value),indent=2),encoding='utf-8')
    return value


def studio_output(here,name='lyric-studio'):
    """Where projects are kept: the environment's folder, else the one chosen in Settings, else the folder of an install
    that already has one (its projects hold full paths and are not moved), else Documents/Kinetic Lyrics."""
    override=os.environ.get('KINETIC_LYRICS_OUTPUT')
    if override:return Path(override).expanduser().resolve()
    saved=saved_projects_folder()
    if saved:return Path(saved).expanduser().resolve()
    for existing in (here.parent/'output'/name,here/'output'/name):
        if existing.is_dir():return existing
    return documents_folder()/'Kinetic Lyrics'
