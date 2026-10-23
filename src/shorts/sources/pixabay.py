"""Pixabay: free stock video (Pixabay Content License: free commercial use, no credit required).

The API key travels in the address (Pixabay has no other way), so search errors are reported
without it and `shorts.net` hides it from request logs.
"""

import json

import httpx

from shorts.net import fetch_text
from shorts.sources.stock import StockClip, StockSource, fits, sharpest, trusted_file

SEARCH_URL = "https://pixabay.com/api/videos/"
LICENCE_TERMS = ("Pixabay Content License https://pixabay.com/service/license-summary/ "
                 "(free commercial use, credit given in description)")
SEARCH_MAX_BYTES = 2_000_000
PER_PAGE = 20  # enough choice to skip clips used in earlier videos
MAX_QUERY_CHARS = 100
PAGE_PREFIX = "https://pixabay.com/"
FILE_HOST = "cdn.pixabay.com"
_SIZES = ("large", "medium", "small", "tiny")


def _best_file(videos: object) -> str | None:
    renditions = [videos.get(size) for size in _SIZES] if isinstance(videos, dict) else []
    files = [(r["width"], r["height"], r["url"]) for r in renditions if isinstance(r, dict)
             and trusted_file(r.get("url"), FILE_HOST) and isinstance(r.get("width"), int) and isinstance(r.get("height"), int)]
    return sharpest(files)


def parse_search(payload: object) -> list[StockClip]:
    hits = payload.get("hits") if isinstance(payload, dict) else None
    clips = []
    for hit in hits if isinstance(hits, list) else []:
        if not isinstance(hit, dict) or not isinstance(hit.get("id"), int) or not fits(hit.get("duration")):
            continue
        file_url = _best_file(hit.get("videos"))
        page = hit.get("pageURL")
        if file_url and isinstance(page, str) and page.startswith(PAGE_PREFIX):
            clips.append(StockClip(hit["id"], page, float(hit["duration"]), str(hit.get("user") or "Pixabay"), file_url))
    return clips


def search_clips(client: httpx.Client, api_key: str, query: str) -> list[StockClip]:
    params = {"key": api_key, "q": query[:MAX_QUERY_CHARS], "video_type": "film", "safesearch": "true",
              "per_page": PER_PAGE}
    body = fetch_text(client, str(httpx.URL(SEARCH_URL, params=params)), max_bytes=SEARCH_MAX_BYTES)
    return parse_search(json.loads(body))


def _refused(response: httpx.Response) -> bool:
    """Pixabay answers a bad key with 400 "Invalid API key", and other bad requests with 400 too."""
    return response.status_code in (401, 403) or (response.status_code == 400 and "API key" in response.text)


SOURCE = StockSource("pixabay", "Pixabay", "PIXABAY_API_KEY", LICENCE_TERMS, search_clips, refused=_refused)
