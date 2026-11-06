"""Curated local image models; metadata shared by the CLI and studio."""
# Only models that take reference pictures are offered: the recurring characters, objects and places and the
# user's own pictures are given to every image as pictures.
MODEL = 'Qwen/Qwen-Image-2.1'
MODELS = [
    # The 4-bit (Q4_K_M) base transformer from abenzerps/Qwen-Image-2.1-Uncensored-Quantized, not the Turbo build: at
    # these 40 steps Turbo mottled skin and frayed hair at every size, on 2026-11-05 (safetensors-free
    # GGUF, no code), with the text encoder, VAE and configs from Qwen's own repository. Qwen Research licence:
    # non-commercial use only; Qwen Image Edit 2511 (Apache 2.0) is the choice for commercial work. peak_gib: the
    # whole run at 1920x1088 with four references (weights 12 GB, plus reading the pictures or painting).
    # max_references: a hard limit of 4, though the model reads 10: four at 1920x1088 already peaked at 20 GiB on a
    # 24 GB card, on 2026-11-06.
    dict(id='Qwen/Qwen-Image-2.1', name='Qwen Image 2.1 Uncensored (Q4_K_M)', pipeline='QwenImage21Pipeline', steps=40, guidance=1., references=True, max_references=4, quantize=['text_encoder'], gguf=('abenzerps/Qwen-Image-2.1-Uncensored-Quantized', 'qwen-image-2.1-UC-Q4_K_M.gguf'), transformer_class='QwenImage21Transformer2DModel', vram_gib=12, peak_gib=20, disk_gb=26, license='Qwen Research licence: non-commercial (research or evaluation) use only', description='Generates and edits with up to 4 reference pictures and keeps people recognisable; uncensored, 4-bit. Non-commercial use only: choose Qwen Image Edit 2511 for commercial work.'),
    dict(id='black-forest-labs/FLUX.2-klein-4B', name='FLUX.2 Klein 4B', pipeline='Flux2KleinPipeline', steps=4, guidance=1., references=True, quantize=[], vram_gib=18, disk_gb=22, license='Apache 2.0', description='Fast illustration and reference-image support.'),
    dict(id='black-forest-labs/FLUX.2-klein-9B', name='FLUX.2 Klein 9B', pipeline='Flux2KleinPipeline', steps=4, guidance=1., references=True, quantize=['transformer','text_encoder'], vram_gib=16, disk_gb=40, license='FLUX non-commercial / gated', description='More detail; 4-bit loading; GPU-only execution.'),
    dict(id='Qwen/Qwen-Image-Edit-2511', name='Qwen Image Edit 2511', pipeline='QwenImageEditPlusPipeline', steps=40, guidance=4., references=True, quantize=['transformer','text_encoder'], vram_gib=20, disk_gb=62, license='Apache 2.0', description='Qwen\'s editing model guided by reference pictures; steadier characters and less drift than 2509.'),
]

# Removed: no reference pictures, or replaced by a newer model. A project made with one reads as the default.
REMOVED = ('krea/Krea-2-Turbo', 'Qwen/Qwen-Image-Edit-2509', 'Tongyi-MAI/Z-Image-Turbo', 'Qwen/Qwen-Image-2512',
           'black-forest-labs/FLUX.1-schnell')


def selected_model(job, config):
    """The image model chosen in the studio now; artwork made earlier with another model is redone with it. A model
    no longer offered gives way to the default."""
    offered = {spec['id'] for spec in MODELS}
    for model in ((config or {}).get('image_model'), job.get('model')):
        if model in offered:
            return model
    return MODEL


def model_spec(model):
    if model in REMOVED:
        model = MODEL
    for spec in MODELS:
        if spec['id'] == model:
            return spec
    if model == 'black-forest-labs/FLUX.2-dev':
        return dict(id=model, pipeline='Flux2Pipeline', guidance=4., references=True,
                    quantize=['transformer','text_encoder'], vram_gib=28, disk_gb=113)
    raise ValueError('Unsupported image model: '+model)


def image_dimensions(width,height,total_gib,ceiling=None):
    """Bound activation memory on smaller cards; preserve aspect ratio."""
    if ceiling is None:ceiling=512*512 if total_gib<12 else 1024*1024 if total_gib<20 else 1536*1024
    if width*height<=ceiling:return width,height
    scale=(ceiling/(width*height))**.5
    return max(64,int(width*scale)//64*64),max(64,int(height*scale)//64*64)


def sheet_dimensions(width,height,total_gib):
    """The canvas of a reference sheet (direction.entities.sheet_size): larger than a scene's, since the scene is
    given one view cut from it, and that view must be clear. 1440p on a 20 GiB card or more (within the 2K the
    models paint natively), 1080p on a 12 GiB one, 720p below."""
    ceiling=1280*720 if total_gib<12 else 1920*1088 if total_gib<20 else 2560*1440
    return image_dimensions(width,height,total_gib,ceiling)
