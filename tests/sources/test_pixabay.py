import json
import logging
import shutil
from pathlib import Path

import httpx
import pytest
import respx

from shorts.models import AssetKind, RightsBasis
from shorts.sources import stock
from shorts.sources.pixabay import SEARCH_URL, SOURCE, parse_search
from shorts.sources.stock import collect_stock_assets

FIXTURES = Path(__file__).parent.parent / "fixtures"
PAYLOAD = json.loads((FIXTURES / "pixabay_search.json").read_text())


def test_parse_picks_full_hd_and_skips_too_short_clips():
    clips = parse_search(PAYLOAD)
    assert [c.id for c in clips] == [201, 203]
    assert clips[0].file_url == "https://cdn.pixabay.com/video/2025/01/01/201-medium.mp4"  # not the 4K file
    assert clips[1].file_url == "https://cdn.pixabay.com/video/2025/01/01/203-medium.mp4"  # empty large is skipped
    assert clips[0].author == "Carla Reis" and clips[0].page_url == "https://pixabay.com/videos/laptop-keyboard-201/"


def _hit(**overrides):
    base = {"id": 9, "pageURL": "https://pixabay.com/videos/x-9/", "duration": 10, "user": "A",
            "videos": {"medium": {"url": "https://cdn.pixabay.com/video/9.mp4", "width": 1920, "height": 1080}}}
    return {**base, **overrides}


def test_parse_ignores_malformed_entries():
    assert parse_search({"hits": [{"id": "x"}, _hit(videos=[]), _hit(videos={"medium": 5}), 7]}) == []
    assert parse_search({"oops": 1}) == []
    assert parse_search([1, 2]) == []


def test_only_pixabay_links_are_trusted():
    assert parse_search({"hits": [_hit(pageURL="https://evil.example/x")]}) == []
    plain_http = {"medium": {"url": "http://cdn.pixabay.com/video/9.mp4", "width": 1920, "height": 1080}}
    assert parse_search({"hits": [_hit(videos=plain_http)]}) == []
    elsewhere = {"medium": {"url": "https://evil.example/9.mp4", "width": 1920, "height": 1080}}
    assert parse_search({"hits": [_hit(videos=elsewhere)]}) == []


@pytest.fixture
def fake_download(monkeypatch, synthetic_video):
    def _copy(client, url, dest, *, max_bytes):
        shutil.copy(synthetic_video, dest)
        return dest

    monkeypatch.setattr(stock, "download_file", _copy)


@respx.mock
def test_collect_searches_films_and_logs_the_licence(tmp_path, settings, fake_download):
    route = respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    assets = collect_stock_assets(SOURCE, httpx.Client(), "key-123", ["gaming laptop"], tmp_path, settings)
    params = route.calls.last.request.url.params
    assert params["key"] == "key-123" and params["q"] == "gaming laptop"
    assert params["video_type"] == "film" and params["safesearch"] == "true"
    assert [a.source_url for a in assets] == ["https://pixabay.com/videos/laptop-keyboard-201/",
                                              "https://pixabay.com/videos/desk-setup-203/"]
    first = assets[0]
    assert first.kind == AssetKind.STOCK_VIDEO and first.rights_basis == RightsBasis.LICENSED
    assert first.rightsholder == "Carla Reis" and "pixabay.com/service/license" in first.licence_terms_ref
    assert first.music_stripped and first.source_platform == "pixabay"


@respx.mock
def test_long_search_terms_are_cut_to_pixabay_limit(tmp_path, settings, fake_download):
    route = respx.get(url__startswith=SEARCH_URL).respond(200, json={"hits": []})
    collect_stock_assets(SOURCE, httpx.Client(), "k", ["x" * 150], tmp_path, settings)
    assert len(route.calls.last.request.url.params["q"]) == 100


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403])
def test_refused_key_means_no_stock_footage(tmp_path, settings, caplog, status):
    respx.get(url__startswith=SEARCH_URL).respond(status, text="[ERROR 400] Invalid API key")
    assert collect_stock_assets(SOURCE, httpx.Client(), "bad", ["laptop", "desk"], tmp_path, settings) == []
    assert "PIXABAY_API_KEY" in caplog.text


@respx.mock
def test_the_key_never_reaches_the_logs(tmp_path, settings, caplog):
    caplog.set_level(logging.INFO)
    respx.get(url__startswith=SEARCH_URL).respond(500, text="oops")
    collect_stock_assets(SOURCE, httpx.Client(), "SECRET-KEY-42", ["laptop"], tmp_path, settings)
    assert "500" in caplog.text
    assert "SECRET-KEY-42" not in caplog.text


def test_broken_file_address_is_skipped_not_fatal():
    broken = {"medium": {"url": "https://cdn.pixabay.com/\x00", "width": 1920, "height": 1080}}
    assert parse_search({"hits": [_hit(videos=broken)]}) == []


@respx.mock
def test_bad_request_that_is_not_about_the_key_tries_the_next_term(tmp_path, settings, fake_download, caplog):
    def _answer(request):
        if request.url.params["q"] == "odd term":
            return httpx.Response(400, text='[ERROR 400] "q" is out of range')
        return httpx.Response(200, json=PAYLOAD)

    respx.get(url__startswith=SEARCH_URL).mock(side_effect=_answer)
    assets = collect_stock_assets(SOURCE, httpx.Client(), "k", ["odd term", "laptop"], tmp_path, settings)
    assert len(assets) == 2 and "PIXABAY_API_KEY" not in caplog.text
