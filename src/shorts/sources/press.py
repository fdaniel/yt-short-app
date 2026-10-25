"""Official newsroom photos: the footage of a tech story, taken only from the story's own article."""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from PIL import Image, UnidentifiedImageError

from shorts.config import Settings
from shorts.models import Asset, AssetKind, RightsBasis
from shorts.net import DownloadTooLarge, UnsafeURLError, download_file

log = logging.getLogger(__name__)

MAX_PRESS_IMAGES = 12
MIN_LONG_SIDE = 800  # smaller is a thumbnail or an icon, blurry at 1080x1920
MAX_ASPECT = 2.5  # wider or taller is a banner or a strip
SAME_PICTURE = 12  # mean colour difference (0-255) below which two downloads are the same photo at two sizes
PRESS_TERMS = "official-newsroom: press image published with the story, used in news coverage of it"
_OG_IMAGE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.I)
_GRAPHIC = re.compile(r'<graphic[^>]*\ssrc="([^"]+)"')
_NOT_PHOTOS = (".svg", ".gif")
_DOWNLOAD_ERRORS = (httpx.HTTPError, OSError, DownloadTooLarge, UnsafeURLError)
_BRANDS = {"nvidia": "NVIDIA", "amd": "AMD"}
_GENERIC_TLDS = {"com", "net", "org", "io", "co", "uk", "us", "eu"}


def brand(url: str) -> str:
    """The company behind a newsroom address: news.samsung.com -> Samsung, blog.google -> Google."""
    labels = [label for label in (urlparse(url).hostname or "").split(".") if label]
    while len(labels) > 1 and labels[-1] in _GENERIC_TLDS:
        labels.pop()
    name = labels[-1] if labels else "the publisher"
    return _BRANDS.get(name, name.capitalize())


def press_image_urls(page_url: str, html: str) -> list[str]:
    """The page's share image, then the photos inside the article itself (never the site's
    navigation or other stories' thumbnails), as absolute addresses without repeats."""
    xml = trafilatura.extract(html, url=page_url, include_images=True, output_format="xml") or ""
    found = _OG_IMAGE.findall(html)[:1] + _GRAPHIC.findall(xml)
    urls: list[str] = []
    for raw in found:
        url = urljoin(page_url, raw.strip().replace("&amp;", "&"))
        path = urlparse(url).path.lower()
        if url.startswith(("https://", "http://")) and not path.endswith(_NOT_PHOTOS) and url not in urls:
            urls.append(url)
    return urls


def _fingerprint(path: Path) -> tuple[int, ...] | None:
    """A tiny colour thumbnail, or None if the file is not a usable photo."""
    try:
        with Image.open(path) as img:
            long_side, short_side = max(img.size), min(img.size)
            if long_side < MIN_LONG_SIDE or long_side > MAX_ASPECT * short_side:
                return None
            return tuple(img.convert("RGB").resize((8, 8)).tobytes())
    except (OSError, UnidentifiedImageError):
        return None


def _same(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) < SAME_PICTURE


def _asset(path: Path, url: str, page_url: str) -> Asset:
    return Asset(
        id=None, kind=AssetKind.PRESS_IMAGE, local_path=path, source_url=url,
        source_platform=urlparse(page_url).hostname or "", rightsholder=brand(page_url),
        rights_basis=RightsBasis.PRESS_KIT_EDITORIAL, licence_terms_ref=PRESS_TERMS, music_stripped=False,
        fetched_at=datetime.now(UTC), notes=f"from {page_url}",
    )


def collect_press_images(client: httpx.Client, page_url: str, html: str, work_dir: Path, settings: Settings) -> list[Asset]:
    """Up to MAX_PRESS_IMAGES big, different photos from the article; a broken or small one is skipped."""
    work_dir.mkdir(parents=True, exist_ok=True)
    assets: list[Asset] = []
    seen: list[tuple[int, ...]] = []
    for i, url in enumerate(press_image_urls(page_url, html)):
        if len(assets) >= MAX_PRESS_IMAGES:
            break
        try:
            path = download_file(client, url, work_dir / f"press_{i}.img", max_bytes=settings.limits.max_image_bytes)
        except _DOWNLOAD_ERRORS as exc:
            log.warning("Skipping press image %s: %s", url, exc)
            continue
        fingerprint = _fingerprint(path)
        if fingerprint is None or any(_same(fingerprint, other) for other in seen):
            path.unlink(missing_ok=True)
            continue
        seen.append(fingerprint)
        assets.append(_asset(path, url, page_url))
    return assets
