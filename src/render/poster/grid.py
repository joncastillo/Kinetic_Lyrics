"""The title grid: a tilted architectural grid with the sung word across its flooded cell."""

import math
import numpy as np
from PIL import Image, ImageDraw
from effects.kinetic.easing import clamp, pulse, smoother, window
from render.poster.common import LEAVE, SECOND_INK, STACK_FONT, WALL_FONT, WHITE, paste, tint, word_mask


class GridScene:
    def paint_grid(self, screen, line, t):
        """A strongly tilted architectural grid, as in classic title sequences: bold rules sweep in, each word
        glides along its rule into its cell, filling the cell's height; when a word is sung its cell floods
        with colour and the word is knocked out in dark ink and stretched to the cell's full width."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() for w in line['words']]
        n = len(words)
        leave = smoother(clamp((t - (line['end'] - LEAVE)) / LEAVE))
        canvas = Image.new('RGBA', (W, H))
        draw = ImageDraw.Draw(canvas)
        cols = 2 if n > 3 else 1
        rows = math.ceil(n / cols)
        left, right, top, bottom = W * 0.1, W * 0.9, H * 0.14, H * 0.8
        row_h = (bottom - top) / rows
        col_w = (right - left) / cols
        rule = smoother(clamp((t - line['start']) / 0.3)) * (1 - leave)
        width = max(6, round(H / 60))
        for r in range(rows + 1):
            y = top + r * row_h
            reach = W * clamp(rule * 1.6 - r * 0.15)  # rule by rule
            x0, x1 = (0, reach) if r % 2 == 0 else (W - reach, W)
            draw.line((x0, y, x1, y), fill=(*pill, 255), width=width)
        for c in range(cols + 1):
            x = left + c * col_w
            draw.line((x, top, x, top + (bottom - top) * rule), fill=(*pill, 255), width=width)
        for i, word in enumerate(words):
            r, c = i % rows, i // rows
            cell = (left + c * col_w, top + r * row_h, left + (c + 1) * col_w, top + (r + 1) * row_h)
            start = line['words'][i]['start'] - 0.32
            glide = smoother(clamp((t - start) / 0.42))
            if glide <= 0:
                continue
            direction = -1 if r % 2 else 1
            sung = i == k
            # the last sung word drains its cell and eases back to size as the next floods, never in one frame
            drain = 1 - smoother(clamp((t - since) / 0.25)) if i == k - 1 else 0.0
            mask = word_mask(word, WALL_FONT if sung or drain > 0.5 else STACK_FONT, 200)
            tall = row_h * (0.86 if sung else 0.8)
            natural = min(col_w * 0.9, mask.width * tall / mask.height)
            flood = smoother(clamp((t - since) / 0.3)) if sung else drain
            wide = min(
                col_w * 0.86, natural + (col_w * 0.86 - natural) * flood
            )  # the sung word stretches to fill its cell
            tall *= 1 - 0.08 * pulse(window(t, since, since + 0.3)) if sung else 1.0  # and squashes as it lands
            tile = mask.resize((max(1, round(wide)), max(1, round(tall))), Image.Resampling.BICUBIC)
            off = direction * (1 - glide) * col_w * 0.4 - leave * direction * W * 0.9
            if flood > 0:
                fx0 = cell[0] if direction > 0 else cell[2] - (cell[2] - cell[0]) * flood
                fx1 = cell[0] + (cell[2] - cell[0]) * flood if direction > 0 else cell[2]
                draw.rectangle((fx0 + off, cell[1] + width, fx1 + off, cell[3] - width), fill=(*accent, 255))
                kick = round(width * 1.2 * pulse(window(t, since, since + 0.42)))
                if kick > 0:
                    draw.rectangle(
                        (cell[0] + off - kick / 2, cell[1] - kick / 2, cell[2] + off + kick / 2, cell[3] + kick / 2),
                        outline=(*pill, 255),
                        width=kick,
                    )
            x = cell[0] + (col_w - tile.width) / 2 + off
            y = cell[1] + (row_h - tile.height) / 2
            paste(canvas, tint(tile, WHITE if i <= k else SECOND_INK), x, y)
            if flood > 0:  # inside the flooded part of the cell the word is knocked out dark
                dark = Image.new('RGBA', canvas.size)
                paste(dark, tint(tile, shade), x, y)
                clip = Image.new('L', canvas.size)
                ImageDraw.Draw(clip).rectangle((fx0 + off, cell[1], fx1 + off, cell[3]), fill=255)
                dark.putalpha(Image.fromarray(np.minimum(np.asarray(dark.getchannel('A')), np.asarray(clip))))
                canvas.alpha_composite(dark)
        # A building face in perspective: shear and a vertical skew so the grid reads as a tilted plane.
        canvas = canvas.transform(
            (W, H),
            Image.Transform.AFFINE,
            (
                1,
                -0.32 * self.setting(line, 'motion'),
                0.32 * H / 2 * self.setting(line, 'motion'),
                0.16 * self.setting(line, 'motion'),
                1,
                -0.16 * W / 2 * self.setting(line, 'motion'),
            ),
            Image.Resampling.BICUBIC,
        )
        screen.alpha_composite(canvas)
