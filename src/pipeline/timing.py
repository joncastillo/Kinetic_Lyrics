"""Lyric lines and word timings: reading, checking and repairing them."""
from __future__ import annotations
import math
import re
import sys
from core.text import normalized


def lyrics_lines(path):
    lines = [s.strip() for s in path.read_text(encoding="utf-8-sig").splitlines()]
    lines = [s for s in lines if s and not re.fullmatch(r"\[.*\]", s)]
    if not lines:
        raise ValueError("Lyrics contain no lines. Use UTF-8 text; section labels are ignored.")
    return lines


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
