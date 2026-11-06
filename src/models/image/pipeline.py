"""Load, configure and release diffusers image pipelines on CUDA."""
from __future__ import annotations
import gc
import json
import os
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
        # A model whose transformer comes from a GGUF file never has the repository's own transformer downloaded,
        # so the snapshot counts as incomplete; the snapshot folder itself is still there.
        repo = Path(cache)/('models--'+model.replace('/', '--'))
        try:
            snapshot = repo/'snapshots'/(repo/'refs'/'main').read_text(encoding='utf-8').strip()
        except OSError:
            return None
        if not snapshot.is_dir():
            return None
    return Path(cache)/'quantized-nf4'/model.replace('/', '--')/snapshot.name


def source_weights(folder, name):
    """What a saved component was made from: the content names (blob hashes) of the original snapshot's weight files.
    `folder` is a saved model's folder, quantized-nf4/<model>/<snapshot>; the original sits at models--<model>."""
    original = folder.parent.parent.parent/('models--'+folder.parent.name)/'snapshots'/folder.name/name
    try:
        return frozenset(Path(os.readlink(f)).name if f.is_symlink() else f"{f.name}:{f.stat().st_size}" for f in original.glob("*.safetensors")) or None
    except OSError:
        return None


def saved_component(folder, name):
    """The saved 4-bit `name` of this model, or of another model with exactly the same weights (Qwen Image and Qwen
    Image Edit share their text encoder), so a component already quantized once is never read at full size again."""
    if (folder/name/'.complete').is_file():
        return folder/name
    wanted = source_weights(folder, name)
    if not wanted:
        return None
    for other in folder.parent.parent.glob(f'*/*/{name}/.complete'):
        if other.parent.parent != folder and source_weights(other.parent.parent, name) == wanted:
            return other.parent
    return None


def load_quantized(folder, components, torch):
    """{name: component} for every component already saved in 4-bit (by this model or one with the same weights)."""
    import importlib
    loaded = {}
    for name in components:
        place = saved_component(folder, name)
        if place is None:
            continue
        try:
            meta = json.loads((place/'.complete').read_text(encoding='utf-8'))
            cls = getattr(importlib.import_module(meta['module']), meta['class'])
            # straight onto the GPU: staged in RAM first, a 4-bit 7B encoder holds ~7 GB of Windows commit for the whole load
            loaded[name] = cls.from_pretrained(place, torch_dtype=torch.bfloat16, device_map='cuda')
            if place.parent != folder:
                print(f'Reusing the saved 4-bit {name} of {place.parent.parent.name} (same weights).', flush=True)
        except Exception as exc:
            print(f'Saved 4-bit {name} could not be loaded ({exc}); quantizing it from the original checkpoint.', flush=True)
            loaded.pop(name, None);gc.collect();torch.cuda.empty_cache()
            # only a broken copy of this model's own is removed: never another model's, never over a memory error
            if place.parent == folder and not isinstance(exc, (OSError, MemoryError)) and 'out of memory' not in str(exc).lower():
                shutil.rmtree(place, ignore_errors=True)
    return loaded


