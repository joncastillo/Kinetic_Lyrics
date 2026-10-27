"""Turn audio and UTF-8 lyrics into a kinetic typography MP4 using FFmpeg."""
from __future__ import annotations

from project_paths import default_model_cache
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from kinetic_progress import emit


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def archive_legacy_subtitles(path):
    """Keep editable subtitles, but prevent players auto-loading a second layer."""
    if not path.exists():
        return
    folder = path.parent / 'legacy-subtitles'
    folder.mkdir(exist_ok=True)
    target = folder / path.name
    number = 1
    while target.exists():
        target = folder / f'{path.stem}-{number}{path.suffix}'
        number += 1
    path.rename(target)
    print(f'Archived old subtitle layer: {target}', flush=True)


def lyrics_lines(path):
    lines = [s.strip() for s in path.read_text(encoding="utf-8-sig").splitlines()]
    lines = [s for s in lines if s and not re.fullmatch(r"\[.*\]", s)]
    if not lines:
        raise ValueError("Lyrics contain no lines. Use UTF-8 text; section labels are ignored.")
    return lines


def normalized(text):
    return "".join(c.casefold() for c in text if c.isalnum())


def theme_for(prompt):
    """Resolve supported mood vocabulary; preserve the full prompt in metadata."""
    text = prompt.lower()
    if re.search(r"sad|solemn|melanchol|mourn|somber|sombre|heartbreak", text):
        return dict(name="solemn", background="0x101521", ink="DCD7CE", accent="C3A383",
                    motion=28, angle=2, entrance=620, font="Georgia", bold=0)
    if re.search(r"joy|happy|playful|bright|sunny|fun", text):
        return dict(name="playful", background="0x261638", ink="F8F3FF", accent="73DEFF",
                    motion=95, angle=9, entrance=240, font="Arial", bold=-1)
    if re.search(r"energetic|edm|neon|electric|aggressive|dance|bold", text):
        return dict(name="electric", background="0x080D16", ink="FFFFFF", accent="D5FF39",
                    motion=130, angle=12, entrance=160, font="Arial", bold=-1)
    if re.search(r"romantic|warm|love|tender|dream", text):
        return dict(name="romantic", background="0x271923", ink="E9E1FF", accent="A9ADFF",
                    motion=45, angle=3, entrance=450, font="Georgia", bold=0)
    return dict(name="minimal", background="0x12151C", ink="F2F2F2", accent="EBCB87",
                motion=60, angle=5, entrance=320, font="Arial", bold=-1)


def whisper_model(args):
    try:
        import stable_whisper
    except ImportError as exc:
        raise ValueError("Whisper transcription/alignment needs stable-ts. Install requirements-kinetic.txt "
                         "or supply --timings with reviewed word timestamps.") from exc
    return stable_whisper.load_model(args.model, device=args.device,
        download_root=str((Path(getattr(args,'image_cache',None) or Path(__file__).resolve().parent.parent/'.cache')/'speech'/'whisper').resolve()))


def release_whisper_memory():
    import gc
    gc.collect()
    if 'torch' in sys.modules and sys.modules['torch'].cuda.is_available():
        sys.modules['torch'].cuda.empty_cache()


def transcribe(audio, args):
    """Recover lyric lines and word timing together when no text is supplied."""
    if getattr(args,'asr_model','legacy') != 'legacy':
        from speech_models import transcribe_selected
        return transcribe_selected(audio,args)
    print(f'Transcribing lyrics with Whisper {args.model} ({args.device})...', flush=True)
    model = whisper_model(args)
    try:
        result = model.transcribe(str(audio), language=args.language,
            task='transcribe', word_timestamps=True, regroup=True)
    finally:
        model.cpu()
        del model
        release_whisper_memory()
    data = []
    if result is not None:
        for segment in result.to_dict().get('segments', []):
            words = [dict(text=w['word'].strip(), start=w['start'], end=w['end'])
                     for w in segment.get('words', []) if w.get('word', '').strip()]
            if words:
                data.append(dict(text=' '.join(w['text'] for w in words), words=words))
            elif segment.get('text', '').strip():
                raise ValueError('Whisper returned text without word timestamps; supply reviewed lyrics/timings.')
    if not data:
        raise ValueError('Whisper found no lyrics. Supply a lyrics file or try --alignment-audio with isolated vocals.')
    print('Whisper lyrics are an estimate: review the saved .lyrics.txt and .timings.json.', flush=True)
    return data


