"""Free stock video (Pixabay, Pexels): search, download and log the licence of each clip.

Used for stories with no game trailer, mostly hardware news. The footage is generic
(a laptop, a chip), never the announced product itself.
"""

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from shorts.config import Settings
from shorts.media.ffmpeg import FFmpegError, strip_audio
from shorts.models import Asset, AssetKind, RightsBasis
from shorts.net import DownloadTooLarge, UnsafeURLError, download_file, redact

log = logging.getLogger(__name__)

MAX_CLIP_BYTES = 100_000_000
MAX_CLIPS = 4
MAX_PER_QUERY = 2
MIN_DURATION_S = 5
MAX_DURATION_S = 60
MIN_SIDE, MAX_SIDE = 720, 1440  # sharp enough for 1080x1920, without downloading 4K
CACHE_TTL_S = 24 * 3600  # Pixabay asks for search results to be kept a day instead of searching again
_DOWNLOAD_ERRORS = (httpx.HTTPError, DownloadTooLarge, UnsafeURLError, FFmpegError, OSError)
_SEARCH_ERRORS = (httpx.HTTPError, ValueError, DownloadTooLarge, UnsafeURLError)


@dataclass(frozen=True)
class StockClip:
    id: int
    page_url: str
    duration: float
    author: str
    file_url: str


@dataclass(frozen=True)
class StockSource:
    platform: str  # stored on each asset, e.g. "pixabay"
    name: str  # shown to people, e.g. "Pixabay"
    key_env: str  # the .env line to check when the key is refused
    licence_terms: str
    search: Callable[[httpx.Client, str, str], list[StockClip]]  # (client, api_key, query)
    refused: Callable[[httpx.Response], bool] = lambda response: response.status_code in (401, 403)


def trusted_file(url: object, host: str) -> bool:
    """An https address on the site's own file server."""
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        return False
    return parsed.scheme == "https" and parsed.host == host


def fits(duration: object) -> bool:
    return isinstance(duration, (int, float)) and MIN_DURATION_S <= duration <= MAX_DURATION_S


def sharpest(files: list[tuple[int, int, str]]) -> str | None:
    """The sharpest (width, height, url) between MIN_SIDE and MAX_SIDE on its short side."""
    fitting = [f for f in files if MIN_SIDE <= min(f[0], f[1]) <= MAX_SIDE]
    return max(fitting, key=lambda f: min(f[0], f[1]))[2] if fitting else None


def _cache_file(source: StockSource, query: str, settings: Settings) -> Path:
    name = hashlib.sha256(query.encode()).hexdigest()[:32]
    return settings.data_dir / "cache" / "stock" / source.platform / f"{name}.json"


def _cached(path: Path) -> list[StockClip] | None:
    try:
        if not 0 <= time.time() - path.stat().st_mtime <= CACHE_TTL_S:
            return None
        return [StockClip(**clip) for clip in json.loads(path.read_text())]
    except (OSError, ValueError, TypeError):
        return None


def _search(source: StockSource, client: httpx.Client, api_key: str, query: str, settings: Settings) -> list[StockClip]:
    path = _cache_file(source, query, settings)
    found = _cached(path)
    if found is None:
        found = source.search(client, api_key, query)
        _save(path, found)
    return found


def _save(path: Path, found: list[StockClip]) -> None:
    """Best effort: a search that cannot be saved is simply sent again next time."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        partial.write_text(json.dumps([asdict(clip) for clip in found]))
        os.replace(partial, path)  # another run never reads a half-written file
    except OSError as exc:
        log.warning("Could not save the stock video search in %s: %s", path.parent, exc)


def _asset(source: StockSource, clip: StockClip, path: Path) -> Asset:
    return Asset(
        id=None, kind=AssetKind.STOCK_VIDEO, local_path=path, source_url=clip.page_url,
        source_platform=source.platform, rightsholder=clip.author, rights_basis=RightsBasis.LICENSED,
        licence_terms_ref=source.licence_terms, music_stripped=True, fetched_at=datetime.now(UTC),
        notes=f"{source.name} video {clip.id}",
    )


def _download(source: StockSource, clip: StockClip, client: httpx.Client, work_dir: Path, timeout_s: int) -> Path:
    raw = work_dir / f"stock_{source.platform}_{clip.id}_raw.mp4"
    try:
        download_file(client, clip.file_url, raw, max_bytes=MAX_CLIP_BYTES)
        return strip_audio(raw, work_dir / f"stock_{source.platform}_{clip.id}.mp4", timeout_s=timeout_s)
    finally:
        raw.unlink(missing_ok=True)


def collect_stock_assets(
    source: StockSource, client: httpx.Client, api_key: str, queries: list[str], work_dir: Path,
    settings: Settings, *, wanted: int = MAX_CLIPS, used: frozenset[str] = frozenset(),
) -> list[Asset]:
    """Up to `wanted` clips (at most MAX_PER_QUERY per search term, no repeats), audio removed.

    Clips whose page is in `used` (shown in earlier videos) are taken only when a search finds nothing new.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    assets: list[Asset] = []
    seen: set[int] = set()
    for query in queries:
        if len(assets) >= wanted:
            break
        try:
            found = _search(source, client, api_key, query, settings)
        except httpx.HTTPStatusError as exc:
            if source.refused(exc.response):
                log.warning("%s refused the API key: check %s in .env", source.name, source.key_env)
                return assets
            if exc.response.status_code == 429:
                log.warning("%s search limit reached (HTTP 429): no more searches there for now", source.name)
                return assets
            log.warning("%s search for %r failed: HTTP %s", source.name, query, exc.response.status_code)
            continue
        except _SEARCH_ERRORS as exc:
            log.warning("%s search for %r failed: %s", source.name, query, redact(str(exc)))
            continue
        fresh_first = sorted(found, key=lambda clip: clip.page_url in used)  # stable: keeps the site's order
        assets += _download_some(source, fresh_first, seen, min(MAX_PER_QUERY, wanted - len(assets)), client,
                                 work_dir, settings)
    return assets


def _download_some(
    source: StockSource, found: list[StockClip], seen: set[int], wanted: int, client: httpx.Client,
    work_dir: Path, settings: Settings,
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
            assets.append(_asset(source, clip, _download(source, clip, client, work_dir,
                                                          settings.limits.ffmpeg_timeout_s)))
        except _DOWNLOAD_ERRORS as exc:
            log.warning("Skipping %s video %s: %s", source.name, clip.id, redact(str(exc)))
    return assets
