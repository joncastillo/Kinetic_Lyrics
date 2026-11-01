# Video generation

This optional step comes after the artwork is approved. It turns each illustration into
a short clip with a local image-to-video model. The compositor then plays the clip in
place of the still image. The step is off unless a video model is chosen.

```
illustrate -> review -> animate -> direct -> render
                        (this folder)
```

## Models

| Model | Clip | Download | Licence |
|---|---|---|---|
| [`Lightricks/LTX-2.5-Diffusers`](https://huggingface.co/Lightricks/LTX-2.5-Diffusers) | 121 frames at 24 fps (5 s), 960×544 | about 72 GB, gated (automatic approval) | LTX-2.x Community License, free under $10M yearly revenue |
| [`MiniMaxAI/MiniMax-H3`](https://huggingface.co/MiniMaxAI/MiniMax-H3) | 124 frames at 24 fps (5.2 s), 1344×768 | about 125 GB | MiniMax H3 Community License, which **does not licence use in the US, EU, UK or South Korea** |

Both models also generate a soundtrack, which is thrown away because the song is the
audio. LTX-2.5 runs its distilled checkpoint without guidance, using automatic CPU
offload. MiniMax H3 quantizes its transformer and its Qwen3-VL encoder to 8-bit weights
with torchao, and streams them from system RAM. On a 24 GB card H3 needs about 75 GB of
RAM and is much slower than LTX-2.5.

## Setup

Both models ship as Modular Diffusers blocks. These are only on diffusers `main`, while
the main environment keeps the diffusers release that the image models were tested with.
The video models therefore get their own environment. The user runs this once from the
project folder:

```powershell
powershell -ExecutionPolicy Bypass -File src\video_generation\setup.ps1
```

This creates `.venv-video` in the project, or in the folder named by `KINETIC_VIDEO_ENV`
(for example `D:\AI_Models\.venv-video` to keep its ~4 GB off the system drive). The video
step runs its worker with that environment's Python. To use a different interpreter, set
`KINETIC_VIDEO_PYTHON`. Without either, the
step falls back to the main environment, and the run then fails with a message pointing
at the setup script.

## How it works

- `step.py` runs as the `animate` step of the pipeline graph. It fingerprints each
  illustration (SHA-256), skips any image that already has a clip, and starts the
  worker for the rest.
- `generation.py` is the GPU worker. It waits for the same GPU lock as the image worker
  and unloads resident Ollama models. Then it loads the video model and writes
  `video-clips/<digest>-<model>/clip.mp4` and `clip.json` for each image. After the
  first clip it reports the measured time per clip and an estimate for the remaining
  clips in the Studio progress line.
- `clips.py` cuts each clip into JPEG frames at the video's size
  (`frames-<width>x<height>/`), once for all render workers. It also plays clips forwards
  then backwards, so a 5-second clip fills a scene of any length without a jump.
- `render/compositor.py` looks clips up by the same image digest. An image without a
  clip, such as one replaced after the video step, stays a still image.

## Limits

- Only the `fullscreen` and `verse` artwork modes are supported. Cutouts need
  transparency, and greenscreen scenery needs a matte for every frame. Neither model
  produces these.
- The 3D stage and the stage colour swatches still use the still images.
- A Studio section rebuild after an image replacement keeps the new image still. The
  next full run animates it.
- Neither model card publishes timings for consumer GPUs, so the first clip of a run is
  the only reliable measure. The worker logs the time for every clip.
