# Kinetic_Lyrics

Generate a music video directly from audio files (like MP3) through AI capabilities.

Kinetic Lyrics aligns supplied lyrics to a song, plans typography and scene art with a
local LLM, generates illustrations with a local image model, reviews them with a local
vision model, and renders a kinetic-typography video with particle transitions.
Everything runs locally, but requires a capable GPU. The goal of this project is to 
achieve visually rich kinetic typography comparable to those manually done using graphic
design tools such as Adobe After Effects.

## Requirements

- Windows with an NVIDIA CUDA GPU (24 GB VRAM recommended)
- Python 3.12
- FFmpeg on `PATH` (NVENC is used when available)
- [Ollama](https://ollama.com) with a text model, plus a vision model for artwork review

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File kinetic-lyrics\setup.ps1
```

This creates `kinetic-lyrics\.venv`, installs CUDA PyTorch and the dependencies in
`requirements.txt`. Model weights download on first use into
`KINETIC_LYRICS_MODEL_CACHE` (default `~/.cache/kinetic-lyrics`). Set
`KINETIC_LYRICS_OUTPUT` to choose where projects are written.

## Studio

```powershell
kinetic-studio.cmd
```

Opens a local web UI at http://127.0.0.1:8765. Upload audio, paste lyrics (or leave
them blank to transcribe), pick style references, models and effects, then review,
replace or regenerate artwork before the video renders. Finished videos can be
partially rebuilt after swapping an image, and earlier exports stay available.

## Command line

```powershell
kinetic-lyrics.cmd song.mp3 lyrics.txt --theme "bright, uplifting" -o output\song.mp4
```

Useful options: `--style-reference a.png b.png`, `--illustrations art.png ...`,
`--no-illustrations`, `--illustration-lines N`, `--language tl`, `--encoder libx264`,
`--render-workers N`. Run with `--help` for the full list.

## Style reference

`kinetic-lyrics/assets/default-style-reference.jpg` is the bundled default art style
reference. Studio preloads it for new sessions and the command line uses it when no
`--style-reference` is given. Pass `--no-default-style-references` to disable it.

## Particle effects

Entrance and exit effects are JSON recipes in `kinetic-lyrics/particles/`. See
[`particles/README.md`](kinetic-lyrics/particles/README.md) for the format.
