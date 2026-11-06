"""The block drop: each sung word falls as a heavy block and lands beside the last, building the line on shelves."""

import math
import random

from PIL import Image

from effects.kinetic.easing import clamp, smoother
from render.poster.common import SECOND_INK, STACK_FONT, WALL_INK, WHITE, paste, tint, word_mask


class DropScene:
    def paint_drop(self, screen, line, t):
        """Each word of the line is a heavy block. As it is sung it falls from above the frame under gravity and
        lands beside the previous word with a squash; the block it lands next to gives with the hit. The words
        line up left to right on a shelf, and a full shelf starts a new one below, so the line reads in order;
        the camera eases down to each new shelf. The sung block is the accent, the rest alternate paper and grey,
        and at the line's end the blocks tip off their shelf one after another, left to right, pivoting on the shelf edge
        and dropping away."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() or '~' for w in line['words']]
        leave = clamp((t - (line['end'] - line.get('linger', 0.0) - 0.5)) / 0.5)  # the blocks tumble onto the floor
        if t >= line['end'] or (leave >= 0.999 and not line.get('linger')) or t < line['start']:
            return
        rng = random.Random(line['index'] * 7919 + len(words))
        tall = H * 0.24
        gap = tall * 0.08
        row_w = W * 0.9
        # layout: (mask, width, height, x, y, tilt) per block, left to right on shelves, top shelf first
        sized = []
        for word in words:
            mask = word_mask(word, STACK_FONT, 200)
            h = tall * (1.15 if len(word) <= 3 else 1.0)
            w = min(mask.width * h * 0.62 / mask.height + h * 0.5, row_w)
            sized.append((mask, w, h))
        rows, row = [], []
        for item in sized:
            if row and sum(r[1] for r in row) + gap * len(row) + item[1] > row_w:
                rows.append(row)
                row = []
            row.append(item)
        rows.append(row)
        blocks, shelf, y = [], [], 0.0
        for r, items in enumerate(rows):
            span = sum(it[1] for it in items) + gap * (len(items) - 1)
            x = (W - span) / 2
            base = y + max(it[2] for it in items)  # every block in a shelf sits on the same floor
            for mask, w, h in items:
                blocks.append((mask, w, h, x, base - h, rng.uniform(-3, 3)))
                shelf.append(r)
                x += w + gap
            y = base + tall * 0.18
        land = 0.2  # seconds for a block to fall onto its place

        # each block falls just before its word, so it lands on the word
        starts = [w['start'] for w in line['words']]
        # the first block lands on its word, knocking away the last line's pile (which lingers until then)
        flight = [0.4 if shelf[i] > 0 else land for i in range(len(blocks))]  # a lower shelf's block is lobbed in
        last = max((i for i in range(len(blocks)) if t >= starts[i] - flight[i]), default=-1)
        if last < 0:
            return

        # the camera fits the line built so far: tight on the first block, easing out as the line grows
        def framing(n):
            left = min(b[3] for b in blocks[: n + 1])
            right = max(b[3] + b[1] for b in blocks[: n + 1])
            top = min(b[4] for b in blocks[: n + 1])
            bottom = max(b[4] + b[2] for b in blocks[: n + 1])
            zoom = min(1.9, cap, W * 0.86 / (right - left), H * 0.8 / (bottom - top))
            return (left + right) / 2, (top + bottom) / 2, zoom

        cap = float('inf')
        cap = framing(len(blocks) - 1)[2] * 1.6  # never more than 1.6x the finished line's scale: no pumping
        # it frames the next block a beat before that block starts to fall, so the landing spot is in view
        ahead = 0.25
        coming = max((i for i in range(len(blocks)) if t >= starts[i] - flight[i] - ahead), default=0)
        move = smoother(clamp((t - (starts[coming] - flight[coming] - ahead)) / 0.4)) if coming > 0 else 1.0
        before, after = framing(max(0, coming - 1)), framing(coming)
        fx, fy = (a + (b - a) * move for a, b in zip(before[:2], after[:2]))
        zoom = math.exp(math.log(before[2]) + (math.log(after[2]) - math.log(before[2])) * move)  # even in scale
        cam = 0.0
        landed = max((i for i in range(last + 1) if t >= starts[i]), default=-1)
        impact = t - starts[landed] if landed >= 0 else -1.0
        give = 0.08 * math.exp(-max(0.0, impact) * 9) * math.sin(max(0.0, impact) * 30) if impact > 0 else 0.0
        if impact > 0:  # the whole frame dips with the hit
            cam = tall * 0.08 * zoom * math.exp(-impact * 10) * math.sin(min(math.pi, impact * 24))
        drawn = []
        for i in range(last + 1):
            mask, w, h, x, y0, tilt = blocks[i]
            if i > landed:  # falling under gravity
                fall = clamp((t - (starts[i] - flight[i])) / flight[i])
                if shelf[i] > 0:  # a lower shelf: lobbed in from the near side, tumbling, peaking just under the
                    # shelf above (outside its span), then dropping the last third into its slot: it never crosses a word
                    away = 1 if x + w / 2 > W / 2 else -1
                    x += away * W * 0.5 * (1 - smoother(min(1.0, fall / 0.67)))
                    if fall < 0.6:
                        y0 += h * 0.7 - h * 0.75 * (1 - (1 - fall / 0.6) ** 2)  # rising, slowing to its peak
                    else:
                        y0 -= h * 0.05 * (1 - ((fall - 0.6) / 0.4) ** 2)  # and falling into place
                    tilt += away * 32 * (1 - smoother(fall))
                else:
                    y0 = y0 - (1 - fall * fall) * h * 2.2  # from a couple of block heights above its place
                squash = 1.0
            elif i == landed:  # the squash on landing
                squash = 1 + 0.32 * math.exp(-impact * 10) * math.cos(impact * 26)
            elif shelf[i] == shelf[landed]:
                squash = 1 + give * 0.7 ** (landed - 1 - i)  # the jolt ripples along the shelf
            else:
                squash = 1.0
            bw, bh = w * squash**0.5 * zoom, h / squash * zoom
            order = i / max(1, len(blocks) - 1)  # left to right, one after another
            topple = clamp((leave - order * 0.4) / 0.6)  # tips over, then drops with gravity
            side = 1 if line['index'] % 2 else -1
            sx = W / 2 + (x + w / 2 - fx) * zoom  # world to screen, through the camera
            sy = H / 2 + (y0 + h - fy) * zoom + cam  # the block's foot
            xx = sx - bw / 2 + smoother(min(1.0, topple * 2)) * bw * 0.55 * side  # rolls over the shelf edge
            yy = sy - bh + max(0.0, topple - 0.3) ** 2 * H * 1.15  # then falls away
            plain = WHITE if i % 2 == 0 else SECOND_INK
            hot = WALL_INK if sum(accent) / 3 > 140 else WHITE
            if i == k or i > landed:
                fill, ink = accent, hot
            elif i == k - 1:  # the last sung block cools to paper over a few frames, not in one
                f = smoother(clamp((t - since) / 0.1))
                fill = tuple(round(a + (b - a) * f) for a, b in zip(accent, plain))
                ink = WALL_INK  # dark text from the first cooling frame, so it never goes grey on salmon
            else:
                fill, ink = plain, WALL_INK
            block = Image.new('RGBA', (max(1, round(bw)), max(1, round(bh))), (*fill, 255))
            word = mask.resize(
                (max(1, round(mask.width * bh * 0.62 / mask.height)), max(1, round(bh * 0.62))),
                Image.Resampling.BICUBIC,
            )
            if word.width > block.width * 0.92:
                word = word.resize((round(block.width * 0.92), word.height), Image.Resampling.BICUBIC)
            block.alpha_composite(tint(word, ink), ((block.width - word.width) // 2, (block.height - word.height) // 2))
            turn = tilt - smoother(min(1.0, topple * 1.6)) * 100 * side
            cx, cy = xx + bw / 2, yy + bh / 2
            if (
                topple > 0 or leave >= 1
            ):  # the toppled blocks pile on the frame's floor, then are knocked out as the next line lands
                cy = min(cy, H * 0.8 - max(bw, bh) * 0.2)  # a floor in the lower third, so the burst stays in view
                # the next line's first block lands on the pile and bursts it apart: the blocks it hits (the middle)
                # drive down spinning hardest, the outer ones are flung out to their side, each leaving in turn
                reach = (cx - W / 2) / (W / 2)
                away = 1 if reach >= 0 else -1
                knock = clamp((t - (line['end'] - 0.6) - abs(reach) * 0.08) / 0.5)
                cx += away * W * (0.2 + 0.55 * abs(reach)) * knock**1.3
                cy += -H * (0.12 + 0.3 * abs(reach)) * math.sin(math.pi * min(1.0, knock * 1.3)) + H * 0.95 * knock**2.2
                turn += away * (140 + 200 * (1 - abs(reach))) * knock
            shadow = Image.new('RGBA', block.size, (*shade, 255))
            if abs(turn) > 0.05:
                block = block.rotate(turn, Image.Resampling.BICUBIC, expand=True)
                shadow = shadow.rotate(turn, Image.Resampling.BICUBIC, expand=True)
            behind = False  # a falling block passes in front of the shelf above it
            drawn.append((0 if behind else 1, i, shadow, block, cx, cy, h * 0.07 * zoom))
        for _, _, shadow, block, cx, cy, off in sorted(drawn, key=lambda d: (d[0], d[1])):
            paste(screen, shadow, cx - shadow.width / 2 + off, cy - shadow.height / 2 + off)
            paste(screen, block, cx - block.width / 2, cy - block.height / 2)
