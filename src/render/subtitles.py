"""The legacy renderer: ASS subtitle animation burned into the video with FFmpeg."""
from __future__ import annotations
from pathlib import Path
import shutil
import subprocess
import tempfile


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

def render_subtitles(audio, output, ass_path, data, duration, theme, args):
    """The legacy renderer: ASS subtitle animation burned over a plain or photo background."""
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
                   '-vf', base_filter + 'ass=lyrics.ass' + fonts + ',scale=out_color_matrix=bt709:out_range=tv', '-t', str(duration),
                   *encoding, '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', '-pix_fmt', 'yuv420p',
                   '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(temp / 'video.mp4')]
        print(f'Rendering moving typography with {args.encoder}...', flush=True)
        subprocess.run(command, cwd=temp, check=True)
        (temp / 'video.mp4').replace(output)
