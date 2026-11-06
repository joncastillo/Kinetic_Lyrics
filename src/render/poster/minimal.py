"""Restrained editorial scenes: readable phrases, quiet motion and ample negative space."""

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from core.color import hex_rgb
from core.fonts import truetype
from effects.kinetic.easing import clamp, smoother
from render.poster.common import paste, tint


@lru_cache(maxsize=512)
def tracked_mask(text, size, tracking, weight):
    if weight == 'serif':
        face = truetype('DMSerifDisplay-Regular.ttf', size)
    else:
        face = truetype('Montserrat-Variable.ttf', size)
        face.set_variation_by_axes([650 if weight == 'heavy' else 450])
    spacing = size * tracking
    boxes = [face.getbbox(c) for c in text]
    top = min(b[1] for b in boxes)
    bottom = max(b[3] for b in boxes)
    widths = [face.getlength(c) for c in text]
    mask = Image.new('L', (max(1, round(sum(widths) + spacing * max(0, len(text) - 1) + 4)), max(1, bottom - top + 4)))
    draw = ImageDraw.Draw(mask)
    x = 2.0
    for char, width in zip(text, widths):
        draw.text((x, 2 - top), char, font=face, fill=255)
        x += width + spacing
    return mask


class MinimalScenes:
    def paint_minimal(self, screen, line, t):
        width, height = screen.size
        kind = line['layout']
        config = line.get('config', {})
        speed = config.get('speed', 1.0)
        motion = config.get('motion', 1.0)
        tracking = config.get('tracking', 0.015)
        accent = hex_rgb(config['accent']) if config.get('accent') else (244, 238, 222)
        words = line['words']
        # Short phrases provide breathing space, while baseline and caption retain the complete lyric line.
        active = max((i for i, word in enumerate(words) if word['start'] - 0.06 <= t), default=0)
        first = active // 3 * 3 if kind in ('editorial', 'focus') else 0
        group = words[first : first + 3] if kind in ('editorial', 'focus') else words
        start = line['start'] if first == 0 else group[0]['start'] - 0.06
        following = first + len(group)
        end = min(line['end'], words[following]['start'] - 0.06) if following < len(words) else line['end']
        duration = max(0.02, min(0.42 / speed, (end - start) * 0.3))
        arrive = smoother(clamp((t - start) / duration))
        leave = smoother(clamp((t - (end - duration)) / duration))
        opacity = arrive * (1 - leave)
        if opacity <= 0.001:
            return
        size = max(
            8,
            round(
                height * (0.065 if kind == 'caption' else 0.12 if kind == 'focus' else 0.105) * config.get('size', 1.0)
            ),
        )
        max_width = width * (0.7 if kind == 'caption' else 0.8)

        # Wrap at word boundaries and fit long words; no glyph or lyric is discarded.
        def layout(size):
            space = size * 0.35
            rows, row, used = [], [], 0.0
            for i, word in enumerate(group):
                text = word['text'].strip() or ' '
                weight = (
                    'serif'
                    if kind == 'focus'
                    else 'heavy'
                    if kind == 'editorial' and i == len(group) - 1
                    else 'regular'
                )
                if kind == 'baseline':
                    text = text.upper()
                mask = tracked_mask(text, size, tracking, weight)
                if row and (used + space + mask.width > max_width or kind == 'editorial' and i == len(group) - 1):
                    rows.append((row, used))
                    row, used = [], 0.0
                x = used + (space if row else 0.0)
                row.append((first + i, word, mask, x))
                used = x + mask.width
            if row:
                rows.append((row, used))
            return rows

        rows = layout(size)
        while size > 8 and (max(w for _, w in rows) > max_width or len(rows) * size * 1.45 > height * 0.65):
            size = max(8, int(size * 0.9))
            rows = layout(size)
        row_height = size * 1.45
        top = (
            height * 0.78 - (len(rows) - 1) * row_height
            if kind == 'caption'
            else height * 0.47 - len(rows) * row_height / 2
        )
        layer = Image.new('RGBA', screen.size)
        for r, (row, row_width) in enumerate(rows):
            left = (width - row_width) / 2 if kind == 'focus' else width * 0.12
            baseline = top + r * row_height + size
            for index, word, mask, x in row:
                color = accent if index == active else (231, 233, 237)
                if kind == 'baseline':
                    local = smoother(clamp((t - word['start'] + 0.12) / duration))
                    reveal = local * (1 - leave)
                    glyph = tint(mask, color, opacity)
                    y = baseline - mask.height + mask.height * (1 - reveal) * (1 + motion * 0.3)
                    visible = max(0, min(mask.height, round(baseline - y)))
                    if visible:
                        paste(layer, glyph.crop((0, 0, glyph.width, visible)), left + x, y)
                else:
                    offset = (
                        size * 0.22 * motion * (1 - arrive - leave)
                        if kind == 'editorial'
                        else size * 0.3 * motion * (1 - arrive)
                        if kind == 'caption'
                        else 0.0
                    )
                    paste(layer, tint(mask, color, opacity), left + x, baseline - mask.height + offset)
        if kind in ('editorial', 'caption'):
            draw = ImageDraw.Draw(layer)
            y = top - size * 0.3
            draw.line(
                (width * 0.12, y, width * 0.12 + width * 0.08 * opacity, y),
                fill=(*accent, round(210 * opacity)),
                width=max(1, round(height / 540)),
            )
        if kind == 'focus':
            blur = (1 - arrive + leave) * size * 0.055 * motion
            if blur > 0.15:
                layer = layer.filter(ImageFilter.GaussianBlur(blur))
            zoom = 1 + 0.025 * motion * (1 - arrive)
            layer = layer.transform(
                screen.size,
                Image.Transform.AFFINE,
                (1 / zoom, 0, width / 2 * (1 - 1 / zoom), 0, 1 / zoom, height / 2 * (1 - 1 / zoom)),
                Image.Resampling.BICUBIC,
            )
        screen.alpha_composite(layer)
