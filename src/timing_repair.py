"""Recover lyric word times from timestamped transcription when forced alignment collapses."""

from difflib import SequenceMatcher
import re


def collapsed_lines(data):
    """Line numbers whose words were squeezed too tightly to be sung or read."""
    result = []
    for index, line in enumerate(data):
        words = line.get('words', [])
        if len(words) < 4:
            continue
        span = float(words[-1]['end']) - float(words[0]['start'])
        if span < max(.5, .13 * len(words)):
            result.append(index)
    return result


def transcript_timing(lines, heard, min_coverage=.75):
    """Map Whisper's timestamped words onto the exact supplied lyric text.

    Exact matches keep their measured timestamps. Only words omitted or changed by
    transcription are interpolated between surrounding matched words.
    """
    target = [(line_index, word) for line_index, line in enumerate(lines)
              for word in line.split()]
    clean = lambda value: re.sub(r'\W+', '', value.casefold())
    expected = [clean(word) for _, word in target]
    observed = [(clean(str(item.get('word', item.get('text', '')))), item)
                for item in heard]
    observed = [(word, item) for word, item in observed if word]
    matcher = SequenceMatcher(None, expected, [word for word, _ in observed], autojunk=False)
    matched = {a + offset: observed[b + offset][1]
               for a, b, count in matcher.get_matching_blocks() for offset in range(count)}
    if not target or len(matched) / len(target) < min_coverage:
        raise ValueError('Transcription did not match enough supplied lyrics for reliable word timing.')
    timed = [None] * len(target)
    for index, item in matched.items():
        timed[index] = (float(item['start']), float(item['end']))
    anchors = sorted(matched)
    for left, right in zip([-1] + anchors, anchors + [len(target)]):
        count = right - left - 1
        if not count:
            continue
        before = timed[left][1] if left >= 0 else max(0., timed[right][0] - .22 * count)
        after = timed[right][0] if right < len(target) else before + .22 * count
        available = max(0., after - before)
        for offset in range(count):
            start = before + available * offset / count
            end = before + available * (offset + 1) / count
            timed[left + offset + 1] = (start, end)
    output = [dict(text=line, words=[]) for line in lines]
    previous = 0.
    for (line_index, word), (start, end) in zip(target, timed):
        start = max(previous, start)
        end = max(start + .08, end)
        output[line_index]['words'].append(dict(text=word, start=round(start, 3), end=round(end, 3)))
        previous = start
    return output


WORD_SECONDS = .3  # an unhurried sung word, used when the audio gave no usable time


def spread_collapsed(data):
    """Re-time lines neither aligner could place (often backing vocals transcription never heard).

    Each run of consecutive collapsed lines has its words spread evenly over the free time between
    the line before the run and the line after it, about WORD_SECONDS per word where there is room.
    Returns the line numbers that changed, so the caller can ask for them to be reviewed.
    """
    collapsed = collapsed_lines(data)
    runs = []
    for index in collapsed:
        if runs and runs[-1][-1] == index - 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    timed = [i for i, line in enumerate(data) if line.get('words')]
    for run in runs:
        words = [word for index in run for word in data[index]['words']]
        before = [i for i in timed if i < run[0]]
        after = [i for i in timed if i > run[-1]]
        low = float(data[before[-1]]['words'][-1]['end']) if before else 0.
        start = max(low, float(words[0]['start']))
        high = float(data[after[0]]['words'][0]['start']) if after else start + WORD_SECONDS * len(words)
        # use the time the squeezed words already claim, widened to the free gap around them
        start = max(low, min(start, high - WORD_SECONDS * len(words)))
        step = max(.08, (high - start) / len(words)) if high > start else .08
        step = min(step, WORD_SECONDS * 2)
        for offset, word in enumerate(words):
            word['start'] = round(start + step * offset, 3)
            word['end'] = round(start + step * (offset + .9), 3)
    return [index for run in runs for index in run]
