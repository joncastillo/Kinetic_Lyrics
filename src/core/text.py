"""Text matching shared by lyric alignment, timing checks, OCR and the language-model replies."""
import json
import re

# Letters and digits in any script, so accented and non-Latin lyrics stay whole words.
WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*")


def normalized(text):
    return "".join(c.casefold() for c in text if c.isalnum())


def words(text):
    """The words of `text`, lower-cased, keeping accented letters and inner apostrophes ("don't")."""
    return WORD.findall(text.casefold())


def json_object(content):
    """A model reply parsed as a JSON object; ValueError for invalid JSON or any other shape."""
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f'Expected a JSON object, got {type(value).__name__}')
    return value
