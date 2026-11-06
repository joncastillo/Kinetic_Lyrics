"""The type mobile: the line's words hang on threads from a rail and swing; each sung word drops and swings wide."""

import math

from PIL import Image, ImageDraw

from effects.kinetic.easing import back_out, clamp, smoother
from render.poster.common import LEAVE, STACK_FONT, WALL_INK, WHITE, paste, tint, word_mask


def swing(t, start, amplitude, period=1.1, damping=2.2):
    """A damped pendulum kicked from rest at `start`: its angle in degrees at time t (0 at the kick, no jump)."""
    s = max(0.0, t - start)
    return amplitude * 1.6 * math.exp(-damping * s) * math.sin(2 * math.pi * s / period)


class MobileScene:
    def paint_mobile(self, screen, line, t):
        """The line's words hang on thin threads from a rail across the top of the frame, like a mobile, each
        tile swaying gently. Each word drops in on its thread as the line arrives; the sung word drops lower on
        a longer thread, turns the accent and swings wide before it settles; at the end the threads reel the
        words up out of frame."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() or '~' for w in line['words']]
        n = len(words)
        arrive = clamp((t - line['start']) / 0.6)
        leave = smoother(clamp((t - (line['end'] - LEAVE)) / LEAVE))
        if leave >= 0.999 or arrive <= 0:
            return
        rail = H * 0.08
        draw = ImageDraw.Draw(screen)
        span = W * 0.84 * smoother(clamp(arrive * 1.6))
        draw.rectangle((W / 2 - span / 2, rail - 3, W / 2 + span / 2, rail + 3), fill=(*pill, 255))
        masks = [word_mask(w, STACK_FONT, 200) for w in words]
        tall = H * 0.16
        widths = [m.width * tall / m.height for m in masks]
        gap = W * 0.84 / n
        scale = min(1.0, gap * 0.9 / max(widths))
        for i in sorted(range(n), key=lambda i: i == k):  # the swinging words hang in front
            mask = masks[i]
            sung = i == k
            anchor = W / 2 - W * 0.42 + gap * (i + 0.5)
            drop = back_out(clamp((arrive * 1.5 - i * 0.08) / 0.5), 1.6)  # each word drops in on its thread
            if drop <= 0:
                continue
            settled = H * (0.3 + 0.07 * ((i * 37) % 3))  # staggered thread lengths
            longer = 0.0
            if sung:
                longer = back_out(clamp((t - since) / 0.35), 1.8)
                if k + 1 < n:  # it hands back its size just before the next word is due
                    due = line['words'][k + 1]['start'] - 0.06
                    longer *= 1 - smoother(clamp((t - (due - 0.2)) / 0.2))
            length = (settled + H * 0.18 * longer) * drop * (1 - leave)
            if abs(i - k) == 1:  # the neighbours lift clear while the sung word swings
                length *= 1 - 0.35 * smoother(clamp((t - since) / 0.15)) * (1 - clamp((t - since) / 1.2))
            sway = 3.0 * math.sin(t * 1.3 + i * 1.7)  # the whole mobile breathes
            inward = 1 if anchor < W / 2 else -1  # a sung word swings toward the middle first, never out of frame
            kick = swing(t, line['words'][i]['start'] - 0.06, 20.0 * inward) if i <= k else 0.0  # each on its own clock
            angle = math.radians(sway + kick)
            bx, by = anchor + math.sin(angle) * length, rail + math.cos(angle) * length
            draw.line((anchor, rail, bx, by), fill=(*pill, 255), width=max(1, round(H * 0.004)))
            size = (
                scale + (max(scale * 1.56, W * 0.22 / widths[i]) - scale) * longer
            )  # the sung tile is big at any line length
            w, h = max(1, round(widths[i] * size)), max(1, round(tall * size))
            word = mask.resize((w, h), Image.Resampling.BICUBIC)
            pad = round(h * 0.28)
            tile = Image.new('RGBA', (w + pad * 2, h + pad * 2), (*(accent if sung else WHITE), 255))
            ink = (WALL_INK if sum(accent) / 3 > 140 else WHITE) if sung else WALL_INK
            tile.alpha_composite(tint(word, ink), (pad, pad))
            shadow = Image.new('RGBA', tile.size, (*shade, 255))
            turn = -math.degrees(angle)
            tile = tile.rotate(turn, Image.Resampling.BICUBIC, expand=True)
            shadow = shadow.rotate(turn, Image.Resampling.BICUBIC, expand=True)
            # the tile hangs from its top centre, at the end of the thread
            cx, cy = bx + math.sin(angle) * (h + pad * 2) / 2, by + math.cos(angle) * (h + pad * 2) / 2
            off = h * 0.12
            paste(screen, shadow, cx - shadow.width / 2 + off, cy - shadow.height / 2 + off)
            paste(screen, tile, cx - tile.width / 2, cy - tile.height / 2)
