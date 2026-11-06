"""Lyric lines and word timings: reading, checking and repairing them."""
from __future__ import annotations
import math
import json
import re
import sys
from core.text import normalized


# Genius page furniture. These are matched case-sensitively and anchored, because looser patterns also match
# real lyrics ("I see the way you live", "Singing these lyrics").
HEADER = re.compile(r'\d*\s*Contributors?\b.*|.+\sLyrics')
BANNER = re.compile(r'^See .+ Live(?=Get tickets|$)|Get tickets as low as')


def normalized_newlines(text):
    """Normalize Windows (including accidentally doubled CR) and old-Mac line endings."""
    return re.sub(r'\r+\n', '\n', str(text or '')).replace('\r', '\n')


def sanitize_lyrics(text):
    """Deterministically strip Genius/web-scraper ad banners, recommendation blocks, and embed tags."""
    if not text:
        return ''
    lines = []
    skip_block = False
    for raw in normalized_newlines(text).split('\n'):
        line = re.sub(r'\s+', ' ', raw).strip()
        line = re.sub(r'\d*\s*Embed$', '', line, flags=re.I).strip()
        if not lines and HEADER.fullmatch(line):
            continue
        if re.search(r'\bYou might also like\b', line, re.I):
            skip_block = True
            continue
        if BANNER.search(line):
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
    def content(text):
        return [line for line in (re.sub(r'\s+', ' ', raw_line).strip() for raw_line in text.splitlines()) if line]
    # Rewrite the file only when something was actually removed (not for line endings or spacing), and keep
    # the original beside it once, so a wrongly removed line can always be recovered.
    if content(cleaned) != content(raw):
        try:
            original = path.with_name(path.stem + '.original' + path.suffix)
            if not original.exists():
                original.write_text(raw, encoding='utf-8')
            path.write_text(cleaned + '\n', encoding='utf-8')
            print(f'Cleaned web scraping and recommendation artifacts from lyrics; the original is in {original.name}.', flush=True)
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


def timing_text_matches(data, lines):
    return (isinstance(data, list) and len(data) == len(lines)
            and all(isinstance(item, dict) and item.get('text') == line
                    for item, line in zip(data, lines)))


def imported_timings(payload):
    """Read a timeline export or raw timing list without changing reviewed timestamps."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload.lstrip('\ufeff'))
        except ValueError as exc:
            raise ValueError('The lyric timing file is not valid JSON') from exc
    data = payload.get('timings') if isinstance(payload, dict) else payload
    if not isinstance(data, list) or not data:
        raise ValueError('The lyric timing file must contain a non-empty timings list')
    clean = []
    for index, line in enumerate(data, 1):
        if not isinstance(line, dict) or not isinstance(line.get('text'), str) or not line['text'].strip():
            raise ValueError(f'Timing line {index} needs lyric text')
        if '\n' in line['text'] or '\r' in line['text'] or re.fullmatch(r'\s*\[.*\]\s*', line['text']):
            raise ValueError(f'Timing line {index} must be a single lyric line')
        if not isinstance(line.get('words'), list) or not line['words']:
            raise ValueError(f'Timing line {index} needs word timestamps')
        words = []
        for word in line['words']:
            if (not isinstance(word, dict) or not isinstance(word.get('text'), str) or not word['text'].strip()
                    or any(type(word.get(key)) not in (int, float) for key in ('start', 'end'))):
                raise ValueError(f'Timing line {index} needs word text and numeric start/end timestamps')
            words.append(dict(word))
        clean.append(dict(line, text=line['text'].strip(), words=words))
    validate(clean, [line['text'] for line in clean], max(w['end'] for line in clean for w in line['words']))
    return clean


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
