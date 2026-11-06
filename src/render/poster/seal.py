"""The word seal: the line around a solid badge ring, the sung word stamped in its centre."""

import math
from PIL import Image, ImageDraw
from core.fonts import truetype
from effects.kinetic.easing import back_out, clamp, keyframes, pulse, smoother, window
from render.poster.common import CAPTION_FONT, ENTRY, FONTS, LEAVE, STACK_FONT, WALL_FONT, WHITE, paste, tint, word_mask


class SealScene:
    def paint_seal(self, screen, line, t):
        """The whole line set around a solid badge ring, like the band of a stamp or a record label, with the
        word being sung stamped large in the middle on a hard shadow. The badge spins in whole and settles;
        the ring's letters are knocked out of the band in dark ink, the sung word's letters on the ring swell;
        each new word is stamped in the centre with an overshoot and a slight turn; on leaving the badge spins
        up and shrinks away."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() for w in line['words']]
        text = ' • '.join(words) + ' • '
        arrive = clamp((t - line['start']) / (ENTRY * 0.9))
        leave = smoother(clamp((t - (line['end'] - LEAVE)) / LEAVE))
        grow = back_out(arrive, 1.7) * (1 - leave)
        if grow <= 0.02:
            return
        cx, cy = W / 2, H * 0.47
        radius = (
            min(W, H) * 0.34 * self.setting(line, 'size') * grow * (1 + 0.12 * pulse(window(t, since, since + 0.45)))
        )
        band = radius * 0.2
        spin = (
            (t - line['start']) * 0.3 * self.setting(line, 'motion')
            + (1 - arrive) ** 2 * 2.2
            + leave * leave * 3.0
            + line['seed'] * math.tau
            + 0.3 * (k + back_out(clamp((t - since) / 0.2), 1.6))
        )
        size = band * 0.62
        face = truetype(str(FONTS / CAPTION_FONT), max(6, round(size)))
        total = sum(face.getlength(c) for c in text)
        mid = radius - band / 2
        scale = 2 * math.pi * mid / max(1.0, total)
        draw = ImageDraw.Draw(screen)
        off = band * 0.18
        lobes = {'round': 0, 'scalloped': 18, 'sawtooth': 12}.get(
            self.setting(line, 'shape', 'auto'), (0, 18, 12)[line['index'] % 3]
        )  # a round badge, a scalloped seal or a sawtooth stamp, by line

        def outline(r, dx=0.0):
            if not lobes:
                return [
                    (cx + dx + math.cos(a) * r, cy + dx + math.sin(a) * r)
                    for a in (math.tau * i / 120 for i in range(120))
                ]
            pts = []
            for i in range(lobes * 8):
                a = spin + math.tau * i / (lobes * 8)
                bump = (
                    (0.06 * abs(math.sin(a * lobes / 2 - spin * lobes / 2)))
                    if lobes == 18
                    else (0.07 * (1 - 2 * abs(((a - spin) * lobes / math.tau) % 1 - 0.5)))
                )
                pts.append((cx + dx + math.cos(a) * r * (1 - bump), cy + dx + math.sin(a) * r * (1 - bump)))
            return pts

        draw.polygon(outline(radius * 1.04, off), fill=(*shade, 255))
        draw.polygon(outline(radius * 1.04), fill=(*pill, 255))
        inner = radius - band
        draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), fill=(*accent, 255))
        draw.ellipse(
            (cx - inner * 0.93, cy - inner * 0.93, cx + inner * 0.93, cy + inner * 0.93),
            outline=(*shade, 255),
            width=max(1, round(band * 0.06)),
        )
        owner = []
        for word_index, word in enumerate(words):
            owner.extend([word_index] * len(word))
            owner.extend([-1] * 3)
        distance = 0.0
        for char, who in zip(text, owner):
            advance = face.getlength(char) * scale
            angle = spin + (distance + advance / 2) / mid
            distance += advance
            if char == ' ':
                continue
            sung = who == k
            swell = 1.25 if sung else 1.0
            glyph = word_mask(char, CAPTION_FONT, 120)
            g = glyph.resize(
                (max(1, round(glyph.width * size * swell / 120)), max(1, round(glyph.height * size * swell / 120))),
                Image.Resampling.BICUBIC,
            )
            g = tint(g, shade, 1.0 if who <= k else 0.45)
            g = g.rotate(-math.degrees(angle) - 90, Image.Resampling.BICUBIC, expand=True)
            paste(screen, g, cx + math.cos(angle) * mid - g.width / 2, cy + math.sin(angle) * mid - g.height / 2)
        word = words[k] or '~'
        mask = word_mask(word, WALL_FONT if max(map(len, words)) <= 5 else STACK_FONT, 200)
        stamp = keyframes(clamp((t - since) / 0.24), [(0, 1.25), (0.4, 0.92), (0.7, 1.04), (1, 1.0)])
        squash = 1 + 0.2 * pulse(window(clamp((t - since) / 0.34), 0.2, 0.8))
        turn = (6 if k % 2 else -6) * (1 - smoother(clamp((t - since) / 0.24)))
        width = min(inner * 1.6, mask.width * inner * 1.0 / mask.height)
        tall = width * mask.height / mask.width
        tile = mask.resize(
            (max(1, round(width * stamp * squash**0.5)), max(1, round(tall * stamp / squash))), Image.Resampling.BICUBIC
        )
        for color, d in ((shade, tall * 0.08), (WHITE, 0)):
            image = tint(tile, color)
            if abs(turn) > 0.1:
                image = image.rotate(turn, Image.Resampling.BICUBIC, expand=True)
            paste(screen, image, cx - image.width / 2 + d, cy - image.height / 2 + d)
