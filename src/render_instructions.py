"""Special instructions typed for the renderer, such as: Apply a neon effect to the word "neong".

Each line (or sentence) names one or more words in quotes and what to do with them: a letter effect from the
catalog, matched by its name ("neon" finds Neon tube ignite), and/or a colour by name or #hex. A word is matched
wherever it is sung, ignoring case and punctuation. Lines that name no word, or nothing to do, are reported back
so the person can rephrase them; they never stop a render.
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
# Words that say nothing about which effect is meant.
FILLER = frozenset('''a an the to of on in for with and or as at by into onto this that these those word words letter
letters lettering apply applies add use make give put set effect effects style styled look please it its them'''.split())


def bare(text):
    return text.strip(string.punctuation+'“”‘’«»„ ').lower()


def parse_instructions(text, entrances):
    """[(directive, problem)] for every instruction line: a directive is dict(words=set of bare words,
    effect=entrance effect id or None, color=(r, g, b) or None); a problem is a short reason it was skipped."""
    results = []
    for line in re.split(r'[\n;]+|(?<=[.!?])\s+(?=[A-Z])', text or ''):
        line = line.strip()
        if not line:
            continue
        words = {bare(a or b) for a, b in QUOTED.findall(line)} or {bare(w) for w in UNQUOTED.findall(line)}
        words = {w for w in words if w}
        if not words:
            results.append((None, f'No word named in "{line}" (put the word in quotes)'))
            continue
        rest = QUOTED.sub(' ', line).lower()
        color = None
        if HEX.search(rest):
            value = HEX.search(rest).group(1)
            color = tuple(int(value[i:i+2], 16) for i in (0, 2, 4))
        else:
            named = next((COLORS[w] for w in re.findall(r'[a-z]+', rest) if w in COLORS), None)
            if named:
                color = tuple(int(named[i:i+2], 16) for i in (1, 3, 5))
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
