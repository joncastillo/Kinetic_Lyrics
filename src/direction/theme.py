"""Mood vocabulary for the legacy renderer, resolved from the theme prompt."""
from __future__ import annotations
import re


def theme_for(prompt):
    """Resolve supported mood vocabulary; preserve the full prompt in metadata."""
    text = prompt.lower()
    if re.search(r"\b(?:sad(?:ness|ly|der)?\b|solemn|melanchol|mourn|somber|sombre|heartbr[eo]k)", text):
        return dict(name="solemn", background="0x101521", ink="DCD7CE", accent="C3A383",
                    motion=28, angle=2, entrance=620, font="Georgia", bold=0)
    if re.search(r"\b(?:joy(?:ful|ous)?\b|happ(?:y|iness|ier)\b|playful|bright|sunny\b|fun(?:ny)?\b)", text):
        return dict(name="playful", background="0x261638", ink="F8F3FF", accent="73DEFF",
                    motion=95, angle=9, entrance=240, font="Arial", bold=-1)
    if re.search(r"\b(?:energetic|edm\b|neon|electric|aggressive|danc(?:e|ing|ey)\b|bold\b)", text):
        return dict(name="electric", background="0x080D16", ink="FFFFFF", accent="D5FF39",
                    motion=130, angle=12, entrance=160, font="Arial", bold=-1)
    if re.search(r"\b(?:romantic|warm(?:th)?\b|lov(?:e|ing|er|ers|ely)\b|tender|dream)", text):
        return dict(name="romantic", background="0x271923", ink="E9E1FF", accent="A9ADFF",
                    motion=45, angle=3, entrance=450, font="Georgia", bold=0)
    return dict(name="minimal", background="0x12151C", ink="F2F2F2", accent="EBCB87",
                motion=60, angle=5, entrance=320, font="Arial", bold=-1)
