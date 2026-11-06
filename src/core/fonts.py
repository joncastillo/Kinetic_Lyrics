"""Font files by name: the one asked for when this machine has it, otherwise a bundled free look-alike.

The renderer names Windows fonts (Impact, Segoe UI Black, Georgia...). Those cannot be redistributed, so
assets/fonts/ ships openly licensed stand-ins of the same weight and character, and every font is looked
up here: a path as given, assets/fonts/, the Windows fonts folder, the system's own fonts, and only then
the bundled substitute.
"""
from functools import lru_cache
import os
from pathlib import Path

from PIL import ImageFont

from core.paths import ASSET_ROOT

FONTS_DIR = ASSET_ROOT/'fonts'
WINDOWS_FONTS = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'
# Lower-case Windows file name -> bundled stand-in in assets/fonts/.
SUBSTITUTES = {
    'impact.ttf': 'Anton-Regular.ttf',
    'ariblk.ttf': 'ArchivoBlack-Regular.ttf',
    'seguibl.ttf': 'ArchivoBlack-Regular.ttf',
    'gilsanub.ttf': 'ArchivoBlack-Regular.ttf',
    'rockeb.ttf': 'AlfaSlabOne-Regular.ttf',
    'arial.ttf': 'DejaVuSans.ttf',
    'segoeui.ttf': 'DejaVuSans.ttf',
    'arialbd.ttf': 'DejaVuSans-Bold.ttf',
    'segoeuib.ttf': 'DejaVuSans-Bold.ttf',
    'seguisb.ttf': 'DejaVuSans-Bold.ttf',
    'ariali.ttf': 'DejaVuSans-Oblique.ttf',
    'segoeuii.ttf': 'DejaVuSans-Oblique.ttf',
    'segoeuil.ttf': 'DejaVuSans-ExtraLight.ttf',
    'calibril.ttf': 'DejaVuSans-ExtraLight.ttf',
    'bahnschrift.ttf': 'DejaVuSansCondensed-Bold.ttf',
    'georgia.ttf': 'DejaVuSerif.ttf',
    'georgiab.ttf': 'DejaVuSerif-Bold.ttf',
    'georgiai.ttf': 'DejaVuSerif-Italic.ttf',
    'cour.ttf': 'DejaVuSansMono.ttf',
}


@lru_cache(maxsize=None)
def font_file(name):
    """A loadable file for `name` (a file name or a path), or OSError when neither it nor a stand-in exists."""
    path = Path(name)
    if path.is_file():
        return str(path)
    for folder in (FONTS_DIR, WINDOWS_FONTS):
        if (folder/path.name).is_file():
            return str(folder/path.name)
    try:
        ImageFont.truetype(path.name, 10)  # Pillow also searches the system's font folders by file name
        return path.name
    except OSError:
        pass
    substitute = SUBSTITUTES.get(path.name.lower())
    if substitute and (FONTS_DIR/substitute).is_file():
        return str(FONTS_DIR/substitute)
    raise OSError(f'Font not found: {name}')


# Bundled variable fonts default to their thinnest instance; lettering wants their display cut.
VARIATIONS = {
    'bigshouldersdisplay[wght].ttf': {'Weight': 800},
    'syne[wght].ttf': {'Weight': 800},
    'unbounded[wght].ttf': {'Weight': 800},
    'fraunces[soft,wonk,opsz,wght].ttf': {'Weight': 900, 'Optical Size': 144, 'Softness': 100, 'Wonky': 1},
    'bricolagegrotesque[opsz,wdth,wght].ttf': {'Weight': 800, 'Optical size': 96, 'Width': 100},
}


def truetype(name, size, **options):
    path = font_file(str(name))
    font = ImageFont.truetype(path, size, **options)
    wanted = VARIATIONS.get(Path(path).name.lower())
    if wanted:
        try:
            axes = font.get_variation_axes()
            values = []
            for axis in axes:
                label = axis['name'].decode() if isinstance(axis['name'], bytes) else axis['name']
                values.append(wanted.get(label, axis['default']))
            font.set_variation_by_axes(values)
        except (OSError, KeyError):  # Pillow built without variation support keeps the default instance
            pass
    return font


def first_font(names, size):
    """The first of `names` that loads (each looked up as font_file does, Windows fonts folder included), or None."""
    for name in names:
        try:
            return truetype(name, size)
        except OSError:
            continue
    return None
