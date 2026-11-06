"""The horizon rise: each word climbs out from behind a horizon rule."""

from PIL import Image, ImageDraw
from effects.kinetic.easing import back_out, clamp, pulse, smoother, window
from render.poster.common import LEAVE, SECOND_INK, STACK_FONT, WHITE, letter_edges, paste, tint, word_mask


class HorizonScene:
    def paint_horizon(self, screen, line, t):
        """A hard horizon rule crosses the frame; each word rises out from behind it as it is sung, the sung word
        tall in the accent with a squash as it clears the rule, the words before it settling lower and smaller
        to make room; at the line's end every word sinks back behind the horizon, one after another."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() or '~' for w in line['words']]
        leave = clamp((t - (line['end'] - LEAVE)) / LEAVE)
        horizon = H * (0.66, 0.6, 0.7)[line['index'] % 3]
        rule = smoother(clamp((t - line['start']) / 0.5)) * (1 - smoother(leave))
        draw = ImageDraw.Draw(screen)
        weight = max(3, round(H * 0.012))
        if rule > 0.01:
            span = W * 0.9 * rule
            draw.rectangle((W / 2 - span / 2, horizon, W / 2 + span / 2, horizon + weight), fill=(*pill, 255))
        masks = [word_mask(word, STACK_FONT, 200) for word in words]
        handover = smoother(clamp((t - since) / 0.3))  # nothing switches on the beat: sizes and colours blend

        def hero(i):
            return handover if i == k else 1 - handover if i == k - 1 else 0.0

        def presence(i):  # the oldest of the shown words sinks out as the new one rises
            return 1 - handover if i == k - 3 else handover if i == k else 1.0 if i >= k - 2 else 0.0

        sizes = []
        for i, mask in enumerate(masks):
            tall = H * (0.15 + 0.15 * hero(i))
            sizes.append((mask.width * tall / mask.height, tall))
        gap = H * 0.03
        first = max(0, k - 3)
        total = sum((sizes[i][0] + gap) * presence(i) for i in range(first, k + 1)) - gap
        scale = min(1.0, W * 0.78 / max(1.0, total * 1.2))
        x = W / 2 - total * scale / 2
        for i in range(first, k + 1):
            word = line['words'][i]
            keep = presence(i)
            if keep <= 0.001:
                continue
            width, tall = sizes[i][0] * scale * keep, sizes[i][1] * scale
            rise = back_out(smoother(clamp((t - word['start'] + 0.06 - 0.08 * (len(words[i]) - 1)) / 0.42)), 1.2)
            sink = smoother(clamp(leave * 1.6 - i * 0.12))
            lift = rise * (1 - sink) * keep
            squash = 0.1 * pulse(window(clamp((t - word['start'] + 0.06) / 0.5), 0.45, 0.9)) if i == k else 0.0
            tile = masks[i].resize(
                (max(1, round(width * (1 + squash))), max(1, round(tall * (1 - squash)))), Image.Resampling.BICUBIC
            )
            base = WHITE if i % 2 == 0 else SECOND_INK
            color = tuple(round(b + (a - b) * hero(i)) for a, b in zip(accent, base))
            top = horizon - tile.height * lift
            visible = round(horizon - top)  # only the part above the horizon shows
            if visible <= 0:
                x += width + gap * scale * keep
                continue
            if i == k and t - word['start'] + 0.06 < 0.3 + 0.08 * len(
                words[i]
            ):  # the sung word's letters rise one after another
                edges = letter_edges(words[i], STACK_FONT)
                for n in range(len(edges) - 1):
                    a, b = round(edges[n] * tile.width), round(edges[n + 1] * tile.width)
                    if b <= a:
                        continue
                    letter_lift = back_out(smoother(clamp((t - word['start'] + 0.06 - 0.08 * n) / 0.42)), 1.2) * (
                        1 - sink
                    )
                    letter_top = horizon - tile.height * letter_lift
                    shown = round(horizon - letter_top)
                    if shown <= 0:
                        continue
                    piece = tile.crop((a, 0, b, min(tile.height, shown)))
                    paste(screen, tint(piece, shade), x + a + tile.height * 0.05, letter_top + tile.height * 0.05)
                    paste(screen, tint(piece, color), x + a, letter_top)
                x += width + gap * scale
                continue
            part = tile.crop((0, 0, tile.width, min(tile.height, visible)))
            if hero(i) > 0.02:
                paste(screen, tint(part, shade, hero(i)), x + tile.height * 0.05, top + tile.height * 0.05)
            paste(screen, tint(part, color), x, top)
            x += width + gap * scale * keep
