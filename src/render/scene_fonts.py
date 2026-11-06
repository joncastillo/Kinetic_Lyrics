"""Per-scene typefaces with context-aware caches; one scene never changes another's fonts."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache, wraps

from core import fonts

FONT_FILES = {
    'modern-sans': 'Montserrat-Variable.ttf',
    'humanist': 'BricolageGrotesque[opsz,wdth,wght].ttf',
    'condensed': 'BigShouldersDisplay[wght].ttf',
    'geometric': 'Syne[wght].ttf',
    'serif': 'DMSerifDisplay-Regular.ttf',
    'display-serif': 'Fraunces[SOFT,WONK,opsz,wght].ttf',
}
_FONT = ContextVar('scene_typeface', default=None)


def current_font():
    return _FONT.get()


@contextmanager
def font_scope(choice, inherited=None):
    token = _FONT.set(FONT_FILES.get(choice) or (str(inherited) if choice == 'auto' and inherited else None))
    try:
        yield
    finally:
        _FONT.reset(token)


def truetype(name, size, **options):
    return fonts.truetype(current_font() or name, size, **options)


def first_font(names, size):
    return fonts.first_font((current_font(),) if current_font() else names, size)


def font_cache(maxsize=128):
    """Include the selected face in raster/layout cache keys without leaking context between requests."""

    def decorate(function):
        @lru_cache(maxsize=maxsize)
        def cached(face, args, kwargs):
            return function(*args, **dict(kwargs))

        @wraps(function)
        def wrapped(*args, **kwargs):
            return cached(current_font(), args, tuple(sorted(kwargs.items())))

        wrapped.cache_clear = cached.cache_clear
        wrapped.cache_info = cached.cache_info
        return wrapped

    return decorate


def configure_scene_fonts(engine):
    for name in ('plan', 'frame', 'wisp_runs'):
        original = getattr(engine, name, None)
        if original is None:
            continue

        @wraps(original)
        def scoped(*args, _method=original, **kwargs):
            with font_scope(engine.scene_config.get('font', 'auto'), getattr(engine.c, 'custom_font', None)):
                return _method(*args, **kwargs)

        setattr(engine, name, scoped)
