"""The word spiral: the line along a turning spiral, the sung word in its eye."""

import math
from PIL import Image
from core.fonts import truetype
from effects.kinetic.easing import clamp, keyframes, pulse, smoother, window
from render.poster.common import (
    CAPTION_FONT,
    ENTRY,
    FONTS,
    LEAVE,
    WALL_FONT,
    WHITE,
    paste,
    spiral_glyph,
    tint,
    word_mask,
)


class SpiralScene:
    def paint_spiral(self, screen, line, t):
        """The line, repeated, runs along an Archimedean spiral that fills the frame. The spiral turns slowly
        while its text streams in towards the centre; every copy of the sung word lights up in the accent, and
        the sung word is stamped large in the eye of the spiral. The spiral grows out from the centre when the
        line arrives and winds back into it when the line leaves."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() for w in line['words']]
        arrive = smoother(clamp((t - line['start']) / (ENTRY * 1.5)))
        leave = smoother(clamp((t - (line['end'] - LEAVE)) / LEAVE))
        if leave >= 0.999:
            return
        gap = H * (0.085, 0.1, 0.075)[line['index'] % 3]
        size = max(8, round(gap * 0.66))
        cx, cy = W / 2, H / 2
        r0 = gap * 3.9
        reach = r0 + gap * 4
        grow = r0 + (reach - r0) * arrive * (1 - leave)
        b = gap / (2 * math.pi)
        turn = ((t - line['start']) * 0.22 + leave * leave * 2.0) * (1 if line['index'] % 2 == 0 else -1)
        flow = (t - line['start']) * gap * 1.6  # text streams inward along the spiral
        unit = ' • '.join(words) + ' • '
        owner = []
        for i, word in enumerate(words):
            owner.extend([i] * len(word))
            owner.extend([-1] * 3)
        face = truetype(str(FONTS / CAPTION_FONT), size)
        widths = [face.getlength(c) for c in unit]
        period = sum(widths)
        # Walk the spiral by arc length from the centre outward; theta grows as ds / r.
        s = -(flow % period)
        theta = r0 / b
        index = 0
        while True:
            r = b * theta
            if r > grow:
                break
            char = unit[index % len(unit)]
            adv = widths[index % len(unit)]
            mid_theta = theta + adv / 2 / max(r, 1.0)
            if s >= 0 and char != ' ':
                angle = mid_theta + turn
                px = cx + math.cos(angle) * b * mid_theta
                py = cy + math.sin(angle) * b * mid_theta
                who = owner[index % len(unit)]
                tone = 1 - 0.6 * clamp(
                    (b * mid_theta - r0) / max(1.0, reach - r0)
                )  # outer rings recede so the eye leads
                color = tuple(round(c * 0.55) for c in accent) if who == k else tuple(round(c * tone) for c in WHITE)
                glyph = spiral_glyph(
                    char,
                    round(size * 1.3) if who == k else size,
                    round((-math.degrees(angle) - 90) % 360 / 4) * 4,
                    color,
                )
                paste(screen, glyph, px - glyph.width / 2, py - glyph.height / 2)
            s += adv
            theta += adv / max(r, 1.0)
            index += 1
        # The sung word, stamped in the eye of the spiral.
        word = words[k] or '~'
        mask = word_mask(word, WALL_FONT, 200)
        stamp = keyframes(clamp((t - since) / 0.2), [(0, 1.06), (0.5, 0.98), (1, 1.0)])
        drop = 0.0  # the word stamps in place, inside the ring
        squash = 0.22 * pulse(window(clamp((t - since) / 0.36), 0.4, 0.9))
        width = min(r0 * 1.55, mask.width * r0 * 1.0 / mask.height)
        tall = width * mask.height / mask.width
        appear = (1 - leave) * smoother(clamp((t - line['start']) / 0.2))
        if appear > 0.02:
            tile = mask.resize(
                (
                    max(1, round(width * stamp * appear * (1 + squash))),
                    max(1, round(tall * stamp * appear * (1 - squash))),
                ),
                Image.Resampling.BICUBIC,
            )
            paste(
                screen, tint(tile, shade), cx - tile.width / 2 + tall * 0.07, cy - tile.height / 2 + tall * 0.07 - drop
            )
            paste(screen, tint(tile, accent), cx - tile.width / 2, cy - tile.height / 2 - drop)
