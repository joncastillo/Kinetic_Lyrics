"""The counter dive: one huge word at a time, the camera diving through a letter's counter to the next."""

from functools import lru_cache

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from effects.kinetic.easing import back_out, clamp, smoother, window
from render.poster.common import LEAVE, WALL_FONT, WHITE, letter_edges, paste, tint, word_mask


@lru_cache(maxsize=256)
def counter_of(text):
    """Where to dive into `text` (set in the wall font): the centre of its biggest letter counter (the hole in an
    O, A, R...) and that hole as a mask; or, with no counter, a round hole punched through the word's middle
    (the last value says which)."""
    mask = word_mask(text, WALL_FONT, 200)
    solid = mask.point(lambda v: 255 if v > 110 else 0)
    padded = Image.new('L', (solid.width + 4, solid.height + 4))
    padded.paste(solid, (2, 2))
    ImageDraw.floodfill(padded, (0, 0), 128)
    holes = np.asarray(padded)[2:-2, 2:-2] == 0
    edges = [round(e * mask.width) for e in letter_edges(text, WALL_FONT)]
    best, count = None, 0
    for a, b in zip(edges, edges[1:]):
        n = int(holes[:, a:b].sum())
        if n > count:
            best, count = (a, b), n
    if best is not None and count >= 40:
        region = np.zeros_like(holes)
        region[:, best[0] : best[1]] = holes[:, best[0] : best[1]]
        ys, xs = np.nonzero(region)
        size = min(xs.max() - xs.min(), ys.max() - ys.min()) + 1
        return (
            float(xs.mean()),
            float(ys.mean()),
            float(size),
            Image.fromarray((region * 255).astype('uint8'), 'L'),
            False,
        )
    # No counter: punch a round hole through the middle of the word and dive into that.
    radius = mask.height * 0.3
    punch = Image.new('L', mask.size)
    ImageDraw.Draw(punch).ellipse(
        (mask.width / 2 - radius, mask.height / 2 - radius, mask.width / 2 + radius, mask.height / 2 + radius), fill=255
    )
    return mask.width / 2, mask.height / 2, radius * 2, punch, True


class DiveScene:
    def paint_dive(self, screen, line, t):
        """One word at a time, huge. Before the next word is sung the camera dives into a counter of the current
        one (the hole in its O, A or R), and the next word is waiting inside the hole; the hole opens past the frame
        and that word becomes the next to dive through. The line ends with a dive into the last word."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() or '~' for w in line['words']]
        n = len(words)
        if t < line['start'] or t >= line['end']:
            return
        if k + 1 < n:
            due = line['words'][k + 1]['start'] - 0.06
            length = max(
                0.16, due - since
            )  # the push into the counter runs the whole word: it was read inside the last hole
        else:
            due = line['end']
            length = LEAVE
        u = clamp((t - (due - length)) / length)

        def rest(mask):
            return min(W * 0.84 / mask.width, H * 0.62 / mask.height)

        def colour(i):
            return accent if i % 2 == 0 else WHITE

        mask = word_mask(words[k], WALL_FONT, 200)
        fx, fy, hole, clip, punched = counter_of(words[k])
        scale = rest(mask) * (1 + 0.12 * smoother(clamp((t - since) / 0.8)))  # a slow push while the word holds
        if k == 0:
            scale *= 0.5 + 0.5 * back_out(clamp((t - line['start']) / 0.3), 1.5)
        end = 1.8 * max(W, H) / max(4.0, hole)
        zoom = (
            scale * (1 + 0.4 * u) * (end / (scale * 1.4)) ** (u ** self.setting(line, 'dive_curve', 3.0))
        )  # a steady push the whole word long, then the dive takes off
        mix = smoother(clamp(u * 1.6))
        px = mask.width / 2 + (fx - mask.width / 2) * mix
        py = mask.height / 2 + (fy - mask.height / 2) * mix

        def camera(shift=0.0):
            return (1 / zoom, 0, px - (W / 2 + shift) / zoom, 0, 1 / zoom, py - (H / 2 + shift) / zoom)

        lift = max(2.0, zoom * mask.height * 0.035)
        crisp = lambda image: image.point(lambda v: max(0, min(255, (v - 96) * 4)))  # a hard print edge at any zoom
        body = ImageChops.subtract(mask, clip) if punched else mask  # a word with no counter has one punched through it
        paste(
            screen,
            tint(crisp(body.transform((W, H), Image.Transform.AFFINE, camera(lift), Image.Resampling.BILINEAR)), shade),
            0,
            0,
        )
        paste(
            screen,
            tint(crisp(body.transform((W, H), Image.Transform.AFFINE, camera(), Image.Resampling.BILINEAR)), colour(k)),
            0,
            0,
        )
        if u > 0 and k + 1 < n:  # the next word, waiting inside the hole
            following = word_mask(words[k + 1], WALL_FONT, 200)
            hx, hy = W / 2 + (fx - px) * zoom, H / 2 + (fy - py) * zoom
            radius = max(hole * zoom * 0.42, H * 0.1) * (
                1 - smoother(window(u, 0.55, 1.0))
            )  # a disc about a fifth of the frame from the start
            inner = min(rest(following), max(hole * zoom * 0.75, radius * 1.6) / following.width)
            coeffs = (1 / inner, 0, following.width / 2 - hx / inner, 0, 1 / inner, following.height / 2 - hy / inner)
            word = following.transform((W, H), Image.Transform.AFFINE, coeffs, Image.Resampling.BILINEAR)
            shadow = following.transform(
                (W, H),
                Image.Transform.AFFINE,
                (
                    1 / inner,
                    0,
                    following.width / 2 - (hx + max(2.0, inner * following.height * 0.035)) / inner,
                    0,
                    1 / inner,
                    following.height / 2 - (hy + max(2.0, inner * following.height * 0.035)) / inner,
                ),
                Image.Resampling.BILINEAR,
            )
            disc = Image.new('L', (W, H))
            ImageDraw.Draw(disc).ellipse((hx - radius, hy - radius, hx + radius, hy + radius), fill=255)
            portal = crisp(clip.transform((W, H), Image.Transform.AFFINE, camera(), Image.Resampling.BILINEAR))
            seen = ImageChops.lighter(
                portal, disc
            )  # the next word shows through the hole, or the disc while that is bigger
            word, shadow = ImageChops.multiply(word, seen), ImageChops.multiply(shadow, seen)
            paste(screen, tint(disc, shade), 0, 0)  # the next word waits on a dark disc set in the hole
            paste(screen, tint(shadow, shade), 0, 0)
            paste(screen, tint(word, colour(k + 1)), 0, 0)
