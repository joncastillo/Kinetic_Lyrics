"""Lyric lines grouped into squarish, justified blocks.

Consecutive lines that are sung close together form one block (a couplet or a short
verse). Each block is set like a poster: its words are broken into rows and every row is
scaled so it fills the same width, so short rows become big and long rows become small.
The row breaks are the ones whose finished block comes closest to the target shape (a
wide rectangle on a landscape screen), preferring breaks between sung lines so each line
reads as a row, without letting a lone short word grow absurdly large. Pure layout: no
drawing, no timing.
"""
import math

BLOCK_GAP = 1.4
BLOCK_LINES = 4
BLOCK_WORDS = 14
BLOCK_SECONDS = 10.
TARGET_RATIO = .58
OFF_LINE_BREAK = .2
MAX_ROW_SCALE = 2.6
LEADING = .2
WORD_GAP = .28


def group_lines(data, breaks=()):
    """Index lists of consecutive lines, one per block. A long pause, a full block or a
    line index in `breaks` (such as the start of a new illustration) starts a new block."""
    blocks, current, words = [], [], 0
    breaks = set(breaks)
    for index, line in enumerate(data):
        if current:
            previous = data[current[-1]]
            gap = line['words'][0]['start']-previous['words'][-1]['end']
            span = line['words'][-1]['end']-data[current[0]]['words'][0]['start']
            if (gap > BLOCK_GAP or len(current) >= BLOCK_LINES or words+len(line['words']) > BLOCK_WORDS
                    or span > BLOCK_SECONDS or index in breaks):
                blocks.append(current)
                current, words = [], 0
        current.append(index)
        words += len(line['words'])
    if current:
        blocks.append(current)
    return blocks


def partitions(widths, rows):
    """Contiguous split of the word widths into `rows` rows of nearly equal natural width."""
    count = len(widths)
    prefix = [0.]
    for width in widths:
        prefix.append(prefix[-1]+width)
    target = prefix[-1]/rows
    best = {(0, 0): (0., None)}
    for row in range(1, rows+1):
        for end in range(row, count-(rows-row)+1):
            options = []
            for start in range(row-1, end):
                if (start, row-1) in best:
                    cost = best[(start, row-1)][0]+(prefix[end]-prefix[start]-target)**2
                    options.append((cost, start))
            if options:
                best[(end, row)] = min(options)
    cuts, end = [], count
    for row in range(rows, 0, -1):
        start = best[(end, row)][1]
        cuts.append((start, end))
        end = start
    return cuts[::-1]


def justify(sizes, groups, width=1., leading=LEADING):
    """Rows scaled to `width`: [(scale, top, [x of each word])] and the total height.
    `sizes` holds (natural width, cap height) per word at one reference size."""
    rows, top = [], 0.
    for start, end in groups:
        row = sizes[start:end]
        cap = max(h for _, h in row)
        gap = cap*WORD_GAP
        natural = sum(w for w, _ in row)+gap*(len(row)-1)
        scale = width/natural
        xs, x = [], 0.
        for w, _ in row:
            xs.append(x*scale)
            x += w+gap
        rows.append((scale, top, xs))
        top += cap*scale*(1+leading)
    return rows, top-rows[-1][0]*max(h for _, h in sizes[groups[-1][0]:groups[-1][1]])*leading


def line_rows(lines, widths):
    """Each sung line as one row, then the widest row split in two, again and again."""
    rows, start = [], 0
    for count in lines:
        rows.append((start, start+count))
        start += count
    yield list(rows)
    while any(b-a > 1 for a, b in rows):
        widest = max((r for r in rows if r[1]-r[0] > 1), key=lambda r: sum(widths[r[0]:r[1]]))
        a, b = widest
        halves = partitions(widths[a:b], 2)
        index = rows.index(widest)
        rows[index:index+1] = [(a+x, a+y) for x, y in halves]
        yield list(rows)


def layout_block(sizes, ratio=TARGET_RATIO, width=1., lines=None, leading=LEADING):
    """Row breaks and placement for one block of words; `lines` holds each sung line's word count and
    `leading` the gap between rows as a share of the taller row's cap height.

    Returns dict(rows=[(start, end)], words=[dict(row, x, y, scale)], width, height), where
    y is the top of the word's row and scale multiplies the reference size."""
    count = len(sizes)
    widths = [w for w, _ in sizes]
    boundaries = set()
    for total in (sum((lines or [count])[:n]) for n in range(1, len(lines or [count]))):
        boundaries.add(total)
    candidates = [partitions(widths, rows) for rows in range(1, min(count, 8)+1)]
    if lines:
        candidates += list(line_rows(lines, widths))
    best = None
    for groups in candidates:
        placed, height = justify(sizes, groups, width, leading)
        heights = sorted(scale*max(h for _, h in sizes[a:b]) for (scale, _, _), (a, b) in zip(placed, groups))
        middle = heights[len(heights)//2]
        cost = abs(math.log(height/width/ratio))
        cost += sum(max(0., h/middle-MAX_ROW_SCALE) for h in heights)
        cost += OFF_LINE_BREAK*sum(1 for _, end in groups[:-1] if end not in boundaries)
        cost += OFF_LINE_BREAK*sum(1 for b in boundaries if b not in {end for _, end in groups[:-1]})*.5
        if best is None or cost < best[0]:
            best = (cost, groups, placed, height)
    _, groups, placed, height = best
    words = []
    for number, ((start, end), (scale, top, xs)) in enumerate(zip(groups, placed)):
        for k in range(start, end):
            words.append(dict(row=number, x=xs[k-start], y=top, scale=scale))
    return dict(rows=groups, words=words, width=width, height=height)
