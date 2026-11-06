"""The receding stack: earlier words step back into depth behind the sung word."""

from PIL import Image, ImageDraw
from effects.kinetic.easing import back_out, clamp, keyframes, smoother
from render.poster.common import LEAVE, WALL_FONT, WALL_INK, WHITE, paste, tint, word_mask


class RecedeScene:
    def paint_recede(self, screen, line, t):
        """The sung word stands large on a solid plate in front, and the line's earlier words step back behind
        it into depth, each smaller, higher and darker. Each new word slams in at the front and the whole stack
        dollies back a step; at the line's end the stack rushes away into the distance."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() for w in line['words']]
        leave = smoother(clamp((t - (line['end'] - LEAVE)) / LEAVE))
        if leave >= 0.999 or t < line['start']:
            return
        push = smoother(clamp((t - since) / 0.45))
        handover = smoother(clamp((t - since) / 0.32))  # the plate passes from the last word to the new one
        slam = keyframes(clamp((t - since) / 0.38), [(0, 1.1), (0.45, 0.97), (0.75, 1.01), (1, 1.0)])
        base_w = W * 0.62 * self.setting(line, 'size')
        vanish = (W * 0.5, -H * 0.3)
        front = (W * 0.5, H * 0.66)
        for depth_index in range(0, k + 1):  # farthest first, so nearer words cover them
            step = (k - depth_index) - (1 - push) + leave * 4.0  # how many steps back this word sits
            if step < 0:
                step = 0.0
            scale = 0.66**step
            if scale < 0.06:
                continue
            if vanish[1] + (front[1] - vanish[1]) * scale < H * 0.04:  # it would reach the top edge: let it go
                continue
            word = words[depth_index] or '~'
            mask = word_mask(word, WALL_FONT, 200)
            width = min(base_w, mask.width * H * 0.2 * self.setting(line, 'size') / mask.height) * scale
            hero = handover if depth_index == k else 1 - handover if depth_index == k - 1 else 0.0
            if depth_index == k:
                width *= slam * (0.35 + 0.65 * back_out(handover, 1.15))  # it scales in, never pops
            tall = width * mask.height / mask.width
            cx = vanish[0] + (front[0] - vanish[0]) * scale
            cy = vanish[1] + (front[1] - vanish[1]) * scale
            if hero > 0.02:
                pad = tall * 0.28
                draw = ImageDraw.Draw(screen)
                draw.rectangle(
                    (
                        cx - (width / 2 + pad) * hero + tall * 0.08,
                        cy - (tall / 2 + pad * 0.6) * hero + tall * 0.08,
                        cx + (width / 2 + pad) * hero + tall * 0.08,
                        cy + (tall / 2 + pad * 0.6) * hero + tall * 0.08,
                    ),
                    fill=(*shade, 255),
                )
                tilt_in = (1 - back_out(smoother(clamp((t - since) / 0.42)), 1.1)) * -6
                plate = Image.new(
                    'RGBA',
                    (max(1, round((width + pad * 2) * hero)), max(1, round((tall + pad * 1.2) * hero))),
                    (*accent, 255),
                )
                if abs(tilt_in) > 0.2:
                    plate = plate.rotate(tilt_in, Image.Resampling.BICUBIC, expand=True)
                paste(screen, plate, cx - plate.width / 2, cy - plate.height / 2)
            on_plate = WALL_INK if sum(accent) / 3 > 140 else WHITE
            mix = 0.25 + 0.5 * (1 - scale)  # each step back takes more of the accent
            keep = 0.55**step  # each step back sinks about half way into the night
            color = tuple(
                round((a * mix + w * (1 - mix)) * keep + n * (1 - keep)) for a, w, n in zip(accent, WHITE, (24, 32, 62))
            )
            color = tuple(round(c + (o - c) * hero) for c, o in zip(color, on_plate))  # the ink follows the plate
            tile = tint(mask.resize((max(1, round(width)), max(1, round(tall))), Image.Resampling.BICUBIC), color)
            paste(screen, tile, cx - tile.width / 2, cy - tile.height / 2)
