"""Load the image-to-video models through Modular Diffusers and turn one picture into frames.

Both models only ship as Modular Diffusers blocks, which are on diffusers `main` and not in the
release that requirements.txt pins for the image models. They therefore run in their own Python
environment (see setup.ps1 in this folder); `step.video_python` picks it up automatically.
"""
from __future__ import annotations
import gc

TEXT_COMPONENTS = ('text_encoder', 'tokenizer', 'connectors')


class LTXStages:
    """LTX-2.5's video stage plus the text conditioning already computed for every prompt of the job."""

    def __init__(self, pipe, encoded):
        self.pipe, self.encoded = pipe, encoded


def load(spec, cache, torch, prompts=()):
    """The model ready to animate; for LTX-2.5 `prompts` (every prompt the job will use) are encoded first."""
    if not torch.cuda.is_available():
        raise ValueError('CUDA is required for video generation.')
    try:
        from diffusers import ModularPipeline
        from diffusers.modular_pipelines import ComponentsManager
        if spec['loader'] == 'ltx':
            from diffusers import LTX2Guidance  # noqa: F401
    except ImportError as exc:
        raise ValueError(f'Video generation needs Modular Diffusers from diffusers main ({exc}). '
                         'Run src/video_generation/setup.ps1 to create the video environment.') from exc
    _check_access(spec['id'], cache)
    print(f"Loading {spec['id']}; first use downloads about {spec['disk_gb']} GB.", flush=True)
    try:
        if spec['loader'] == 'ltx':
            return _load_ltx(spec, cache, torch, prompts)
        from video_generation.model_files import fetch, local_sources
        manager = ComponentsManager()
        pipe = ModularPipeline.from_pretrained(spec['id'], components_manager=manager, cache_dir=str(cache))
        # The first-frame workflow's components; `transformer_ref` belongs to the reference workflow.
        used = {c.name for c in pipe.blocks.get_workflow(spec['workflow']).expected_components}
        names = [n for n in pipe.pretrained_component_names if n in used]
        # Download first, resumably, into a plain folder; then load from it rather than through the hub cache.
        root = fetch(spec['id'], names, cache)
        pipe.load_components(names=names, dtype=torch.bfloat16,
                             pretrained_model_name_or_path=local_sources(root, spec['id'], names))
        _require(pipe, names, spec)
        _int8(pipe, torch)
        manager.enable_auto_cpu_offload(device='cuda', memory_reserve_margin='4GB')
        return pipe
    except Exception as exc:
        if 'gated' in str(exc).lower() or '401' in str(exc) or '403' in str(exc):
            raise ValueError(f"Access required: accept the model terms at https://huggingface.co/{spec['id']} "
                             'and sign in with hf auth login, then retry.') from exc
        raise


