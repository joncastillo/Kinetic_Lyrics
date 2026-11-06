"""The type ribbon: the line along a rippling paper ribbon that twists to show its printed back."""

import math
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw

from core.fonts import truetype
from effects.kinetic.easing import back_out, clamp, pulse, smoother
from render.poster.common import CAPTION_FONT, FONTS, LEAVE, WALL_INK, WHITE, paste, tint


@lru_cache(maxsize=64)
def ribbon_texture(words, k, band, width, accent, shade):
    """The ribbon's printed front and its darker back, the line repeated along it with the sung word on an accent
    block; and where each word's centre sits along one repeat."""
    face = truetype(str(FONTS / CAPTION_FONT), max(8, round(band * 0.5)))
    unit = ' \u2022 '.join(words) + ' \u2022 '
    period = max(8, round(face.getlength(unit)))
    stripe = max(2, round(band * 0.09))
    front = Image.new('RGBA', (period, band), (*WHITE, 255))
    back = Image.new('RGBA', (period, band), (*tuple(round(c * 0.58) for c in accent), 255))
    fd, bd = ImageDraw.Draw(front), ImageDraw.Draw(back)
    for draw, color in ((fd, accent), (bd, tuple(round(c + (255 - c) * 0.55) for c in accent))):
        draw.rectangle((0, 0, period, stripe), fill=(*color, 255))
        draw.rectangle((0, band - stripe, period, band), fill=(*color, 255))
    centres, x = [], 0.0
    for i, word in enumerate(words):
        w = face.getlength(word)
        if i == k:
            fd.rectangle((x - band * 0.12, stripe * 1.6, x + w + band * 0.12, band - stripe * 1.6), fill=(*accent, 255))
        centres.append(x + w / 2)
        x += w + face.getlength(' \u2022 ')
    ink = WALL_INK
    fd.text((0, band / 2), unit, font=face, fill=(*ink, 255), anchor='lm')
    bd.text((0, band / 2), unit, font=face, fill=(*tuple(round(c * 0.36) for c in accent), 255), anchor='lm')
    reps = width * 3 // period + 2
    tile = lambda image: np.tile(np.asarray(image), (1, reps, 1))
    return tile(front), tile(back), tuple(centres), period, reps


class RibbonScene:
    def paint_ribbon(self, screen, line, t):
        """The line printed along a paper ribbon that ripples across the frame and twists about its own length,
        showing its darker back where it turns over. The ribbon is pinned flat and swollen at the centre, where
        each sung word slides in on an accent block; it twists shut edge-on at the line's end."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = tuple(w['text'].strip().upper() or '~' for w in line['words'])
        arrive = smoother(clamp((t - line['start']) / 0.45))
        leave = smoother(clamp((t - (line['end'] - LEAVE)) / LEAVE))
        if arrive <= 0.001 or leave >= 0.999:
            return
        band = max(8, round(H * 0.22))
        front, back, centres, period, reps = ribbon_texture(words, k, band, W, accent, shade)
        tex_w = period * reps
        settle = back_out(clamp((t - since) / 0.32), 1.3)
        c = centres[max(0, k - 1)] + (centres[k] - centres[max(0, k - 1)]) * settle
        start = (
            period * (reps // 2) + c - W / 2 + (1 - arrive) * W * 0.7
        )  # the ribbon slides in, then glides to each sung word
        xs = np.arange(W, dtype=np.float32)
        middle = np.exp(-(((xs - W / 2) / (W * 0.13)) ** 2))
        span = W * (0.92 + 0.08 * math.sin((t - line['start']) * 0.9))
        phi = 2 * math.pi * (xs - W / 2) / span + leave * 1.4
        stamp = pulse(clamp((t - since) / 0.3))
        swell = 1 + 0.75 * middle * (1 + 0.25 * stamp)
        h = band / 2 * np.cos(phi) * swell * arrive * (1 - leave)
        drift = (t - line['start']) * 0.7
        style = line['index'] % 3  # each line runs its own course: a slow swell, a diagonal run, a tight wave
        if style == 0:
            path = H * 0.12 * np.sin(2 * math.pi * xs / (W * 1.25) + drift)
        elif style == 1:
            path = H * 0.34 * (xs / W - 0.5) * (1 - middle) + H * 0.05 * np.sin(2 * math.pi * xs / (W * 0.6) + drift)
        else:
            path = H * 0.19 * np.sin(2 * math.pi * xs / (W * 0.72) + drift)
        yc = H * 0.5 + path * (1 - 0.75 * middle)
        top = int(max(0, np.floor((yc - np.abs(h)).min()) - 1))
        bottom = int(min(H, np.ceil((yc + np.abs(h)).max()) + 2))
        if bottom - top < 2:
            return
        ys = np.arange(top, bottom, dtype=np.float32)[:, None]
        safe = np.where(np.abs(h) < 1e-3, 1e-3, h)
        v = (ys - yc[None, :]) / (
            2 * safe[None, :]
        ) + 0.5  # a negative half-height flips the texture: the back, upside down
        inside = (v >= 0) & (v < 1) & (np.abs(h)[None, :] > 0.5)
        rows = np.clip((v * band).astype(np.int32), 0, band - 1)
        cols = np.broadcast_to(((xs + start).astype(np.int64) % tex_w)[None, :], rows.shape)
        image = np.where((h > 0)[None, :, None], front[rows, cols], back[rows, cols]).astype(np.float32)
        light = (0.55 + 0.45 * np.abs(np.cos(phi)))[None, :, None]
        image[..., :3] *= light
        image[..., 3] = inside * 255
        ribbon = Image.fromarray(image.clip(0, 255).astype('uint8'), 'RGBA')
        shadow = tint(ribbon.getchannel('A'), shade)
        paste(screen, shadow, band * 0.08, top + band * 0.1)
        paste(screen, ribbon, 0, top)
