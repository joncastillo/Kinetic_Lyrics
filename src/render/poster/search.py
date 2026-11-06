"""The word search: the line's words hidden in a grid of letters, each found with a marker as it is sung."""

import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw

from effects.kinetic.easing import clamp, smoother
from render.poster.common import LEAVE, WALL_INK, WHITE, drum_glyph, paste

DIRECTIONS = ((0, 1), (0, 1), (0, 1), (1, 0), (1, 1))  # mostly across, some down, some diagonal


@lru_cache(maxsize=32)
def search_grid(words, seed):
    """A letter grid with the line's words hidden in it (across, down or diagonal), the rest filled with the
    line's own letters; and where each word sits: (row, col, d_row, d_col, length), or None if it did not fit."""
    rng = random.Random(seed)
    clean = [''.join(c for c in w if c.isalpha()) or 'O' for w in words]
    cols = min(14, max(10, max(len(w) for w in clean) + 3))
    rows = 7
    grid = [[None] * cols for _ in range(rows)]
    spots = []
    for word in clean:
        placed = None
        for _ in range(300):
            dr, dc = rng.choice(DIRECTIONS)
            if len(word) > (cols if dr == 0 else min(rows, cols)):
                dr, dc = 0, 1
            r = rng.randrange(rows - (len(word) - 1) * dr)
            c = rng.randrange(cols - (len(word) - 1) * dc)
            cells = [(r + n * dr, c + n * dc) for n in range(len(word))]
            if all(grid[a][b] in (None, ch) for (a, b), ch in zip(cells, word)):
                for (a, b), ch in zip(cells, word):
                    grid[a][b] = ch
                placed = (r, c, dr, dc, len(word))
                break
        spots.append(placed)
    pool = ''.join(clean)
    filled = tuple(''.join(ch or rng.choice(pool) for ch in row) for row in grid)
    return filled, tuple(spots)


class SearchScene:
    def paint_search(self, screen, line, t):
        """A word-search puzzle made of the line: a grid of letters with the line's words hidden across, down and
        diagonally. The letters drop in when the line arrives; as each word is sung a marker sweeps along its
        letters in the accent and the camera leans in on it; words already found keep a dark capsule. At the
        line's end the grid drops away."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = tuple(w['text'].strip().upper() or '~' for w in line['words'])
        arrive = clamp((t - line['start']) / 0.6)
        leave = clamp((t - (line['end'] - LEAVE)) / LEAVE)
        if leave >= 0.999 or arrive <= 0:
            return
        grid, spots = search_grid(words, line['index'] * 7919 + len(words))
        rows, cols = len(grid), len(grid[0])
        cell = min(W * 0.8 / cols, H * 0.66 / rows)  # room for the lean-in zoom
        left, top = W / 2 - cell * cols / 2, H / 2 - cell * rows / 2
        layer = Image.new('RGBA', (W, H))
        draw = ImageDraw.Draw(layer)

        def centre(r, c):
            return left + (c + 0.5) * cell, top + (r + 0.5) * cell

        def capsule(spot, color, reach=1.0, width=0.78):
            r, c, dr, dc, n = spot
            x0, y0 = centre(r, c)
            x1, y1 = centre(r + (n - 1) * dr, c + (n - 1) * dc)
            x1, y1 = x0 + (x1 - x0) * reach, y0 + (y1 - y0) * reach
            w = cell * width
            draw.line((x0, y0, x1, y1), fill=(*color, 255), width=round(w))
            for x, y in ((x0, y0), (x1, y1)):
                draw.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=(*color, 255))

        def hero(i, at):
            """How far word i's hero beat (swell and push-in) has come at time `at`."""
            start = line['words'][i]['start'] - 0.06
            return smoother(clamp((at - start - 0.1) / 0.42))  # a slow, even push-in

        rise = hero(k, t)
        relax = hero(k - 1, since) * (1 - smoother(clamp((t - since) / 0.42))) if k else 0.0
        found = set()
        for i, spot in enumerate(spots):
            if spot is None or i > k:
                continue
            r, c, dr, dc, n = spot
            if i < k:
                capsule(spot, shade)
            else:
                sweep = smoother(
                    clamp((t - since) * self.setting(line, 'marker_speed') / 0.45)
                )  # the marker glides along the word
                if sweep > 0.02:
                    capsule(spot, accent, sweep)
            found.update((r + m * dr, c + m * dc, i) for m in range(n))
        lit = {(r, c): i for r, c, i in found}
        size = max(8, round(cell * 0.6))
        for r in range(rows):
            for c in range(cols):
                delay = (r * 0.6 + c * 0.4) / (rows + cols) * 0.5
                drop = 1 - smoother(clamp((arrive - delay) / 0.45))  # letters settle in, no bounce
                fall = smoother(clamp((leave - delay * 0.6) / 0.5))
                if arrive < delay or fall >= 0.999:
                    continue
                i = lit.get((r, c))
                current = i == k
                color = WALL_INK if current and sum(accent) / 3 > 140 else WHITE if i is not None else (132, 142, 172)
                grow = 1.0
                if current:
                    r0, c0, dr, dc, n = spots[k]
                    order = max(abs(r - r0), abs(c - c0))
                    grow = (1 + 0.18 * math.sin(math.pi * smoother(clamp((t - since - order * 0.04) / 0.4)))) * (
                        1 + 0.45 * rise
                    )
                glyph = drum_glyph(grid[r][c], max(6, round(size * grow)), color)
                x, y = centre(r, c)
                paste(layer, glyph, x - glyph.width / 2, y - glyph.height / 2 - drop * cell * 1.5 + fall * H * 0.6)

        # The camera leans in on the word being found.
        def focus(i):
            spot = spots[i] if 0 <= i < len(spots) else None
            if spot is None:
                return W / 2, H / 2
            r, c, dr, dc, n = spot
            (x0, y0), (x1, y1) = centre(r, c), centre(r + (n - 1) * dr, c + (n - 1) * dc)
            return (x0 + x1) / 2, (y0 + y1) / 2

        move = smoother(clamp((t - since) / 0.5))  # the camera glides on as the last push-in relaxes
        (ax, ay), (bx, by) = focus(k - 1) if k else (W / 2, H / 2), focus(k)
        fx, fy = ax + (bx - ax) * move, ay + (by - ay) * move

        def close(i):
            """The zoom that makes word i fill about half the frame width."""
            spot = spots[i] if 0 <= i < len(spots) else None
            if spot is None:
                return 1.0
            span = spot[4] * cell * (1.41 if spot[2] and spot[3] else 1.0)
            return min(2.0, max(1.0, W * 0.45 / span))

        base = 1 + 0.1 * smoother(arrive)
        # zoom blends in log space, so pushing in and out feel equally even
        zoom = (
            base
            * math.exp(math.log(close(k)) * rise + (math.log(close(k - 1)) * relax if k else 0.0))
            * (1 - 0.1 * smoother(leave))
        )
        if zoom > 1.002:
            lean = 0.35 + 0.65 * min(
                1.0, max(rise, relax) * 1.8
            )  # lean while the grid settles, follow the found word on its hero beat
            fx, fy = W / 2 + (fx - W / 2) * lean, H / 2 + (fy - H / 2) * lean
            box = (fx - W / 2 / zoom, fy - H / 2 / zoom, fx + W / 2 / zoom, fy + H / 2 / zoom)
            layer = layer.transform((W, H), Image.Transform.EXTENT, box, Image.Resampling.BICUBIC)
        screen.alpha_composite(layer)
