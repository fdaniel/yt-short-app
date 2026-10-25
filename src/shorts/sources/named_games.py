"""A tech story's footage from the games it names ("FSR 4.1 now in Cyberpunk 2077"): their Steam media."""

import logging
from pathlib import Path

import httpx

from shorts.config import Settings
from shorts.media.ffmpeg import FFmpegError
from shorts.models import Asset
from shorts.net import DownloadTooLarge, UnsafeURLError
from shorts.sources.steam import (
    SteamError,
    collect_steam_assets,
    fetch_steam_app,
    find_steam_app_id,
    maker_named,
    normalise_title,
)

log = logging.getLogger(__name__)

MAX_NAMED_GAMES = 2
TRAILERS_PER_GAME = 1  # the story is the tech, not the game: a little of each game is enough
SCREENSHOTS_PER_GAME = 4
_ERRORS = (SteamError, httpx.HTTPError, ValueError, OSError, FFmpegError, DownloadTooLarge, UnsafeURLError)


def named_in(name: str, text: str) -> bool:
    wanted = normalise_title(name)
    return bool(wanted) and f" {wanted} " in f" {normalise_title(text)} "


def _game_assets(name: str, text: str, client: httpx.Client, work_dir: Path, settings: Settings,
                 blocked: set[str]) -> list[Asset]:
    app_id = find_steam_app_id(client, name)
    if app_id is None:
        return []
    app = fetch_steam_app(client, app_id, max_bytes=settings.limits.max_html_bytes)
    # a one-word title ("Control", "Farlands") is often a feature or another game: its maker must be named too
    if len(normalise_title(app.name).split()) < 2 and not maker_named(app, text):
        log.warning("Not using %r for %r: one-word title and the story names none of its makers", app.name, name)
        return []
    return collect_steam_assets(app, client, work_dir / str(app_id), settings, blocked,
                                max_trailers=TRAILERS_PER_GAME, max_screenshots=SCREENSHOTS_PER_GAME)


def named_game_assets(names: list[str], text: str, client: httpx.Client, work_dir: Path, settings: Settings,
                      blocked: set[str]) -> list[Asset]:
    """Steam footage of up to MAX_NAMED_GAMES games that the story `text` itself names; a name the story
    does not contain, or with no exact store match, adds nothing."""
    assets: list[Asset] = []
    games = 0
    for name in dict.fromkeys(names):
        if games >= MAX_NAMED_GAMES:
            break
        if not named_in(name, text):
            log.warning("AI named game %r but the story does not mention it; no footage from it", name)
            continue
        try:
            found = _game_assets(name, text, client, work_dir, settings, blocked)
        except _ERRORS as exc:
            log.warning("Steam footage unavailable for %r: %s", name, exc)
            continue
        if found:
            assets += found
            games += 1
    return assets
