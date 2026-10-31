"""Saved clips: where they live, cutting them into render-size frames, and reading a frame by time.

Each clip is stored under `<project>/video-clips/` in a folder named after the SHA-256 of the
illustration it animates, so a replaced image never reuses the old image's clip. The compositor
fingerprints its artwork the same way and looks clips up by that digest.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess

FOLDER = 'video-clips'


def image_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clip_folder(project, model, digest):
    return Path(project)/FOLDER/(digest[:24]+'-'+model.split('/')[-1].lower())


def ensure_frames(folder, width, height):
    """JPEG frames of the clip at the video's size, cut once and reused by every render worker."""
    frames = folder/f'frames-{width}x{height}'
    if (frames/'.complete').is_file():
        return frames
    frames.mkdir(parents=True, exist_ok=True)
    for stale in frames.glob('*.jpg'):
        stale.unlink()
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(folder/'clip.mp4'),
                    '-vf', f'scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height}',
                    '-q:v', '2', str(frames/'%05d.jpg')], check=True)
    (frames/'.complete').write_text('', encoding='utf-8')
    return frames


def saved_clips(project, model, digests, width, height):
    """{image digest: frame folder} for every finished clip of these images made with `model`."""
    found = {}
    for digest in dict.fromkeys(digests):
        folder = clip_folder(project, model, digest)
        if (folder/'clip.json').is_file() and (folder/'clip.mp4').is_file():
            found[digest] = str(ensure_frames(folder, width, height))
    return found


class ClipFrames:
    """Frames of one clip, played forwards then backwards so a short clip fills a scene of any length."""

    def __init__(self, frames):
        self.frames = Path(frames)
        meta = json.loads((self.frames.parent/'clip.json').read_text(encoding='utf-8'))
        self.fps = meta['fps']
        self.paths = sorted(self.frames.glob('*.jpg'))
        if not self.paths:
            raise ValueError(f'Clip has no frames: {self.frames}')
        self._cache = {}

    def __getstate__(self):
        return dict(self.__dict__, _cache={})

    def index(self, elapsed):
        count = len(self.paths)
        if count == 1:
            return 0
        position = max(0, round(elapsed*self.fps)) % (2*count-2)
        return position if position < count else 2*count-2-position

    def frame(self, elapsed):
        from PIL import Image
        number = self.index(elapsed)
        if number not in self._cache:
            if len(self._cache) >= 4:
                self._cache.pop(next(iter(self._cache)))
            with Image.open(self.paths[number]) as source:
                self._cache[number] = source.convert('RGB')
        return self._cache[number].copy()


def clips_for(video_clips, digests):
    """One ClipFrames (or None for a still) per artwork slot, in the compositor's slot order."""
    if not video_clips:
        return []
    return [ClipFrames(video_clips[digest]) if digest in video_clips else None for digest in digests]
