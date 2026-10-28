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
`--render-workers N`, `--reading-flow realtime|preview`, `--kinetic '{...}'`,
`--effect-speeds '{"glass-shatter": 0.5}'`. Run with `--help` for the full list.

## Real-time kinetic flow

The default reading flow writes each word exactly as it is sung:

- **One continuous camera.** Every illustration is stitched into one collage; the camera
  glides along a smooth path through it at constant speed, and each line is written where
  the camera is heading so it crosses the whole screen while it is sung.
- **Font mix by role.** Small typewriter function words, heavy content words and huge
  condensed hero words. Hero words can form through particle and material lettering.
- **Melody and instruments.** Demucs separates the vocals and instruments. Line starts snap to
  the measured vocal onset, high notes turn hero words hot, fast passages snap in, and some
  lines pulse with their dominant instrument (never the voice).
- **Backdrops and traces.** Whole-line marquees, echo and giant words, glowing underlines,
  a thread that wraps shapes around hero words, and drawn-on geometry.
- **Readable colour.** Every entrance recipe has a measured base colour; lettering is never
  paired with a background of the same colour.

Everything is adjustable in Studio's **Kinetic effects** panel and saved in profiles,
including a separate particle speed for each effect. `--reading-flow preview` keeps the
earlier style where the whole line appears before it is sung.

Exports are encoded and tagged as BT.709, and each frame is a pure function of time, so
renders split across CPU workers are identical to single-core output.

## Style reference

`kinetic-lyrics/assets/default-style-reference.jpg` is the bundled default art style
reference. Studio preloads it for new sessions and the command line uses it when no
`--style-reference` is given. Pass `--no-default-style-references` to disable it.

## Particle effects

Entrance and exit effects are JSON recipes in `kinetic-lyrics/particles/`. See
[`particles/README.md`](kinetic-lyrics/particles/README.md) for the format.