def save_quantized(pipe, folder, components):
    try:
        for name in components:
            component = getattr(pipe, name)
            target = folder/name
            if saved_component(folder, name) is not None:continue
            staging = folder/(name+'.partial')
            shutil.rmtree(staging, ignore_errors=True)
            component.save_pretrained(staging)  # default shards: smaller ones split 4-bit stats from their layers
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
    required = int(spec['vram_gib']*2**30)
    if spec.get('quantize') or spec.get('gguf'):
        # 4-bit weights cannot move to RAM, so a model that does not fit would spill into shared GPU memory (very
        # slow) or run out at its first step: wait for other programs to free the card instead
        wait_for_gpu_memory(spec, int(spec.get('peak_gib', spec['vram_gib'])*2**30)+int(.5*2**30), torch)
    free, _ = gpu_memory.dedicated_memory(torch)
    if free < 1.*2**30:
        raise ValueError(f'Only {free/2**30:.1f} GiB of GPU memory is free; close other GPU programs and retry.')
    if free < required + .5*2**30:
        offload = True
        # 4-bit (quantised) weights must stay on the GPU, so only unquantised models can move parts to RAM.
        print(f'GPU-only estimate: {spec["vram_gib"]} GiB plus 0.5 GiB reserve; {free/2**30:.1f} GiB is free. '
              + ('Loading anyway: 4-bit weights cannot be offloaded to RAM.' if spec.get('quantize') else 'Enabling automatic RAM offload.'),
              flush=True)
    _, total = gpu_memory.dedicated_memory(torch)
    limit=min(.98,(free+torch.cuda.memory_allocated()-.5*2**30)/total)
    torch.cuda.set_per_process_memory_fraction(max(.01,limit))
    pipeline_type = getattr(diffusers, spec['pipeline'])
    options = dict(torch_dtype=torch.bfloat16, cache_dir=cache, device_map='cuda',
                   max_memory={torch.cuda.current_device():int(free-.5*2**30)})
    # Qwen's 8-bit modulation layers are restored from the original shards after loading (protect_image_modulation),
    # and the save below runs before that step, so its cached copy is plain NF4 and safe to reuse.
    saved = quantized_folder(model, cache) if spec['quantize'] else None
    # Components already saved in 4-bit are left out of the pipeline load and added after it: loading one costs
    # several GB of Windows commit, and each 10 GB checkpoint shard of the rest needs its own; one after the other fits.
    preloaded = [name for name in spec['quantize'] if saved_component(saved, name) is not None] if saved else []
    to_quantize = [name for name in spec['quantize'] if name not in preloaded]
    if to_quantize:
        options['quantization_config'] = diffusers.PipelineQuantizationConfig(
            quant_backend='bitsandbytes_4bit',
            quant_kwargs=dict(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                              bnb_4bit_compute_dtype=torch.bfloat16),
            components_to_quantize=to_quantize)
    print(f'Loading {model} with CUDA quantization'+(' / saved 4-bit weights' if preloaded and not to_quantize else ' / some saved 4-bit weights' if preloaded else ' / 4-bit weights' if spec['quantize'] else '')
          +(' / automatic RAM offload' if offload and not spec.get('quantize') else ' / GPU resident'),flush=True)
    if spec.get('gguf'):  # a GGUF transformer (already 4-bit): loaded on its own, the rest from the model's repository
        options['transformer'] = gguf_transformer(spec, model, cache, torch)
    try:
        pipe = pipeline_type.from_pretrained(model, **{name: None for name in preloaded}, **options)
    except Exception as exc:
        if 'gated' in str(exc).lower() or '401' in str(exc) or '403' in str(exc):
            raise ValueError(f'Access required: accept the model terms at https://huggingface.co/{model} '
                             'and sign in with hf auth login, then retry.') from exc
        raise
    if saved and to_quantize:
        save_quantized(pipe, saved, to_quantize)
    if preloaded:
        gc.collect();torch.cuda.empty_cache()
        loaded = load_quantized(saved, preloaded, torch)
        if len(loaded) < len(preloaded):
            raise ValueError('Saved 4-bit weights could not be loaded (see the message above); if memory was short, close other apps and start the step again.')
        pipe.register_modules(**loaded)
    for name, component in pipe.components.items():
        placed = {part: str(device) for part, device in (getattr(component,'hf_device_map',None) or {}).items()
                  if str(device) in ('cpu','disk','meta')}
        if placed:
            raise ValueError(f'CUDA model preparation placed part of the {name} on CPU/disk/meta before offload hooks '
                             f'could be installed: {dict(list(placed.items())[:6])}')
        if hasattr(component,'parameters'):
            if any(parameter.device.type!='cuda' for parameter in component.parameters()):
                raise ValueError('Image weights must finish CUDA preparation before automatic offload hooks can be installed.')
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
    if spec['pipeline'] in QWEN_PIPELINES:
        from models.image.precision import protect_image_modulation
        protect_image_modulation(pipe,model,cache,torch)
    if offload and not spec.get('quantize') and not getattr(pipe, 'hf_device_map', None):
        try:
            pipe.enable_model_cpu_offload(gpu_id=torch.cuda.current_device(), device='cuda')
            print('Automatic image offload enabled: inactive components use RAM; computation stays on CUDA.', flush=True)
        except Exception as exc:
            print(f'Warning: Automatic image offload could not be installed ({exc}).', flush=True)
    pipe.vae.enable_tiling(**VAE_TILES.get(spec['pipeline'], {}))
    if hasattr(pipe.vae,'enable_slicing'):pipe.vae.enable_slicing()
    if spec['pipeline'] in LEAN_TEXT_PIPELINES and saved and saved_component(saved, 'text_encoder') is not None:
        lean_text_encoder(pipe, saved, torch, park_transformer=bool(spec.get('gguf')))
    from core.stopping import stop_at_steps
    stop_at_steps(pipe)
    return pipe, spec['guidance']


