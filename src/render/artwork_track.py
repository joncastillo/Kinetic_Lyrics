"""The illustrations behind the lyrics: loaded at the frame size, when each appears, and how each is shown.

Split out of the Compositor, which keeps the lyrics; this class knows nothing about words. The Compositor builds one
(`Compositor.artwork`) and forwards the attributes and methods the engines use (art, art_starts, illustration(),
scenery(), art_crossing()...), so code that reads them from the compositor is unchanged.
"""

import bisect
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from core.easing import cubic_out as ease
from render.layout import FULL_FRAME, illustration_layout
from render.timeline import checked_art_times, illustration_starts


class ArtworkTrack:
    def __init__(
        self, width, height, duration, artwork_mode, cinematic, layout_seed, lead_in, source_cues, illustration_lines
    ):
        self.width, self.height, self.duration = width, height, duration
        self.artwork_mode, self.cinematic, self.layout_seed = artwork_mode, cinematic, layout_seed
        self.lead_in, self.source_cues, self.illustration_lines = lead_in, source_cues, illustration_lines
        self.art, self.art_starts, self.mattes, self.open_boxes, self._scenery = [], [], [], [], {}
        self.videos, self.clips, self.illustration_paths, self.artwork_revisions = {}, [], [], {}

    def load(self, illustrations, preserve_art_slots, art_times, video_clips):
        """Load the illustrations (and mattes, clips and uploaded videos) at the frame size, and when each appears."""
        width, height, duration = self.width, self.height, self.duration
        artwork_mode, cinematic, layout_seed = self.artwork_mode, self.cinematic, self.layout_seed
        self.art = []
        self.mattes, self.open_boxes, self._scenery = [], [], {}
        self.videos = {}  # art slot -> VideoArt, for slots whose artwork is an uploaded clip
        self.illustration_paths = [Path(p) for p in (illustrations or [])]
        self.artwork_revisions = {}
        self.text_box = (0, 0, width, height)
        if illustrations:
            initial = illustration_layout(0, width, height, cinematic, artwork_mode, layout_seed)
            self.art_box, self.text_box = initial['art_box'], initial['text_box']
            seen, kept = set(), []
            # Line groups and hand-placed times count illustrations by slot, so a repeated picture must keep its slot;
            # dropping it would shift every later painting and fail the groups' or times' count.
            record = Path(illustrations[0]).parent / 'illustrations.json'
            try:
                grouped = (
                    record.is_file() and json.loads(record.read_text(encoding='utf-8')).get('line_groups') is not None
                )
            except (OSError, ValueError, AttributeError):
                grouped = False
            keep_slots = preserve_art_slots or grouped or art_times is not None
            for slot, path in enumerate(illustrations):
                source_bytes = Path(path).read_bytes()
                from artwork.video_art import VideoArt, sidecar

                clip = sidecar(path)
                # A clip beside the still makes the slot a video; its own fingerprint marks the slot changed.
                from artwork.video_art import clip_settings

                fingerprint = hashlib.sha256(
                    source_bytes
                    + (clip.read_bytes() + json.dumps(clip_settings(path), sort_keys=True).encode() if clip else b'')
                ).digest()
                self.artwork_revisions[str(slot)] = fingerprint.hex()
                if fingerprint in seen and not keep_slots:
                    continue
                seen.add(fingerprint)
                # Generated clips are keyed by the still alone; an uploaded clip beside it is handled by self.videos.
                kept.append(hashlib.sha256(source_bytes).hexdigest())
                if artwork_mode == 'matte':
                    from artwork.greenscreen import load as load_matte, open_box

                    image, matte = load_matte(BytesIO(source_bytes))
                    self.art.append(ImageOps.fit(image, (width, height), Image.Resampling.LANCZOS))
                    self.mattes.append(ImageOps.fit(matte, (width, height), Image.Resampling.LANCZOS))
                    self.open_boxes.append(open_box(self.mattes[-1], round(min(width, height) * 0.03)))
                    continue
                with Image.open(BytesIO(source_bytes)) as source:
                    image = source.convert('RGBA')
                    if artwork_mode in FULL_FRAME:
                        prepare = lambda picture: ImageOps.fit(picture, (width, height), Image.Resampling.LANCZOS)
                    else:
                        box = illustration_layout(len(self.art), width, height, cinematic, artwork_mode, layout_seed)[
                            'art_box'
                        ]
                        size = tuple(max(1, round(v * 0.94)) for v in box[2:]) if cinematic else box[2:]

                        def prepare(picture, size=size):
                            bounds = picture.getchannel('A').getbbox()
                            if not bounds:
                                raise ValueError(f'Illustration is fully transparent: {path}')
                            return ImageOps.contain(picture.crop(bounds), size, Image.Resampling.LANCZOS)

                    if clip:
                        from artwork.video_art import clip_framing, frame_picture

                        framing = clip_framing(path)
                        prepare = lambda picture, fit=prepare, framing=framing: fit(
                            frame_picture(picture, framing, (width, height))
                        )
                        self.videos[len(self.art)] = VideoArt(clip, prepare)
                    self.art.append(prepare(image))
        self.clips = []
        if self.open_boxes and self.open_boxes[0]:
            self.text_box = self.open_boxes[0]
        self.default_text_box = self.text_box
        line_groups = None
        if illustrations:
            record = Path(illustrations[0]).parent / 'illustrations.json'
            if record.is_file():
                line_groups = json.loads(record.read_text(encoding='utf-8')).get('line_groups')
                if line_groups is not None:
                    from direction.song_structure import valid_line_groups

                    if not valid_line_groups(line_groups, len(self.source_cues)) or len(line_groups) != len(self.art):
                        raise ValueError('Illustration line groups do not match the aligned lyrics')
        self.art_starts = illustration_starts(
            self.source_cues, len(self.art), self.illustration_lines, self.lead_in, line_groups
        )
        if art_times is not None and self.art:
            try:
                self.art_starts = checked_art_times(art_times, len(self.art), duration)
            except ValueError as exc:
                print(f'Warning: ignoring timeline illustration times ({exc}).', flush=True)

    def composition(self, artwork):
        """A stable reading area for each drawing; change only with new art."""
        layout = illustration_layout(
            artwork, self.width, self.height, self.cinematic, self.artwork_mode, self.layout_seed
        )
        if artwork is not None and artwork < len(self.open_boxes) and self.open_boxes[artwork]:
            return layout['art_box'], self.open_boxes[artwork]
        return layout['art_box'], layout['text_box']

    def scenery(self, t):
        """Keyed greenscreen scenery that sits in front of the lyrics, or None outside greenscreen mode.

        While one scene blends into the next, the layer covers everything either scene covers,
        so lyrics never show through the scenery of the outgoing or the incoming picture.
        """
        if not self.mattes or not self.art_starts:
            return None
        current = min(len(self.mattes) - 1, max(0, bisect.bisect_right(self.art_starts, t) - 1))
        blend = ease(min(1.0, max(0.0, (t - self.art_starts[current]) / 0.9))) if current > 0 else 1.0
        if blend >= 1:
            if current not in self._scenery:
                if len(self._scenery) >= 3:
                    self._scenery.pop(next(iter(self._scenery)))
                layer = self.art[current].convert('RGBA')
                layer.putalpha(self.mattes[current])
                self._scenery[current] = layer
            return self._scenery[current]
        layer = Image.blend(self.art[current - 1].convert('RGB'), self.art[current].convert('RGB'), blend).convert(
            'RGBA'
        )
        layer.putalpha(ImageChops.lighter(self.mattes[current - 1], self.mattes[current]))
        return layer

    def illustration(self, frame, index, t):
        if self.artwork_mode in FULL_FRAME:
            return
        if not self.art_starts or t < self.art_starts[0] or t >= self.duration:
            return
        current = bisect.bisect_right(self.art_starts, t) - 1
        progress = ease((t - self.art_starts[current]) / 0.9)

        def draw_art(number, opacity):
            (x, y, w, h), _ = self.composition(number)
            image = self.art[number]
            result = Image.new('RGBA', (w, h))
            if self.cinematic:
                shadow = Image.new('RGBA', image.size, (0, 0, 0, 0))
                shadow.putalpha(image.getchannel('A').point(lambda a: round(a * 0.22)))
                result.alpha_composite(
                    shadow, ((w - image.width) // 2 + round(w * 0.018), (h - image.height) // 2 + round(h * 0.018))
                )
            result.alpha_composite(image, ((w - image.width) // 2, (h - image.height) // 2))
            result.putalpha(result.getchannel('A').point(lambda a: round(a * opacity)))
            frame.paste(result, (x, y), result)

        opacity = min(1.0, max(0.0, (self.duration - t) / 0.45))
        if current > 0 and progress < 1:
            draw_art(current - 1, (1 - progress) * opacity)
        draw_art(current, progress * opacity)

    def art_frame(self, number, t):
        """Scene `number` at time t: its animated clip's frame when one was generated, else the still."""
        clip = self.clips[number] if number < len(self.clips) else None
        if not clip:
            return self.art[number].convert('RGB')
        # A clip plays from the moment its painting is on screen. The first painting is shown from the start of
        # the video, through the instrumental intro, not only from its first lyric (which can be half a minute in).
        return clip.frame(t - (0.0 if number == 0 else self.art_starts[number]))

    def art_crossing(self, current):
        if current <= 0:
            return 0.0
        gap = (
            self.art_starts[current + 1] - self.art_starts[current]
            if current + 1 < len(self.art_starts)
            else self.art_starts[current] - self.art_starts[current - 1]
        )
        return min(20.0, max(1.0, gap * 0.9))

    def advance_videos(self, t):
        """Put each video slot's frame for time t in its place; a clip plays from its slot's start and loops."""
        if not self.videos or not self.art_starts:
            return
        current = max(0, bisect.bisect_right(self.art_starts, t) - 1)
        for slot, video in self.videos.items():
            if current - 1 <= slot <= current + 1 and slot < len(self.art_starts):  # on screen, or crossing in or out
                self.art[slot] = video.frame(t - self.art_starts[slot])
