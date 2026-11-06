"""Detect an existing seamless loop and prepare quiet MP4s for repeating backdrops."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

LOOP_TAG = 'kinetic-loop:seamless'


def probe(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
        capture_output=True,
        check=True,
        text=True,
    )
    info = json.loads(result.stdout)
    video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('This file has no video track')
    return video, info.get('format', {})


def seamless(path):
    """Detect a marked loop or a boundary as quiet as the adjacent frames. This is a visual heuristic, not a
    filename convention: clips with a visible end-to-start jump need a crossfade."""
    import numpy as np

    _, info = probe(path)
    if LOOP_TAG in str(info.get('tags', {}).get('comment', '')):
        return True
    shape = (64, 64, 3)
    common = ['-vf', 'scale=64:64', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
    first = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', str(path), '-frames:v', '2', *common], capture_output=True, check=True
    ).stdout
    last = subprocess.run(
        ['ffmpeg', '-v', 'error', '-sseof', '-0.25', '-i', str(path), *common], capture_output=True, check=True
    ).stdout
    a = np.frombuffer(first, np.uint8).reshape(-1, *shape).astype(np.float32)
    b = np.frombuffer(last, np.uint8).reshape(-1, *shape).astype(np.float32)
    if not len(a) or not len(b):
        return False
    boundary = float(np.abs(a[0] - b[-1]).mean())
    adjacent = max(
        float(np.abs(a[1] - a[0]).mean()) if len(a) > 1 else 0.0,
        float(np.abs(b[-1] - b[-2]).mean()) if len(b) > 1 else 0.0,
    )
    return boundary <= max(2.5, min(10.0, adjacent * 1.5))


def prepare_loop(source, target, max_seconds=120, max_width=1920, fps=30, seconds=None, crossfade=True):
    try:
        return _prepare_loop(source, target, max_seconds, max_width, fps, seconds, crossfade)
    except FileNotFoundError as exc:
        raise ValueError('FFmpeg and ffprobe are needed to read video backdrops') from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr or b''
        if isinstance(detail, bytes):
            detail = detail.decode('utf-8', 'replace')
        raise ValueError(
            'This video could not be read: ' + (detail.strip().splitlines()[-1:] or ['invalid video'])[0]
        ) from exc


def _prepare_loop(source, target, max_seconds, max_width, fps, seconds, crossfade):
    """Normalise a backdrop and crossfade only when its boundary needs it. A crossfade overlaps the tail with the
    head once; native/browser and renderer playback can then repeat that cycle without another fade."""
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='video-loop-', dir=target.parent) as scratch:
        normal = Path(scratch) / 'normal.mp4'
        subprocess.run(
            [
                'ffmpeg',
                '-v',
                'error',
                '-y',
                '-i',
                str(source),
                '-t',
                str(max_seconds),
                '-an',
                '-map_metadata',
                '-1',
                '-vf',
                f"scale='min({max_width},iw)':-2,fps={fps}",
                '-c:v',
                'libx264',
                '-preset',
                'veryfast',
                '-crf',
                '18',
                '-pix_fmt',
                'yuv420p',
                '-movflags',
                '+faststart',
                str(normal),
            ],
            check=True,
            capture_output=True,
        )
        _, original = probe(source)
        marked = LOOP_TAG in str(original.get('tags', {}).get('comment', ''))
        detected = (marked and float(original.get('duration') or 0) <= max_seconds) or seamless(normal)
        if not detected and not crossfade:
            raise ValueError(
                'This clip does not close smoothly. Regenerate its motion with matching start and end frames; no crossfade was applied.'
            )
        _, info = probe(normal)
        duration = float(info.get('duration') or 0.0)
        if duration <= 0:
            raise ValueError('This video has no playable frames')
        fade = min(0.75, duration / 4)
        command = ['ffmpeg', '-v', 'error', '-y', '-i', str(normal)]
        if detected or duration < 4 / fps:
            command += ['-c:v', 'copy']
        else:
            # Rotating past the head leaves one periodic cycle: body, then tail fading into the head.
            graph = (
                f'[0:v]split=2[a][b];[a][b]xfade=transition=fade:duration={fade:.6f}:'
                f'offset={duration-fade:.6f},trim=start={fade:.6f}:end={duration:.6f},setpts=PTS-STARTPTS[v]'
            )
            command += [
                '-filter_complex_threads',
                '1',
                '-filter_complex',
                graph,
                '-map',
                '[v]',
                '-c:v',
                'libx264',
                '-preset',
                'veryfast',
                '-crf',
                '18',
                '-pix_fmt',
                'yuv420p',
            ]
        encoded = Path(scratch) / 'cycle.mp4' if seconds is not None else target
        command += ['-an', '-metadata', f'comment={LOOP_TAG}', '-movflags', '+faststart', str(encoded)]
        subprocess.run(command, check=True, capture_output=True)
        if seconds is not None:
            _, cycle = probe(encoded)
            scale = float(seconds) / float(cycle['duration'])
            # Stretch the whole cycle slightly to keep its seam and the exact requested duration. Repeating a
            # partial cycle then cutting it to length would introduce a new jump at the end.
            subprocess.run(
                [
                    'ffmpeg',
                    '-v',
                    'error',
                    '-y',
                    '-i',
                    str(encoded),
                    '-an',
                    '-vf',
                    f'setpts={scale:.12f}*PTS,fps={fps},tpad=stop_mode=clone:stop_duration=1',
                    '-frames:v',
                    str(round(float(seconds) * fps)),
                    '-c:v',
                    'libx264',
                    '-preset',
                    'veryfast',
                    '-crf',
                    '18',
                    '-pix_fmt',
                    'yuv420p',
                    '-metadata',
                    f'comment={LOOP_TAG}',
                    '-movflags',
                    '+faststart',
                    str(target),
                ],
                check=True,
                capture_output=True,
            )
    return dict(loop=True, loop_detected=detected, crossfaded=not detected and duration >= 4 / fps)


def poster(source, target):
    subprocess.run(
        ['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-frames:v', '1', str(target)],
        check=True,
        capture_output=True,
    )