def wait_for_gpu_memory(spec, needed, torch, poll=5., sleep=None):
    """Pause until `needed` bytes of dedicated GPU memory are free, telling Studio what is short; Cancel still
    stops the run. Returns the free bytes."""
    import time
    from core.progress import emit
    sleep = sleep or time.sleep
    gc.collect();torch.cuda.empty_cache()
    free, _ = gpu_memory.dedicated_memory(torch)
    if free >= needed:
        return free
    name = spec.get('name') or spec['id']
    shown = None
    while free < needed:
        message = (f'Paused: {name} needs about {needed/2**30:.1f} GiB of free GPU memory and {free/2**30:.1f} GiB '
                   'is free. Close other GPU programs (browsers, games, other AI tools); painting continues on its own.')
        if shown is None or abs(free-shown) > .25*2**30:  # say it again only when the number moves
            print('Warning: '+message, flush=True)
            shown = free
        emit('model', 0, message=message, paused=True, free_gib=round(free/2**30, 1), needed_gib=round(needed/2**30, 1))
        sleep(poll)
        free, _ = gpu_memory.dedicated_memory(torch)
    print(f'GPU memory is free again ({free/2**30:.1f} GiB); loading {name}.', flush=True)
    emit('model', 0, message=f'Loading {name}')
    return free


def gguf_file(repo, name, cache, **download_options):
    """The GGUF file on disk, downloaded only when missing. Asking the Hub first failed every image on 2026-11-04 with
    the file already here: its repository had been renamed and the new one no longer held it. Every snapshot is
    searched, as that failed request also moved the cache's `main` to a commit without the file."""
    from huggingface_hub import hf_hub_download
    folder = Path(cache)/('models--'+repo.replace('/', '--'))
    found = [path for path in sorted(folder.glob(f'snapshots/*/{name}')) if path.is_file()]
    if found:
        return str(found[0])
    legacy_candidates = [
        folder,
        Path(cache)/'models--abenzerps--Qwen-Image-2.1-Uncensored-Quantized',
        Path(cache)/'models--abenzerps--Qwen-Image-2.1-Turbo-Quantized',
    ]
    for leg_folder in legacy_candidates:
        for pattern in (name, '*.gguf'):
            leg_found = [p for p in sorted(leg_folder.glob(f'snapshots/*/{pattern}')) if p.is_file()]
            if leg_found:
                return str(leg_found[0])
    return hf_hub_download(repo, name, cache_dir=cache, **download_options)


def gguf_transformer(spec, model, cache, torch):
    """The transformer from a GGUF file (spec['gguf'] = (repository, file)), with the model's own transformer config."""
    import diffusers
    repo, name = spec['gguf']
    print(f'Loading the {name} transformer from {repo}.', flush=True)
    path = gguf_file(repo, name, cache)
    cls = getattr(diffusers, spec['transformer_class'])
    transformer = cls.from_single_file(path, quantization_config=diffusers.GGUFQuantizationConfig(compute_dtype=torch.bfloat16),
                                       config=model, subfolder='transformer', torch_dtype=torch.bfloat16, cache_dir=cache)
    unpack_small_weights(transformer, torch)
    transformer = transformer.to('cuda')
    if getattr(transformer, 'hf_device_map', None):  # loaded on the CPU, then moved: the map still says CPU
        transformer.hf_device_map = {'': 'cuda'}
    return transformer


def unpack_small_weights(model, torch):
    """diffusers unpacks a GGUF weight only inside its GGUF linear layers; a GGUF file may also store small weights
    of other layers (Qwen Image 2.1's RMS norms) as raw BF16 bytes, which those layers would read as twice as many
    numbers. Unpack them into ordinary weights (a few MB in all)."""
    from diffusers.quantizers.gguf.utils import GGUFLinear, GGUFParameter, dequantize_gguf_tensor
    unpacked = 0
    for module in model.modules():
        if isinstance(module, GGUFLinear):
            continue
        for name, parameter in list(module.named_parameters(recurse=False)):
            if isinstance(parameter, GGUFParameter):
                weight = dequantize_gguf_tensor(parameter).to(torch.bfloat16)
                setattr(module, name, torch.nn.Parameter(weight, requires_grad=False))
                unpacked += 1
    if unpacked:
        print(f'Unpacked {unpacked} small packed weights outside the GGUF layers.', flush=True)


