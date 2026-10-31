"""Load the image-to-video models through Modular Diffusers and turn one picture into frames.

Both models only ship as Modular Diffusers blocks, which are on diffusers `main` and not in the
release that requirements.txt pins for the image models. They therefore run in their own Python
environment (see setup.ps1 in this folder); `step.video_python` picks it up automatically.
"""
from __future__ import annotations
import gc

MOTION = ('The camera drifts slowly and steadily. Gentle, continuous natural motion in hair, fabric, foliage, water, light '
              'and atmosphere. The composition, characters and colours stay the same as the first frame; no cuts, no new '
              'objects, no text or lettering.')


def load(spec, cache, torch):
    if not torch.cuda.is_available():
        raise ValueError('CUDA is required for video generation.')
    try:
        from diffusers import ModularPipeline
        from diffusers.modular_pipelines import ComponentsManager
    except ImportError as exc:
        raise ValueError('Video generation needs Modular Diffusers from diffusers main. '
                         'Run src/video_generation/setup.ps1 to create the video environment.') from exc
    manager = ComponentsManager()
    print(f"Loading {spec['id']}; first use downloads about {spec['disk_gb']} GB.", flush=True)
    try:
        pipe = ModularPipeline.from_pretrained(spec['id'], components_manager=manager, cache_dir=str(cache))
        if spec['loader'] == 'ltx':
            pipe.load_components(dtype=torch.bfloat16)
            from diffusers.modular_pipelines.ltx2.guider import LTX2Guidance
            # The distilled checkpoint is unguided: one transformer pass per step.
            pipe.update_components(guider=LTX2Guidance(guidance_scale=1.), audio_guider=LTX2Guidance(guidance_scale=1.))
            decoder = getattr(pipe, 'diffusion_decoder', None)
            if decoder is not None:
                decoder.enable_tiling()
            manager.enable_auto_cpu_offload(device='cuda', memory_reserve_margin='4GB')
        else:
            pipe.load_components(workflow=spec['workflow'], dtype=torch.bfloat16)
            _int8(pipe, torch)
            manager.enable_auto_cpu_offload(device='cuda', memory_reserve_margin='4GB')
    except Exception as exc:
        if 'gated' in str(exc).lower() or '401' in str(exc) or '403' in str(exc):
            raise ValueError(f"Access required: accept the model terms at https://huggingface.co/{spec['id']} "
                             'and sign in with hf auth login, then retry.') from exc
        raise
    return pipe


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


def animate(pipe, spec, image, prompt, seed, torch):
    """Frames (uint8, frames × height × width × 3) that start from `image` and move as `prompt` describes."""
    generator = torch.Generator('cpu').manual_seed(seed)
    if spec['loader'] == 'ltx':
        from diffusers.pipelines.ltx2.utils import DEFAULT_NEGATIVE_PROMPT, DISTILLED_SIGMA_VALUES
        # The generated soundtrack is requested only because the pipeline returns both; the song is the audio.
        result = pipe(image=image, prompt=prompt, negative_prompt=DEFAULT_NEGATIVE_PROMPT,
                      width=image.width, height=image.height, num_frames=spec['frames'], frame_rate=float(spec['fps']),
                      sigmas=DISTILLED_SIGMA_VALUES, generator=generator, output_type='np', output=['videos', 'audio'])
    else:
        result = pipe(prompt=prompt, image=image, num_frames=spec['frames'], generator=generator,
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
