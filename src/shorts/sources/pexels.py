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
FULL_HD_SIDE = 1080
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


def _best_file(files: list) -> str | None:
    """The smallest mp4 at least Full HD on its short side, else the largest mp4 there is."""
    mp4s = [f for f in files if isinstance(f, dict) and f.get("file_type") == "video/mp4" and f.get("link")
            and isinstance(f.get("width"), int) and isinstance(f.get("height"), int)]
    if not mp4s:
        return None
    sharp = [f for f in mp4s if _short_side(f) >= FULL_HD_SIDE]
    return (min(sharp, key=_short_side) if sharp else max(mp4s, key=_short_side))["link"]


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
        if file_url and isinstance(video.get("url"), str):
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
    raw = download_file(client, clip.file_url, work_dir / f"stock_{clip.id}_raw.mp4", max_bytes=MAX_CLIP_BYTES)
    clean = strip_audio(raw, work_dir / f"stock_{clip.id}.mp4", timeout_s=timeout_s)
    raw.unlink(missing_ok=True)
    return clean


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
        fresh = [c for c in found if c.id not in seen][:MAX_PER_QUERY]
        for clip in fresh:
            if len(assets) == MAX_CLIPS:
                return assets
            seen.add(clip.id)
            try:
                assets.append(_asset(clip, _download(clip, client, work_dir, settings.limits.ffmpeg_timeout_s)))
            except _DOWNLOAD_ERRORS as exc:
                log.warning("Skipping Pexels video %s: %s", clip.id, exc)
    return assets
