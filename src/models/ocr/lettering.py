"""RapidOCR check for accidental lettering in generated artwork."""
from __future__ import annotations
import re


def detected_lettering(ocr, image):
    """Ignore tiny low-confidence shape readings; flag substantial drawn lettering."""
    import numpy as np
    results, _ = ocr(np.asarray(image.convert('RGB')))
    readings = [dict(text=entry[1], confidence=float(entry[2])) for entry in (results or [])
                if entry[2] >= .82 and len(re.sub(r'\W', '', entry[1])) >= 3]
    return readings if sum(len(re.sub(r'\W', '', entry['text'])) for entry in readings) >= 6 else []
