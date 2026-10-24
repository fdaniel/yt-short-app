"""Steam store: game trailers and screenshots, logged with their rights basis."""

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from shorts.config import Settings
from shorts.media.ffmpeg import FFmpegError, download_hls, strip_audio
from shorts.models import Asset, AssetKind, RightsBasis
from shorts.net import DownloadTooLarge, UnsafeURLError, download_file, fetch_text

log = logging.getLogger(__name__)

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&l=english"
SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
SEARCH_MAX_BYTES = 1_000_000
MAX_TRAILERS = 3
MAX_SCREENSHOTS = 12  # enough that a video never has to show the same picture twice
TRAILER_TERMS = "steam-store-promo: short news-coverage excerpts (owner decision, option A)"
SCREENSHOT_TERMS = "steam-store-promo: store screenshot used in news coverage"
_DOWNLOAD_ERRORS = (httpx.HTTPError, DownloadTooLarge, UnsafeURLError, FFmpegError, OSError)


class SteamError(Exception):
    """The Steam store API did not return usable data."""


@dataclass(frozen=True)
class SteamMovie:
    id: int
    name: str
    mp4_url: str | None
    hls_url: str | None
    highlight: bool


@dataclass(frozen=True)
class SteamApp:
    app_id: int
    name: str
    publishers: tuple[str, ...]
    movies: tuple[SteamMovie, ...]
    screenshots: tuple[str, ...]


def _parse_movie(raw: dict) -> SteamMovie:
    mp4 = raw.get("mp4") or {}
    return SteamMovie(
        id=int(raw.get("id", 0)),
        name=str(raw.get("name", "")),
        mp4_url=mp4.get("max") or mp4.get("480"),
        hls_url=raw.get("hls_h264"),
        highlight=bool(raw.get("highlight", False)),
    )


def parse_appdetails(app_id: int, payload: dict) -> SteamApp:
    entry = payload.get(str(app_id)) or {}
    if not entry.get("success") or "data" not in entry:
        raise SteamError(f"Steam has no store data for app {app_id}")
    data = entry["data"]
    return SteamApp(
        app_id=app_id,
        name=str(data.get("name", "")),
        publishers=tuple(data.get("publishers") or ()),
        movies=tuple(_parse_movie(m) for m in data.get("movies") or ()),
        screenshots=tuple(s["path_full"] for s in data.get("screenshots") or () if s.get("path_full")),
    )


def fetch_steam_app(client: httpx.Client, app_id: int, *, max_bytes: int) -> SteamApp:
    body = fetch_text(client, APPDETAILS_URL.format(app_id=app_id), max_bytes=max_bytes)
    try:
        return parse_appdetails(app_id, json.loads(body))
    except json.JSONDecodeError as exc:
        raise SteamError(f"Steam returned invalid data for app {app_id}") from exc


def _asset(kind: AssetKind, path: Path, url: str, app: SteamApp, terms: str) -> Asset:
    return Asset(
        id=None,
        kind=kind,
        local_path=path,
        source_url=url,
        source_platform="steam",
        rightsholder=app.publishers[0] if app.publishers else app.name,
        rights_basis=RightsBasis.STORE_PROMO,
        licence_terms_ref=terms,
        music_stripped=kind == AssetKind.TRAILER,
        fetched_at=datetime.now(UTC),
        notes=f"{app.name} (Steam app {app.app_id})",
    )


def _download_trailer(movie: SteamMovie, client: httpx.Client, work_dir: Path, settings: Settings) -> Path:
    raw = work_dir / f"trailer_{movie.id}_raw.mp4"
    limits = settings.limits
    if movie.mp4_url:
        download_file(client, movie.mp4_url, raw, max_bytes=limits.max_trailer_bytes)
    else:
        download_hls(movie.hls_url, raw, max_seconds=limits.max_hls_seconds, timeout_s=limits.ffmpeg_timeout_s)
    clean = strip_audio(raw, work_dir / f"trailer_{movie.id}.mp4", timeout_s=limits.ffmpeg_timeout_s)
    raw.unlink(missing_ok=True)
    return clean


def _trailers(app: SteamApp, client: httpx.Client, work_dir: Path, settings: Settings) -> list[Asset]:
    candidates = sorted(
        (m for m in app.movies if m.mp4_url or m.hls_url), key=lambda m: not m.highlight
    )[:MAX_TRAILERS]
    assets = []
    for movie in candidates:
        try:
            path = _download_trailer(movie, client, work_dir, settings)
        except _DOWNLOAD_ERRORS as exc:
            log.warning("Skipping trailer %s: %s", movie.id, exc)
            continue
        assets.append(_asset(AssetKind.TRAILER, path, movie.mp4_url or movie.hls_url, app, TRAILER_TERMS))
    return assets


def _screenshots(app: SteamApp, client: httpx.Client, work_dir: Path, settings: Settings) -> list[Asset]:
    assets = []
    for i, url in enumerate(app.screenshots[:MAX_SCREENSHOTS]):
        try:
            path = download_file(
                client, url, work_dir / f"screenshot_{i}.jpg", max_bytes=settings.limits.max_image_bytes
            )
        except _DOWNLOAD_ERRORS as exc:
            log.warning("Skipping screenshot %s: %s", url, exc)
            continue
        assets.append(_asset(AssetKind.SCREENSHOT, path, url, app, SCREENSHOT_TERMS))
    return assets


def collect_steam_assets(
    app: SteamApp, client: httpx.Client, work_dir: Path, settings: Settings, blocked: set[str]
) -> list[Asset]:
    """Download trailers (unless the publisher is blocked) and screenshots for `app`."""
    work_dir.mkdir(parents=True, exist_ok=True)
    publisher_blocked = any(p.strip().lower() in blocked for p in app.publishers)
    if publisher_blocked:
        log.info("Trailers from %s are blocked; using screenshots only", app.publishers)
    trailers = [] if publisher_blocked else _trailers(app, client, work_dir, settings)
    return trailers + _screenshots(app, client, work_dir, settings)


def normalise_title(title: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", re.sub(r"[®™©]", "", title.casefold())).split())


def find_steam_app_id(client: httpx.Client, game_title: str) -> int | None:
    """The app ID of the game whose store name is `game_title` (ignoring case, ®/™ and punctuation),
    or, for Steam's top search result only, whose name after the series prefix ("Series: Title") is.

    No fuzzy matching: a near miss could put another game's footage in the video.
    """
    wanted = normalise_title(game_title)
    if not wanted:
        return None
    url = str(httpx.URL(SEARCH_URL, params={"term": game_title, "l": "english", "cc": "US"}))
    try:
        items = json.loads(fetch_text(client, url, max_bytes=SEARCH_MAX_BYTES)).get("items", [])
    except (httpx.HTTPError, ValueError, AttributeError, DownloadTooLarge, UnsafeURLError) as exc:
        log.warning("Steam search failed for %r: %s", game_title, exc)
        return None
    apps = [(int(i["id"]), str(i.get("name", ""))) for i in items if i.get("type") == "app" and "id" in i]
    exact = [app_id for app_id, name in apps if normalise_title(name) == wanted]
    if exact:
        return exact[0]
    # "Modern Warfare 4" for "Call of Duty: Modern Warfare 4": only Steam's top result may match this way;
    # "Black Ops" would otherwise find the 2010 game for a Black Ops 7 story
    subtitle = [app_id for app_id, name in apps if ":" in name and normalise_title(name.split(":", 1)[1]) == wanted]
    return subtitle[0] if apps and subtitle == [apps[0][0]] else None
