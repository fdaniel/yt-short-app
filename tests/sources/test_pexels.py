import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx

from shorts.models import AssetKind, RightsBasis
from shorts.sources import pexels
from shorts.sources.pexels import SEARCH_URL, collect_stock_assets, parse_search

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

    monkeypatch.setattr(pexels, "download_file", _copy)


@respx.mock
def test_collect_logs_the_licence_and_strips_audio(tmp_path, settings, fake_download):
    route = respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    assets = collect_stock_assets(httpx.Client(), "key-123", ["gaming laptop"], tmp_path, settings)
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
    assets = collect_stock_assets(httpx.Client(), "k", ["laptop", "desk"], tmp_path, settings)
    assert len({a.source_url for a in assets}) == len(assets) == 2


@respx.mock
def test_at_most_max_clips(tmp_path, settings, fake_download, monkeypatch):
    many = {"videos": [{**PAYLOAD["videos"][0], "id": i, "url": f"https://www.pexels.com/video/{i}/"}
                       for i in range(10)]}
    respx.get(url__startswith=SEARCH_URL).respond(200, json=many)
    assets = collect_stock_assets(httpx.Client(), "k", ["a", "b", "c"], tmp_path, settings)
    assert len(assets) == pexels.MAX_CLIPS


@respx.mock
def test_refused_key_means_no_stock_footage(tmp_path, settings, caplog):
    respx.get(url__startswith=SEARCH_URL).respond(401, json={"error": "bad key"})
    assert collect_stock_assets(httpx.Client(), "bad", ["laptop"], tmp_path, settings) == []
    assert "PEXELS_API_KEY" in caplog.text


@respx.mock
def test_broken_download_is_skipped(tmp_path, settings, monkeypatch):
    respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    monkeypatch.setattr(pexels, "download_file", lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("slow")))
    assert collect_stock_assets(httpx.Client(), "k", ["laptop"], tmp_path, settings) == []
