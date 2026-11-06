"""Constants and drawing helpers shared by the poster scenes."""

from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from core.fonts import truetype
from core.paths import ASSET_ROOT

FONTS = ASSET_ROOT / 'fonts'
STACK_FONT = 'BigShouldersDisplay[wght].ttf'
WALL_FONT = 'BricolageGrotesque[opsz,wdth,wght].ttf'
CAPTION_FONT = 'Syne[wght].ttf'
LEAD, ENTRY, LEAVE, SWAP, UNROLL = 0.35, 0.4, 0.3, 0.22, 0.11
SECOND_INK = (226, 232, 242)
FIELDS = ((219, 151, 100), (135, 162, 188), (191, 193, 150), (99, 166, 157), (196, 148, 166), (224, 194, 133))
WALL_INK = (22, 18, 30)
FLIP = (
    0.12  # seconds a wall row takes to flip over  # the stack's other rows alternate off-white and this cool grey-blue
)
PALETTES = (  # (accent, extrusion/shade, pill)
    ((219, 151, 100), (26, 32, 44), (220, 213, 192)),
    ((135, 162, 188), (20, 31, 43), (228, 197, 156)),
    ((191, 193, 150), (28, 34, 30), (225, 208, 187)),
    ((196, 148, 166), (35, 27, 39), (187, 202, 211)),
    ((99, 166, 157), (16, 32, 37), (232, 204, 158)),
)
WHITE = (248, 246, 240)


@lru_cache(maxsize=512)
def word_mask(text, font_name, size=220, stroke=0):
    """A tight alpha mask of `text`, drawn large once and scaled freely afterwards."""
    face = truetype(str(FONTS / font_name), size)
    box = face.getbbox(text, stroke_width=stroke)
    mask = Image.new('L', (box[2] - box[0] + 4, box[3] - box[1] + 4))
    draw = ImageDraw.Draw(mask)
    if stroke:
        draw.text((2 - box[0], 2 - box[1]), text, font=face, fill=255, stroke_width=stroke, stroke_fill=255)
        inner = Image.new('L', mask.size)
        ImageDraw.Draw(inner).text((2 - box[0], 2 - box[1]), text, font=face, fill=255)
        mask = Image.fromarray(
            np.clip(np.asarray(mask, np.int16) - np.asarray(inner, np.int16), 0, 255).astype('uint8')
        )
    else:
        draw.text((2 - box[0], 2 - box[1]), text, font=face, fill=255)
    return mask


def tint(mask, color, alpha=1.0):
    image = Image.new('RGBA', mask.size, (*color, 0))
    image.putalpha(mask if alpha >= 0.999 else mask.point(lambda v: round(v * alpha)))
    return image


def paste(screen, image, left, top):
    left, top = round(left), round(top)
    if left >= screen.width or top >= screen.height or left + image.width <= 0 or top + image.height <= 0:
        return
    crop = (max(0, -left), max(0, -top), min(image.width, screen.width - left), min(image.height, screen.height - top))
    if crop != (0, 0, image.width, image.height):
        image = image.crop(crop)
    screen.alpha_composite(image, (max(0, left), max(0, top)))


@lru_cache(maxsize=512)
def letter_edges(text, font_name=STACK_FONT):
    """Where each letter of `text` ends, as shares of the word's width (0 first, 1 last), from the font itself."""
    face = truetype(str(FONTS / font_name), 220)
    total = max(1.0, face.getlength(text))
    return tuple([0.0] + [face.getlength(text[:i]) / total for i in range(1, len(text))] + [1.0])


TOUR_FONT = 'Syne[wght].ttf'


@lru_cache(maxsize=256)
def tour_sprite(text, thickness, color):
    """`text` as a word sprite whose cap height is `thickness` pixels, with glyph spans for the kinetic entrances."""
    mask = word_mask(text, TOUR_FONT, 200)
    width = max(1, round(mask.width * thickness / mask.height))
    body = mask.resize((width, max(1, thickness)), Image.Resampling.BICUBIC)
    pad = max(2, round(thickness * 0.12))
    sprite = Image.new('RGBA', (width + pad * 2, thickness + pad * 2))
    sprite.alpha_composite(tint(body, color), (pad, pad))
    edges = letter_edges(text, TOUR_FONT)
    cuts = [0] + [pad + round(e * width) for e in edges[1:-1]] + [sprite.width]
    return sprite, tuple(zip(cuts, cuts[1:]))


@lru_cache(maxsize=4096)
def spiral_glyph(char, size, angle, color):
    """One character of the spiral, turned to follow the curve (angles bucketed so the cache stays small)."""
    mask = word_mask(char, CAPTION_FONT, 120)
    glyph = tint(
        mask.resize(
            (max(1, round(mask.width * size / 120)), max(1, round(mask.height * size / 120))), Image.Resampling.BICUBIC
        ),
        color,
    )
    return glyph.rotate(angle, Image.Resampling.BICUBIC, expand=True)


@lru_cache(maxsize=2048)
def drum_glyph(char, size, color):
    mask = word_mask(char, CAPTION_FONT, 120)
    return tint(
        mask.resize(
            (max(1, round(mask.width * size / 120)), max(1, round(mask.height * size / 120))), Image.Resampling.BICUBIC
        ),
        color,
    )


def rows_of(words):
    """Rows for the stack: one word each, a short function word leaning on its neighbour, at most six."""
    rows = []
    for word in words:
        text = word['text'].strip().upper().strip('.,!?;:"')
        if not text:
            continue
        if rows and (len(text) <= 2 or len(rows[-1]['text']) <= 2) and len(rows[-1]['text']) + len(text) <= 7:
            rows[-1]['text'] += ' ' + text
            rows[-1]['words'].append(word)
        else:
            rows.append(dict(text=text, words=[word]))
    while len(rows) > 6:
        k = min(range(len(rows) - 1), key=lambda i: len(rows[i]['text']) + len(rows[i + 1]['text']))
        rows[k] = dict(text=rows[k]['text'] + ' ' + rows[k + 1]['text'], words=rows[k]['words'] + rows[k + 1]['words'])
        del rows[k + 1]
    return rows
