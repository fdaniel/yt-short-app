"""Turn a pasted YouTube link into a video id."""

import re
from urllib.parse import parse_qs, urlsplit

_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "studio.youtube.com", "youtu.be"}


def youtube_id_from(text: str) -> str | None:
    """None for an empty field; ValueError for anything that is not a YouTube video link or id."""
    text = text.strip()
    if not text:
        return None
    if _ID.fullmatch(text):
        return text
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or parts.hostname not in _HOSTS:
        raise ValueError(f"not a YouTube link: {text[:80]}")
    candidates = parse_qs(parts.query).get("v", []) + [p for p in parts.path.split("/") if p]
    for candidate in candidates:
        if _ID.fullmatch(candidate):
            return candidate
    raise ValueError(f"no video id in that link: {text[:80]}")
