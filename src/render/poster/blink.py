"""The word blink: one word per beat on its own band of colour."""

from PIL import Image
from effects.kinetic.easing import clamp, keyframes, smoother
from render.poster.common import ENTRY, FIELDS, LEAVE, STACK_FONT, WALL_FONT, WALL_INK, WHITE, paste, tint, word_mask


class BlinkScene:
    def paint_blink(self, screen, line, t):
        """One word per beat on its own band of flat colour (a new colour every word). Each band slams in from
        the side it steps towards over a few frames, at one of four heights and a slight tilt; the word hits
        with a squash, alternating a wide heavy cut and a tall condensed one; the line runs in a pill below."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() for w in line['words']]
        arrive = clamp((t - line['start']) / ENTRY)
        leave = clamp((t - (line['end'] - LEAVE)) / LEAVE)
        gone = smoother(leave)
        if gone >= 0.999:
            return
        enter = smoother(clamp((t - since) / 0.26)) if k else smoother(clamp((t - line['start']) / 0.3))
        hit = keyframes(clamp((t - since) / 0.3), [(0, 1.04), (0.4, 0.9), (0.7, 1.02), (1, 1.0)])
        band_h = H * 0.4 * (1 - gone)
        if k > 0 and enter < 1:  # the previous word's band holds until the new one has slammed over it
            self.blink_band(screen, line, words, k - 1, 1.0, 1.0, band_h, t, since)
        self.blink_band(screen, line, words, k, enter, hit, band_h, t, since)
        self.paint_caption(screen, line, t, pill, shade, arrive, leave)

    def blink_band(self, screen, line, words, k, enter, hit, band_h, t, since):
        W, H = screen.size
        field = FIELDS[(line['index'] * 5 + k * 2) % len(FIELDS)]
        slot = (line['index'] * 3 + k) % 4
        centre = H * (0.3, 0.52, 0.38, 0.6)[slot]
        tilt = (-3, 2, 3, -2)[slot]
        side = 1 if k % 2 else -1
        strip = Image.new('RGBA', (round(W * 1.3), max(1, round(band_h))), (*field, 255))
        condensed = k % 2 == 1
        word = words[k] or '~'
        mask = word_mask(word, STACK_FONT if condensed else WALL_FONT, 200)
        width = min(W * 0.74, mask.width * band_h * (0.8 if condensed else 0.62) / max(1, mask.height))
        tall = width * mask.height / mask.width
        if band_h > 4 and tall > 2:
            tile = mask.resize((max(1, round(width * (2 - hit))), max(1, round(tall * hit))), Image.Resampling.BICUBIC)
            ink = WALL_INK if sum(field) / 3 > 140 else WHITE
            paste(strip, tint(tile, ink), (strip.width - tile.width) / 2, (strip.height - tile.height) / 2)
        if (
            k == len(words) - 1 and len(words) > 1 and t - since < 0.48
        ):  # the line's last word: two halves slam together
            half = strip.height // 2
            gap = band_h * 0.03 * (1 - smoother(clamp((t - since) / 0.45)))
            for part, (a, b), sign, lag in (
                (strip.crop((0, 0, strip.width, half)), (0, half), 1, 0.0),
                (strip.crop((0, half, strip.width, strip.height)), (half, strip.height), -1, 0.06),
            ):
                part = part.rotate(tilt, Image.Resampling.BICUBIC, expand=True)
                arrive_half = smoother(clamp((t - since - lag * 0.4) / 0.26))
                paste(
                    screen,
                    part,
                    (W - part.width) / 2
                    + sign * (1 - arrive_half) * W * 1.1
                    + sign * W * 0.05 * (1 - smoother(clamp((t - since) / 0.6))),
                    centre - strip.height / 2 + a - sign * gap / 2,
                )
            return
        strip = strip.rotate(tilt, Image.Resampling.BICUBIC, expand=True)
        dx = side * (1 - enter) * W * 1.1
        paste(screen, strip, (W - strip.width) / 2 + dx, centre - strip.height / 2)
