"""Pexels: free stock video (Pexels License: free commercial use, no credit required).

Used for stories with no game trailer, mostly hardware news. The footage is generic
(a laptop, a chip), never the announced product itself.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from shorts.config import Settings
from shorts.media.ffmpeg import FFmpegError, strip_audio
from shorts.models import Asset, AssetKind, RightsBasis
from shorts.net import DownloadTooLarge, UnsafeURLError, download_file, fetch_text

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.pexels.com/videos/search"
LICENCE_TERMS = "Pexels License https://www.pexels.com/license/ (free commercial use, credit given in description)"
SEARCH_MAX_BYTES = 2_000_000
MAX_CLIP_BYTES = 100_000_000
PER_PAGE = 10
MAX_CLIPS = 4
MAX_PER_QUERY = 2
MIN_DURATION_S = 5
MAX_DURATION_S = 60
MIN_SIDE, MAX_SIDE = 720, 1440  # sharp enough for 1080x1920, without downloading 4K
PAGE_PREFIX = "https://www.pexels.com/"
FILE_HOSTS = ("videos.pexels.com", "player.vimeo.com")
_DOWNLOAD_ERRORS = (httpx.HTTPError, DownloadTooLarge, UnsafeURLError, FFmpegError, OSError)


@dataclass(frozen=True)
class StockClip:
    id: int
    page_url: str
    duration: float
    author: str
    file_url: str


def _short_side(file: dict) -> int:
    return min(file["width"], file["height"])


def _trusted_file(link: object) -> bool:
    return isinstance(link, str) and httpx.URL(link).scheme == "https" and httpx.URL(link).host in FILE_HOSTS


def _best_file(files: list) -> str | None:
    """The sharpest mp4 between MIN_SIDE and MAX_SIDE on its short side, from a Pexels host."""
    mp4s = [f for f in files if isinstance(f, dict) and f.get("file_type") == "video/mp4"
            and _trusted_file(f.get("link")) and isinstance(f.get("width"), int) and isinstance(f.get("height"), int)]
    fitting = [f for f in mp4s if MIN_SIDE <= _short_side(f) <= MAX_SIDE]
    return max(fitting, key=_short_side)["link"] if fitting else None


def parse_search(payload: object) -> list[StockClip]:
    videos = payload.get("videos") if isinstance(payload, dict) else None
    clips = []
    for video in videos if isinstance(videos, list) else []:
        if not isinstance(video, dict) or not isinstance(video.get("id"), int):
            continue
        duration = video.get("duration")
        file_url = _best_file(video.get("video_files") or [])
        user = video.get("user") if isinstance(video.get("user"), dict) else {}
        if not isinstance(duration, (int, float)) or not MIN_DURATION_S <= duration <= MAX_DURATION_S:
            continue
        page = video.get("url")
        if file_url and isinstance(page, str) and page.startswith(PAGE_PREFIX):
            clips.append(StockClip(video["id"], video["url"], float(duration), str(user.get("name") or "Pexels"),
                                   file_url))
    return clips


def search_clips(client: httpx.Client, api_key: str, query: str) -> list[StockClip]:
    url = str(httpx.URL(SEARCH_URL, params={"query": query, "orientation": "portrait", "size": "medium",
                                            "per_page": PER_PAGE}))
    body = fetch_text(client, url, max_bytes=SEARCH_MAX_BYTES, headers={"Authorization": api_key})
    return parse_search(json.loads(body))


def _asset(clip: StockClip, path: Path) -> Asset:
    return Asset(
        id=None, kind=AssetKind.STOCK_VIDEO, local_path=path, source_url=clip.page_url, source_platform="pexels",
        rightsholder=clip.author, rights_basis=RightsBasis.LICENSED, licence_terms_ref=LICENCE_TERMS,
        music_stripped=True, fetched_at=datetime.now(UTC), notes=f"Pexels video {clip.id}",
    )


def _download(clip: StockClip, client: httpx.Client, work_dir: Path, timeout_s: int) -> Path:
    raw = work_dir / f"stock_{clip.id}_raw.mp4"
    try:
        download_file(client, clip.file_url, raw, max_bytes=MAX_CLIP_BYTES)
        return strip_audio(raw, work_dir / f"stock_{clip.id}.mp4", timeout_s=timeout_s)
    finally:
        raw.unlink(missing_ok=True)


def collect_stock_assets(
    client: httpx.Client, api_key: str, queries: list[str], work_dir: Path, settings: Settings
) -> list[Asset]:
    """Up to MAX_CLIPS clips (at most MAX_PER_QUERY per search term, no repeats), audio removed."""
    work_dir.mkdir(parents=True, exist_ok=True)
    assets: list[Asset] = []
    seen: set[int] = set()
    for query in queries:
        try:
            found = search_clips(client, api_key, query)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                log.warning("Pexels refused the API key: check PEXELS_API_KEY in .env")
                return assets
            log.warning("Pexels search for %r failed: %s", query, exc)
            continue
        except (httpx.HTTPError, ValueError, DownloadTooLarge, UnsafeURLError) as exc:
            log.warning("Pexels search for %r failed: %s", query, exc)
            continue
        assets += _download_some(found, seen, min(MAX_PER_QUERY, MAX_CLIPS - len(assets)), client, work_dir,
                                 settings)
        if len(assets) >= MAX_CLIPS:
            break
    return assets


def _download_some(
    found: list[StockClip], seen: set[int], wanted: int, client: httpx.Client, work_dir: Path, settings: Settings
) -> list[Asset]:
    """Up to `wanted` new clips from one search, moving on to the next result when a download fails."""
    assets: list[Asset] = []
    for clip in found:
        if len(assets) >= wanted:
            break
        if clip.id in seen:
            continue
        seen.add(clip.id)
        try:
            assets.append(_asset(clip, _download(clip, client, work_dir, settings.limits.ffmpeg_timeout_s)))
        except _DOWNLOAD_ERRORS as exc:
            log.warning("Skipping Pexels video %s: %s", clip.id, exc)
    return assets
