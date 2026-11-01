"""Video clips as illustrations: an uploaded clip replaces one artwork slot and plays, looping, behind its lyrics.

A slot's still image (`003.png`) stays the reference for review, the gallery and every place that needs one
picture; the clip sits beside it as `003.mp4`. At render time the compositor swaps the slot's picture for the
clip's frame at the moment being drawn."""
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image

VIDEO_SUFFIXES = {'.mp4', '.mov', '.webm', '.m4v', '.mkv', '.avi'}
FPS = 30
MAX_WIDTH = 1920
MAX_SECONDS = 120


def sidecar(image):
    """The clip that belongs to a slot's still image, if there is one."""
    path = Path(image).with_suffix('.mp4')
    return path if path.is_file() else None


def offset_path(image):
    return Path(image).with_suffix('.clip.json')


def clip_settings(image):
    """The slot's saved clip settings: {'offset': seconds, 'framing': {...}}; empty when none were chosen."""
    try:
        value = json.loads(offset_path(image).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def clip_offset(image):
    """Seconds into the clip that play when its slot starts; chosen by dragging it in the timeline."""
    try:
        value = float(clip_settings(image).get('offset', 0.))
        return value if value >= 0 else 0.
    except (TypeError, ValueError):
        return 0.


FRAMING = dict(zoom=1., x=0., y=0., left=0., top=0., right=0., bottom=0.)
FRAMING_LIMITS = dict(zoom=(.1, 6.), x=(-1.5, 1.5), y=(-1.5, 1.5), left=(0., .45), top=(0., .45), right=(0., .45), bottom=(0., .45))


def checked_framing(value):
    """A complete framing from user input, every number inside its range."""
    if not isinstance(value, dict):
        raise ValueError('Invalid video framing')
    result = dict(FRAMING)
    for key, (low, high) in FRAMING_LIMITS.items():
        if key in value:
            number = float(value[key])
            if not low <= number <= high:
                raise ValueError(f'Video framing {key} is out of range')
            result[key] = number
    return result


def clip_framing(image):
    """How the clip sits in the frame, set by double-clicking it in the timeline: zoom 1 fills the frame (as an
    image does), smaller zooms leave white around a centred picture, x/y move it by fractions of the frame, and
    left/top/right/bottom crop those fractions off the clip's edges first."""
    try:
        return checked_framing(clip_settings(image).get('framing') or {})
    except (TypeError, ValueError):
        return dict(FRAMING)


def frame_picture(picture, framing, size):
    """`picture` placed in a `size` frame by `framing`, on white where it does not reach. The studio's
    framing editor draws with the same arithmetic, so what is set there is what renders."""
    width, height = size
    w0, h0 = picture.size
    left, top = round(w0*framing['left']), round(h0*framing['top'])
    right, bottom = max(left+1, round(w0*(1-framing['right']))), max(top+1, round(h0*(1-framing['bottom'])))
    source = picture.crop((left, top, right, bottom))
    sw, sh = source.size
    scale = max(width/sw, height/sh)*framing['zoom']  # zoom 1 covers the frame
    dw, dh = max(1, round(sw*scale)), max(1, round(sh*scale))
    dx = round((width-dw)/2+framing['x']*width)
    dy = round((height-dh)/2+framing['y']*height)
    canvas = Image.new('RGBA', size, (255, 255, 255, 255))
    canvas.alpha_composite(source.convert('RGBA').resize((dw, dh), Image.Resampling.LANCZOS)
                           .crop((max(0, -dx), max(0, -dy), max(0, -dx)+min(dw, width), max(0, -dy)+min(dh, height))),
                           (max(0, dx), max(0, dy)))
    return canvas


def clip_duration(clip):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(clip)],
                                capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return 0.


def copy_slot_clip(selected, target):
    """Make `target`'s clip match the image being selected: copy the candidate's clip and start, or remove a
    previous clip when the new selection is a still image."""
    import shutil
    clip, own = sidecar(selected), Path(target).with_suffix('.mp4')
    if clip:
        shutil.copy2(clip, own)
        if offset_path(selected).is_file():shutil.copy2(offset_path(selected), offset_path(target))
        else:offset_path(target).unlink(missing_ok=True)
    else:
        own.unlink(missing_ok=True)
        offset_path(target).unlink(missing_ok=True)


