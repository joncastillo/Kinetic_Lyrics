"""The stamp collage: each sung word is rubber-stamped onto the frame, and the stamps build up a collage."""

import math
import random
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from effects.kinetic.easing import clamp, keyframes, smoother
from render.poster.common import LEAVE, WALL_FONT, WHITE, paste, tint, word_mask


@lru_cache(maxsize=128)
def stamp_mask(text, seed, wear=1.0):
    """`text` as a rubber stamp: the word inside a double-ruled border, with the speckled gaps of real ink."""
    word = word_mask(text, WALL_FONT, 160)
    pad = round(word.height * 0.45)
    mask = Image.new('L', (word.width + pad * 2, word.height + pad * 2))
    mask.paste(word, (pad, pad))
    draw = ImageDraw.Draw(mask)
    rule = max(3, round(word.height * 0.07))
    draw.rounded_rectangle(
        (rule, rule, mask.width - rule, mask.height - rule), radius=pad * 0.6, outline=255, width=rule
    )
    inner = rule * 3
    draw.rounded_rectangle(
        (inner, inner, mask.width - inner, mask.height - inner), radius=pad * 0.4, outline=255, width=max(1, rule // 2)
    )
    rng = np.random.default_rng(seed)
    speckle = rng.random((mask.height // 3 + 1, mask.width // 3 + 1)) > 0.12 * wear  # gaps where the ink did not take
    speckle = np.repeat(np.repeat(speckle, 3, 0), 3, 1)[: mask.height, : mask.width]
    return Image.fromarray((np.asarray(mask) * speckle).astype('uint8'), 'L')


@lru_cache(maxsize=32)
def stamp_spots(words, seed, width, height):
    """Where each word's stamp lands, in order: near its place on an inward spiral (so the collage builds toward
    the centre), but nudged to wherever it covers least of the stamps already down. They overlap border to
    border, not lettering to lettering, and stay inside the frame. With a tilt for each."""
    rng = random.Random(seed)
    count = len(words)
    placed = []  # (left, top, right, bottom) of the lettering of each settled stamp
    spots = []
    for i, word in enumerate(words):
        mask = stamp_mask(word, seed * 31 + i)
        size = min(width * 0.42 / mask.width, height * 0.3 / mask.height)
        w, h = mask.width * size, mask.height * size
        reach = 0.3 + 0.7 * (1 - (i + 1) / count) ** 0.8
        angle = i * 2.4 + rng.uniform(-0.3, 0.3)
        want = (
            width / 2 + math.cos(angle) * width * 0.34 * reach,
            height / 2 + math.sin(angle) * height * 0.32 * reach,
        )
        best, score = want, None
        for gx in range(9):
            for gy in range(7):
                x = width * (0.05 + 0.9 * gx / 8)
                y = height * (0.05 + 0.9 * gy / 6)
                x = min(max(x, width * 0.05 + w * 0.76), width * 0.95 - w * 0.76)
                y = min(max(y, height * 0.05 + h * 0.95), height * 0.95 - h * 0.95)
                # the lettering is the middle of the stamp, inside its border
                box = (x - w * 0.36, y - h * 0.22, x + w * 0.36, y + h * 0.22)
                cover = sum(
                    max(0.0, min(box[2], b[2]) - max(box[0], b[0])) * max(0.0, min(box[3], b[3]) - max(box[1], b[1]))
                    for b in placed
                )
                cost = cover / (w * h * 0.32) * 4 + ((x - want[0]) ** 2 + (y - want[1]) ** 2) ** 0.5 / width
                if score is None or cost < score:
                    best, score = (x, y), cost
        x, y = best
        settled = 0.7  # an older stamp settles to 70%
        placed.append((x - w * 0.36 * settled, y - h * 0.22 * settled, x + w * 0.36 * settled, y + h * 0.22 * settled))
        spots.append((x, y, rng.uniform(-10, 10)))
    return tuple(spots)


class StampScene:
    def paint_stamp(self, screen, line, t):
        """A rubber-stamp collage. As each word is sung it is stamped big onto the frame in a ruled border: it comes
        down lifted on a shadow, hits with a squash and a ring of ink splatter, and settles at a tilt in the accent.
        The stamps land on an inward spiral, overlapping, so the line builds into a collage toward the centre with
        the newest on top; earlier stamps keep paler tints of the accent. At the end they are swept away in turn."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() or '~' for w in line['words']]
        leave = clamp((t - (line['end'] - LEAVE)) / LEAVE)
        if leave >= 0.999 or t < line['start'] + 0.1:
            return
        spots = stamp_spots(tuple(words), line['index'], W, H)
        draw = ImageDraw.Draw(screen)
        for i in range(k + 1):
            start = since if i == k else line['words'][i]['start'] - 0.06
            age = t - start
            x, y, tilt = spots[i]
            tilt *= self.setting(line, 'imperfection')
            mask = stamp_mask(words[i], line['index'] * 31 + i, self.setting(line, 'imperfection'))
            size = min(W * 0.42 / mask.width, H * 0.3 / mask.height) * self.setting(
                line, 'size'
            )  # the newest stamp is big whatever the word
            press = keyframes(clamp(age / 0.32), [(0, 1.4), (0.35, 0.9), (0.55, 1.04), (1, 1.0)])  # down, hit, settle
            squash = 1 + 0.12 * (1 - abs(clamp(age / 0.32) - 0.38) / 0.2) if 0.18 < clamp(age / 0.32) < 0.58 else 1.0
            lift = (1 - smoother(clamp(age / 0.11))) * H * 0.04  # lifted on its shadow until it hits
            spread = 0.0 if age > 0.25 else (1 - abs(age - 0.12) / 0.13) if age > 0 else 0.0  # ink spreads on impact
            sweep = smoother(clamp((leave * 1.5 - i * 0.12) / 0.5))
            if sweep >= 0.999:
                continue
            if i < k:  # older stamps settle a little smaller once the next word is stamped over them
                size *= 1 - 0.3 * smoother(clamp((t - (line['words'][i + 1]['start'] - 0.06)) / 0.3))
            reach_x = mask.width * size * 1.45 / 2 * 1.05  # its widest, mid-fall, with the tilt
            reach_y = mask.height * size * 1.45 / 2 * 1.3
            x = min(max(x, W * 0.05 + reach_x), W * 0.95 - reach_x)  # always fully inside the frame
            y = min(max(y, H * 0.05 + reach_y), H * 0.95 - reach_y)
            w = max(1, round(mask.width * size * press * squash))
            h = max(1, round(mask.height * size * press / squash))
            body = mask.resize((w, h), Image.Resampling.BICUBIC)
            if spread > 0.05:
                body = body.filter(ImageFilter.MaxFilter(3 if spread < 0.6 else 5))
            body = body.rotate(tilt, Image.Resampling.BICUBIC, expand=True)
            fresh = i == k
            if fresh:
                pale = 0.0
            else:  # older stamps fade to paler tints of the accent, easing as each new word is stamped over them
                pale = sum(
                    (0.35 if n == i + 1 else 0.12) * smoother(clamp((t - (line['words'][n]['start'] - 0.06)) / 0.3))
                    for n in range(i + 1, min(k, i + 4) + 1)
                )
            ink = tuple(round(c * (1 - pale) + w_ * pale) for c, w_ in zip(accent, WHITE))
            dx = -sweep * W * 0.9 * (1 if i % 2 else -1)
            come = smoother(clamp(age / 0.07))  # it comes down out of the air over a couple of frames, not in one
            if lift > 0.5:
                paste(
                    screen,
                    tint(body, shade, 0.45 * come),
                    x - body.width / 2 + lift * 0.6 + dx,
                    y - body.height / 2 + lift,
                )
            paste(screen, tint(body, ink, come), x - body.width / 2 + dx, y - body.height / 2 - lift * 0.4)
            burst = clamp((age - 0.1) / 0.3)
            if fresh and 0 < burst < 1:  # a ring of ink splatter thrown out on impact
                rng = random.Random(line['index'] * 101 + i)
                for n in range(16):
                    a = n / 16 * 2 * math.pi + rng.uniform(-0.2, 0.2)
                    reach = (0.55 + 0.25 * rng.random() + 0.35 * smoother(burst)) * body.width / 2
                    dot = H * (0.006 + 0.01 * rng.random()) * (1 - burst)
                    px, py = x + dx + math.cos(a) * reach, y + math.sin(a) * reach * body.height / body.width * 1.6
                    if dot > 0.5:
                        draw.ellipse((px - dot, py - dot, px + dot, py + dot), fill=(*accent, 255))
