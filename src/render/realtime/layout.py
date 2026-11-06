"""Fonts by role, the Word record, word roles, line layout and word sprites."""
from dataclasses import dataclass, field
from functools import lru_cache
import math
import string
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from core.fonts import first_font, truetype
from core.color import hex_rgb
from render.realtime.common import DISPLAY_ROLES, FUNCTION_WORDS, HOT_COLORS, ROLE_FONTS, ROLE_SCALE, ROW_LEADING, _chosen_font

def use_display_font(path):
    """Content and hero words use `path` (the font chosen in Studio or on the command line), or the role fonts
    again when it is None. Fonts are looked up per process, so a render sets this once before it lays out."""
    global _chosen_font
    path = str(path) if path else None
    if path != _chosen_font:
        _chosen_font = path
        role_font.cache_clear()


@lru_cache(maxsize=256)
def role_font(role, size):
    if _chosen_font and role in DISPLAY_ROLES:
        try:
            return truetype(_chosen_font, size)
        except OSError:
            pass
    return first_font(ROLE_FONTS[role], size) or ImageFont.load_default(size)


@dataclass
class Word:
    index: int
    text: str
    role: str
    start: float
    end: float
    size: int
    color: tuple
    hot: bool
    held: bool
    fast: bool
    x: float = 0.
    y: float = 0.
    width: float = 0.
    row: int = 0
    glow: str = ''
    shape: tuple = ()
    ink: tuple = (0., 0.)  # top and bottom of the drawn glyphs, relative to y
    effect: object = None  # a letter effect a special instruction gave this word
    glows: dict = field(default_factory=dict)  # instrument -> glow colour, matched to the artwork when asked


def bare(text):
    return text.strip(string.punctuation+'“”‘’').lower()


def assign_roles(line, features, emphasis):
    """Function words stay small; the planned emphasis and the most sung-out words become heroes."""
    words = line['words']
    roles = ['function' if len(words) > 2 and bare(w['text']) in FUNCTION_WORDS else 'content' for w in words]
    def weight(i):
        f = features[i] if features else {}
        return (f.get('pitch_rank') or 0)+(f.get('duration_rank') or 0)+(f.get('loudness_rank') or 0)*.5
    candidates = [i for i, role in enumerate(roles) if role == 'content']
    heroes = {emphasis} if 0 <= emphasis < len(words) and roles[emphasis] == 'content' else set()
    for i in sorted(candidates, key=weight, reverse=True):
        if len(heroes) >= (2 if len(words) > 4 else 1):
            break
        if not heroes or weight(i) >= 1.6:
            heroes.add(i)
    return ['hero' if i in heroes else role for i, role in enumerate(roles)]


class LineLayout:
    """Mixed-size, left-justified rows inside a box (screen coordinates at the line's start). Rows sit
    close together, measured from the glyphs' own ink so no row touches the next."""

    def __init__(self, line, features, scene, palette, base, box, min_scale=.55):
        ink, accent = hex_rgb(palette[2]), hex_rgb(palette[3])
        roles = assign_roles(line, features, scene.get('emphasis', -1))
        self.words = []
        for i, (word, role) in enumerate(zip(line['words'], roles)):
            f = features[i] if features else {}
            hot = (f.get('pitch_rank') or 0) >= .8
            color = hex_rgb(HOT_COLORS[i % 2]) if role == 'hero' and hot else accent if role == 'hero' else ink
            self.words.append(Word(i, word['text'].upper() if role != 'function' else word['text'].lower(), role,
                                   word['start'], word['end'], 1, color, hot,
                                   held=(f.get('duration_rank') or 0) >= .75, fast=(f.get('rate_rank') or 0) >= .7))
        x0, y0, w, h = box
        scale = 1.
        while True:
            rows = self._flow(base*scale, w)
            leading = base*scale*ROW_LEADING
            height = sum(r['height'] for r in rows)+leading*(len(rows)-1)
            if height <= h or scale <= min_scale:
                break
            scale *= .92
        self.height = height
        self.width = max(r['width'] for r in rows)
        self.gap = rows[0]['gap']
        y = y0+(h-height)/2
        for number, row in enumerate(rows):
            x, baseline = x0, y-row['top']
            for word in row['words']:
                word.row = number
                word.x, word.y = x, baseline-role_font(word.role, word.size).getmetrics()[0]
                x += word.width+row['gap']
            y += row['height']+leading

    def bounds(self):
        return (min(w.x for w in self.words), min(w.y+w.ink[0] for w in self.words),
                max(w.x+w.width for w in self.words), max(w.y+w.ink[1] for w in self.words))

    def move(self, dx, dy):
        for word in self.words:
            word.x += dx
            word.y += dy

    def _flow(self, base, max_width):
        for word in self.words:
            word.size = max(10, round(base*ROLE_SCALE[word.role]))
            word.width = role_font(word.role, word.size).getlength(word.text)
            if word.width > max_width:
                word.size = max(10, round(word.size*max_width/word.width))
                word.width = role_font(word.role, word.size).getlength(word.text)
        for word in self.words:
            font = role_font(word.role, word.size)
            box = font.getbbox(word.text)
            word.ink = (box[1], box[3])
        rows, current = [], []
        gap = base*.24
        for word in self.words:
            if current and sum(w.width for w in current)+gap*len(current)+word.width > max_width:
                rows.append(current)
                current = []
            current.append(word)
        if current:
            rows.append(current)
        result = []
        for row in rows:
            # Ink extents relative to the shared baseline.
            ascents = [role_font(w.role, w.size).getmetrics()[0] for w in row]
            top = min(w.ink[0]-a for w, a in zip(row, ascents))
            bottom = max(w.ink[1]-a for w, a in zip(row, ascents))
            result.append(dict(words=row, gap=gap, top=top, height=bottom-top,
                               width=sum(w.width for w in row)+gap*(len(row)-1)))
        return result


def word_sprite(word, size, color, alpha=1., glitch=False):
    """The word drawn at `size` with a soft shadow; also returns padding and glyph spans."""
    font = role_font(word.role, size)
    pad = max(8, round(size*.12))
    sprite = Image.new('RGBA', (math.ceil(font.getlength(word.text))+pad*2, round(size*1.4)+pad*2))
    shadow = Image.new('RGBA', sprite.size)
    ImageDraw.Draw(shadow).text((pad, pad+round(size*.04)), word.text, font=font, fill=(0, 0, 0, round(150*alpha)))
    sprite.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(1, size*.05))))
    draw = ImageDraw.Draw(sprite)
    if glitch:
        shift = max(1, round(size*.03))
        draw.text((pad-shift, pad), word.text, font=font, fill=(255, 40, 120, round(170*alpha)))
        draw.text((pad+shift, pad), word.text, font=font, fill=(40, 220, 255, round(170*alpha)))
    draw.text((pad, pad), word.text, font=font, fill=(*color, round(255*alpha)))
    edges = [0]+[pad+round(font.getlength(word.text[:k])) for k in range(1, len(word.text))]+[sprite.width]
    return sprite, pad, list(zip(edges, edges[1:]))
