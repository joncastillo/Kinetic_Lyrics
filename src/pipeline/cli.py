"""Command line: turn audio and UTF-8 lyrics into a kinetic typography MP4."""
from __future__ import annotations
from core.paths import default_model_cache
import argparse
import math
from pathlib import Path
from core.paths import PROJECT_ROOT
import shutil
import subprocess


class _AnyEffect:
    """Accepts every effect ID: reads a pool's raw selection to report what was dropped."""
    def __contains__(self, item):
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('lyrics', type=Path, nargs='?', help='Optional UTF-8 lyrics; omit to transcribe audio with Whisper')
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--theme', default='minimal cinematic', help='Mood prompt; see README.md')
    parser.add_argument('--timings', type=Path, help='Reuse/edit a generated timings JSON')
    parser.add_argument('--alignment-audio', type=Path, help='Optional matching vocal stem, same time origin')
    parser.add_argument('--language', help='Whisper language code, e.g. en or tl; transcription autodetects by default')
    parser.add_argument('--model', default='base')
    parser.add_argument('--asr-model', default='legacy', help='Transcription model preset from the studio catalog')
    parser.add_argument('--alignment-model', default='legacy', help='auto, qwen3-aligner, whisper-large-v3 or whisper-turbo')
    parser.add_argument('--device', default='cuda', choices=['cpu', 'cuda'],
                        help='Whisper alignment device (default: cuda; use cpu without CUDA)')
    parser.add_argument('--encoder', default='h264_nvenc', choices=['h264_nvenc', 'libx264'],
                        help='Video encoder (default: h264_nvenc for NVIDIA GPU)')
    parser.add_argument('--renderer', default='editorial', choices=['editorial', 'ass'],
                        help='Editorial block compositor (default), or legacy ASS animation')
    parser.add_argument('--artwork-mode', choices=['cutout','fullscreen','verse','matte'], default='cutout', help='Cutout illustrations, full-screen scenes, verse-inspired painted backgrounds, or greenscreen scenery whose keyed sky is the only place lyrics appear')
    parser.add_argument('--cinematic', action='store_true', help='Large steady illustrations, depth shadows and drifting light; no Blender required')
    from render.text_effects import EFFECTS, TEXT_ANIMATIONS
    parser.add_argument('--particle-intensity', type=float, default=1., help='Particle density: 0 to 2')
    parser.add_argument('--particle-speed', type=float, default=1., help='Particle velocity multiplier: 0.2 to 3')
    parser.add_argument('--type-effect', choices=EFFECTS, default='none', help='Typography effect: mixed, shatter, melt, slime or liquid')
    from render.typography_settings import FONT_FAMILIES, FONT_STYLES, typography_options
    parser.add_argument('--font-family',choices=FONT_FAMILIES,default='auto')
    parser.add_argument('--reading-flow',choices=('realtime','preview','stage','mixed','cinema'),default='realtime',help='realtime: words land as sung; preview: whole line before the vocal; stage: lines grouped into blocks in a 3D world; mixed: each song section in one of the ticked scene effects (kinetic "scenes"); cinema: black hole sun, one short phrase at a time in hairline and heavy type over the artwork')
    parser.add_argument('--stage-pictures',choices=('ai-painted','ai-library','keywords','off'),default='ai-painted',
                        help='3D stage pictures: AI picks them and paints new ones, AI picks from the library only, keyword matches, or none')
    parser.add_argument('--effect-speeds',default=None,help='JSON per-effect particle speeds, e.g. {"glass-shatter": 0.5}')
    parser.add_argument('--instruments',choices=('auto','off'),default='off',help='Also paint and animate pictures of the instruments the analysis confidently hears (auto); by default (off) the music shows only as words pulsing with light')
    parser.add_argument('--effect-intensities',default=None,help='JSON per-effect letter-effect intensities, e.g. {"paper-burn": 1.5}')
    parser.add_argument('--kinetic',default=None,help='JSON real-time effect settings (pan_speed, backdrop_rate, backdrops, traces, geometry, frames, glows, glow_strength, glitch)')
    parser.add_argument('--instructions',default='',help='Special instructions for the renderer, one per line, e.g. Apply a neon effect to the word "neong"')
    parser.add_argument('--lettering-styles',default=None,help='JSON list of allowed text styles: swiss, poster, outline, cutout (default: all, as planned)')
    parser.add_argument('--font-style',choices=FONT_STYLES,default='auto')
    parser.add_argument('--font-scale',type=float,default=1.25,help='Relative font size, 0.6 to 2; long lines still fit the reading area')
    parser.add_argument('--text-pool',default=None,help='JSON list of word animations enabled in mixed mode')
    parser.add_argument('--text-animation', choices=TEXT_ANIMATIONS, default='directed', help='Word highlighting, timed sweep, slide, fade or scene-directed motion')
    parser.add_argument('--audio-mode', choices=('original', 'karaoke'), default='original',
                        help='Use the original song or export an instrumental mix without the vocal stem')
    parser.add_argument('--entrance-pool', default=None, help='JSON list of enabled entrance IDs for mixed mode')
    parser.add_argument('--exit-pool', default=None, help='JSON list of enabled exit IDs for mixed mode')
    parser.add_argument('--entrance-effect', default=None, help='Entrance recipe filename without .json, mixed, ai (chosen per line from scene, lyrics and readable colours), or none')
    parser.add_argument('--exit-effect', default=None, help='Exit recipe filename without .json, mixed, or none')
    parser.add_argument('--director', default='ollama', choices=['ollama', 'rules'],
                        help='Local AI art direction (default), or explicit offline rules')
    parser.add_argument('--ai-model', default='auto', help='Ollama model; auto chooses a GPU-fit general-purpose Qwen model')
    parser.add_argument('--plan', type=Path, help='Reuse/edit a generated .design.json art direction plan')
    parser.add_argument('--art-times', type=Path, help='Illustration start times saved by the Studio timeline editor')
    parser.add_argument('--lead-in', type=float, default=1.,
                        help='Minimum entrance lead-in in seconds (default: 1; particles finish before each line, with longer lead-ins for slower vocal pacing)')
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--render-workers',type=int,default=0,help='CPU frame workers: 0 auto (physical cores and free memory), 1 sequential, up to the logical CPU count')
    parser.add_argument('--font', type=Path, help='Optional TTF/OTF font')
    parser.add_argument('--background', type=Path, help='Optional still image, including AI artwork')
    art_options = parser.add_mutually_exclusive_group()
    art_options.add_argument('--illustrations', type=Path, nargs='+', help='Illustration files in sequence; transparent PNGs blend with typography (editorial only)')
    art_options.add_argument('--no-illustrations', action='store_true', help='Render typography without illustration panels')
    parser.add_argument('--illustration-lines', default='2', help='Lyric lines per illustration (1–50), or auto to let the text model choose after alignment')
    parser.add_argument('--image-instructions', default='', help='Additional direction for the AI image prompt model and generated image prompts')
    parser.add_argument('--style-reference', type=Path, nargs='+', help='One or more reference images for generated linework, palette and paint style')
    from direction.illustration_prompts import STYLE_PROMPT
    parser.add_argument('--style-prompt', default=STYLE_PROMPT, help='Art style instruction accompanying reference images')
    parser.add_argument('--image-cache', type=Path, default=default_model_cache(), help='Model cache (default: KINETIC_LYRICS_MODEL_CACHE, else OLLAMA_MODELS or ~/.ollama/models)')
    parser.add_argument('--image-model', default='Qwen/Qwen-Image-2512', help='Local image repository (default: Qwen Image 2512)')
    parser.add_argument('--image-steps', type=int, default=None, help='Illustration inference steps (default: selected model recommendation)')
    from video_generation.catalog import MODELS as VIDEO_MODELS, VIDEO_MODES
    parser.add_argument('--video-model', choices=[m['id'] for m in VIDEO_MODELS], default=None,
                        help='Animate each approved illustration with this local image-to-video model (full-screen and verse artwork only; off by default)')
    parser.add_argument('--image-seed', '--seed', dest='image_seed', type=int, default=None,
                        help='Model seed for image generation, prompts and layouts (default: random per run)')
    parser.add_argument('--validate-ocr', action='store_true', help='OCR one encoded frame per lyric line')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Continue an interrupted run from its last completed step (saved in <output>.graph.sqlite)')
    parser.add_argument('--review-artwork', action='store_true', help='Wait for studio approval before rendering')
    parser.add_argument('--preserve-art-slots', action='store_true', help='Keep illustration group positions even when image pixels repeat')
    parser.add_argument('--no-default-style-references', action='store_true', help='Use only explicitly supplied style references')
    args = parser.parse_args(argv)
    args.preserve_art_slots = args.preserve_art_slots or args.review_artwork
    if args.cinematic and args.renderer != 'editorial':
        parser.error('--cinematic requires --renderer editorial.')
    if args.image_seed is None or args.image_seed < 0:
        import secrets
        args.image_seed = secrets.randbelow(2**31)
    print(f'Model seed: {args.image_seed}', flush=True)
    if args.illustration_lines != 'auto':
        try:args.illustration_lines = int(args.illustration_lines)
        except ValueError:parser.error('--illustration-lines must be auto or an integer from 1 to 50.')
        if not 1 <= args.illustration_lines <= 50:
            parser.error('--illustration-lines must be auto or an integer from 1 to 50.')
    if args.image_steps is None:
        from models.image.catalog import model_spec
        args.image_steps = model_spec(args.image_model)['steps']
    if not 1 <= args.image_steps <= 150:
        parser.error('--image-steps must be between 1 and 150.')
    if args.style_reference and (args.no_illustrations or args.illustrations or args.renderer != 'editorial'):
        parser.error('--style-reference requires automatically generated editorial illustrations.')
    if args.renderer == 'editorial' and not args.no_illustrations and not args.illustrations and args.style_reference is None and not args.no_default_style_references:
        default_reference = PROJECT_ROOT / 'assets' / 'default-style-reference.jpg'
        args.style_reference = [default_reference] if default_reference.is_file() else []
    if args.video_model and (args.renderer != 'editorial' or args.no_illustrations or args.artwork_mode not in VIDEO_MODES):
        parser.error('--video-model needs editorial illustrations with --artwork-mode fullscreen or verse.')
    if args.illustrations and args.renderer != 'editorial':
        parser.error('--illustrations requires --renderer editorial.')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        parser.error('Install FFmpeg with libass and put ffmpeg/ffprobe on PATH.')
    if min(args.width, args.height) < 128 or args.width % 2 or args.height % 2 or not 1 <= args.fps <= 120:
        parser.error('Use even dimensions >=128 and fps between 1 and 120.')
    if not math.isfinite(args.lead_in) or not 0 <= args.lead_in <= 5:
        parser.error('--lead-in must be between 0 and 5 seconds.')
    from effects.particles.catalog import discover_effects, validate_choice, parse_pool
    try:
        typography_options(vars(args))
        catalog = discover_effects()
        validate_choice(args.entrance_effect, 'entrance', catalog)
        validate_choice(args.exit_effect, 'exit', catalog)
        for phase in ('entrance', 'exit'):  # a saved job may still list effects that were removed since
            chosen = getattr(args, phase+'_pool')
            pool = parse_pool(chosen, phase, catalog, strict=False)
            dropped = sorted(set(parse_pool(chosen, phase, {phase: _AnyEffect()}) or [])-set(pool or []))
            if dropped:
                print(f"Skipping {phase} effects that no longer exist: {', '.join(dropped)}", flush=True)
            setattr(args, phase+'_pool', pool)
        if not math.isfinite(args.particle_speed) or not .2 <= args.particle_speed <= 3:
            raise ValueError('--particle-speed must be between 0.2 and 3')
        if not math.isfinite(args.particle_intensity) or not 0 <= args.particle_intensity <= 2:
            raise ValueError('--particle-intensity must be between 0 and 2')
    except ValueError as exc:
        parser.error(str(exc))
    audio = args.audio.resolve()
    output = (args.output or args.audio.with_suffix('.kinetic.mp4')).resolve()
    timing_path = output.with_suffix('.timings.json')
    ass_path = output.with_suffix('.ass')
    meta_path = output.with_suffix('.theme.json')
    ocr_path = output.with_suffix('.ocr.json')
    design_path = output.with_suffix('.design.json')
    lyrics_path = output.with_suffix('.lyrics.txt')
    protected = [args.audio, args.lyrics, args.timings, args.alignment_audio, args.font, args.background, args.plan]
    protected += args.illustrations or []
    protected += args.style_reference or []
    if any(p and p.resolve() in [output, ass_path, meta_path, ocr_path]+([] if args.lyrics else [lyrics_path]) for p in protected):
        parser.error('Output paths must differ from inputs.')
    if not args.plan and any(p and p.resolve() == design_path for p in protected):
        parser.error('Design output would overwrite an input.')
    if args.timings is None and any(p and p.resolve() == timing_path for p in protected):
        parser.error('Timing output would overwrite an input.')
    for path in [output, meta_path] + ([ass_path] if args.renderer == 'ass' else []) + ([design_path] if args.renderer == 'editorial' and not args.plan else []) + ([ocr_path] if args.validate_ocr else []) + ([] if args.timings else [timing_path]) + ([] if args.lyrics else [lyrics_path]):
        if path.exists() and not (args.overwrite or args.resume):
            parser.error(f'{path} exists. Use --overwrite to replace generated files.')
    try:
        if args.renderer == 'editorial':
            from render.timeline import load_art_times
            args.art_times = load_art_times(args.art_times) if args.art_times else None
        from pipeline.graph import run as run_pipeline
        run_pipeline(args, audio, output, resume=args.resume)
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError, TypeError) as exc:
        detail = getattr(exc, 'stderr', None) or str(exc)
        parser.exit(1, f'Error: {detail}\n')

if __name__ == '__main__':
    main()
