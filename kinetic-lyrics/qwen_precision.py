"""Protect Qwen's image-stream modulation from accumulating 4-bit noise."""
from collections import defaultdict
import json
import logging
from pathlib import Path


def protect_image_modulation(pipe,model,cache,torch):
    import bitsandbytes as bnb
    from huggingface_hub import snapshot_download
    from safetensors import safe_open
    class ExpectedCastFilter(logging.Filter):
        def filter(self,record):return not record.getMessage().startswith('MatMul8bitLt: inputs will be cast')
    logging.getLogger('bitsandbytes.autograd._functions').addFilter(ExpectedCastFilter())
    snapshot=Path(snapshot_download(model,cache_dir=cache,local_files_only=True))/'transformer'
    index=next(snapshot.glob('*.safetensors.index.json'),None)
    if index is None:raise ValueError('Qwen transformer weight index is missing; complete its model download first.')
    mapping=json.loads(index.read_text(encoding='utf-8'))['weight_map']
    targets=[name for name,module in pipe.transformer.named_modules() if name.endswith('.img_mod.1')]
    if not targets:raise ValueError('Cannot locate Qwen image-modulation layers; refusing the grain-prone uniform 4-bit path.')
    groups=defaultdict(list)
    for name in targets:
        key=name+'.weight'
        if key not in mapping:raise ValueError('Original modulation weights are missing: '+key)
        groups[mapping[key]].append((name,key))
    converted=0
    for filename,layers in groups.items():
        with safe_open(snapshot/filename,framework='pt',device='cpu') as weights:
            for name,key in layers:
                old=pipe.transformer.get_submodule(name)
                device=old.weight.device
                if device.type!='cuda':raise ValueError('Qwen modulation must be restored on CUDA.')
                new=bnb.nn.Linear8bitLt(old.in_features,old.out_features,bias=old.bias is not None,
                                       has_fp16_weights=False,threshold=6.0)
                new.weight=bnb.nn.Int8Params(weights.get_tensor(key),requires_grad=False,has_fp16_weights=False)
                if old.bias is not None:new.bias=torch.nn.Parameter(old.bias.detach().clone(),requires_grad=False)
                new=new.to(device).eval()
                parent,attribute=name.rsplit('.',1)
                setattr(pipe.transformer.get_submodule(parent),attribute,new)
                del old,new
                converted+=1
                if converted%10==0:torch.cuda.empty_cache()
    torch.cuda.empty_cache()
    print(f'Protected {converted} Qwen image-modulation layers at 8-bit; other large layers remain 4-bit.',flush=True)
    return converted
