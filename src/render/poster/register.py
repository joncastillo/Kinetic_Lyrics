"""Misregistration: the line printed as three offset colour plates; each sung word's plates slide into register."""

import math

import numpy as np
from PIL import Image, ImageChops

from effects.kinetic.easing import back_out, clamp, pulse, smoother, window
from render.poster.common import paste, tint
from render.poster.halftone import halftone_layout

PLATES = ((255, 40, 96), (40, 220, 150), (70, 110, 255))  # three inks that add up to near white in register
RISO = ((255, 72, 176), (0, 169, 165), (255, 226, 0))  # fluoro pink, teal and yellow: real overprinting inks


def overprint(mask, offsets):
    """The word printed once per riso ink at `offsets`, multiplied where the plates overlap (pink over yellow
    makes red, teal over yellow green, all three a dark ink), opaque. Returns the image and its top-left."""
    m = np.asarray(mask, np.float32) / 255
    xs = [round(dx) for dx, _ in offsets]
    ys = [round(dy) for _, dy in offsets]
    left, top = min(xs), min(ys)
    w, h = mask.width + max(xs) - left, mask.height + max(ys) - top
    color = np.ones((h, w, 3), np.float32)
    alpha = np.zeros((h, w), np.float32)
    for (x, y), ink in zip(zip(xs, ys), RISO):
        cover = np.zeros((h, w), np.float32)
        cover[y - top : y - top + mask.height, x - left : x - left + mask.width] = m
        color *= 1 - cover[..., None] * (1 - np.array(ink, np.float32) / 255)
        alpha = np.maximum(alpha, cover)
    deep = np.array((58, 44, 196), np.float32) / 255  # ultramarine: where inks pile up dark, it stays visible
    dark = (color.mean(axis=-1, keepdims=True) < deep.mean()).astype(np.float32)
    color = color * (1 - dark) + deep * dark
    out = np.dstack([color * 255, alpha * 255]).clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, 'RGBA'), left, top


