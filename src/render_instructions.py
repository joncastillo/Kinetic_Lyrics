"""Special instructions typed for the renderer, such as: Apply a neon effect to the word "neong".

Each line (or sentence) names one or more words in quotes and what to do with them: a letter effect from the
catalog, matched by its name ("neon" finds Neon tube ignite), and/or a colour by name or #hex. A word is matched
wherever it is sung, ignoring case and punctuation. Lines that name no word, or nothing to do, are reported back
so the person can rephrase them; they never stop a render.

A line that names no word but asks for the lettering as a whole in a colour, such as "Make all lyrics gold" or
"Accent colour #FF5DA2", sets the song's line ink or accent colour instead, wherever lettering uses them.
"""
import re
import string

QUOTED = re.compile(r'["“”„«»]([^"“”„«»]+)["“”„«»]|(?<![\w])[\'‘’]([^\'‘’]+)[\'‘’](?![\w])')
UNQUOTED = re.compile(r'\bwords?\s+([^\s,.;:!?]+)', re.IGNORECASE)
HEX = re.compile(r'#([0-9a-fA-F]{6})\b')
COLORS = {'red': '#E53935', 'crimson': '#C2185B', 'pink': '#FF3D7F', 'rose': '#F48FB1', 'orange': '#FB8C00',
          'gold': '#FFC93C', 'golden': '#FFC93C', 'yellow': '#FFD23F', 'green': '#43A047', 'teal': '#26A69A',
          'cyan': '#4CC9FF', 'blue': '#1E88E5', 'navy': '#1A237E', 'purple': '#8E44AD', 'violet': '#8A6BFF',
          'magenta': '#E040FB', 'white': '#FFFFFF', 'black': '#111111', 'silver': '#CFD8DC', 'grey': '#9E9E9E',
          'gray': '#9E9E9E', 'brown': '#795548'}
# A song-wide colour line talks about the lettering as a whole; "accent" or "highlight" targets the accent colour.
WHOLE = re.compile(r'\b(all|every|lyrics?|text|typography|lettering|letters|font|type|ink)\b', re.IGNORECASE)
ACCENT_WORDS = re.compile(r'\b(accents?|highlights?|hero)\b', re.IGNORECASE)
# Words that say nothing about which effect is meant.
FILLER = frozenset('''a an the to of on in for with and or as at by into onto this that these those word words letter
letters lettering apply applies add use make give put set effect effects style styled look please it its them'''.split())


def bare(text):
    return text.strip(string.punctuation+'“”‘’«»„ ').lower()


def color_in(text):
    """(r, g, b) for the first #hex or colour name in the text, or None."""
    if HEX.search(text):
        value = HEX.search(text).group(1)
        return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))
    named = next((COLORS[w] for w in re.findall(r'[a-z]+', text.lower()) if w in COLORS), None)
    return tuple(int(named[i:i+2], 16) for i in (1, 3, 5)) if named else None


def parse_instructions(text, entrances):
    """[(directive, problem)] for every instruction line: a directive is dict(words=set of bare words,
    effect=entrance effect id or None, color=(r, g, b) or None), or for a song-wide colour line
    dict(words=None, scope='ink' or 'accent', color=(r, g, b)); a problem is a short reason it was skipped."""
    results = []
    for line in re.split(r'[\n;]+|(?<=[.!?])\s+(?=[A-Z])', text or ''):
        line = line.strip()
        if not line:
            continue
        quoted = {bare(a or b) for a, b in QUOTED.findall(line)}
        whole = color_in(line) if not quoted and (WHOLE.search(line) or ACCENT_WORDS.search(line)) else None
        if whole:
            results.append((dict(words=None, scope='accent' if ACCENT_WORDS.search(line) else 'ink', color=whole), None))
            continue
        words = quoted or {bare(w) for w in UNQUOTED.findall(line)}
        words = {w for w in words if w}
        if not words:
            results.append((None, f'No word named in "{line}" (put the word in quotes)'))
            continue
        rest = QUOTED.sub(' ', line).lower()
        color = color_in(rest)
        effect = match_effect(rest, entrances, ignore=set(COLORS) if color else set())
        if effect is None and color is None:
            results.append((None, f'No known effect or colour in "{line}"'))
            continue
        results.append((dict(words=words, effect=effect, color=color), None))
    return results


def match_effect(text, entrances, ignore=()):
    """The entrance effect whose ID and name share the most words with the text (prefix matches count, so
    "glassy" finds glass), or None."""
    asked = [w for w in re.findall(r'[a-z]+', text) if w not in FILLER and w not in ignore and len(w) > 2]
    if not asked:
        return None
    best, best_score = None, (0, 0.)
    for effect_id, recipe in entrances.items():
        names = set(effect_id.split('-')) | set(re.findall(r'[a-z]+', str(getattr(recipe, 'name', '')).lower()))
        names = {n for n in names-FILLER if len(n) > 2}
        hits = sum(1 for w in asked if any(n.startswith(w[:5]) or w.startswith(n[:5]) for n in names))
        score = (hits, hits/max(1, len(names)))  # ties go to the effect whose name is mostly what was asked
        if hits and score > best_score:
            best, best_score = effect_id, score
    return best


def word_directives(data, text, entrances):
    """{(line, word index): directive} for every sung word an instruction names, plus the problems found."""
    directives, problems = {}, []
    for directive, problem in parse_instructions(text, entrances):
        if problem:
            problems.append(problem)
            continue
        if directive['words'] is None:
            continue
        found = False
        for line, entry in enumerate(data):
            for index, word in enumerate(entry['words']):
                if bare(word['text']) in directive['words']:
                    merged = dict(directives.get((line, index), {}))
                    merged.update({k: v for k, v in directive.items() if k != 'words' and v is not None})
                    directives[(line, index)] = merged
                    found = True
        if not found:
            problems.append('Not sung in this song: '+', '.join(f'"{w}"' for w in sorted(directive['words'])))
    return directives, problems


def typography_colors(text):
    """Song-wide (ink, accent) colours asked for in the instructions, each (r, g, b) or None; later lines win."""
    chosen = dict(ink=None, accent=None)
    for directive, _ in parse_instructions(text, {}):
        if directive and directive['words'] is None:
            chosen[directive['scope']] = directive['color']
    return chosen['ink'], chosen['accent']
