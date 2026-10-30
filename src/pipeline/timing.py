"""Lyric lines and word timings: reading, checking and repairing them."""
from __future__ import annotations
import math
import re
import sys
from core.text import normalized


def sanitize_lyrics(text):
    """Deterministically strip Genius/web-scraper ad banners, recommendation blocks, and embed tags."""
    if not text:
        return ''
    lines = []
    skip_block = False
    for raw in str(text).replace('\r', '').split('\n'):
        line = re.sub(r'\s+', ' ', raw).strip()
        line = re.sub(r'\d*\s*Embed$', '', line, flags=re.I).strip()
        if not lines and re.fullmatch(r'\d*\s*Contributors?|.*Lyrics', line, re.I):
            continue
        if re.search(r'\bYou might also like\b', line, re.I):
            skip_block = True
            continue
        if re.search(r'See\s+.*\s+Live|Get tickets as low as', line, re.I):
            skip_block = True
            continue
        if skip_block:
            if re.match(r'^\s*\[.*\]\s*$', line):
                skip_block = False
            elif not line:
                skip_block = False
                continue
            else:
                continue
        if re.fullmatch(r'\d*\s*Embed', line, re.I):
            continue
        if line or (lines and lines[-1]):
            lines.append(line)
    return '\n'.join(lines).strip()


def lyrics_lines(path):
    raw = path.read_text(encoding="utf-8-sig")
    cleaned = sanitize_lyrics(raw)
    if cleaned != raw.strip():
        try:
            path.write_text(cleaned + '\n', encoding='utf-8')
            print('Cleaned web scraping and recommendation artifacts from lyrics.', flush=True)
        except OSError:
            pass
    lines = [s.strip() for s in cleaned.splitlines()]
    lines = [s for s in lines if s and not re.fullmatch(r"\[.*\]", s)]
    if not lines:
        raise ValueError("Lyrics contain no lines. Use UTF-8 text; section labels are ignored.")
    return lines


def repair_zero_durations(data, duration):
    """Give collapsed or non-chronological automatic alignments a valid, reviewable duration."""
    repaired = 0
    previous = 0.0
    for line in data:
        for word in line.get('words', []):
            start = float(word.get('start', 0.0))
            end = float(word.get('end', 0.0))
            if not math.isfinite(start) or not math.isfinite(end):
                continue
            if start < previous:
                word['start'] = previous
                start = previous
                repaired += 1
            if end <= start:
                word['end'] = min(duration, start + .08)
                if word['end'] <= word['start']:
                    word['start'] = max(0.0, word['end'] - .08)
                repaired += 1
            if word['end'] > duration + 0.05:
                word['end'] = duration
                if word['start'] >= word['end']:
                    word['start'] = max(0.0, word['end'] - .08)
                repaired += 1
            previous = float(word['start'])
    if repaired:
        print(f'Warning: repaired {repaired} timing issue(s) (zero duration or non-chronological). '
              'Review the generated timings JSON for synchronization.', file=sys.stderr)
    return repaired


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