def align(audio, lines, args):
    from speech_models import ALIGN_LANGUAGES, qwen_alignment
    import copy
    options=copy.copy(args)
    choice=getattr(args,'alignment_model','legacy')
    duration=float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(audio)])) if choice=='auto' else 0
    use_qwen=choice=='qwen3-aligner' or (choice=='auto' and args.language in ALIGN_LANGUAGES and duration<=300)
    if use_qwen:
        words=qwen_alignment(audio,lines,args)
    else:
        if choice in ('auto','whisper-large-v3'):options.model='large-v3'
        elif choice=='whisper-turbo':options.model='turbo'
        print(f'Aligning supplied lyrics with Whisper {options.model} ({args.device})...',flush=True)
        model=whisper_model(options)
        try:
            language=args.language
            if not language:
                import whisper
                waveform=whisper.load_audio(str(audio))
                mel=whisper.log_mel_spectrogram(whisper.pad_or_trim(waveform),n_mels=model.dims.n_mels).to(model.device)
                _,probabilities=model.detect_language(mel)
                language=max(probabilities,key=probabilities.get)
                print('Detected alignment language: '+language,flush=True)
            result=model.align(str(audio),"\n".join(lines),language=language,original_split=True,regroup=False)
        finally:
            model.cpu();del model;release_whisper_memory()
        if result is None:raise ValueError('No vocals could be aligned. Try a vocal stem.')
        words=[w for segment in result.to_dict()['segments'] for w in segment.get('words',[])]
    target = ''.join(normalized(line) for line in lines)
    actual = ''.join(normalized(w['word']) for w in words)
    if target != actual:
        raise ValueError("Aligner did not retain all lyric text. Check the lyrics or supply --timings.")
    spans, offset = [], 0
    for word in words:
        length = len(normalized(word['word']))
        if length:
            spans.append((offset, offset + length, float(word['start']), float(word['end'])))
        offset += length
    offset, output = 0, []
    for line in lines:
        timed = []
        for word in line.split():
            length = len(normalized(word))
            matches = [s for s in spans if s[0] < offset + length and s[1] > offset]
            if not matches:
                if not length and timed:
                    timed[-1]['text'] += ' ' + word
                    continue
                raise ValueError(f"Cannot align token {word!r}; remove standalone punctuation.")
            timed.append(dict(text=word, start=matches[0][2], end=matches[-1][3]))
            offset += length
        output.append(dict(text=line, words=timed))
    return output


def repair_zero_durations(data, duration):
    """Give collapsed automatic alignments a short, reviewable duration."""
    repaired = 0
    for line in data:
        for word in line['words']:
            start, end = float(word['start']), float(word['end'])
            if math.isfinite(start) and start == end and 0 <= start <= duration:
                word['end'] = min(duration, start + .08)
                if word['end'] == start:
                    word['start'] = max(0, start - .08)
                repaired += 1
    if repaired:
        print(f'Warning: repaired {repaired} zero-duration aligned word(s). '
              'Review the generated timings JSON for synchronization.', file=sys.stderr)


def validate(data, lines, duration):
    if len(data) != len(lines):
        raise ValueError("Timing file must have one entry per lyric line.")
    previous = -1.0
    for line, item in zip(lines, data):
        if item.get('text') != line or not item.get('words'):
            raise ValueError(f"Timing text differs from lyrics: {line!r}")
        if normalized(' '.join(w['text'] for w in item['words'])) != normalized(line):
            raise ValueError(f"Timing words differ from line: {line!r}")
        for word in item['words']:
            start, end = float(word['start']), float(word['end'])
            if not all(math.isfinite(v) for v in (start, end)) or not (0 <= start < end <= duration + .05):
                raise ValueError(f"Invalid/zero duration timestamp for {word['text']!r}: {start}, {end}")
            if start < previous:
                raise ValueError("Word starts must be chronological. Review the timings JSON.")
            previous = start


def timestamp(t):
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def escape(text):
    return text.replace('\\', '／').replace('{', '｛').replace('}', '｝').replace('\n', ' ')


