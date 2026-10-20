"""Pexels: free stock video (Pexels License: free commercial use, no credit required).

New Pexels API keys were paused in September 2026; existing keys still work.
"""

import json

import httpx

from shorts.net import fetch_text
from shorts.sources.stock import StockClip, StockSource, fits, sharpest, trusted_file

SEARCH_URL = "https://api.pexels.com/videos/search"
LICENCE_TERMS = "Pexels License https://www.pexels.com/license/ (free commercial use, credit given in description)"
SEARCH_MAX_BYTES = 2_000_000
PER_PAGE = 10
PAGE_PREFIX = "https://www.pexels.com/"
FILE_HOSTS = ("videos.pexels.com", "player.vimeo.com")


def _trusted_file(link: object) -> bool:
    return any(trusted_file(link, host) for host in FILE_HOSTS)


def _best_file(files: list) -> str | None:
    """The sharpest fitting mp4 from a Pexels host."""
    mp4s = [(f["width"], f["height"], f["link"]) for f in files if isinstance(f, dict)
            and f.get("file_type") == "video/mp4" and _trusted_file(f.get("link"))
            and isinstance(f.get("width"), int) and isinstance(f.get("height"), int)]
    return sharpest(mp4s)


def parse_search(payload: object) -> list[StockClip]:
    videos = payload.get("videos") if isinstance(payload, dict) else None
    clips = []
    for video in videos if isinstance(videos, list) else []:
        if not isinstance(video, dict) or not isinstance(video.get("id"), int) or not fits(video.get("duration")):
            continue
        file_url = _best_file(video.get("video_files") or [])
        user = video.get("user") if isinstance(video.get("user"), dict) else {}
        page = video.get("url")
        if file_url and isinstance(page, str) and page.startswith(PAGE_PREFIX):
            clips.append(StockClip(video["id"], page, float(video["duration"]), str(user.get("name") or "Pexels"),
                                   file_url))
    return clips


def search_clips(client: httpx.Client, api_key: str, query: str) -> list[StockClip]:
    url = str(httpx.URL(SEARCH_URL, params={"query": query, "orientation": "portrait", "size": "medium",
                                            "per_page": PER_PAGE}))
    body = fetch_text(client, url, max_bytes=SEARCH_MAX_BYTES, headers={"Authorization": api_key})
    return parse_search(json.loads(body))


SOURCE = StockSource("pexels", "Pexels", "PEXELS_API_KEY", LICENCE_TERMS, search_clips)
