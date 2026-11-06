"""Ten original, quiet studio backdrops for samples; never applied to a user's video."""

import os

import numpy as np
from PIL import Image

# id, label, mode, base, illuminated tone, architectural treatment
BACKDROPS = (
    ('midnight', 'Midnight studio', 'dark', (7, 11, 19), (49, 68, 92), 'wash'),
    ('graphite', 'Graphite silk', 'dark', (8, 10, 14), (64, 71, 84), 'silk'),
    ('deep-teal', 'Deep teal', 'dark', (5, 18, 23), (39, 89, 95), 'arch'),
    ('ink-plum', 'Ink plum', 'dark', (12, 8, 19), (76, 49, 88), 'fold'),
    ('obsidian', 'Obsidian glow', 'dark', (8, 10, 13), (92, 67, 43), 'halo'),
    ('porcelain', 'Porcelain', 'light', (205, 211, 218), (251, 250, 245), 'wash'),
    ('warm-paper', 'Warm paper', 'light', (195, 183, 163), (250, 243, 229), 'fold'),
    ('silver-mist', 'Silver mist', 'light', (181, 199, 212), (243, 249, 252), 'silk'),
    ('sage-stone', 'Sage stone', 'light', (183, 202, 189), (243, 247, 232), 'arch'),
    ('rose-quartz', 'Rose quartz', 'light', (207, 184, 189), (253, 243, 237), 'halo'),
)
DEFAULT_BACKDROP = BACKDROPS[0][0]


def backdrop_choices():
    return [dict(id=id_, name=name, mode=mode) for id_, name, mode, *_ in BACKDROPS]


def backdrop_spec(id_):
    for spec in BACKDROPS:
        if spec[0] == id_:
            return spec
    raise ValueError('Choose an available preview background')


def render_backdrop(id_, size):
    _, _, mode, base, light, treatment = backdrop_spec(id_)
    width, height = size
    y, x = np.mgrid[0:height, 0:width] / np.array((height, width))[:, None, None]
    field = np.exp(-(((x - 0.7) / 0.7) ** 2 + ((y - 0.28) / 0.8) ** 2)) * 0.65
    if treatment == 'wash':
        horizon = 0.73 + 0.08 * (x - 0.5) ** 2
        field += 0.23 * np.exp(-(((y - horizon) / 0.055) ** 2)) - 0.12 / (1 + np.exp(-(y - horizon) * 45))
    elif treatment == 'silk':
        field += 0.31 * np.sin(x * 8 + y * 3) + 0.13 * np.cos(x * 15 - y * 2)
    elif treatment == 'arch':
        distance = np.hypot((x - 0.88) * 1.15, (y - 0.9) * 0.85)
        field += 0.72 * np.exp(-(((distance - 0.62) / 0.075) ** 2)) - 0.34 * np.exp(-(((distance - 0.73) / 0.065) ** 2))
    elif treatment == 'fold':
        diagonal = x * 0.7 + y * 0.8
        field += (
            0.42 * np.exp(-(((diagonal - 0.6) / 0.04) ** 2))
            + 0.18 * np.tanh((diagonal - 0.6) * 25)
            - 0.2 * np.exp(-(((diagonal - 0.5) / 0.08) ** 2))
        )
    elif treatment == 'halo':
        field += 0.65 * np.exp(-(((x - 0.22) / 0.22) ** 2 + ((y - 0.78) / 0.38) ** 2))
    field = np.clip(field, 0, 1)
    color = np.array(base) + (np.array(light) - np.array(base)) * field[..., None]
    # A restrained vignette and sub-pixel grain avoid banding without distracting from the letters.
    edge = np.clip(((x - 0.5) ** 2 + (y - 0.5) ** 2) * 0.22, 0, 0.12)
    color *= 1 - edge[..., None] * (1 if mode == 'dark' else 0.25)
    seed = next(i for i, spec in enumerate(BACKDROPS) if spec[0] == id_)
    grain = np.random.default_rng(seed).normal(0, 0.45, (height, width, 1))
    return Image.fromarray(np.uint8(np.clip(color + grain, 0, 255)), 'RGB')


def scene_backdrop(folder, size, id_=DEFAULT_BACKDROP):
    backdrop_spec(id_)
    path = folder / f'scene-backdrop-v3-{id_}-{size[0]}x{size[1]}.png'
    if not path.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f'.{os.getpid()}.tmp')
        render_backdrop(id_, size).save(temporary, format='PNG')
        temporary.replace(path)
    return path
