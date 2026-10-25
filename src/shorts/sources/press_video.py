"""Official newsroom video clips: the moving footage a company publishes inside the story itself."""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse

import httpx

from shorts.config import Settings
from shorts.media.ffmpeg import FFmpegError, probe_video, strip_audio
from shorts.models import Asset, AssetKind, RightsBasis
from shorts.net import DownloadTooLarge, UnsafeURLError, download_file
from shorts.sources.press import brand

log = logging.getLogger(__name__)

MAX_PRESS_CLIPS = 4
MIN_CLIP_S = 2.0  # shorter is a button animation, not footage
MIN_CLIP_SIDE = 480  # smaller is a thumbnail-sized loop, blurry at 1080x1920
CLIP_TERMS = "official-newsroom: video clip published with the story, used muted in news coverage of it"
_MP4 = re.compile(r"""["'(]([^"'()\s<>]+?\.mp4)(?:[?#][^"'()\s<>]*)?["')]""", re.I)
# Apple serves each clip at several sizes in one folder: keep the biggest
_SIZES = ("large_2x", "large", "medium", "small")
_ERRORS = (httpx.HTTPError, OSError, ValueError, FFmpegError, DownloadTooLarge, UnsafeURLError)


def _size_rank(url: str) -> int:
    stem = PurePosixPath(urlparse(url).path).stem.lower()
    return _SIZES.index(stem) if stem in _SIZES else 0


def _clip_key(url: str) -> str:
    """One key per clip: the folder for a clip served at several sizes, else the address itself."""
    path = PurePosixPath(urlparse(url).path)
    return str(path.parent) if path.stem.lower() in _SIZES else url


def press_video_urls(page_url: str, html: str) -> list[str]:
    """The page's own .mp4 clips, as absolute addresses, one per clip, in page order."""
    best: dict[str, str] = {}
    for raw in _MP4.findall(html):
        url = urljoin(page_url, raw.replace("&amp;", "&"))
        if not url.startswith(("https://", "http://")):
            continue
        key = _clip_key(url)
        if key not in best or _size_rank(url) < _size_rank(best[key]):
            best[key] = url
    return list(best.values())


def _asset(path: Path, url: str, page_url: str) -> Asset:
    return Asset(
        id=None, kind=AssetKind.PRESS_VIDEO, local_path=path, source_url=url,
        source_platform=urlparse(page_url).hostname or "", rightsholder=brand(page_url),
        rights_basis=RightsBasis.PRESS_KIT_EDITORIAL, licence_terms_ref=CLIP_TERMS, music_stripped=True,
        fetched_at=datetime.now(UTC), notes=f"from {page_url}",
    )


def _download_clip(client: httpx.Client, url: str, work_dir: Path, i: int, settings: Settings) -> Path | None:
    """The clip without its sound, or None if it is too short or too small to use."""
    limits = settings.limits
    raw = download_file(client, url, work_dir / f"press_clip_{i}_raw.mp4", max_bytes=limits.max_trailer_bytes)
    try:
        info = probe_video(raw)
        if info.duration < MIN_CLIP_S or min(info.width, info.height) < MIN_CLIP_SIDE:
            return None
        return strip_audio(raw, work_dir / f"press_clip_{i}.mp4", timeout_s=limits.ffmpeg_timeout_s)
    finally:
        raw.unlink(missing_ok=True)


def collect_press_clips(client: httpx.Client, page_url: str, html: str, work_dir: Path, settings: Settings) -> list[Asset]:
    """Up to MAX_PRESS_CLIPS muted clips from the article; a broken, short or tiny one is skipped."""
    work_dir.mkdir(parents=True, exist_ok=True)
    assets: list[Asset] = []
    for i, url in enumerate(press_video_urls(page_url, html)):
        if len(assets) >= MAX_PRESS_CLIPS:
            break
        try:
            path = _download_clip(client, url, work_dir, i, settings)
        except _ERRORS as exc:
            log.warning("Skipping press clip %s: %s", url, exc)
            continue
        if path is not None:
            assets.append(_asset(path, url, page_url))
    return assets