def write_ass(path, data, duration, width, height, theme, font_path=None):
    from PIL import ImageFont
    size = round(height * .10)
    if font_path:
        font_name = ImageFont.truetype(str(font_path), size).getname()[0]
        font_source = str(font_path)
    else:
        font_name = theme['font']
        font_source = ('georgia.ttf' if font_name == 'Georgia' else 'arialbd.ttf')
    try:
        font = ImageFont.truetype(font_source, size)
    except OSError:
        font_source = 'DejaVuSans.ttf'
        font = ImageFont.truetype(font_source, size)
        font_name = font.getname()[0]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lyric,{font_name},{size},&H00{theme['ink']},&H00{theme['accent']},&H00101520,&H80000000,{theme['bold']},0,0,0,100,100,0,0,1,1.2,0,5,30,30,30,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for index, line in enumerate(data):
        words = line['words']
        line_end = min(duration, max(words[-1]['end'] + .6, words[-1]['start'] + .3))
        if index + 1 < len(data):
            line_end = min(line_end, data[index + 1]['words'][0]['start'])
        current_size = size
        while True:
            font = ImageFont.truetype(font_source, current_size)
            space = font.getlength(' ')
            rows, row, used = [], [], 0
            for word in words:
                length = font.getlength(word['text'])
                if row and used + space + length > width * .78:
                    rows.append(row)
                    row, used = [], 0
                row.append((word, length))
                used += length + (space if len(row) > 1 else 0)
            if row:
                rows.append(row)
            if len(rows) <= 3 and all(length <= width * .78 for r in rows for _, length in r):
                break
            current_size -= 2
            if current_size < 10:
                raise ValueError("Lyric line is too long. Split it into shorter lines.")
        for row_number, row in enumerate(rows):
            row_width = sum(length for _, length in row) + space * (len(row) - 1)
            placement = index % 4
            x = (width - row_width) / 2
            if placement == 1:
                x = width * .11
            elif placement == 3:
                x = width * .89 - row_width
            baseline = (.50, .43, .56, .48)[placement]
            y = height * baseline + (row_number - (len(rows) - 1) / 2) * current_size * 1.35
            for word_number, (word, length) in enumerate(row):
                start, end = word['start'], line_end
                if end <= start:
                    raise ValueError("Overlapping lyric lines: review the timing file.")
                life = max(1, round((end - start) * 1000))
                entrance = min(theme['entrance'], max(1, life // 3))
                exit_start = max(entrance, life - min(350, life // 4))
                direction = 1 if (word_number + index) % 2 else -1
                cx = x + length / 2
                motion = theme['motion'] * height / 1080
                angle = direction * theme['angle']
                variant = (index * 3 + row_number + word_number) % 6
                restrained = theme['name'] in ('solemn', 'romantic')
                small, large = (94, 106) if restrained else (72, 125)
                profiles = [
                    (0, motion, small, small, 0, 0),
                    (direction * motion * 1.5, 0, 100, 100, 0, 0),
                    (0, 0, large, large, 0, 2 if restrained else 5),
                    (0, -motion, 100, small, -angle, 0),
                    (0, 0, small, 100, 0, 0),
                    (direction * motion * .5, motion * .5, small, small, angle * 2, 0),
                ]
                dx, dy, sx, sy, rotation, blur = profiles[variant]
                peak = 102 if restrained else 108
                exit_scale = 104 if variant % 2 else 96
                tags = (f"\\an5\\fs{current_size}\\move({cx+dx:.1f},{y+dy:.1f},{cx:.1f},{y:.1f},0,{entrance})"
                        f"\\frz{rotation}\\fscx{sx}\\fscy{sy}\\blur{blur}\\alpha&HFF&"
                        f"\\t(0,{entrance},\\alpha&H00&\\blur0\\fscx{peak}\\fscy{peak}\\frz0)"
                        f"\\t({entrance},{min(life, entrance*2)},\\fscx100\\fscy100)"
                        f"\\t({exit_start},{life},\\alpha&HFF&\\blur{1 if restrained else 2}\\frz{-angle}\\fscx{exit_scale}\\fscy{exit_scale})"
                        f"\\1c&H{theme['accent']}&\\t(0,{min(life, entrance*2)},\\1c&H{theme['ink']}&)")
                events.append(f"Dialogue: 0,{timestamp(start)},{timestamp(end)},Lyric,,0,0,0,,{{{tags}}}{escape(word['text'])}\n")
                x += length + space
    path.write_text(header + ''.join(events), encoding='utf-8-sig')


def validate_ocr(video, data, duration, report_path):
    """Inspect actual encoded frames. Flags are review hints, not alignment scores."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise ValueError('OCR requires: python -m pip install rapidocr-onnxruntime') from exc
    engine = RapidOCR()
    results = []
    with tempfile.TemporaryDirectory(prefix='ocr-', dir=video.parent) as temp:
        for i, line in enumerate(data):
            last = line['words'][-1]
            end = min(duration, last['end'] + .6)
            if i + 1 < len(data):
                end = min(end, data[i + 1]['words'][0]['start'])
            sample = max(0, min(last['start'] + .7, (last['start'] + end) / 2))
            frame = Path(temp) / f'{i}.png'
            run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(sample),
                 '-i', str(video), '-frames:v', '1', '-y', str(frame)])
            found, _ = engine(str(frame))
            recognized = ' '.join(item[1] for item in (found or []))
            expected = normalized(line['text'])
            observed = normalized(recognized)
            results.append(dict(line=i + 1, time=sample, expected=line['text'],
                                observed=recognized, passed=expected in observed))
    report_path.write_text(json.dumps(dict(
        note='OCR checks visible spelling only; inspect flagged lines and listen to verify sync.',
        frames=results), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"OCR: {sum(r['passed'] for r in results)}/{len(results)} lines passed; {report_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('lyrics', type=Path, nargs='?', help='Optional UTF-8 lyrics; omit to transcribe audio with Whisper')
    parser.add_argument('-o', '--output', type=Path)
    parser.add_argument('--theme', default='minimal cinematic', help='Mood prompt; see kinetic-lyrics/README.md')
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
    parser.add_argument('--artwork-mode', choices=['cutout','fullscreen','verse'], default='cutout', help='Cutout illustrations, full-screen scenes, or simple verse-inspired abstract backgrounds')
    parser.add_argument('--cinematic', action='store_true', help='Large steady illustrations, depth shadows and drifting light; no Blender required')
    from kinetic_effects import EFFECTS, TEXT_ANIMATIONS
    parser.add_argument('--particle-intensity', type=float, default=1., help='Particle density: 0 to 2')
    parser.add_argument('--particle-speed', type=float, default=1., help='Particle velocity multiplier: 0.2 to 3')
    parser.add_argument('--type-effect', choices=EFFECTS, default='none', help='Typography effect: mixed, shatter, melt, slime or liquid')
    from typography_settings import FONT_FAMILIES,FONT_STYLES,typography_options
    parser.add_argument('--font-family',choices=FONT_FAMILIES,default='auto')
    parser.add_argument('--font-style',choices=FONT_STYLES,default='auto')
    parser.add_argument('--font-scale',type=float,default=1.25,help='Relative font size, 0.6 to 2; long lines still fit the reading area')
    parser.add_argument('--text-pool',default=None,help='JSON list of word animations enabled in mixed mode')
    parser.add_argument('--text-animation', choices=TEXT_ANIMATIONS, default='directed', help='Word highlighting, timed sweep, slide, fade or scene-directed motion')
    parser.add_argument('--entrance-pool', default=None, help='JSON list of enabled entrance IDs for mixed mode')
    parser.add_argument('--exit-pool', default=None, help='JSON list of enabled exit IDs for mixed mode')
    parser.add_argument('--entrance-effect', default=None, help='Entrance recipe filename without .json, mixed, or none')
    parser.add_argument('--exit-effect', default=None, help='Exit recipe filename without .json, mixed, or none')
    parser.add_argument('--director', default='ollama', choices=['ollama', 'rules'],
                        help='Local AI art direction (default), or explicit offline rules')
    parser.add_argument('--ai-model', default='auto', help='Ollama model; auto chooses a GPU-fit general-purpose Qwen model')
    parser.add_argument('--plan', type=Path, help='Reuse/edit a generated .design.json art direction plan')
    parser.add_argument('--lead-in', type=float, default=1.,
                        help='Minimum entrance lead-in in seconds (default: 1; particles finish before each line, with longer lead-ins for slower vocal pacing)')
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--render-workers',type=int,default=0,help='CPU frame workers: 0 auto, 1 sequential, up to 8')
    parser.add_argument('--font', type=Path, help='Optional TTF/OTF font')
    parser.add_argument('--background', type=Path, help='Optional still image, including AI artwork')
    art_options = parser.add_mutually_exclusive_group()
    art_options.add_argument('--illustrations', type=Path, nargs='+', help='Illustration files in sequence; transparent PNGs blend with typography (editorial only)')
    art_options.add_argument('--no-illustrations', action='store_true', help='Render typography without illustration panels')
    parser.add_argument('--illustration-lines', type=int, default=2, help='Generate and hold one unique illustration per this many lyric lines (default: 2)')
    parser.add_argument('--style-reference', type=Path, nargs='+', help='One or more reference images for generated linework, palette and paint style')
    from kinetic_illustrations import STYLE_PROMPT
    parser.add_argument('--style-prompt', default=STYLE_PROMPT, help='Art style instruction accompanying reference images')
    parser.add_argument('--image-cache', type=Path, default=default_model_cache(), help='Model cache (default: KINETIC_LYRICS_MODEL_CACHE or ~/.cache/kinetic-lyrics)')
    parser.add_argument('--image-model', default='Qwen/Qwen-Image-2512', help='Local image repository (default: Qwen Image 2512)')
    parser.add_argument('--image-steps', type=int, default=None, help='Illustration inference steps (default: selected model recommendation)')
    parser.add_argument('--image-seed', type=int, default=42)
    parser.add_argument('--validate-ocr', action='store_true', help='OCR one encoded frame per lyric line')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--review-artwork', action='store_true', help='Wait for studio approval before rendering')
    parser.add_argument('--preserve-art-slots', action='store_true', help='Keep illustration group positions even when image pixels repeat')
    parser.add_argument('--no-default-style-references', action='store_true', help='Use only explicitly supplied style references')
    args = parser.parse_args(argv)
    args.preserve_art_slots = args.preserve_art_slots or args.review_artwork
    if args.cinematic and args.renderer != 'editorial':
        parser.error('--cinematic requires --renderer editorial.')
    if args.illustration_lines < 1:
        parser.error('--illustration-lines must be positive.')
    if args.image_steps is None:
        from image_models import model_spec
        args.image_steps = model_spec(args.image_model)['steps']
    if not 1 <= args.image_steps <= 150:
        parser.error('--image-steps must be between 1 and 150.')
    if args.style_reference and (args.no_illustrations or args.illustrations or args.renderer != 'editorial'):
        parser.error('--style-reference requires automatically generated editorial illustrations.')
    if args.renderer == 'editorial' and not args.no_illustrations and not args.illustrations and args.style_reference is None and not args.no_default_style_references:
        default_reference = Path(__file__).resolve().parent / 'assets' / 'default-style-reference.jpg'
        args.style_reference = [default_reference] if default_reference.is_file() else []
    if args.illustrations and args.renderer != 'editorial':
        parser.error('--illustrations requires --renderer editorial.')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        parser.error('Install FFmpeg with libass and put ffmpeg/ffprobe on PATH.')
    if min(args.width, args.height) < 128 or args.width % 2 or args.height % 2 or not 1 <= args.fps <= 120:
        parser.error('Use even dimensions >=128 and fps between 1 and 120.')
    if not math.isfinite(args.lead_in) or not 0 <= args.lead_in <= 5:
        parser.error('--lead-in must be between 0 and 5 seconds.')
    from particle_catalog import discover_effects, validate_choice, parse_pool
    try:
        typography_options(vars(args))
        catalog = discover_effects()
        validate_choice(args.entrance_effect, 'entrance', catalog)
        validate_choice(args.exit_effect, 'exit', catalog)
        args.entrance_pool = parse_pool(args.entrance_pool, 'entrance', catalog)
        args.exit_pool = parse_pool(args.exit_pool, 'exit', catalog)
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
        if path.exists() and not args.overwrite:
            parser.error(f'{path} exists. Use --overwrite to replace generated files.')
    try:
        for reference in args.style_reference or []:
            from PIL import Image
            with Image.open(reference) as image:
                image.verify()
        lines = lyrics_lines(args.lyrics) if args.lyrics else None
        duration = float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                              '-of', 'default=noprint_wrappers=1:nokey=1', str(audio)]).strip())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Audio duration must be finite and positive.')
        emit('alignment', 0, message='Aligning supplied lyrics' if lines is not None else 'Transcribing lyrics from audio')
        if args.timings:
            data = json.loads(args.timings.read_text(encoding='utf-8-sig'))
        elif lines is not None:
            data = align((args.alignment_audio or audio).resolve(), lines, args)
        else:
            data = transcribe((args.alignment_audio or audio).resolve(), args)
        if lines is None:
            lines = [line['text'] for line in data]
            if not lines:
                raise ValueError('No lyric lines were found in the timing data.')
        if not args.timings:
            repair_zero_durations(data, duration)
        validate(data, lines, duration)
        from song_structure import annotate_sections
        annotate_sections(data,args.lyrics)
        emit('alignment', 1, message='Lyric timing validated')
        theme = theme_for(args.theme)
        print(f"Theme: {theme['name']}; {len(lines)} lines; {duration:.1f}s", flush=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.lyrics is None:
            lyrics_path.write_text('\n'.join(lines)+'\n', encoding='utf-8')
            print(f'Saved recovered lyrics: {lyrics_path}', flush=True)
        if not args.timings:
            timing_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        meta_path.write_text(json.dumps(dict(prompt=args.theme, cinematic=args.cinematic, **theme), indent=2), encoding='utf-8')
        if args.renderer == 'editorial':
            from kinetic_director import direct, render, validate_plan
            if not args.no_illustrations and args.illustrations is None:
                from kinetic_illustrations import generate
                args.illustrations = generate(data, output.parent / (output.stem+'.artwork'), args)
            if args.illustrations:
                print('Illustration panels: ' + ', '.join(str(p) for p in args.illustrations), flush=True)
                if args.review_artwork:
                    import time
                    approval = output.parent / 'artwork-approved'
                    approval.unlink(missing_ok=True)
                    emit('review', 0, message='Review illustrations, then approve to render')
                    while not approval.exists():
                        time.sleep(.5)
            else:
                print('Illustration panels: none (typography only).', flush=True)
            from lyric_placement import ensure_placements
            ensure_placements(args.illustrations,vars(args),output)
            emit('direction', 0, message='Planning typography and motion')
            plan = (validate_plan(json.loads(args.plan.read_text(encoding='utf-8-sig')), data)
                    if args.plan else direct(data, theme, args.theme, args.ai_model, args.director))
            if args.text_animation=='ai':
                from animation_director import ensure_word_direction
                plan=ensure_word_direction(data,plan,vars(args))
            if not args.plan or args.text_animation=='ai':
                design_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f"Design: {plan.get('concept', 'Custom editorial plan')}", flush=True)
            emit('direction', 1, message='Typography plan ready')
            from generation_queue import before_video_render,ReplacementsPending
            while True:
                before_video_render(output,args)
                try:
                    render(audio, output, data, plan, duration, args)
                    break
                except ReplacementsPending:
                    emit('illustrations',1,message='Pausing video render for queued image replacements')
            archive_legacy_subtitles(ass_path)
            print(f'Saved {output}\nArt direction: {args.plan or design_path}\nTiming source: {args.timings or timing_path}')
            if args.validate_ocr:
                validate_ocr(output, data, duration, ocr_path)
            emit('complete', 1, message='Video ready')
            return
        write_ass(ass_path, data, duration, args.width, args.height, theme, args.font)
        with tempfile.TemporaryDirectory(prefix='kinetic-', dir=output.parent) as temp:
            temp = Path(temp)
            shutil.copyfile(ass_path, temp / 'lyrics.ass')
            fonts = ''
            if args.font:
                (temp / 'fonts').mkdir()
                shutil.copyfile(args.font, temp / 'fonts' / args.font.name)
                fonts = ':fontsdir=fonts'
            if args.background:
                source = ['-loop', '1', '-framerate', str(args.fps), '-i', str(args.background.resolve())]
                base_filter = (f'scale={args.width}:{args.height}:force_original_aspect_ratio=increase,'
                               f'crop={args.width}:{args.height},drawbox=color=black@0.45:t=fill,')
            else:
                source = ['-f', 'lavfi', '-i', f'color=c={theme["background"]}:s={args.width}x{args.height}:r={args.fps}']
                base_filter = ''
            encoding = (['-c:v', 'h264_nvenc', '-preset', 'p5', '-tune', 'hq',
                         '-rc', 'vbr', '-cq', '18', '-b:v', '0']
                        if args.encoder == 'h264_nvenc' else
                        ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18'])
            command = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y', *source,
                       '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0',
                       '-vf', base_filter + 'ass=lyrics.ass' + fonts, '-t', str(duration),
                       *encoding, '-pix_fmt', 'yuv420p',
                       '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(temp / 'video.mp4')]
            print(f'Rendering moving typography with {args.encoder}...', flush=True)
            subprocess.run(command, cwd=temp, check=True)
            (temp / 'video.mp4').replace(output)
        print(f'Saved {output}\nAnimation: {ass_path}\nTiming source: {args.timings or timing_path}')
        if args.validate_ocr:
            validate_ocr(output, data, duration, ocr_path)
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError, TypeError) as exc:
        detail = getattr(exc, 'stderr', None) or str(exc)
        parser.exit(1, f'Error: {detail}\n')


if __name__ == '__main__':
    main()
