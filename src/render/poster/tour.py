"""The camera tour: a tight block of words, the camera flying to each sung word."""

import math
from PIL import Image
from effects.kinetic.easing import clamp, smoother
from render.poster.common import SECOND_INK, TOUR_FONT, WHITE, paste, tour_sprite, word_mask


class TourScene:
    TOUR_EFFECTS = (
        'kinetic-pop-extrude',
        'kinetic-elastic-stretch',
        'kinetic-dot-stamp',
        'kinetic-echo-cascade',
        'kinetic-echo-chain',
        'kinetic-page-peel',
    )

    def tour_layout(self, line):
        """Pack the line's words into one tight block, each word fitted to the block it joins: alternately
        set across the bottom at the block's full width, or turned on its side up the right edge at the block's
        full height. Returns [(centre_x, centre_y, length, thickness, angle)] in world units."""
        if 'tour' in line:
            return line['tour']
        placed = []
        x0 = y0 = 0.0
        x1 = y1 = None
        for i, word in enumerate(line['words']):
            text = word['text'].strip().upper() or '~'
            mask = word_mask(text, TOUR_FONT, 200)
            aspect = mask.width / max(1, mask.height)  # length per unit of thickness
            if i == 0:
                length, thick = aspect, 1.0
                placed.append(((length) / 2, 0.5, length, thick, 0.0))
                x1, y1 = length, 1.0
                continue
            width, height = x1 - x0, y1 - y0
            side = (
                i % 2 == 1 and len(text) >= 3 and height / aspect >= 0.45
            )  # only words that stay big turn up the side
            if side:
                length = height
                thick = min(length / aspect, width)
                length = thick * aspect
                placed.append((x1 + thick / 2, y1 - length / 2, length, thick, 90.0))
                x1 += thick
            else:
                length = width
                thick = min(length / aspect, height)
                length = thick * aspect
                placed.append((x0 + length / 2, y1 + thick / 2, length, thick, 0.0))
                y1 += thick
        line['tour'] = placed
        line['tour_box'] = (x0, y0, x1, y1)
        return placed

    def tour_camera(self, line, t, W, H):
        """(centre_x, centre_y, zoom, angle) of the camera: it flies to frame each word as it is sung, turning so
        sideways words read upright. It stays on the last word; the exit is in paint_tour."""
        placed = self.tour_layout(line)
        words = line['words']

        def framing(i):
            cx, cy, length, thick, angle = placed[i]
            wide = 0.78 if i < 2 else 1.0  # the first words are framed wider so the next ones fit
            return cx, cy, min(W * 0.5 / length, H * 0.32 / thick) * wide, -angle

        shots = [(words[i]['start'] - 0.34, framing(i)) for i in range(len(words))]
        current = shots[0][1]
        for when, shot in shots[1:]:
            if t < when:
                break
            f = smoother(
                clamp((t - when) * self.setting(line, 'travel_speed') / 0.42)
            )  # an unhurried flight; a new one blends from wherever the last has got to
            previous = current
            # zoom eases in log space so the camera never swings past the word it is heading for
            zoom = math.exp(math.log(previous[2]) + (math.log(shot[2]) - math.log(previous[2])) * f)
            current = (
                previous[0] + (shot[0] - previous[0]) * f,
                previous[1] + (shot[1] - previous[1]) * f,
                zoom,
                previous[3] + (shot[3] - previous[3]) * f,
            )
        return current

    @staticmethod
    def tour_inside(sx, sy, length, thick, angle, W, H):
        a = math.radians(angle)
        half_w = (abs(math.cos(a)) * length + abs(math.sin(a)) * thick) / 2
        half_h = (abs(math.sin(a)) * length + abs(math.cos(a)) * thick) / 2
        return (
            sx - half_w >= W * 0.03 and sx + half_w <= W * 0.97 and sy - half_h >= H * 0.03 and sy + half_h <= H * 0.97
        )

    def paint_tour(self, screen, line, t):
        """A camera tour of a tight block of words: each sung word joins the block, fitted to it (across the
        bottom, or turned up the side), entering with its own kinetic entrance, while the camera flies, zooms
        and turns to frame it. At the line's end the camera pulls away from wherever it is, still turning, and the
        block shrinks and spins off (no swing back to level first)."""
        from effects.kinetic import paint_kinetic
        from effects.particles.catalog import discover_effects

        W, H = screen.size
        accent, shade, pill = line['palette']
        placed = self.tour_layout(line)
        k, since = self.sung_word(line, t)
        leave = smoother(clamp((t - (line['end'] - 0.5)) / 0.5))  # the camera pulls away over half a second
        if leave >= 0.999:
            return
        cx, cy, zoom, cam = self.tour_camera(line, t, W, H)
        zoom *= 1 - 0.94 * leave  # pulling away
        cam += 50 * leave * (1 if line['index'] % 2 else -1)  # and still turning, the way it was going
        theta = math.radians(cam)
        catalog = getattr(self, '_tour_catalog', None) or discover_effects()['entrance']
        self._tour_catalog = catalog
        cache = getattr(self, '_tour_cache', None)
        if cache is None:
            cache = self._tour_cache = {}
        for i, (wx, wy, length, thick, angle) in enumerate(placed):
            word = line['words'][i]
            start = word['start'] - (0.3 if i == 0 else 0.12)
            if t < start:
                break
            dx, dy = wx - cx, wy - cy
            sx = W / 2 + zoom * (dx * math.cos(theta) + dy * math.sin(theta))
            sy = H / 2 + zoom * (-dx * math.sin(theta) + dy * math.cos(theta))
            px_thick = thick * zoom
            if px_thick < 3 or px_thick > H * 3:
                continue
            if i != k and leave <= 0 and not self.tour_inside(sx, sy, length * zoom, px_thick, angle + cam, W, H):
                continue
            text = word['text'].strip().upper() or '~'
            base = WHITE if i % 2 == 0 else SECOND_INK
            lift = smoother(clamp(leave * 3))  # the waiting words brighten as the whole block comes into view
            color = accent if i == k else tuple(round(d + (b - d) * lift) for d, b in zip((58, 72, 112), base))
            sprite, spans = tour_sprite(text, round(px_thick), color)
            progress = clamp((t - start) / 0.5)
            total = angle + cam
            if progress >= 1 or i != k:
                image = sprite
            else:
                pad = round(px_thick * 1.4)
                image = Image.new('RGBA', (sprite.width + pad * 2, sprite.height + pad * 2))
                pair = (
                    self.TOUR_EFFECTS[(line['index'] * 2) % len(self.TOUR_EFFECTS)],
                    self.TOUR_EFFECTS[(line['index'] * 2 + 1) % len(self.TOUR_EFFECTS)],
                )
                effect = catalog.get(pair[i % 2])  # one pair of entrance families per line
                if effect is None:
                    image.alpha_composite(sprite, (pad, pad))
                else:
                    paint_kinetic(image, sprite, pad, pad, progress, effect, line['index'] * 31 + i, 1.0, cache, spans)
            if abs(total) > 0.2:
                image = image.rotate(total, Image.Resampling.BICUBIC, expand=True)
            paste(screen, image, sx - image.width / 2, sy - image.height / 2)
