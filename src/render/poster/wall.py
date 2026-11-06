"""The word wall: marquee rows on flat colour fields."""

import math
from PIL import Image, ImageDraw
from effects.kinetic.easing import clamp, pulse, smoother, window
from render.poster.common import (
    ENTRY,
    FIELDS,
    FLIP,
    LEAVE,
    STACK_FONT,
    WALL_FONT,
    WALL_INK,
    WHITE,
    paste,
    tint,
    word_mask,
)


class WallScene:
    def paint_wall(self, screen, line, t):
        """A band of marquee rows on flat colour fields, one field colour per sung word. Rows alternate a
        condensed and a wide face, and solid dark type with white outline type; the middle row carries the word
        in white on a hard shadow. On each new word the rows flip over one after another like a split-flap
        board, showing the next word on the next colour."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper().strip('.,!?;:"') or '~' for w in line['words']]
        rows = 5
        shift = H * (0.08 if line['index'] % 2 else -0.06)  # the band moves up or down from line to line
        band_top, band_bottom = H * 0.26 + shift, H * 0.68 + shift
        row_h = (band_bottom - band_top) / rows
        middle = rows // 2
        arrive = clamp((t - line['start']) / ENTRY)
        leave = clamp((t - (line['end'] - LEAVE)) / LEAVE)
        lock = None

        def y_of(r):
            return band_top + r * row_h

        for r in range(rows):
            start = since + 0.03 * abs(r - middle)
            flip = clamp((t - start) / FLIP) if k > 0 else 1.0
            shown = k if flip >= 0.5 else k - 1
            fold = 0.35 + 0.65 * abs(math.cos(math.pi * flip)) if flip < 1 else 1.0
            opened = smoother(clamp((t - line['start'] - 0.04 * abs(r - middle)) / FLIP))
            closed = 1 - smoother(clamp((t - (line['end'] - LEAVE) - 0.04 * (middle - abs(r - middle))) / FLIP))
            fold *= opened * closed
            height = round(row_h * fold)
            if height < 2:
                continue
            field = FIELDS[(line['index'] * 3 + shown) % len(FIELDS)]
            strip = Image.new('RGBA', (W, round(row_h)), (*field, 255))
            turning = fold < 0.999
            if r == middle:
                lock = (field, words[shown], y_of(r), turning)
            face = WALL_FONT
            outline = r % 2 == 1
            mask = word_mask(words[shown], STACK_FONT if outline else face, 160)
            size = row_h * 0.78 / mask.height
            tile = mask.resize(
                (max(1, round(mask.width * size)), max(1, round(row_h * 0.78))), Image.Resampling.BICUBIC
            )
            spacing = tile.width + row_h * 0.5
            speed = (1 if r % 2 else -1) * W * 0.07 * (1 + 0.3 * (r % 3))
            phase = (t * speed + line['seed'] * spacing + r * spacing * 0.37) % spacing
            if r == middle:  # the sung word locks dead centre while the rows around it run
                phase = ((W - tile.width) / 2) % spacing
            ink = WHITE if r == middle else WALL_INK
            image = tint(tile, ink)
            shadow = tint(tile, WALL_INK) if r == middle else None
            xx = -spacing + phase
            top = (row_h - tile.height) / 2
            if r == middle:  # one instance, centred, with clear field either side
                xx, spacing = (W - tile.width) / 2, W * 2
            while xx < W and not turning and r != middle:
                if shadow is not None:
                    paste(strip, shadow, xx + row_h * 0.05, top + row_h * 0.05)
                paste(strip, image, xx, top)
                xx += spacing
            if height != strip.height:
                strip = strip.resize((W, height), Image.Resampling.BICUBIC)
            y = band_top + r * row_h + (row_h - height) / 2
            paste(screen, strip, 0, y)
            edge = round(row_h * 0.4 * (1 - fold)) if fold < 1 else 0
            if edge > 0:  # the row's thick edge shows as it turns, a shade darker than its field
                shade_field = tuple(round(c * 0.62) for c in field)
                ImageDraw.Draw(screen).rectangle((0, y + height, W, y + height + edge), fill=(*shade_field, 255))
        if lock is not None:  # the sung word, big and heavy, breaking out of its row (shown at once)
            field, word, y0, _ = lock
            mask = word_mask(word, WALL_FONT, 200)
            squash = 0.26 * pulse(window(t, since, since + 0.5))
            tall = row_h * 1.3 * (1 + 0.12 * pulse(window(t, since + FLIP, since + FLIP + 0.16))) * (1 - squash)
            tile = mask.resize(
                (max(1, round(mask.width * tall / mask.height * (1 + squash * 1.6))), max(1, round(tall))),
                Image.Resampling.BICUBIC,
            )
            if tile.width > W * 0.92:
                tile = tile.resize(
                    (round(W * 0.92), round(tile.height * W * 0.92 / tile.width)), Image.Resampling.BICUBIC
                )
            cx, cy = (W - tile.width) / 2 + W * (0.08, -0.06, 0.04)[line['index'] % 3], y0 + (row_h - tile.height) / 2
            clear = row_h * 1.3 * 1.4  # flat field behind the lock word, so no outline row runs through it
            ImageDraw.Draw(screen).rectangle(
                (0, y0 + row_h / 2 - clear / 2, W, y0 + row_h / 2 + clear / 2), fill=(*field, 255)
            )
            paste(screen, tint(tile, WALL_INK), cx + row_h * 0.08, cy + row_h * 0.08)
            paste(screen, tint(tile, WHITE), cx, cy)
        self.paint_caption(screen, line, t, pill, shade, arrive, leave)