def artwork_lane(folder, config, timings, duration):
    """[{index, start, end, image, video, offset, length}] for each artwork slot in screen order, so the
    timeline can show where every background and clip plays. Mirrors the compositor's slot start times."""
    import math
    from active_artwork import select_manifest
    manifest = select_manifest(Path(folder), config)
    job = json.loads(Path(manifest).read_text(encoding='utf-8'))
    count = len(job.get('prompts', []))
    cues = [line['words'][0]['start'] for line in timings]
    groups = job.get('line_groups')
    if groups and len(groups) == count:
        starts = [cues[group[0]] for group in groups]
    else:
        lines = int(job.get('illustration_lines') or config.get('illustration_lines') or 2)
        art_cues = [max(0., cue-1.) for cue in cues]
        starts = [art_cues[i*lines] for i in range(min(count, math.ceil(len(art_cues)/lines)))]
    lanes = []
    for index, start in enumerate(starts):
        image = Path(manifest).parent/f'{index:03d}.png'
        clip = sidecar(image)
        lanes.append(dict(index=index, start=start, end=starts[index+1] if index+1 < len(starts) else duration,
                          image=image, video=clip, offset=clip_offset(image) if clip else 0.,
                          framing=clip_framing(image) if clip else None,
                          length=clip_duration(clip) if clip else 0.))
    return lanes


def import_clip(source, folder):
    """Normalise an uploaded clip into `folder` as 000.mp4 (H.264, no audio, at most 1920 px wide, 30 fps,
    MAX_SECONDS long) and save its first frame as the slot's still image 000.png. Returns the still."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    clip, still = folder/'000.mp4', folder/'000.png'
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-t', str(MAX_SECONDS), '-an',
                        '-vf', f"scale='min({MAX_WIDTH},iw)':-2,fps={FPS}", '-c:v', 'libx264', '-preset', 'veryfast',
                        '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(clip)],
                       check=True, capture_output=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(clip), '-frames:v', '1', str(still)],
                       check=True, capture_output=True)
    except FileNotFoundError as exc:
        raise ValueError('FFmpeg is needed to import video clips; install it and make sure it is on the PATH') from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:] or ['unknown error']
        raise ValueError('This video could not be read: '+detail[0]) from exc
    with Image.open(still) as image:
        image.convert('RGBA').save(still)
    return still


class VideoArt:
    """The frames of one clip, decoded once into a cache beside it and read back as needed."""

    def __init__(self, clip, prepare):
        self.clip = Path(clip)
        self.prepare = prepare  # the same fitting the slot's still image gets
        self.offset = clip_offset(self.clip.with_suffix('.png'))  # start frame chosen in the timeline
        digest = hashlib.sha256(self.clip.read_bytes()).hexdigest()[:16]
        self.folder = self.clip.parent/'.frames'/digest
        self.fingerprint = digest
        self.count = None
        self.cached = (None, None)

    def decode(self):
        if self.count is not None:
            return
        from filelock import FileLock
        done = self.folder/'frames.json'
        with FileLock(str(self.folder)+'.lock', timeout=-1):  # parallel render workers share one decode
            if not done.is_file():
                self.folder.mkdir(parents=True, exist_ok=True)
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(self.clip), '-vf', f'fps={FPS}',
                                '-q:v', '2', str(self.folder/'%05d.jpg')], check=True, capture_output=True)
                count = len(list(self.folder.glob('*.jpg')))
                if not count:
                    raise ValueError(f'No frames could be read from {self.clip.name}')
                done.write_text(json.dumps(dict(count=count, fps=FPS)), encoding='utf-8')
        self.count = json.loads(done.read_text(encoding='utf-8'))['count']

    def frame(self, seconds):
        """The prepared picture `seconds` into the clip, looping."""
        self.decode()
        number = int(max(0., seconds+self.offset)*FPS) % self.count
        if self.cached[0] != number:
            with Image.open(self.folder/f'{number+1:05d}.jpg') as source:
                self.cached = (number, self.prepare(source.convert('RGBA')))
        return self.cached[1]