# Qwen Image 2.1's own weights are small (4.6 GB transformer), but at 1536x1024 with reference pictures its
# activations plus the 4-bit Qwen3-VL 8B encoder ran out of memory a few hundred MB short.
LEAN_TEXT_PIPELINES = ('QwenImageEditPlusPipeline', 'QwenImage21Pipeline')
# Qwen Image 2.1's default 256 px tiles left magenta streaks every 192 px. These leave 94% fewer streak pixels and add
# no memory; 768 px left none but took 1.2 GiB more, and 1024 px or no tiles ran out at 1920x1088 with four
# references, as the transformer still holds 13.5 GiB when decoding starts (2026-11-06).
VAE_TILES = {'QwenImage21Pipeline': dict(tile_sample_min_height=512, tile_sample_min_width=512,
                                         tile_sample_stride_height=384, tile_sample_stride_width=384)}


def lean_text_encoder(pipe, saved, torch, park_transformer=False):
    """Qwen Image Edit's 18 GB of weights plus its reference-image activations overflow a 24 GB card. Its text encoder
    (5.5 GB) only reads the prompt: drop it when denoising starts and load it back (saved 4-bit, a few seconds) the
    next time a prompt is read. 4-bit layers cannot be parked in RAM on Windows, so dropping is the way to free it.
    park_transformer: a GGUF transformer (plain tensors, not bitsandbytes) waits in RAM while the prompt is read, so
    reading several reference pictures (Qwen Image 2.1, ~0.7 GB per vision attention block) has the card to itself."""
    encode = pipe.encode_prompt

    def encode_prompt(*args, **kwargs):
        if park_transformer and next(pipe.transformer.parameters()).device.type == 'cuda':
            pipe.transformer.to('cpu')
            gc.collect();torch.cuda.empty_cache()
        if getattr(pipe, 'text_encoder', None) is None:
            loaded = load_quantized(saved, ['text_encoder'], torch)
            if 'text_encoder' not in loaded:
                raise ValueError('The Qwen text encoder could not be loaded back for the next image.')
            pipe.register_modules(text_encoder=loaded['text_encoder'])
        return encode(*args, **kwargs)

    def drop(module, args, kwargs):
        if getattr(pipe, 'text_encoder', None) is not None:
            pipe.register_modules(text_encoder=None)
            gc.collect();torch.cuda.empty_cache()
        if park_transformer and next(module.parameters()).device.type != 'cuda':
            module.to('cuda')

    pipe.encode_prompt = encode_prompt
    pipe.transformer.register_forward_pre_hook(drop, with_kwargs=True)


QWEN_NEGATIVE = ('extra limbs, extra fingers, fused fingers, malformed anatomy, mixed male and female anatomy on one body, '
                 'moustache or beard on a woman, nudity, see-through clothing, lettering, watermark, grainy, noisy, '
                 'pixelated, blurry, over-sharpened, low quality')
QWEN_PIPELINES = ('QwenImageEditPlusPipeline',)  # the 20B transformer and its 4-bit handling


def inference_options(model, references):
    """Pipeline arguments for one picture with the selected base model."""
    spec = model_spec(model)
    if spec['pipeline'] == 'QwenImage21Pipeline':
        # Generates from text alone or with up to max_references pictures; sampled without guidance (its model card)
        return dict(image=list(references)[:spec.get('max_references', 10)] or None, true_cfg_scale=1.)
    if spec['pipeline'] == 'QwenImageEditPlusPipeline':
        # Edits always start from images: the references (at most 3, its trained maximum). Same negative prompt as
        # Qwen Image; true CFG as its model card recommends.
        if not references:
            raise ValueError('Qwen Image Edit needs a reference image; add one (for example your main character) '
                             'or choose another image model.')
        return dict(image=list(references)[:3], true_cfg_scale=spec['guidance'], max_sequence_length=1024,
                    negative_prompt=QWEN_NEGATIVE)
    if spec['references']:
        from direction.prompt_fit import FLUX_TOKENS
        return dict(image=references or None, guidance_scale=spec['guidance'], max_sequence_length=FLUX_TOKENS)
    result = dict(guidance_scale=spec['guidance'])
    return result


def release_pipeline(pipe, torch):
    try:
        torch.cuda.synchronize()
    finally:
        if pipe is not None:
            pipe.maybe_free_model_hooks()
