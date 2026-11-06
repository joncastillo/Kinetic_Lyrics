"""Restrained editorial scenes: readable phrases, quiet motion and ample negative space."""

from render.scene_fonts import font_cache as lru_cache


from PIL import Image, ImageDraw, ImageFilter


from core.color import hex_rgb

from render.scene_fonts import truetype

from effects.kinetic.easing import clamp, smoother

from render.poster.common import paste, tint, word_mask, WALL_FONT


@lru_cache(maxsize=512)
def tracked_mask(text, size, tracking, weight):
    if weight == 'serif':
        face = truetype('DMSerifDisplay-Regular.ttf', size)

    elif weight == 'display':
        face = truetype('BricolageGrotesque[opsz,wdth,wght].ttf', size)

    else:
        face = truetype('Montserrat-Variable.ttf', size)

        from render.scene_fonts import current_font

        if not current_font():
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
    @staticmethod
    def phrase_span(words, active, target):
        if not target:
            return 0, words

        from render.cinema import is_function

        connectors = {'upon', 'until', 'through', 'into', 'onto', 'under', 'over', 'between'}

        function = lambda text: is_function(text) or text.lower().strip('.,!?') in connectors

        first = 0

        while first < len(words):
            end = min(len(words), first + target)

            if len(words) - end == 1:
                end = len(words)

            elif end < len(words):
                while end > first + 1 and function(words[end - 1]['text']):
                    end -= 1

            if active < end:
                return first, words[first:end]

            first = end

        return 0, words

    def paint_minimal(self, screen, line, t):
        width, height = screen.size

        kind = line['layout']

        config = line.get('config', {})

        speed = config.get('speed', 1.0)

        motion = config.get('motion', 1.0)

        tracking = config.get('tracking', 0.015)

        accent = hex_rgb(config['accent']) if config.get('accent') else (244, 238, 222)

        light_background = sum(screen.convert('RGB').resize((1, 1)).getpixel((0, 0))) / 3 > 155

        body_ink = (35, 44, 56) if light_background else (231, 233, 237)

        if light_background and not config.get('accent'):
            accent = (16, 26, 39)

        words = line['words']

        # Short phrases provide breathing space, while baseline and caption retain the complete lyric line.

        active = max((i for i, word in enumerate(words) if word['start'] - 0.06 <= t), default=0)

        phrase_words = int(config.get('phrase_words', 3 if kind in ('editorial', 'focus') else 0))

        first, group = self.phrase_span(words, active, phrase_words)

        composition = config.get('composition', 'auto')

        placement = config.get('placement', 'auto')

        start = line['start'] if first == 0 else group[0]['start'] - 0.06

        following = first + len(group)

        end = min(line['end'], words[following]['start'] - 0.06) if following < len(words) else line['end']

        duration = max(0.02, min(0.42 / speed, (end - start) * 0.3))

        arrive = smoother(clamp((t - start) / duration))

        leave = smoother(clamp((t - (end - duration)) / duration))

        opacity = (min(1.0, arrive * 2.5) if kind == 'focus' else arrive) * (1 - leave)

        if opacity <= 0.001:
            return

        size = max(
            8,
            round(
                height * (0.065 if kind == 'caption' else 0.17 if kind == 'focus' else 0.105) * config.get('size', 1.0)
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
                    'display'
                    if kind == 'focus' and i == len(group) - 1
                    else 'regular'
                    if kind == 'focus'
                    else 'heavy'
                    if kind == 'editorial' and i == len(group) - 1
                    else 'regular'
                )

                treatment = config.get('weight', 'auto')

                if treatment != 'auto':
                    weight = (
                        'serif'
                        if treatment == 'serif'
                        else 'heavy'
                        if treatment == 'contrast' and i == len(group) - 1
                        else 'regular'
                    )

                if kind == 'baseline':
                    text = text.upper()

                if kind == 'focus' and i == len(group) - 1:
                    text = text.upper()

                local_size = round(size * (1.55 if i == len(group) - 1 else 0.68)) if kind == 'focus' else size

                mask = tracked_mask(text, local_size, tracking, weight)

                if (
                    row
                    and composition != 'single-line'
                    and (
                        composition == 'stacked'
                        or used + space + mask.width > max_width
                        or composition == 'auto'
                        and kind in ('editorial', 'focus')
                        and i == len(group) - 1
                    )
                ):
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

        if placement == 'lower-left':
            top = height * 0.78 - (len(rows) - 1) * row_height

        elif placement in ('center', 'left'):
            top = height * 0.47 - len(rows) * row_height / 2

        layer = Image.new('RGBA', screen.size)

        for r, (row, row_width) in enumerate(rows):
            centered = placement == 'center' or placement == 'auto' and kind == 'focus'

            left = (width - row_width) / 2 if centered else width * 0.12

            baseline = top + r * row_height + size

            for index, word, mask, x in row:
                color = accent if index == active else body_ink

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
            # An oversized outline initial provides a distinct focal plane behind the readable lyric.

            initial = group[-1]['text'].strip()[:1].upper() or ' '

            outline = word_mask(initial, WALL_FONT, 240, stroke=3)

            scale = min(width * 0.68 / outline.width, height * 0.78 / outline.height)

            outline = outline.resize(
                (max(1, round(outline.width * scale)), max(1, round(outline.height * scale))), Image.Resampling.BICUBIC
            )

            progress = clamp((t - start) / max(0.1, end - start))

            position = width * 0.5 + width * 0.09 * motion * (2 * progress - 1)

            paste(
                screen,
                tint(outline, accent, 0.18 * opacity),
                position - outline.width / 2,
                (height - outline.height) / 2,
            )

            # Three optical bands converge from opposing sides, then resolve as one sharp word.

            bounds = layer.getbbox()

            if bounds and (arrive < 0.999 or leave > 0.001):
                sliced = Image.new('RGBA', screen.size)

                top_, bottom_ = bounds[1], bounds[3]

                for band in range(3):
                    a = top_ + (bottom_ - top_) * band // 3

                    b = top_ + (bottom_ - top_) * (band + 1) // 3

                    travel = max(0.0, (width - (bounds[2] - bounds[0])) / 2 - width * 0.05)

                    shift = round(travel * min(1.0, motion) * ((1 - arrive) ** 2 + leave**2) * (1 if band == 1 else -1))

                    paste(sliced, layer.crop((0, a, width, b)), shift, a)

                layer = sliced

            # A narrow light pass stays inside the glyphs rather than washing across the background.

            from PIL import ImageChops

            pulse = clamp((t - start) / max(0.1, end - start))

            beam = Image.new('L', screen.size)

            bx = width * (-0.15 + 1.3 * pulse)

            ImageDraw.Draw(beam).polygon(
                [(bx - size, 0), (bx + size * 0.15, 0), (bx + size, height), (bx - size * 0.15, height)], fill=95
            )

            beam = beam.filter(ImageFilter.GaussianBlur(max(1, size * 0.08)))

            beam = ImageChops.multiply(beam, layer.getchannel('A'))

            light = Image.new('RGBA', screen.size, (*accent, 0))

            light.putalpha(beam)

            layer.alpha_composite(light)

            zoom = 1 + 1.25 * motion * (1 - arrive) + 0.25 * motion * leave

            box = layer.getbbox()

            if box:
                zoom = min(zoom, width * 0.88 / max(1, box[2] - box[0]), height * 0.8 / max(1, box[3] - box[1]))

            layer = layer.transform(
                screen.size,
                Image.Transform.AFFINE,
                (1 / zoom, 0, width / 2 * (1 - 1 / zoom), 0, 1 / zoom, height / 2 * (1 - 1 / zoom)),
                Image.Resampling.BICUBIC,
            )

            bounds = layer.getbbox()

            if bounds:
                reflected = layer.crop(bounds).transpose(Image.Transpose.FLIP_TOP_BOTTOM)

                reflected = reflected.resize(
                    (reflected.width, max(1, round(reflected.height * 0.24))), Image.Resampling.BICUBIC
                )

                fade = Image.new('L', reflected.size)

                draw = ImageDraw.Draw(fade)

                for row in range(reflected.height):
                    draw.line(
                        (0, row, reflected.width, row), fill=round(32 * (1 - row / max(1, reflected.height - 1)) ** 2)
                    )

                reflected.putalpha(ImageChops.multiply(reflected.getchannel('A'), fade))

                paste(screen, reflected, bounds[0], bounds[3] + size * 0.12)

        screen.alpha_composite(layer)
