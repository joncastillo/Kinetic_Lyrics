"""The type drum: the line around a turning drum that brings each sung word to the front."""

import math
from PIL import Image
from core.fonts import truetype
from effects.kinetic.easing import back_out, clamp, keyframes, smoother
from render.poster.common import (
    CAPTION_FONT,
    ENTRY,
    FONTS,
    LEAVE,
    SECOND_INK,
    WHITE,
    drum_glyph,
    paste,
    tint,
    word_mask,
)


class DrumScene:
    def paint_drum(self, screen, line, t):
        """The line wraps around a tall drum turning about its vertical axis, in rows that turn at different
        speeds; letters squeeze and darken as they turn away. The middle row turns to bring each sung word to
        the front, where it is set larger in the accent. The drum swings in at the line's start and spins away
        at its end."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() for w in line['words']]
        arrive = smoother(clamp((t - line['start']) / ENTRY))
        leave = smoother(clamp((t - (line['end'] - LEAVE)) / LEAVE))
        if leave >= 0.999 or arrive <= 0.001:
            return
        rows = 3
        middle = rows // 2
        row_h = H * 0.19
        size = round(row_h * 0.72)
        radius = W * (0.3 + 0.08 * (max(len(w) for w in words) > 5)) * (1 - leave * 0.6)
        cx = W / 2
        top = H * 0.47 - row_h * rows / 2
        unit = ' • '.join(words) + ' • '
        owner = []
        for i, word in enumerate(words):
            owner.extend([i] * len(word))
            owner.extend([-1] * 3)
        face = truetype(str(FONTS / CAPTION_FONT), size)
        widths = [face.getlength(c) for c in unit]
        period = sum(widths)
        circumference = 2 * math.pi * max(radius, 1.0)
        repeats = max(1, math.floor(circumference / period))
        scale = circumference / (period * repeats)  # the text closes exactly around the drum
        # Where the sung word sits along the unit (its centre, as an angle on the middle row)
        start = sum(widths[: sum(len(w) + 3 for w in words[:k])])
        centre = (start + face.getlength(words[k]) / 2) * scale / max(radius, 1.0)
        settle = back_out(smoother(clamp((t - since) / 0.45)), 1.1)
        previous = (
            (sum(widths[: sum(len(w) + 3 for w in words[: max(0, k - 1)])]) + face.getlength(words[max(0, k - 1)]) / 2)
            * scale
            / max(radius, 1.0)
        )
        spin_middle = -(previous + (centre - previous) * settle) - leave * 3.0
        for r in range(rows):
            y = top + r * row_h + row_h / 2
            if r == middle:
                spin = spin_middle
            else:
                spin = (t - line['start']) * (0.5 if r % 2 else -0.42) * (1 + 0.2 * abs(r - middle)) + r * 1.3
            distance = 0.0
            for n in range(len(unit) * repeats):
                char = unit[n % len(unit)]
                adv = widths[n % len(unit)] * scale
                angle = (distance + adv / 2) / max(radius, 1.0) + spin
                distance += adv
                depth = math.cos(angle)
                if char == ' ' or depth <= 0.55:
                    continue
                who = owner[n % len(unit)]
                sung = r == middle and who == k
                if sung:
                    continue  # drawn flat at the front below
                color = (
                    accent
                    if sung
                    else tuple(
                        round(c * (0.1 + 0.9 * depth**2) * clamp((depth - 0.55) / 0.2))  # fades out as it turns away
                        for c in (WHITE if r == middle else SECOND_INK)
                    )
                )
                glyph = drum_glyph(char, round(size * (1.5 if sung else 1.0)), color)
                squeezed = max(1, round(glyph.width * max(0.7, depth)))
                if squeezed < 2:
                    continue
                edge = clamp((depth - 0.55) / 0.45)
                g = glyph.resize(
                    (squeezed, max(1, round(glyph.height * (0.6 + 0.4 * edge)))), Image.Resampling.BILINEAR
                )
                bow = (1 - edge) * row_h * 0.18 * (r - middle if r != middle else 0)  # outer rows curve away
                paste(screen, g, cx + math.sin(angle) * radius - g.width / 2, y - g.height / 2 + bow)
            if r == middle:  # the sung word, flat and big at the front of the drum; the last one cross-fades out
                swap = smoother(clamp((t - since) / 0.14)) if k > 0 else 1.0
                shown = [(k - 1, 1 - swap, 1.0), (k, swap, None)] if swap < 1 else [(k, 1.0, None)]
                for n, alpha, grown in shown:
                    if alpha <= 0.01:
                        continue
                    mask = word_mask(words[n] or '~', CAPTION_FONT, 200)
                    grow = grown or keyframes(
                        clamp((t - since) / 0.32), [(0, 0.78), (0.45, 1.08), (0.75, 0.98), (1, 1.0)]
                    )
                    tall = size * 1.6 * grow
                    tile = mask.resize(
                        (max(1, round(mask.width * tall / mask.height)), max(1, round(tall))), Image.Resampling.BICUBIC
                    )
                    plate = Image.new(
                        'RGBA',
                        (tile.width + round(size * 0.6), tile.height + round(size * 0.4)),
                        (*shade, round(255 * alpha)),
                    )
                    paste(screen, plate, cx - plate.width / 2, y - plate.height / 2)
                    paste(screen, tint(tile, accent, alpha), cx - tile.width / 2, y - tile.height / 2)
