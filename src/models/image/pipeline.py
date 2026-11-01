"""Load, configure and release diffusers image pipelines on CUDA."""
from __future__ import annotations
import gc
import json
from pathlib import Path
import shutil
import models.gpu.memory as gpu_memory
from models.image.catalog import model_spec


def quantized_folder(model, cache):
    """Per-snapshot home for NF4 weights, so later loads skip reading and quantizing the bf16 checkpoint."""
    from huggingface_hub import snapshot_download
    try:
        snapshot = Path(snapshot_download(model, cache_dir=cache, local_files_only=True))
    except Exception:
        return None
    return Path(cache)/'quantized-nf4'/model.replace('/', '--')/snapshot.name


def load_quantized(folder, components, torch):
    if not all((folder/name/'.complete').is_file() for name in components):
        return {}
    import importlib
    loaded = {}
    try:
        for name in components:
            meta = json.loads((folder/name/'.complete').read_text(encoding='utf-8'))
            cls = getattr(importlib.import_module(meta['module']), meta['class'])
            loaded[name] = cls.from_pretrained(folder/name, torch_dtype=torch.bfloat16)
    except Exception as exc:
        print(f'Saved 4-bit weights could not be loaded ({exc}); quantizing from the original checkpoint.', flush=True)
        loaded.clear();gc.collect();torch.cuda.empty_cache()
        shutil.rmtree(folder, ignore_errors=True)
    return loaded


def save_quantized(pipe, folder, components):
    try:
        for name in components:
            component = getattr(pipe, name)
            target = folder/name
            if (target/'.complete').is_file():continue
            staging = folder/(name+'.partial')
            shutil.rmtree(staging, ignore_errors=True)
            component.save_pretrained(staging)
            (staging/'.complete').write_text(json.dumps({'module': type(component).__module__, 'class': type(component).__name__}), encoding='utf-8')
            shutil.rmtree(target, ignore_errors=True)
            staging.replace(target)
        print(f'Saved 4-bit weights to {folder}; later loads skip quantization.', flush=True)
    except Exception as exc:
        print(f'Warning: could not save 4-bit weights ({exc}); the next load will quantize again.', flush=True)


def load_pipeline(model, cache, torch, offload=False):
    """Quantize on CUDA; offload inactive components to RAM under pressure."""
    import diffusers
    spec = model_spec(model)
    if not torch.cuda.is_available():
        raise ValueError('CUDA is required. CPU fallback is disabled.')
    free, _ = gpu_memory.dedicated_memory(torch)
    required = int(spec['vram_gib']*2**30)
    if free < required + .5*2**30:
        offload = True
        print(f'GPU-only estimate: {spec["vram_gib"]} GiB plus 0.5 GiB reserve; '
              f'{free/2**30:.1f} GiB is free. Enabling automatic RAM offload.',flush=True)
    _, total = gpu_memory.dedicated_memory(torch)
    limit=min(.98,(free+torch.cuda.memory_allocated()-.5*2**30)/total)
    torch.cuda.set_per_process_memory_fraction(max(.01,limit))
    pipeline_type = getattr(diffusers, spec['pipeline'])
    options = dict(torch_dtype=torch.bfloat16, cache_dir=cache, device_map='cuda',
                   max_memory={torch.cuda.current_device():int(free-.5*2**30)})
    # Qwen's 8-bit modulation layers are restored from the original shards after loading (protect_image_modulation),
    # and the save below runs before that step, so its cached copy is plain NF4 and safe to reuse.
    saved = quantized_folder(model, cache) if spec['quantize'] else None
    preloaded = load_quantized(saved, spec['quantize'], torch) if saved else {}
    if spec['quantize'] and not preloaded:
        options['quantization_config'] = diffusers.PipelineQuantizationConfig(
            quant_backend='bitsandbytes_4bit',
            quant_kwargs=dict(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                              bnb_4bit_compute_dtype=torch.bfloat16),
            components_to_quantize=spec['quantize'])
    print(f'Loading {model} with CUDA quantization'+(' / saved 4-bit weights' if preloaded else ' / 4-bit weights' if spec['quantize'] else '')
          +(' / automatic RAM offload' if offload else ' / GPU resident'),flush=True)
    try:
        pipe = pipeline_type.from_pretrained(model, **preloaded, **options)
    except Exception as exc:
        if 'gated' in str(exc).lower() or '401' in str(exc) or '403' in str(exc):
            raise ValueError(f'Access required: accept the model terms at https://huggingface.co/{model} '
                             'and sign in with hf auth login, then retry.') from exc
        raise
    for component in pipe.components.values():
        for device in getattr(component,'hf_device_map',{}).values():
            if str(device) in ('cpu','disk','meta'):
                raise ValueError('CUDA model preparation placed a component on CPU/disk/meta before offload hooks could be installed.')
        if hasattr(component,'parameters'):
            if any(parameter.device.type!='cuda' for parameter in component.parameters()):
                raise ValueError('Image weights must finish CUDA preparation before automatic offload hooks can be installed.')
    if saved and not preloaded:
        save_quantized(pipe, saved, spec['quantize'])
    remaining, _ = gpu_memory.dedicated_memory(torch)
    if not spec.get('quantize'):
        offload = offload or remaining < 3*2**30
        if offload:
            staged=[]
            for name,component in pipe.components.items():
                if name not in ('transformer','unet') and hasattr(component,'parameters'):
                    component.to('cpu');staged.append(name)
            if staged:
                gc.collect();torch.cuda.empty_cache()
                print('Staged inactive components in RAM before image-layer preparation: '+', '.join(staged),flush=True)
    if spec['pipeline']=='QwenImagePipeline':
        from models.image.precision import protect_image_modulation
        protect_image_modulation(pipe,model,cache,torch)
    if offload and not spec.get('quantize') and not getattr(pipe, 'hf_device_map', None):
        try:
            pipe.enable_model_cpu_offload(gpu_id=torch.cuda.current_device(), device='cuda')
            print('Automatic image offload enabled: inactive components use RAM; computation stays on CUDA.', flush=True)
        except Exception as exc:
            print(f'Warning: Automatic image offload could not be installed ({exc}).', flush=True)
    pipe.vae.enable_tiling()
    if hasattr(pipe.vae,'enable_slicing'):pipe.vae.enable_slicing()
    return pipe, spec['guidance']


def inference_options(model, references):
    spec = model_spec(model)
    if spec['references']:
        from direction.prompt_fit import FLUX_TOKENS
        return dict(image=references or None, guidance_scale=spec['guidance'], max_sequence_length=FLUX_TOKENS)
    if spec['pipeline'] == 'QwenImagePipeline':
        return dict(true_cfg_scale=spec['guidance'], max_sequence_length=1024, negative_prompt=
                    'extra limbs, extra fingers, fused fingers, malformed anatomy, mixed male and female anatomy on one body, moustache or beard on a woman, nudity, see-through clothing, lettering, watermark, grainy, noisy, pixelated, blurry, over-sharpened, low quality')
    result = dict(guidance_scale=spec['guidance'])
    if spec['pipeline'] == 'FluxPipeline':
        result['max_sequence_length'] = 512
    return result


def release_pipeline(pipe, torch):
    try:
        torch.cuda.synchronize()
    finally:
        if pipe is not None:
            pipe.maybe_free_model_hooks()