def _load_ltx(spec, cache, torch, prompts):
    """LTX-2.5 in two stages that each fit a 24 GB card and 32 GB of RAM.

    In bf16 the pipeline needs ~78 GB of system RAM (the loader keeps every component there) and Windows kills
    the worker with 0xC0000005. So the 22B transformer and the text encoder load as 4-bit weights streamed onto
    the GPU one shard at a time. 4-bit weights cannot use the automatic CPU offload (moving them to the CPU
    crashes natively on Windows), and both together leave no room for the 6 GB connectors, so the text stage
    (text encoder + connectors, ~17 GB at peak) encodes every prompt of the job first and is freed; the video
    stage (transformer + decoders, ~13 GB) then runs from those stored encodings. The prompt enhancer
    (opt-in via enable_prompt_enhancement, never used here) is not loaded at all."""
    from diffusers import LTX2Guidance, ModularPipeline
    from diffusers.pipelines.ltx2.utils import DEFAULT_NEGATIVE_PROMPT
    from core.progress import emit
    from video_generation.model_files import fetch, local_sources
    from diffusers.modular_pipelines.ltx2.modular_blocks_ltx2 import LTX2AutoDecoderStep
    blocks = ModularPipeline.from_pretrained(spec['id'], cache_dir=str(cache)).blocks
    text_blocks = blocks.sub_blocks.pop('text_encoder')
    blocks.sub_blocks.pop('prompt_enhancer', None)
    # Decode with the convolutional VAE (documented swap). LTX-2.5's default diffusion decoder uses neighbourhood
    # attention through flex_attention, which needs Triton; without it (Windows) PyTorch materialises the whole
    # attention and the decode asks for ~9 GB more than the card has, whatever the tile size.
    blocks.sub_blocks['decode'] = LTX2AutoDecoderStep()
    # Everything the text stage produces that the video stage reads (connector embeddings, masks, batch size, dtype).
    conditioning = [o.name for o in text_blocks.intermediate_outputs if o.name in {i.name for i in blocks.inputs}]
    text, video = text_blocks.init_pipeline(spec['id']), blocks.init_pipeline(spec['id'])
    text_names = list(TEXT_COMPONENTS)
    video_names = [n for n in video.pretrained_component_names
                   if n not in ('prompt_enhancer', 'processor', *TEXT_COMPONENTS)]
    root = fetch(spec['id'], text_names+video_names, cache)
    nf4 = _nf4(torch)

    unique = list(dict.fromkeys(prompts))
    emit('video', 0, message=f'Encoding {len(unique)} motion prompt(s)')
    text.load_components(names=text_names, dtype=torch.bfloat16,
                         pretrained_model_name_or_path=local_sources(root, spec['id'], text_names),
                         quantization_config={'text_encoder': nf4['text_encoder']})
    _require(text, text_names, spec)
    text.connectors.to('cuda')
    encoded = {}
    with torch.no_grad():
        for prompt in unique:
            result = text(prompt=prompt, negative_prompt=DEFAULT_NEGATIVE_PROMPT, output=conditioning)
            encoded[prompt] = {k: v.to('cpu') if hasattr(v, 'to') else v for k, v in result.items()}
    del text, result
    gc.collect()
    torch.cuda.empty_cache()
    print(f'Encoded {len(unique)} prompt(s); text stage released.', flush=True)

    emit('video', 0, message=f"Loading {spec['name']} video stage")
    video.load_components(names=video_names, dtype=torch.bfloat16,
                          pretrained_model_name_or_path=local_sources(root, spec['id'], video_names),
                          quantization_config={'transformer': nf4['transformer']})
    _require(video, video_names, spec)
    for name in video_names:
        component = getattr(video, name)
        if name != 'transformer' and isinstance(component, torch.nn.Module):
            component.to('cuda')  # small; the 4-bit transformer is already on the GPU
    # The distilled checkpoint is unguided: one transformer pass per step.
    video.update_components(guider=LTX2Guidance(guidance_scale=1.), audio_guider=LTX2Guidance(guidance_scale=1.))
    video.vae.enable_tiling()
    return LTXStages(video, encoded)


def _require(pipe, names, spec):
    """load_components only logs a component that fails and carries on; the run would then die later with an
    unrelated error, so stop here with the real cause (logged just above)."""
    missing = [n for n in names if getattr(pipe, n, None) is None]
    if missing:
        raise ValueError(f"{spec['name']} could not load {', '.join(missing)}; see the error logged above.")


def _nf4(torch):
    """Per-component 4-bit settings for LTX-2.5: the transformer is a diffusers model, the text encoder a
    transformers one, and each library takes its own config class."""
    try:
        import bitsandbytes  # noqa: F401
        import diffusers
        import transformers
    except ImportError as exc:
        raise ValueError('LTX-2.5 needs bitsandbytes for 4-bit loading; run src/video_generation/setup.ps1.') from exc
    options = dict(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.bfloat16)
    return {'transformer': diffusers.BitsAndBytesConfig(**options),
            'text_encoder': transformers.BitsAndBytesConfig(**options)}