class RegisterScene:
    def paint_register(self, screen, line, t):
        """The line set big, printed as three colour plates that have slipped out of register, each word's plates
        drifting a little apart. As each word is sung its plates slide together into perfect register and it
        locks as crisp type in the accent; sung words stay in register, the rest of the line wanders. The
        plates fly in from far apart when the line arrives and scatter when it leaves."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = tuple(w['text'].strip().upper() or '~' for w in line['words'])
        leave = clamp((t - (line['end'] - 0.45)) / 0.45)  # a longer exit: the words drop out right up to the end
        if leave >= 0.999 or t < line['start']:
            return
        layout, pitch = halftone_layout(words, W, H, line['index'] % 3)
        if len(layout) != len(words):
            return
        ink = Image.new('RGB', (W, H))
        crisp = []
        printed = []
        rest = max(2.0, H * 0.003) * self.setting(
            line, 'imperfection'
        )  # at rest a hairline misregistration, like a real print run
        opens = line['start']  # gathers as the last line's final words drop away
        settled = opens + len(words) * 0.04 + 0.12
        split_at = max(since, settled) if k == 0 else since  # the first word splits once its line has settled
        # the enlarged sung word (and the last one, easing back) pushes its row-mates aside, keeping word spaces
        locked = back_out(clamp((t - split_at - 0.13) / 0.17), 1.6)
        grown = [(k, 0.11 * smoother(clamp((min(1.0, locked) - 0.85) / 0.15)))]
        if k > 0 and t - since < 0.2:
            grown.append((k - 1, 0.11 * (1 - smoother(clamp((t - since) / 0.2)))))
        shift = [0.0] * len(layout)
        for j, extra in grown:
            jx, jy = layout[j][3]
            half = layout[j][4].width * extra / 2
            for i, entry in enumerate(layout):
                ix, iy = entry[3]
                if i != j and abs(iy - jy) < 2:
                    shift[i] += half if ix > jx else -half
        for i, (*_, mask, (x0, y0)) in enumerate(layout):
            x0 += shift[i]
            mh = mask.height
            arrive = smoother(
                clamp((t - opens - i * 0.04) / 0.12)
            )  # lands with a hairline offset, settled in 3-4 frames  # word by word, gathering into place
            lock = 0.0
            if i == k:  # the sung word's plates split wide, hold a beat, then snap together into register
                pull = smoother(clamp((t - split_at) / 0.08))
                lock = back_out(clamp((t - split_at - 0.13) / 0.17), 1.6)
                drift = mh * 0.36 * pull * (1 - lock) + rest * (1 - pull)
            elif i < k:
                drift = 0.0  # sung words stay in register: clean near-white type
            else:
                drift = rest
            drift += mh * 0.06 * (1 - arrive)
            # opaque from its first frames (no soft ghosts): it arrives as plates sliding into near-register
            level = (1.0 if i <= k else 0.62) * (1.0 if t >= opens + i * 0.04 else 0.0)
            if i == k and lock > 0.85 and leave <= 0:  # the bigger accent covers it: no white showing through
                level *= 1 - smoother(clamp((min(1.0, lock) - 0.85) / 0.15))
            elif i == k - 1 and t - since < 0.2 and leave <= 0:
                level *= smoother(clamp((t - since) / 0.2))
            if i == k and 0 <= t - split_at < 0.4 and drift > 1.5:  # the split: three riso inks, three clear ways
                offsets = [
                    (math.cos(a + i * 0.4) * drift * s, math.sin(a + i * 0.4) * drift * s)
                    for a, s in ((-2.3, 1.0), (0.4, 1.0), (2.3, 0.12))
                ]
                printed.append((*overprint(mask, offsets), x0, y0, level))
            else:
                for p, color in enumerate(PLATES):  # the two loose plates wander on their own slow circles
                    a = p * 2.1 + i * 1.3 + t * 0.9
                    dx, dy = (0.0, 0.0) if p == 0 else (math.cos(a) * drift, math.sin(a) * drift * 0.7)
                    if leave > 0:  # the exit, last word first: each word drops out of the frame
                        go = clamp((leave - (len(words) - 1 - i) * 0.06) / 0.55) ** 1.5
                        dx += (-1, 1, 0)[p] * mh * 0.25 * go + (
                            1 if i % 2 else -1
                        ) * W * 0.12 * go  # a slight split and shear
                        dy += H * 1.1 * go * go + (0, mh * 0.12, mh * 0.24)[p] * go  # dropping out, plates together
                    plate = Image.new('RGB', mask.size, tuple(round(c * level) for c in color))
                    layer = Image.new('RGB', (W, H))
                    layer.paste(plate, (round(x0 + dx), round(y0 + dy)), mask)
                    ink = ImageChops.add(ink, layer)
            if i == k and lock > 0.85:  # locked, the sung word holds a little bigger than the line
                on = smoother(clamp((min(1.0, lock) - 0.85) / 0.15))
                crisp.append((mask, x0, y0, on, 1 + 0.11 * on))
            elif i == k - 1 and t - since < 0.2:  # the last word eases back to size and to white in 6 frames
                off = smoother(clamp((t - since) / 0.2))
                crisp.append((mask, x0, y0, 1 - off, 1 + 0.11 * (1 - off)))
        screen.paste(ImageChops.screen(screen.convert('RGB'), ink).convert('RGBA'), (0, 0))
        for image, left, top, x0, y0, level in printed:  # the split word, opaque riso inks on top
            if level < 0.999:  # still arriving: the same inks, less opaque
                image = image.copy()
                image.putalpha(image.getchannel('A').point(lambda v: round(v * level)))
            paste(screen, image, x0 + left, y0 + top)
        pop = 1 + 0.06 * pulse(window(t, split_at + 0.26, split_at + 0.38))  # a hard pop as it locks
        for mask, x0, y0, alpha, size in crisp:  # registered, the word locks as crisp type in the accent
            a = alpha * (1 - clamp(leave / 0.15))  # the accent clears in two frames as its plates fly
            scale = size * (pop if size > 1.05 and alpha > 0.5 and t - since < 0.6 else 1.0)
            if scale > 1.002:
                big = mask.resize((round(mask.width * scale), round(mask.height * scale)), Image.Resampling.BICUBIC)
                x0, y0 = x0 - (big.width - mask.width) / 2, y0 - (big.height - mask.height) / 2
                mask = big
            paste(screen, tint(mask, shade, a), x0 + pitch * 0.2, y0 + pitch * 0.2)
            paste(screen, tint(mask, accent, a), x0, y0)
