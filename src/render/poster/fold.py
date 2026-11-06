"""The accordion fold: the line printed on a pleated paper strip, one word per pleat."""

import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from effects.kinetic.easing import back_out, clamp, smoother
from render.poster.common import LEAVE, STACK_FONT, WALL_INK, WHITE, paste, tint, word_mask


def perspective_coeffs(quad, width, height):
    """PIL PERSPECTIVE coefficients that map an output quad (TL, TR, BR, BL) back onto a width x height image."""
    source = ((0, 0), (width, 0), (width, height), (0, height))
    rows = []
    for (x, y), (u, v) in zip(quad, source):
        rows.append((x, y, 1, 0, 0, 0, -u * x, -u * y))
        rows.append((0, 0, 0, x, y, 1, -v * x, -v * y))
    return np.linalg.solve(np.array(rows, float), np.array(source, float).reshape(8))


class FoldScene:
    def paint_fold(self, screen, line, t):
        """The line printed on a strip of paper folded like an accordion, one word per pleat. The strip unfolds
        across the frame when the line arrives; each sung word's pleat slaps flat to the camera in the accent
        while the others stay pleated and shaded, and the strip folds shut at the line's end."""
        W, H = screen.size
        accent, shade, pill = line['palette']
        k, since = self.sung_word(line, t)
        words = [w['text'].strip().upper() or '~' for w in line['words']]
        n = len(words)
        arrive = back_out(clamp((t - line['start']) / 0.5), 1.2)
        leave = smoother(clamp((t - (line['end'] - LEAVE)) / LEAVE))
        if leave >= 0.999 or t < line['start']:
            return
        tall = H * 0.42
        text_h = tall * 0.4
        masks = [word_mask(w, STACK_FONT, 200) for w in words]
        widths = [max(tall * 0.5, m.width * text_h / m.height + tall * 0.3) for m in masks]
        base = math.radians(
            89 - (89 - self.setting(line, 'fold_angle', 46.0)) * arrive * (1 - leave)
        )  # rests at about 46 degrees: every pleat stays readable
        flat = [0.0] * n
        flat[k] = back_out(clamp((t - since) / 0.3), 1.8) * (1 - leave)
        if k > 0:
            flat[k - 1] = (1 - smoother(clamp((t - since) / 0.24))) * (1 - leave)
        angles = [base * (1 - f) for f in flat]
        X, Z = [0.0], [0.0]
        for i in range(n):  # the strip's fold edges in 3D: a zigzag, pleat by pleat
            X.append(X[-1] + widths[i] * math.cos(angles[i]))
            Z.append(Z[-1] + (1 if i % 2 == 0 else -1) * widths[i] * math.sin(angles[i]))
        move = smoother(clamp((t - since) / 0.55))  # a slow glide to the sung pleat
        a, b = max(0, k - 1), k
        xc = (X[a] + X[a + 1]) / 2 + (
            (X[b] + X[b + 1]) / 2 - (X[a] + X[a + 1]) / 2
        ) * move  # the camera follows the sung pleat
        zc = (Z[a] + Z[a + 1]) / 2 + ((Z[b] + Z[b + 1]) / 2 - (Z[a] + Z[a + 1]) / 2) * move
        focal = W * 1.15
        cy = H * 0.48

        def project(x, z, y):
            d = focal / max(focal * 0.3, focal + z - zc)
            return (x - xc) * d, y * d

        def framing(m):
            """The zoom that frames pleat m and its neighbours (the rest may run off)."""
            near = range(max(0, m - 1), min(n, m + 2) + 1)
            reach = max(abs(project(X[j], Z[j], 0)[0]) for j in near)
            return min(W * 0.42 / max(1.0, reach), H * 0.78 / tall, 2.2)

        # blend the old framing into the new (in log space), never jump to it
        fit = math.exp(math.log(framing(a)) * (1 - move) + math.log(framing(b)) * move)
        draw = ImageDraw.Draw(screen)
        panels = []
        for i in range(n):
            quad = [
                project(X[i], Z[i], -tall / 2),
                project(X[i + 1], Z[i + 1], -tall / 2),
                project(X[i + 1], Z[i + 1], tall / 2),
                project(X[i], Z[i], tall / 2),
            ]
            quad = [(W / 2 + fit * qx, cy + fit * qy) for qx, qy in quad]
            if quad[1][0] - quad[0][0] < 1.5:
                continue
            panels.append(((Z[i] + Z[i + 1]) / 2, i, quad))
        drop = (tall * fit * 0.05, tall * fit * 0.06)
        for _, i, quad in panels:  # one hard shadow under the whole strip
            draw.polygon([(qx + drop[0], qy + drop[1]) for qx, qy in quad], fill=(*shade, 255))
        for _, i, quad in sorted(panels, reverse=True):  # farthest pleats first
            sung = i == k
            fill = (
                accent if sung else tuple(round(w * 0.86 + a * 0.14) for w, a in zip(WHITE, accent))
            )  # paper tinted by the line's colour
            ink = (WALL_INK if sum(accent) / 3 > 140 else WHITE) if sung else (WALL_INK if i < k else (150, 156, 170))
            pw, ph = max(2, round(widths[i])), max(2, round(tall))
            panel = Image.new('RGBA', (pw, ph), (*fill, 255))
            crease = max(2, round(pw * 0.025))
            pd = ImageDraw.Draw(panel)
            pd.rectangle((0, 0, crease, ph), fill=(*tuple(round(c * 0.82) for c in fill), 255))
            pd.rectangle((pw - crease, 0, pw, ph), fill=(*tuple(round(c * 0.82) for c in fill), 255))
            m = masks[i]
            word = m.resize(
                (max(1, round(m.width * text_h / m.height)), max(1, round(text_h))), Image.Resampling.BICUBIC
            )
            panel.alpha_composite(tint(word, ink), ((pw - word.width) // 2, (ph - word.height) // 2))
            facing = (1 if i % 2 == 0 else -1) * (1 if angles[i] >= 0 else -1)
            dim = abs(math.sin(angles[i])) * (
                0.1 if facing > 0 else 0.45
            )  # light from the left: one face of each fold is in shade
            if dim > 0.01:  # the shaded face takes a deep tint of the accent, not grey
                panel.alpha_composite(
                    Image.new('RGBA', panel.size, (*tuple(round(c * 0.35) for c in accent), round(255 * dim * 1.2)))
                )
            x0, y0 = math.floor(min(q[0] for q in quad)), math.floor(min(q[1] for q in quad))
            x1, y1 = math.ceil(max(q[0] for q in quad)), math.ceil(max(q[1] for q in quad))
            local = [(qx - x0, qy - y0) for qx, qy in quad]
            warped = panel.transform(
                (max(1, x1 - x0), max(1, y1 - y0)),
                Image.Transform.PERSPECTIVE,
                tuple(perspective_coeffs(local, pw, ph)),
                Image.Resampling.BICUBIC,
            )
            mask = Image.new('L', warped.size)
            ImageDraw.Draw(mask).polygon(local, fill=255)
            warped.putalpha(ImageChops.multiply(warped.getchannel('A'), mask))
            paste(screen, warped, x0, y0)
