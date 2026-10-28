"""Curated local image models; metadata shared by the CLI and studio."""
MODEL = 'Qwen/Qwen-Image-2512'
MODELS = [
    dict(id='black-forest-labs/FLUX.2-klein-4B', name='FLUX.2 Klein 4B', pipeline='Flux2KleinPipeline', steps=4, guidance=1., references=True, quantize=[], vram_gib=18, disk_gb=22, license='Apache 2.0', description='Fast illustration and reference-image support.'),
    dict(id='black-forest-labs/FLUX.2-klein-9B', name='FLUX.2 Klein 9B', pipeline='Flux2KleinPipeline', steps=4, guidance=1., references=True, quantize=['transformer','text_encoder'], vram_gib=16, disk_gb=40, license='FLUX non-commercial / gated', description='More detail; 4-bit loading; GPU-only execution.'),
    dict(id='Tongyi-MAI/Z-Image-Turbo', name='Z-Image Turbo', pipeline='ZImagePipeline', steps=9, guidance=0., references=False, quantize=['transformer','text_encoder'], vram_gib=6.5, disk_gb=30, license='Apache 2.0', description='Fast generation. Written style only; no image conditioning.'),
    dict(id=MODEL, name='Qwen Image 2512', pipeline='QwenImagePipeline', steps=50, guidance=2.8, references=False, quantize=['transformer','text_encoder'], vram_gib=20, disk_gb=65, license='Apache 2.0', description='Detailed rendering; 4-bit weights with protected 8-bit image-modulation layers. CUDA inference with automatic RAM offload when needed. Written style only.'),
    dict(id='black-forest-labs/FLUX.1-schnell', name='FLUX.1 Schnell', pipeline='FluxPipeline', steps=4, guidance=0., references=False, quantize=['transformer','text_encoder_2'], vram_gib=14, disk_gb=40, license='Apache 2.0 / gated', description='Fast alternative with 4-bit loading. Written style only.'),
]

def model_spec(model):
    for spec in MODELS:
        if spec['id'] == model:
            return spec
    if model == 'black-forest-labs/FLUX.2-dev':
        return dict(id=model, pipeline='Flux2Pipeline', guidance=4., references=True,
                    quantize=['transformer','text_encoder'], vram_gib=28, disk_gb=90)
    raise ValueError('Unsupported image model: '+model)