def _check_access(model, cache):
    """Fail with the real reason on a gated repo; diffusers reports a 403 as 'could not find model_index.json'."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError
    try:
        hf_hub_download(model, 'model_index.json', cache_dir=str(cache))
    except GatedRepoError as exc:
        raise ValueError(f'Access required: request access to the model at https://huggingface.co/{model} '
                         '(signed in with the same account as hf auth login), wait for approval, then retry.') from exc
    except RepositoryNotFoundError as exc:
        raise ValueError(f'Model {model} was not found on Hugging Face, or this account cannot see it; '
                         'check hf auth login.') from exc
    except Exception:
        pass  # offline or transient: let the normal load use the local cache or report its own error


def _int8(pipe, torch):
    """8-bit weights for the large components so the 33B transformer and its Qwen3-VL encoder fit a consumer card."""
    try:
        from torchao.quantization import Int8WeightOnlyConfig, quantize_
    except ImportError as exc:
        raise ValueError('MiniMax H3 needs torchao for 8-bit weights; run src/video_generation/setup.ps1.') from exc
    for name, component in dict(getattr(pipe, 'components', {}) or {}).items():
        if isinstance(component, torch.nn.Module) and sum(p.numel() for p in component.parameters()) > 2e9:
            print(f'Quantizing {name} to 8-bit weights.', flush=True)
            quantize_(component, Int8WeightOnlyConfig())
            gc.collect()


def animate(pipe, spec, image, prompt, seed, torch, num_frames=None):
    """Frames (uint8, frames × height × width × 3) that start from `image` and move as `prompt` describes;
    `num_frames` (an 8k+1 count) defaults to the model's standard clip length."""
    generator = torch.Generator('cpu').manual_seed(seed)
    num_frames = num_frames or spec['frames']
    if spec['loader'] == 'ltx':
        from diffusers.pipelines.ltx2.utils import DISTILLED_SIGMA_VALUES
        if prompt not in pipe.encoded:
            raise ValueError('This prompt was not encoded when the model loaded; pass every prompt to load().')
        conditioning = {k: v.to('cuda') if hasattr(v, 'to') else v for k, v in pipe.encoded[prompt].items()}
        # The generated soundtrack is requested only because the pipeline returns both; the song is the audio.
        result = pipe.pipe(image=image, width=image.width, height=image.height, num_frames=num_frames,
                           frame_rate=float(spec['fps']), sigmas=DISTILLED_SIGMA_VALUES, generator=generator,
                           output_type='np', output=['videos', 'audio'], **conditioning)
    else:
        result = pipe(prompt=prompt, image=image, num_frames=num_frames, generator=generator,
                      output=['videos', 'audio', 'sampling_rate'])
    return frames_array(result['videos'][0])


def frames_array(video):
    """Normalise a pipeline's video (tensor, array or list of PIL images) to uint8 frames × H × W × RGB."""
    import numpy as np
    if hasattr(video, 'detach'):
        video = video.detach().float().cpu().numpy()
    elif isinstance(video, (list, tuple)) and video and hasattr(video[0], 'convert'):
        video = np.stack([np.asarray(frame.convert('RGB')) for frame in video])
    video = np.asarray(video)
    if video.ndim != 4:
        raise ValueError(f'Unexpected video shape {video.shape}')
    if video.shape[-1] != 3:
        video = np.moveaxis(video, 1 if video.shape[1] == 3 else 0, -1)
    if video.dtype != np.uint8:
        if video.min() < 0:
            video = (video+1)/2
        video = (np.clip(video, 0, 1)*255+.5).astype(np.uint8)
    return np.ascontiguousarray(video)


def release(pipe, torch):
    try:
        torch.cuda.synchronize()
    finally:
        del pipe
        gc.collect()
        torch.cuda.empty_cache()
