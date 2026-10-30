"""Individual glyphs rotate and arrive from deterministic directions."""

import math
import random


def paint_spinning_letters(layer, sprite, x, y, amount, effect, seed, spans=None):
    from effects.particles.motion import tumble, _alpha
    from effects.particles.choreography import entrance_opacity

    if spans is None:
        count = max(1, round(sprite.width / max(1, sprite.height * 0.6)))
        bounds = [round(index * sprite.width / count) for index in range(count + 1)]
        spans = list(zip(bounds, bounds[1:]))
    rng = random.Random(seed)
    for index, (left, right) in enumerate(spans):
        if right <= left:
            continue
        values = [rng.random() for _ in range(5)]
        delay = effect.stagger * values[0]
        arrival = max(0.0, min(1.0, ((1 - amount) - delay) / (1 - delay)))
        q = 1 - arrival * arrival * (3 - 2 * arrival)
        piece = sprite.crop((left, 0, right, sprite.height))
        angle = values[1] * math.tau
        distance = sprite.height * effect.spread * (1 + values[2]) * q
        dx, dy = math.cos(angle) * distance, math.sin(angle) * distance
        if effect.trajectory in ("left", "right"):
            dx = distance * (-1 if effect.trajectory == "left" else 1)
            dy *= 0.35
        elif effect.trajectory in ("up", "down"):
            dy = distance * (-1 if effect.trajectory == "up" else 1)
            dx *= 0.35
        elif effect.trajectory == "spiral":
            dx, dy = (
                math.cos(angle + q * effect.twist) * distance,
                math.sin(angle + q * effect.twist) * distance,
            )
        elif effect.trajectory == "fan":
            dx, dy = distance * (-1 if index % 2 else 1), -distance * 0.6
        piece = tumble(
            piece,
            q * (values[3] - 0.5) * 8 * effect.spin,
            q * (values[4] - 0.5) * 10 * effect.spin,
            q * (values[2] - 0.5) * 8 * effect.spin,
            1.0,
        )
        if piece is not None:
            piece = _alpha(piece, entrance_opacity(1 - amount))
            layer.alpha_composite(
                piece,
                (
                    round(x + (left + right) / 2 + dx - piece.width / 2),
                    round(y + sprite.height / 2 + dy - piece.height / 2),
                ),
            )
