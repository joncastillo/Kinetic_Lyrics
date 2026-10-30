"""Text matching shared by lyric alignment, timing checks and OCR."""


def normalized(text):
    return "".join(c.casefold() for c in text if c.isalnum())
