"""Local image-to-video models that can animate each finished illustration; shared by the CLI and Studio."""
from __future__ import annotations

# Video clips replace whole-frame backdrops only: cutouts need transparency and greenscreen scenery
# needs one key per frame, which these models do not produce.
VIDEO_MODES = ('fullscreen', 'verse')
MODELS = [
    dict(id='Lightricks/LTX-2.5-Diffusers', name='LTX-2.5 (Lightricks)', loader='ltx', workflow=None,
         short_edge=544, long_edge=960, frames=121, chunk_frames=241, fps=24, vram_gib=24, disk_gb=72,
         license='LTX-2.x Community License (free under $10M yearly revenue) / gated',
         description='22B distilled audio-video model. Fast, 5-second clips at 960×544; motion only, the generated audio is discarded.'),
    dict(id='MiniMaxAI/MiniMax-H3', name='MiniMax H3', loader='minimax', workflow='fl2va',
         short_edge=768, long_edge=1344, frames=124, fixed_length=True, fps=24, vram_gib=24, disk_gb=144,
         license='MiniMax H3 Community License: not licensed for use in the US, EU, UK or South Korea',
         description='33B first-frame-to-video model with 8-bit weights and streamed offload. Very slow on one card and needs about 75 GB of system RAM.'),
]


def video_spec(model):
    for spec in MODELS:
        if spec['id'] == model:
            return spec
    raise ValueError('Unsupported video model: '+model)


def clip_size(spec, width, height):
    """The model's native canvas in the video's orientation, in multiples of 32."""
    short, long = spec['short_edge'], spec['long_edge']
    aspect = max(width, height)/min(width, height)
    long = min(long, max(short, round(short*aspect/32)*32))
    return (long, short) if width >= height else (short, long)
