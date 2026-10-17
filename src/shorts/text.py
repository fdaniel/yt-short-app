"""Text cleaning shared by narration, cards and captions."""

import re

_MARKUP = set("{}\\")


def clean_text(text: str) -> str:
    """Drop ASS markup characters and anything outside the Basic Multilingual Plane (emoji)."""
    kept = "".join(ch for ch in text if ch not in _MARKUP and ord(ch) <= 0xFFFF)
    return re.sub(r"\s+", " ", kept).strip()
