"""Pieces several scenes use: the sung word, the sung row and the caption strip."""

from PIL import ImageDraw
from core.fonts import truetype
from effects.kinetic.easing import back_out, clamp, smoother
from render.poster.common import CAPTION_FONT, FONTS, LEAD


class PosterShared:
    @staticmethod
    def setting(line, key, default=1.0):
        return line.get('config', {}).get(key, default)

    def sung_word(self, line, t):
        words = line['words']
        k = 0
        for n, word in enumerate(words):
            if word['start'] - 0.06 <= t:
                k = n
        return k, max(line['start'] + LEAD, words[k]['start'] - 0.06)

    @staticmethod
    def active_row(line, t):
        """The row being sung (or the last one sung), and the time it became active."""
        current, since = None, line['start']
        for k, row in enumerate(line['rows']):
            if row['words'][0]['start'] - 0.08 <= t:
                current, since = k, row['words'][0]['start'] - 0.08
        return current, since

    def paint_caption(self, screen, line, t, pill, shade, arrive, leave):
        """The whole line in a pill strip along the bottom; the sung word knocked out in a dark lozenge."""
        W, H = screen.size
        size = max(12, round(H * 0.045))
        face = truetype(str(FONTS / CAPTION_FONT), size)
        words = [w['text'].strip().upper() for w in line['words']]
        space = face.getlength(' ')
        widths = [face.getlength(w) for w in words]
        total = sum(widths) + space * (len(words) - 1)
        pad = size * 0.7
        # Reserve room for the opening overshoot, including on narrow portrait frames.
        while size > 5 and total + pad * 2 > W * 0.86:
            size = max(5, min(size - 1, int(size * W * 0.86 / (total + pad * 2))))
            face = truetype(str(FONTS / CAPTION_FONT), size)
            space = face.getlength(' ')
            widths = [face.getlength(w) for w in words]
            total = sum(widths) + space * (len(words) - 1)
            pad = size * 0.7
        cx, cy = W / 2, H * 0.885
        open_ = back_out(clamp(arrive * 1.2), 1.6) * (1 - smoother(leave))
        if open_ <= 0.01:
            return
        width = (total + pad * 2) * open_
        draw = ImageDraw.Draw(screen)
        draw.rounded_rectangle(
            (
                cx - width / 2 + size * 0.12,
                cy - size * 0.85 + size * 0.12,
                cx + width / 2 + size * 0.12,
                cy + size * 0.85 + size * 0.12,
            ),
            radius=size * 0.85,
            fill=(*shade, 255),
        )
        draw.rounded_rectangle(
            (cx - width / 2, cy - size * 0.85, cx + width / 2, cy + size * 0.85), radius=size * 0.85, fill=(*pill, 255)
        )
        if open_ < 0.9:
            return
        x = cx - total / 2
        k, _ = self.sung_word(line, t)
        for n, (word, w) in enumerate(zip(words, widths)):
            if n == k:
                draw.rounded_rectangle(
                    (x - size * 0.25, cy - size * 0.62, x + w + size * 0.25, cy + size * 0.62),
                    radius=size * 0.5,
                    fill=(*shade, 255),
                )
            draw.text((x, cy), word, font=face, fill=(*(pill if n == k else shade), 255), anchor='lm')
            x += w + space
