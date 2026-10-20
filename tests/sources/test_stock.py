import json
import os
import shutil
import time
from pathlib import Path

import httpx
import pytest
import respx

from shorts.sources import stock
from shorts.sources.pixabay import SEARCH_URL, SOURCE
from shorts.sources.stock import CACHE_TTL_S, collect_stock_assets

FIXTURES = Path(__file__).parent.parent / "fixtures"
PAYLOAD = json.loads((FIXTURES / "pixabay_search.json").read_text())


@pytest.fixture
def fake_download(monkeypatch, synthetic_video):
    def _copy(client, url, dest, *, max_bytes):
        shutil.copy(synthetic_video, dest)
        return dest

    monkeypatch.setattr(stock, "download_file", _copy)


@respx.mock
def test_same_search_within_a_day_is_not_sent_again(tmp_path, settings, fake_download):
    route = respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    first = collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path / "a", settings)
    second = collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path / "b", settings)
    assert route.call_count == 1
    assert [a.source_url for a in first] == [a.source_url for a in second]


@respx.mock
def test_search_older_than_a_day_is_sent_again(tmp_path, settings, fake_download):
    route = respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path / "a", settings)
    old = time.time() - CACHE_TTL_S - 60
    for cached in (settings.data_dir / "cache").rglob("*.json"):
        os.utime(cached, (old, old))
    collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path / "b", settings)
    assert route.call_count == 2


@respx.mock
def test_cache_never_stores_the_key(tmp_path, settings, fake_download):
    respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    collect_stock_assets(SOURCE, httpx.Client(), "SECRET-KEY-42", ["laptop"], tmp_path, settings)
    files = list((settings.data_dir / "cache").rglob("*"))
    assert files and all("SECRET-KEY-42" not in f.name for f in files)
    assert all("SECRET-KEY-42" not in f.read_text() for f in files if f.is_file())


@respx.mock
def test_broken_cache_file_is_searched_again(tmp_path, settings, fake_download):
    route = respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path / "a", settings)
    for cached in (settings.data_dir / "cache").rglob("*.json"):
        cached.write_text("{not json")
    assert collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path / "b", settings)
    assert route.call_count == 2


@respx.mock
def test_wanted_limits_how_many_clips(tmp_path, settings, fake_download):
    respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    assert len(collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path, settings, wanted=1)) == 1
    assert collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop"], tmp_path, settings, wanted=0) == []


@respx.mock
def test_clips_are_kept_when_the_search_cannot_be_saved(tmp_path, settings, fake_download):
    respx.get(url__startswith=SEARCH_URL).respond(200, json=PAYLOAD)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "cache").write_text("a file where the cache folder should be")
    assert len(collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop", "desk"], tmp_path, settings)) == 2


@respx.mock
def test_rate_limit_stops_asking_that_site(tmp_path, settings, caplog):
    route = respx.get(url__startswith=SEARCH_URL).respond(429, text="API rate limit exceeded.")
    assert collect_stock_assets(SOURCE, httpx.Client(), "k", ["laptop", "desk", "chip"], tmp_path, settings) == []
    assert route.call_count == 1 and "429" in caplog.text
