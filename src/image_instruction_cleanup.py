"""Ignore song summaries that older YouTube imports inserted into image instructions."""
import re


def clean_legacy_imported_meaning(value):
    text = str(value or '').strip()
    if re.match(r'^Song meaning \(a non-literal reading of the full lyrics\):', text, re.I):
        return ''
    if re.match(r'^The narrator is\b', text, re.I) and re.search(r'\bcentral message\b', text, re.I):
        return ''
    return text
