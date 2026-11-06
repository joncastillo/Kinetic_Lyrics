"""The proportion stack: the line in rows, the sung row swelling."""

import math
from PIL import Image, ImageDraw
from effects.kinetic.easing import back_out, clamp, pulse, smoother, window
from render.poster.common import (
    LEAVE,
    SECOND_INK,
    STACK_FONT,
    WHITE,
    letter_edges,
    paste,
    tint,
    word_mask,
)


class StackScene:
    def stack_heights(self, line, t):
        """Each row's share of the block height: the sung row swells to about three times the others."""
        rows = line['rows']

        def weights(active):
            return [2.6 if k == active else 1.0 for k in range(len(rows))]

        active, since = self.active_row(line, t)
        previous = None
        for k, row in enumerate(rows):
            if row['words'][0]['start'] - 0.08 <= since - 1e-6:
                previous = k
        now = weights(active)
        if active is None:
            return [w / sum(now) for w in now]
        before = weights(previous if previous != active else None) if active > 0 else weights(None)
        if active > 0:
            before = weights(active - 1)
        f = back_out(smoother(window(t, since, since + 0.34)), 1.15)  # a calmer swap than the shared SWAP
        mixed = [a + (b - a) * f for a, b in zip(before, now)]
        total = sum(mixed)
        return [w / total for w in mixed]

    def paint_stack(self, screen, line, t):
        W, H = screen.size
        accent, shade, _ = line['palette']
        portrait = H > W
        block_w = W * (0.78 if portrait else 0.46)
        block_h = H * (0.62 if portrait else 0.74)
        left = (W - block_w) / 2 + (0 if portrait else line['side'] * W * 0.16)
        top = (H - block_h) / 2
        heights = self.stack_heights(line, t)
        gap = block_h * 0.018
        rows = line['rows']
        usable = block_h - gap * (len(rows) - 1)
        active, since = self.active_row(line, t)
        y = top
        depth = max(2.0, block_h * 0.012)
        for k, (row, share) in enumerate(zip(rows, heights)):
            h = usable * share
            # Rows unroll from alternate edges of the block on arrival and roll back up, bottom row first, on
            # leaving, so nothing ever slides off the frame or shrinks to a speck.
            arrive = smoother(clamp((t - line['start'] - 0.045 * k) / 0.26)) if k else 1.0
            leave = smoother(clamp((t - (line['end'] - LEAVE) - 0.035 * (len(rows) - 1 - k)) / 0.26))
            reach = max(0.0, arrive * (1 - leave))
            if reach <= 0.01 or h < 2:
                y += h + gap
                continue
            from_right = (k + (line['side'] > 0)) % 2 == 1
            mask = word_mask(row['text'], STACK_FONT).resize(
                (round(block_w), max(2, round(h))), Image.Resampling.BICUBIC
            )
            # Whole letters only: the reveal steps letter by letter and the bar covers the rest of the row.
            letters = len(row['text'])
            count = math.floor(clamp((reach - 0.1) / 0.9) * letters + 1e-6)
            edges = letter_edges(row['text'])
            whole = (1 - edges[letters - count] if from_right else edges[count]) if reach < 1 else 1.0
            shown = round(mask.width * whole)
            mask = (
                mask.crop((mask.width - max(1, shown), 0, mask.width, mask.height))
                if from_right
                else mask.crop((0, 0, max(1, shown), mask.height))
            )
            if shown == 0:
                mask = Image.new('L', mask.size)
            row_left = left + (block_w - shown if from_right else 0)
            sung = k == active
            pop = pulse(window(t, since + 0.16, since + 0.6)) if sung else 0.0
            if pop > 0.01 and reach >= 1:  # the newly sung row lands a touch wide, on a deeper extrusion
                mask = mask.resize(
                    (round(mask.width * (1 + 0.1 * pop)), max(2, round(mask.height * (1 - 0.4 * pop)))),
                    Image.Resampling.BICUBIC,
                )
                row_left -= (mask.width - shown) / 2
            # A solid bar in the line's colour leads each row in and out, so a half-drawn row reads as a wipe.
            if reach < 1:
                lead = max(0.0, block_w - shown) * min(1.0, reach * 8)
                bar_left = row_left - lead if from_right else row_left + shown
                ImageDraw.Draw(screen).rectangle((bar_left, y, bar_left + lead, y + mask.height), fill=(*accent, 255))
            # colours and depth ease over a quarter second as the sung row moves on, never switching in a frame:
            # the sung row warms to the accent, the row just sung cools to half, the one before to plain
            plain = WHITE if k % 2 == 0 else SECOND_INK
            half = tuple(round(a * 0.62 + b * 0.38) for a, b in zip(accent, WHITE))
            f = smoother(clamp((t - since) / 0.25)) if active is not None else 1.0

            def mix(a, b):
                return tuple(round(x + (z - x) * f) for x, z in zip(a, b))

            if sung:
                color, extra = mix(plain, accent), 1.2 * f + 2.0 * pop
            elif active is not None and k == active - 1:
                color, extra = mix(accent, half), 1.2 * (1 - f)
            elif active is not None and k == active - 2:
                color, extra = mix(half, plain), 0.0
            else:
                color, extra = plain, 0.0
            body = tint(mask, color)
            ext = tint(mask, shade)
            for d in range(int(depth * (1.0 + extra)), 0, -1):
                paste(screen, ext, row_left + d, y + d)
            paste(screen, body, row_left, y)
            y += h + gap
