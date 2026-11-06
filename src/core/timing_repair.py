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
    if not target or not matched or len(matched) / len(target) < min_coverage:
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


def read_mono(audio, rate=16000):
    """(samples, rate) of `audio` as one channel. WAV and FLAC are read directly; anything soundfile cannot open
    (m4a, mp3 and other compressed songs) is decoded by FFmpeg."""
    import numpy as np
    try:
        import soundfile as sf
        samples, native = sf.read(str(audio), always_2d=True)
        return samples.mean(1), native
    except Exception:  # noqa: BLE001 (a format soundfile does not know: FFmpeg reads it)
        import subprocess
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(audio), '-f', 'f32le', '-ac', '1', '-ar', str(rate), 'pipe:1'],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.float32).astype(np.float64), rate


def voiced_phrases(audio, hop=.05, gap=.8, quiet_db=30.):
    """[(start, end)] of sung phrases in a vocal stem: stretches within `quiet_db` of the loud singing, joined across
    pauses shorter than `gap` seconds. Used to place lines no aligner could, where the voice actually is."""
    import numpy as np
    mono, rate = read_mono(audio)
    size = max(1, int(rate*hop))
    frames = len(mono)//size
    if not frames:
        return []
    rms = np.sqrt((mono[:frames*size].reshape(frames, size)**2).mean(1))+1e-9
    level = 20*np.log10(rms)
    loud = np.percentile(level, 95)
    voiced = level > max(loud-quiet_db, -50.)
    phrases, begin = [], None
    for k, on in enumerate(np.append(voiced, False)):
        if on and begin is None:
            begin = k
        elif not on and begin is not None:
            phrases.append([begin*hop, k*hop])
            begin = None
    joined = []
    for phrase in phrases:
        if joined and phrase[0]-joined[-1][1] < gap:
            joined[-1][1] = phrase[1]
        else:
            joined.append(phrase)
    return [(round(a, 3), round(b, 3)) for a, b in joined if b-a >= .25]


def syllables(word):
    """A rough syllable count: groups of vowels (at least one)."""
    word = re.sub(r'[^a-z]', '', word.casefold())
    if word.endswith('e') and not word.endswith(('le', 'ee')) and len(re.findall(r'[aeiouy]+', word[:-1])):
        word = word[:-1]          # a silent final e: love, take, life
    return max(1, len(re.findall(r'[aeiouy]+', word)))


def place_on_phrase(words, begin, end):
    """Spread words over a sung phrase, each taking time in proportion to its syllables."""
    weights = [syllables(w['text']) for w in words]
    total = sum(weights)
    cursor = begin
    for word, weight in zip(words, weights):
        length = (end-begin)*weight/total
        word['start'] = round(cursor, 3)
        word['end'] = round(cursor+length*.92, 3)
        cursor += length


def spread_collapsed(data, phrases=None):
    """Re-time lines neither aligner could place (often backing vocals transcription never heard).

    With the vocal stem's sung `phrases` (see voiced_phrases), each line of a run of such lines goes on the next
    phrase in the free time between the line before the run and the line after it, its words spread over the phrase
    by syllables. Without them (or when the gap holds no singing), the words are spread evenly over that free time,
    about WORD_SECONDS per word where there is room. Returns the line numbers that changed, so the caller can ask for
    them to be reviewed.
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
        high = float(data[after[0]]['words'][0]['start']) if after else None
        if phrases:
            sung = [(max(a, low), b if high is None else min(b, high)) for a, b in phrases
                    if b > low+.1 and (high is None or a < high-.1)]
            sung = [(a, b) for a, b in sung if b-a >= .25]
            # A line starts a new phrase: when the line before ends inside a phrase (the aligner cut it short), that
            # phrase is still its own; it keeps it to the end and the run starts on the next one.
            fresh = [(a, b) for a, b in sung if a > low+.05]
            own = next((p for p in phrases if p[0] < low-.2 and p[1] > low+.3), None)
            if before and fresh and own is not None and len(fresh) >= len(run):
                last = data[before[-1]]['words'][-1]
                last['end'] = round(max(float(last['end']), min(own[1], fresh[0][0]-.05)), 3)
                sung = fresh
            if len(sung) >= 1:
                rest = run[len(sung)-1:]  # the lines that share the last phrase, one after another
                for number, index in enumerate(run):
                    if number < len(sung)-1 or len(run) == 1:
                        a, b = sung[number] if number < len(sung) else sung[-1]
                    else:  # more lines than phrases: the rest share the last phrase
                        a, b = sung[-1]
                        share = (b-a)/len(rest)
                        a, b = a+share*(index-rest[0]), a+share*(index-rest[0]+1)
                    place_on_phrase(data[index]['words'], a, b)
                continue
        start = max(low, float(words[0]['start']))
        high = high if high is not None else start + WORD_SECONDS * len(words)
        # use the time the squeezed words already claim, widened to the free gap around them
        start = max(low, min(start, high - WORD_SECONDS * len(words)))
        step = max(.08, (high - start) / len(words)) if high > start else .08
        step = min(step, WORD_SECONDS * 2)
        for offset, word in enumerate(words):
            word['start'] = round(start + step * offset, 3)
            word['end'] = round(start + step * (offset + .9), 3)
    return [index for run in runs for index in run]
