import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx

from shorts.models import AssetKind, RightsBasis
from shorts.sources import stock
from shorts.sources.pexels import SEARCH_URL, SOURCE, parse_search
from shorts.sources.stock import collect_stock_assets

FIXTURES = Path(__file__).parent.parent / "fixtures"
PAYLOAD = json.loads((FIXTURES / "pexels_search.json").read_text())


def test_parse_picks_full_hd_mp4_and_skips_too_short_clips():
    clips = parse_search(PAYLOAD)
    assert [c.id for c in clips] == [101, 103]
    assert clips[0].file_url == "https://videos.pexels.com/101-hd.mp4"  # not the 4K file
    assert clips[1].file_url == "https://videos.pexels.com/103-sd.mp4"  # mp4 only
    assert clips[0].author == "Ana Silva" and clips[0].page_url == "https://www.pexels.com/video/laptop-101/"


def test_parse_ignores_malformed_entries():
    assert parse_search({"videos": [{"id": "x"}, {"id": 5, "duration": 10, "video_files": []}, 7]}) == []
    assert parse_search({"oops": 1}) == []


@pytest.fixture
def fake_download(monkeypatch, synthetic_video):
    def _copy(client, url, dest, *, max_bytes):
        shutil.copy(synthetic_video, dest)
        return dest

    monkeypatch.setattr(stock, "download_file", _copy)


@respx.mock
def test_collect_logs_the_licence_and_strips_audio(tmp_path, settings, fake_download):
    route = respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    assets = collect_stock_assets(SOURCE, httpx.Client(), "key-123", ["gaming laptop"], tmp_path, settings)
    request = route.calls.last.request
    assert request.headers["Authorization"] == "key-123"
    assert request.url.params["query"] == "gaming laptop" and request.url.params["orientation"] == "portrait"
    assert [a.source_url for a in assets] == ["https://www.pexels.com/video/laptop-101/",
                                              "https://www.pexels.com/video/desk-103/"]
    first = assets[0]
    assert first.kind == AssetKind.STOCK_VIDEO and first.rights_basis == RightsBasis.LICENSED
    assert first.rightsholder == "Ana Silva" and "pexels.com/license" in first.licence_terms_ref
    assert first.music_stripped and first.source_platform == "pexels"
    from shorts.media.ffmpeg import probe_video

    assert not probe_video(first.local_path).has_audio


@respx.mock
def test_same_clip_is_not_downloaded_twice(tmp_path, settings, fake_download):
    respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    assets = collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop", "desk"], tmp_path, settings)
    assert len({a.source_url for a in assets}) == len(assets) == 2


@respx.mock
def test_at_most_max_clips(tmp_path, settings, fake_download, monkeypatch):
    many = {"videos": [{**PAYLOAD["videos"][0], "id": i, "url": f"https://www.pexels.com/video/{i}/"}
                       for i in range(10)]}
    respx.get(url__startswith=SEARCH_URL).respond(200, json=many)
    assets = collect_stock_assets(SOURCE, httpx.Client(), "k", ["a", "b", "c"], tmp_path, settings)
    assert len(assets) == stock.MAX_CLIPS


@respx.mock
def test_refused_key_means_no_stock_footage(tmp_path, settings, caplog):
    respx.get(url__startswith=SEARCH_URL).respond(401, json={"error": "bad key"})
    assert collect_stock_assets(SOURCE, httpx.Client(), "bad", ["laptop"], tmp_path, settings) == []
    assert "PEXELS_API_KEY" in caplog.text


@respx.mock
def test_broken_download_is_skipped(tmp_path, settings, monkeypatch):
    respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    monkeypatch.setattr(stock, "download_file", lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("slow")))
    assert collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path, settings) == []


def _video(**overrides):
    base = {"id": 9, "url": "https://www.pexels.com/video/x-9/", "duration": 10, "user": {"name": "A"},
            "video_files": [{"file_type": "video/mp4", "width": 1080, "height": 1920,
                             "link": "https://videos.pexels.com/9.mp4"}]}
    return {**base, **overrides}


def test_only_pexels_links_are_trusted():
    assert parse_search({"videos": [_video(url="https://evil.example/x")]}) == []
    bad_file = [{"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "http://videos.pexels.com/9.mp4"}]
    assert parse_search({"videos": [_video(video_files=bad_file)]}) == []
    odd_link = [{"file_type": "video/mp4", "width": 1080, "height": 1920, "link": 12}]
    assert parse_search({"videos": [_video(video_files=odd_link)]}) == []


def test_prefers_full_hd_over_4k():
    files = [{"file_type": "video/mp4", "width": w, "height": h, "link": f"https://videos.pexels.com/{w}.mp4"}
             for w, h in ((2160, 3840), (1440, 2560), (720, 1280))]
    assert parse_search({"videos": [_video(video_files=files)]})[0].file_url == "https://videos.pexels.com/1440.mp4"
    four_k_only = files[:1]
    assert parse_search({"videos": [_video(video_files=four_k_only)]}) == []  # too big to download


@respx.mock
def test_failed_download_tries_the_next_result(tmp_path, settings, monkeypatch, synthetic_video):
    respx.get(url__startswith=SEARCH_URL).respond(200, json={"videos": [_video(id=i, url=f"https://www.pexels.com/video/{i}/")
                                                                         for i in range(3)]})
    calls = []

    def _flaky(client, url, dest, *, max_bytes):
        calls.append(url)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow")
        shutil.copy(synthetic_video, dest)
        return dest

    monkeypatch.setattr(stock, "download_file", _flaky)
    assert len(collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path, settings)) == stock.MAX_PER_QUERY
