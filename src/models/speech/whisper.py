"""Whisper (stable-ts) model loading and memory release."""
from __future__ import annotations
from pathlib import Path
from core.paths import PROJECT_ROOT
import sys


def whisper_model(args):
    try:
        import stable_whisper
    except ImportError as exc:
        raise ValueError("Whisper transcription/alignment needs stable-ts. Install requirements.txt "
                         "or supply --timings with reviewed word timestamps.") from exc
    return stable_whisper.load_model(args.model, device=args.device,
        download_root=str((Path(getattr(args,'image_cache',None) or PROJECT_ROOT/'.cache')/'speech'/'whisper').resolve()))


def release_whisper_memory():
    import gc
    gc.collect()
    if 'torch' in sys.modules and sys.modules['torch'].cuda.is_available():
        sys.modules['torch'].cuda.empty_cache()
