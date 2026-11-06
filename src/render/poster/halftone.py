"""The halftone bloom: the line set big in halftone dots; each sung word's dots swell until they merge solid."""

from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from core.fonts import truetype
from effects.kinetic.easing import back_out, clamp, smoother
from render.poster.common import FONTS, LEAVE, WALL_FONT, WHITE, paste, tint


@lru_cache(maxsize=32)
def halftone_layout(words, width, height, style=0):
    """The line typeset in up to three centred rows, as halftone cells: for each word the cell centres it covers
    and how much of each cell its ink fills (0-1), the cell pitch, and the word's centre."""
    pitch = max(5, round(height * 0.021))
    rows, current = [], []
    for word in words:
        if current and len(' '.join(current + [word])) > 11:
            rows.append(current)
            current = []
        current.append(word)
    rows.append(current)
    rows = rows[:3] if len(rows) <= 3 else rows[:2] + [sum(rows[2:], [])]
    face = truetype(str(FONTS / WALL_FONT), 200)
    space = face.getlength(' ')
    natural = [sum(face.getlength(w) for w in row) + space * (len(row) - 1) for row in rows]
    line_h = 200 * 1.08
    stagger = width * 0.08 if style == 2 else 0.0  # centred, flush left, or stepped rows, by line
    size = min((width * 0.86 - stagger * (len(rows) - 1)) / max(natural), height * 0.7 / (line_h * len(rows))) * 200
    face = truetype(str(FONTS / WALL_FONT), max(8, round(size)))
    space = face.getlength(' ')
    step = size * 1.08
    top = height / 2 - step * len(rows) / 2
    cells_x, cells_y = width // pitch, height // pitch
    out = []
    for r, row in enumerate(rows):
        row_w = sum(face.getlength(w) for w in row) + space * (len(row) - 1)
        x = width / 2 - row_w / 2 if style == 0 else width * 0.07 + stagger * r
        for word in row:
            mask = Image.new('L', (cells_x * pitch, cells_y * pitch))
            ImageDraw.Draw(mask).text((x, top + r * step + step / 2), word, font=face, fill=255, anchor='lm')
            cover = np.asarray(mask, np.float32).reshape(cells_y, pitch, cells_x, pitch).mean(axis=(1, 3)) / 255
            ys, xs = np.nonzero(cover > 0.03)
            centre = (x + face.getlength(word) / 2, top + r * step + step / 2)
            box = mask.getbbox() or (0, 0, 1, 1)
            out.append(((xs + 0.5) * pitch, (ys + 0.5) * pitch, cover[ys, xs], centre, mask.crop(box), box[:2]))
            x += face.getlength(word) + space
    return tuple(out), pitch


class HalftoneScene:
    def paint_halftone(self, screen, line, t):
        """The whole line set big as a halftone screen of dots. The dots sweep in diagonally when the line arrives;
        each sung word's dots swell in the accent until they merge into solid type, with a ripple running out
        through the screen, then relax back to dots as the next word takes over. The dots shrink away at the end."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = tuple(w['text'].strip().upper() or '~' for w in line['words'])
        arrive = clamp((t - line['start']) / 0.55)
        leave = clamp((t - (line['end'] - LEAVE)) / LEAVE)
        if leave >= 0.999 or arrive <= 0:
            return
        layout, pitch = halftone_layout(
            words,
            W,
            H,
            {'center': 0, 'left': 1, 'stepped': 2}.get(self.setting(line, 'alignment', 'auto'), line['index'] % 3),
        )
        if len(layout) != len(words):
            return
        draw = ImageDraw.Draw(screen)
        ring = (t - since) * W * 1.3  # a ripple runs out through the screen from each newly sung word
        fade = 1 - clamp((t - since) / 0.7)
        cx, cy = layout[k][3]
        for pass_ in (0, 1):  # a hard shadow of every dot first, then the dots
            for i, (xs, ys, cover, *_) in enumerate(layout):
                if i == k:
                    solid = back_out(clamp((t - since) / 0.28), 1.6)
                elif i == k - 1:
                    solid = 1 - smoother(clamp((t - since) / 0.3))
                else:
                    solid = 0.0
                color = accent if i == k else WHITE if i < k else (190, 198, 220)
                handover = (
                    smoother(clamp((min(1.0, solid) - 0.8) / 0.2)) if i >= k - 1 else 0.0
                )  # dots give way to the glyph
                base = 0.4 if i <= k else 0.32  # unsung words are a finer, lighter screen
                if pass_ == 0:
                    color = shade
                delay = xs / W * 0.6 + ys / H * 0.4
                grow = np.clip((arrive * 1.6 - delay) / 0.4, 0, 1)
                shrink = np.clip((leave * 1.6 - delay) / 0.4, 0, 1)
                dist = np.hypot(xs - cx, ys - cy)
                ripple = 0.28 * self.setting(line, 'motion') * fade * np.exp(-(((dist - ring) / (pitch * 3)) ** 2))
                radius = (
                    pitch
                    * np.sqrt(cover)
                    * (base + 0.42 * solid + ripple)
                    * (grow * grow * (3 - 2 * grow))
                    * (1 - shrink)
                    * (1 - handover)
                )
                off = pitch * 0.18 if pass_ == 0 else 0.0
                for x, y, r in zip(xs, ys, radius):
                    if r > 0.4:
                        draw.ellipse((x + off - r, y + off - r, x + off + r, y + off + r), fill=(*color, 255))
        # The bloom finishes as the real glyphs: crisp solid type, not merged dots.
        for i in (k - 1, k):
            if i < 0:
                continue
            solid = back_out(clamp((t - since) / 0.28), 1.6) if i == k else 1 - smoother(clamp((t - since) / 0.3))
            crisp = smoother(clamp((min(1.0, solid) - 0.8) / 0.2)) * (1 - clamp(leave * 2))
            if crisp > 0.02:
                mask, (x0, y0) = layout[i][4], layout[i][5]
                paste(screen, tint(mask, shade, crisp), x0 + pitch * 0.18, y0 + pitch * 0.18)
                paste(screen, tint(mask, accent if i == k else WHITE, crisp), x0, y0)
