"""Recolour an effect to a chosen colour, so the AI director can colour any effect for any line.

A gradient map from black through the chosen colour to white keeps every effect's own light and shade (a gold
filigree's highlights and shadows, a glass shard's rim, a petal's vein) while its colour becomes the chosen one.
Pixels that are the word's own ink are left as they are, so an entrance still lands exactly on the plain word,
and near-white and near-black stay where they are, so white letters and dark shadows are untouched."""

import numpy as np
from PIL import Image


def hex_rgb(color):
    color = color.lstrip('#')
    return np.array([int(color[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def word_ink(sprite):
    """The mean colour of the word's solid letter pixels."""
    pixels = np.asarray(sprite.convert('RGBA'), np.float32)
    solid = pixels[..., 3] > 220
    return pixels[solid][:, :3].mean(axis=0) if solid.any() else None


def recolor(layer, color, sprite=None, strength=0.92):
    """`layer` with its colours mapped onto `color` (black -> color -> white), the word's own ink left alone."""
    target = hex_rgb(color)
    pixels = np.asarray(layer, np.float32).copy()
    rgb, alpha = pixels[..., :3], pixels[..., 3]
    shown = alpha > 0
    if not shown.any():
        return layer
    lum = (rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722) / 255
    dark = np.clip(lum * 2, 0, 1)[..., None]
    light = np.clip(lum * 2 - 1, 0, 1)[..., None]
    mapped = np.where(lum[..., None] < 0.5, target * dark, target + (255 - target) * light)
    weight = np.full(lum.shape, strength, np.float32)
    ink = word_ink(sprite) if sprite is not None else None
    if ink is not None:  # the word's own ink keeps its colour
        distance = np.sqrt(((rgb - ink) ** 2).sum(-1))
        weight *= np.clip((distance - 24) / 40, 0, 1)
    saturation = (rgb.max(-1) - rgb.min(-1)) / 255  # near-white and near-black (greys) keep their value
    extreme = np.clip(np.maximum((lum - 0.9) / 0.1, (0.08 - lum) / 0.08), 0, 1) * (saturation < 0.12)
    weight *= 1 - extreme
    rgb[shown] = rgb[shown] + (mapped[shown] - rgb[shown]) * weight[shown][:, None]
    pixels[..., :3] = rgb
    return Image.fromarray(np.clip(pixels, 0, 255).astype('uint8'), 'RGBA')
