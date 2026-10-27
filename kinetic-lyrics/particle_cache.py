"""Content keys keep temporary/scaled glyphs from reusing stale geometry."""
from hashlib import blake2b

def sprite_key(image):
    return image.mode,image.size,blake2b(image.tobytes(),digest_size=12).digest()
