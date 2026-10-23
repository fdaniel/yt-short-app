import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx

from shorts.media.ffmpeg import probe_video
from shorts.models import AssetKind, RightsBasis
from shorts.sources import steam
from shorts.sources.steam import (
    MAX_TRAILERS,
    SteamError,
    collect_steam_assets,
    fetch_steam_app,
    parse_appdetails,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def copy_from(src: Path):
    def _fake(client, url, dest, *, max_bytes):
        shutil.copy(src, dest)
        return dest

    return _fake


def test_parse_mp4_app():
    app = parse_appdetails(1091500, load("steam_mp4.json"))
    assert app.name == "Cyberpunk 2077" and app.publishers == ("CD PROJEKT RED",)
    assert app.movies[0].mp4_url.endswith("movie_max.mp4")
    assert app.movies[1].mp4_url.endswith("movie480.mp4")
    assert len(app.screenshots) == 2


def test_parse_hls_only_movie():
    m = parse_appdetails(1, load("steam_hls_only.json")).movies[0]
    assert m.mp4_url is None and ".m3u8" in m.hls_url and m.highlight


def test_parse_no_movies():
    assert parse_appdetails(2, load("steam_no_movies.json")).movies == ()


def test_parse_failure_raises():
    with pytest.raises(SteamError, match="123"):
        parse_appdetails(123, load("steam_fail.json"))


@respx.mock
def test_fetch_steam_app():
    respx.get(url__startswith="https://store.steampowered.com/api/appdetails").respond(
        200, json=load("steam_mp4.json")
    )
    with httpx.Client() as c:
        assert fetch_steam_app(c, 1091500, max_bytes=1_000_000).name == "Cyberpunk 2077"


def test_blocked_publisher_gets_no_trailers(tmp_path, settings, monkeypatch, synthetic_video):
    app = parse_appdetails(1091500, load("steam_mp4.json"))
    monkeypatch.setattr(steam, "download_file", copy_from(synthetic_video))
    assets = collect_steam_assets(app, httpx.Client(), tmp_path, settings, {"cd projekt red"})
    assert {a.kind for a in assets} == {AssetKind.SCREENSHOT}


def test_trailer_assets_are_audio_free_and_logged(tmp_path, settings, monkeypatch, synthetic_video):
    monkeypatch.setattr(steam, "download_file", copy_from(synthetic_video))
    app = parse_appdetails(1091500, load("steam_mp4.json"))
    assets = collect_steam_assets(app, httpx.Client(), tmp_path / "w", settings, set())
    trailers = [a for a in assets if a.kind == AssetKind.TRAILER]
    assert len(trailers) == MAX_TRAILERS
    assert "12" in trailers[0].local_path.name  # highlight first
    assert all(a.music_stripped and a.rights_basis == RightsBasis.STORE_PROMO for a in trailers)
    assert all(a.rightsholder == "CD PROJEKT RED" and a.source_platform == "steam" for a in trailers)
    assert all(probe_video(a.local_path).has_audio is False for a in trailers)


def test_hls_trailer_uses_ffmpeg(tmp_path, settings, monkeypatch, synthetic_video):
    calls = []

    def fake_hls(url, dest, *, max_seconds, timeout_s):
        calls.append((url, max_seconds))
        shutil.copy(synthetic_video, dest)
        return dest

    monkeypatch.setattr(steam, "download_hls", fake_hls)
    app = parse_appdetails(1, load("steam_hls_only.json"))
    assets = collect_steam_assets(app, httpx.Client(), tmp_path, settings, set())
    assert [a.kind for a in assets] == [AssetKind.TRAILER]
    assert calls[0][1] == settings.limits.max_hls_seconds


def test_single_failed_download_is_skipped(tmp_path, settings, monkeypatch, synthetic_video):
    def flaky(client, url, dest, *, max_bytes):
        if "ss_a" in url:
            raise httpx.ConnectError("boom")
        shutil.copy(synthetic_video, dest)
        return dest

    monkeypatch.setattr(steam, "download_file", flaky)
    app = parse_appdetails(1091500, load("steam_mp4.json"))
    shots = [a for a in collect_steam_assets(app, httpx.Client(), tmp_path, settings, set())
             if a.kind == AssetKind.SCREENSHOT]
    assert len(shots) == 1


SEARCH = "https://store.steampowered.com/api/storesearch/"


def _search_fixture():
    respx.get(url__startswith=SEARCH).respond(200, json=json.loads((FIXTURES / "steam_search_mw4.json").read_text()))


@respx.mock
def test_exact_title_matches():
    _search_fixture()
    assert steam.find_steam_app_id(httpx.Client(), "Call of Duty: Modern Warfare 4") == 4435490


@respx.mock
def test_title_after_series_name_matches():
    # articles say "Modern Warfare 4"; Steam says "Call of Duty®: Modern Warfare® 4"
    _search_fixture()
    assert steam.find_steam_app_id(httpx.Client(), "Modern Warfare 4") == 4435490


@respx.mock
def test_partial_title_does_not_match():
    _search_fixture()
    assert steam.find_steam_app_id(httpx.Client(), "Warfare 4") is None


@respx.mock
def test_ambiguous_subtitle_does_not_match():
    respx.get(url__startswith=SEARCH).respond(200, json={"items": [
        {"type": "app", "name": "Galaxy: Origins", "id": 1},
        {"type": "app", "name": "Kingdom: Origins", "id": 2},
    ]})
    assert steam.find_steam_app_id(httpx.Client(), "Origins") is None


@respx.mock
def test_older_game_not_matched():
    _search_fixture()
    assert steam.find_steam_app_id(httpx.Client(), "Call of Duty 4") is None


@respx.mock
def test_search_failure_returns_none():
    respx.get(url__startswith=SEARCH).respond(503)
    assert steam.find_steam_app_id(httpx.Client(), "Call of Duty: Modern Warfare 4") is None


@respx.mock
def test_search_garbage_returns_none():
    respx.get(url__startswith=SEARCH).respond(200, text="<html>")
    assert steam.find_steam_app_id(httpx.Client(), "Call of Duty: Modern Warfare 4") is None


def test_blank_title_does_not_search():
    assert steam.find_steam_app_id(httpx.Client(), "  ") is None


@respx.mock
def test_series_match_only_for_top_result():
    # real ordering for "Black Ops" (2026-10-18): the 2010 game is 3rd; a Black Ops 7 story must not get it
    respx.get(url__startswith=SEARCH).respond(200, json={"items": [
        {"type": "app", "name": "Call of Duty\u00ae: Black Ops III", "id": 311210},
        {"type": "app", "name": "Call of Duty\u00ae: Black Ops II", "id": 202970},
        {"type": "app", "name": "Call of Duty\u00ae: Black Ops", "id": 42700},
        {"type": "app", "name": "Call of Duty\u00ae: Black Ops 7", "id": 3606480},
    ]})
    assert steam.find_steam_app_id(httpx.Client(), "Black Ops") is None


@respx.mock
def test_game_not_on_steam_returns_none():
    # e.g. a Nintendo-only game: Steam finds nothing at all
    respx.get(url__startswith=SEARCH).respond(200, json={"total": 0, "items": []})
    assert steam.find_steam_app_id(httpx.Client(), "Pokémon Champions") is None
