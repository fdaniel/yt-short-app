import io
import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image

from datetime import UTC, datetime

from shorts.media.ffmpeg import probe_video
from shorts.media.shots import Shot
from shorts.models import Asset, AssetKind, RightsBasis, VideoFormat, VideoStatus
from shorts.pipeline import PipelineDeps, PipelineError, make_video
from shorts.script.schema import CardFact, Claim, ClaimVerdict, FactCheckResult, ScriptDraft
from shorts.storage.repositories import AssetRepository, VideoRepository
from shorts.sources.article import extract_article
from tests.fakes import Failing, FakeTTS, ScriptedLLM

FIXTURES = Path(__file__).parent / "fixtures"
NEWS = "https://nvidianews.nvidia.com/news/x"

GOOD = ScriptDraft(
    hook="NVIDIA just made the RTX 5090 official.",
    body=[
        "It launches January 30, 2025, and it costs $1,999.",
        "Inside you get 32GB of GDDR7 memory and 21,760 CUDA cores.",
        "NVIDIA says it is up to twice as fast as the RTX 4090 with DLSS 4 Multi Frame Generation turned on.",
        "That feature can generate up to three extra frames for every rendered frame.",
        "And 75 games and apps will support it at launch.",
        "The RTX 5080 arrives the same day for $999 with 16GB of memory.",
    ],
    closing="Is the RTX 5090 worth it for you? Tell me below.",
    title_options=["RTX 5090: price, date and specs", "NVIDIA RTX 5090 is official", "RTX 5090 launch details"],
    description="Everything NVIDIA announced about the GeForce RTX 5090.",
    hashtags=["#nvidia", "#rtx5090", "#gpu"],
    claims=[Claim(text="launch date and price", source_quote="available starting January 30, 2025, at a price of $1,999")],
    card_facts=[CardFact(label="Price", value="$1,999"), CardFact(label="Memory", value="32GB GDDR7")],
)
ALL_OK = FactCheckResult(verdicts=[ClaimVerdict(claim="launch date and price", supported=True, reason="stated")])


def png_bytes(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "navy").save(buf, format="JPEG")
    return buf.getvalue()


def mock_sources():
    respx.get(NEWS).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    respx.get(url__startswith="https://store.steampowered.com/api/appdetails").respond(
        200, json=json.loads((FIXTURES / "steam_no_movies.json").read_text())
    )
    respx.get(url__regex=r".*\.jpg.*").respond(200, content=png_bytes(1920, 1080))


@respx.mock
def test_e2e_no_trailers(settings, conn):
    mock_sources()
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps, conn)
    assert set(deps.tts.voices) == {"af_heart"}  # video #1: the first voice
    info = probe_video(r.video_path)
    assert (info.width, info.height) == (1080, 1920) and info.has_audio
    meta = json.loads(r.metadata_path.read_text())
    assert meta["sources"][0] == NEWS
    assert "Footage: Indie Studio (steam)" in meta["description"]
    record = VideoRepository(conn).get(r.video_id)
    assert record.status == VideoStatus.AWAITING_APPROVAL and record.content_hash
    kinds = {a.kind for a in AssetRepository(conn).list_for_video(r.video_id)}
    assert AssetKind.TRAILER not in kinds and {AssetKind.CARD, AssetKind.SCREENSHOT} <= kinds
    assert not (settings.data_dir / "work" / str(r.video_id)).exists()
    cards = [a for a in AssetRepository(conn).list_for_video(r.video_id) if a.kind == AssetKind.CARD]
    assert len(cards) == 2 + len(GOOD.card_facts)  # hook, fact table, one card per fact


@respx.mock
def test_e2e_empty_article_fails_cleanly(settings, conn):
    respx.get("https://example.com/n").respond(200, text="<html><body><script>x()</script></body></html>")
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([]), FakeTTS())
    with pytest.raises(PipelineError, match="could not extract enough text"):
        make_video("https://example.com/n", None, VideoFormat.NEWS_FLASH, settings, deps, conn)
    record = VideoRepository(conn).get(1)
    assert record.status == VideoStatus.FAILED and "could not extract" in record.failure_reason


@respx.mock
def test_e2e_narration_too_long_fails_before_render(settings, conn):
    mock_sources()
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.2))
    with pytest.raises(PipelineError, match=r"narration is \d+\.\ds, allowed 30–55s"):
        make_video(NEWS, None, VideoFormat.NEWS_FLASH, settings, deps, conn)
    assert not (settings.data_dir / "exports").exists()
    assert VideoRepository(conn).get(1).status == VideoStatus.FAILED


@respx.mock
def test_e2e_no_footage_at_all_is_refused(settings, conn):
    # a Short of text cards only does badly on YouTube: better no video than that one
    respx.get(NEWS).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    respx.get(url__startswith="https://store.steampowered.com/api/appdetails").respond(503)
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    with pytest.raises(PipelineError, match="no footage.*PIXABAY_API_KEY"):
        make_video(NEWS, 999, VideoFormat.NEWS_FLASH, settings, deps, conn)
    assert VideoRepository(conn).get(1).status == VideoStatus.FAILED
    assert not (settings.data_dir / "exports").exists()


@pytest.fixture
def pexels_settings(settings):
    return settings.model_copy(update={"pexels_api_key": "pk"})


def mock_pexels(synthetic_video):
    payload = json.loads((FIXTURES / "pexels_search.json").read_text())
    route = respx.get(url__startswith="https://api.pexels.com/videos/search").respond(200, json=payload)
    respx.get(url__startswith="https://videos.pexels.com/").respond(200, content=synthetic_video.read_bytes())
    return route


@respx.mock
def test_e2e_hardware_story_gets_stock_footage(pexels_settings, conn, synthetic_video):
    respx.get(NEWS).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    search = mock_pexels(synthetic_video)
    draft = GOOD.model_copy(update={"footage_queries": ["gaming laptop", "graphics card"]})
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([draft, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, None, VideoFormat.NEWS_FLASH, pexels_settings, deps, conn)
    assert search.calls[0].request.url.params["query"] == "gaming laptop"
    kinds = [a.kind for a in AssetRepository(conn).list_for_video(r.video_id)]
    assert kinds.count(AssetKind.STOCK_VIDEO) == 2
    meta = json.loads(r.metadata_path.read_text())
    assert "Stock footage: Ana Silva via Pexels (https://www.pexels.com/video/laptop-101/)" in meta["description"]
    assert probe_video(r.video_path).height == 1920


def steam_media(video, screenshot=None):
    def _assets(*args, **kwargs):
        made = [Asset(None, AssetKind.TRAILER, video, "https://steam/x.mp4", "steam", "Pub", RightsBasis.STORE_PROMO,
                      "steam-store-promo", True, datetime.now(UTC))]
        if screenshot:
            made.append(Asset(None, AssetKind.SCREENSHOT, screenshot, "https://steam/s.jpg", "steam", "Pub",
                              RightsBasis.STORE_PROMO, "steam-store-promo", False, datetime.now(UTC)))
        return made

    return _assets


def trailer_scenes_of(length):
    """Trailer scenes of `length` seconds; downloaded stock clips keep their real scenes."""
    from shorts.media.shots import detect_shots as real

    def _detect(path, asset_id, **kwargs):
        if path.name.startswith("stock"):
            return real(path, asset_id, **kwargs)
        return [Shot(path, asset_id, 0.5 + k * length, 0.5 + (k + 1) * length, 1.0) for k in range(8)]

    return _detect


@pytest.fixture
def screenshot(tmp_path):
    path = tmp_path / "shot.jpg"
    path.write_bytes(png_bytes(1920, 1080))
    return path


@respx.mock
def test_e2e_game_with_trailer_and_screenshots_does_not_search_stock(
    pexels_settings, conn, synthetic_video, screenshot, monkeypatch
):
    mock_sources()
    search = mock_pexels(synthetic_video)
    monkeypatch.setattr("shorts.pipeline.collect_steam_assets", steam_media(synthetic_video, screenshot))
    monkeypatch.setattr("shorts.pipeline.detect_shots", trailer_scenes_of(5.0))
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    make_video(NEWS, 2, VideoFormat.NEWS_FLASH, pexels_settings, deps, conn)
    assert search.call_count == 0


@respx.mock
def test_e2e_trailer_with_only_short_scenes_gets_stock(pexels_settings, conn, synthetic_video, monkeypatch):
    # fast-cut trailers: every scene shorter than a slot, so none can be used
    mock_sources()
    search = mock_pexels(synthetic_video)
    monkeypatch.setattr("shorts.pipeline.collect_steam_assets", steam_media(synthetic_video))
    monkeypatch.setattr("shorts.pipeline.detect_shots", trailer_scenes_of(2.0))
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, 2, VideoFormat.NEWS_FLASH, pexels_settings, deps, conn)
    assert search.call_count >= 1
    assert AssetKind.STOCK_VIDEO in {a.kind for a in AssetRepository(conn).list_for_video(r.video_id)}


@respx.mock
def test_e2e_trailer_with_only_short_scenes_and_no_stock_is_refused(settings, conn, synthetic_video, monkeypatch):
    mock_sources()
    monkeypatch.setattr("shorts.pipeline.collect_steam_assets", steam_media(synthetic_video))
    monkeypatch.setattr("shorts.pipeline.detect_shots", trailer_scenes_of(2.0))
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    with pytest.raises(PipelineError, match="no footage"):
        make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps, conn)


@respx.mock
def test_e2e_broken_stock_clip_is_skipped(pexels_settings, conn, synthetic_video, monkeypatch):
    mock_sources()
    mock_pexels(synthetic_video)
    from shorts.media.ffmpeg import FFmpegError
    from shorts.media.shots import detect_shots as real

    def _detect(path, asset_id, **kwargs):
        if path.name == "stock_pexels_101.mp4":
            raise FFmpegError("ffprobe failed")
        return real(path, asset_id, **kwargs)

    monkeypatch.setattr("shorts.pipeline.detect_shots", _detect)
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    assert make_video(NEWS, None, VideoFormat.NEWS_FLASH, pexels_settings, deps, conn).video_path.exists()


def mock_pixabay(synthetic_video, payload=None):
    payload = payload or json.loads((FIXTURES / "pixabay_search.json").read_text())
    route = respx.get(url__startswith="https://pixabay.com/api/videos/").respond(200, json=payload)
    respx.get(url__startswith="https://cdn.pixabay.com/").respond(200, content=synthetic_video.read_bytes())
    return route


@respx.mock
def test_e2e_hardware_story_gets_pixabay_footage(settings, conn, synthetic_video):
    respx.get(NEWS).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    search = mock_pixabay(synthetic_video)
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, None, VideoFormat.NEWS_FLASH, settings.model_copy(update={"pixabay_api_key": "xk"}), deps,
                   conn)
    assert search.called
    assets = AssetRepository(conn).list_for_video(r.video_id)
    assert {a.source_platform for a in assets if a.kind == AssetKind.STOCK_VIDEO} == {"pixabay"}
    meta = json.loads(r.metadata_path.read_text())
    assert "via Pixabay (https://pixabay.com/videos/laptop-keyboard-201/)" in meta["description"]


def _with_more_clips(count):
    payload = json.loads((FIXTURES / "pixabay_search.json").read_text())
    template = payload["hits"][0]
    extra = [{**template, "id": 300 + n, "pageURL": f"https://pixabay.com/videos/server-{300 + n}/"} for n in range(count)]
    return {**payload, "hits": payload["hits"] + extra}


@respx.mock
def test_e2e_next_video_skips_clips_already_used(settings, conn, synthetic_video):
    respx.get(NEWS).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    keyed = settings.model_copy(update={"pixabay_api_key": "xk"})
    mock_pixabay(synthetic_video)
    first = make_video(NEWS, None, VideoFormat.NEWS_FLASH, keyed, PipelineDeps(
        httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07)), conn)
    shutil.rmtree(keyed.data_dir / "cache")  # the next story searches again and finds more clips
    mock_pixabay(synthetic_video, payload=_with_more_clips(6))
    second = make_video(NEWS, None, VideoFormat.NEWS_FLASH, keyed, PipelineDeps(
        httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07)), conn)
    repo = AssetRepository(conn)
    used_first = {a.source_url for a in repo.list_for_video(first.video_id) if a.kind == AssetKind.STOCK_VIDEO}
    used_second = {a.source_url for a in repo.list_for_video(second.video_id) if a.kind == AssetKind.STOCK_VIDEO}
    assert used_first and used_second and not used_first & used_second


@respx.mock
def test_e2e_pexels_fills_in_when_pixabay_finds_nothing(pexels_settings, conn, synthetic_video):
    respx.get(NEWS).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    mock_pixabay(synthetic_video, payload={"hits": []})
    mock_pexels(synthetic_video)
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    both = pexels_settings.model_copy(update={"pixabay_api_key": "xk"})
    r = make_video(NEWS, None, VideoFormat.NEWS_FLASH, both, deps, conn)
    assets = AssetRepository(conn).list_for_video(r.video_id)
    assert {a.source_platform for a in assets if a.kind == AssetKind.STOCK_VIDEO} == {"pexels"}


@respx.mock
def test_e2e_pexels_tops_up_when_pixabay_has_too_few(pexels_settings, conn, synthetic_video):
    respx.get(NEWS).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    one_clip = json.loads((FIXTURES / "pixabay_search.json").read_text())
    one_clip["hits"] = one_clip["hits"][:1]
    mock_pixabay(synthetic_video, payload=one_clip)
    mock_pexels(synthetic_video)
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    both = pexels_settings.model_copy(update={"pixabay_api_key": "xk"})
    r = make_video(NEWS, None, VideoFormat.NEWS_FLASH, both, deps, conn)
    platforms = [a.source_platform for a in AssetRepository(conn).list_for_video(r.video_id)
                 if a.kind == AssetKind.STOCK_VIDEO]
    assert platforms.count("pixabay") == 1 and platforms.count("pexels") == 2
    meta = json.loads(r.metadata_path.read_text())
    assert "via Pixabay" in meta["description"] and "via Pexels" in meta["description"]


@respx.mock
def test_e2e_stock_search_falls_back_to_generic_terms(pexels_settings, conn, synthetic_video):
    respx.get(NEWS).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    search = mock_pexels(synthetic_video)
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    make_video(NEWS, None, VideoFormat.NEWS_FLASH, pexels_settings, deps, conn)
    assert search.calls[0].request.url.params["query"] == "computer hardware"


@respx.mock
def test_given_article_is_not_fetched(settings, conn):
    mock_sources()
    route = respx.get(NEWS)
    given = extract_article(NEWS, (FIXTURES / "article_nvidia.html").read_text())
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps, conn, article=given)
    assert route.call_count == 0


@respx.mock
def test_failure_removes_work_dir(settings, conn, monkeypatch):
    mock_sources()
    monkeypatch.setattr("shorts.pipeline.render_video", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("render crashed")))
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    with pytest.raises(PipelineError, match="render crashed"):
        make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps, conn)
    assert not any((settings.data_dir / "work").glob("*"))


@respx.mock
def test_interrupt_marks_failed(settings, conn):
    mock_sources()
    deps = PipelineDeps(httpx.Client(), Failing(KeyboardInterrupt()), FakeTTS(rate=0.07))
    with pytest.raises(KeyboardInterrupt):
        make_video(NEWS, None, VideoFormat.NEWS_FLASH, settings, deps, conn)
    record = VideoRepository(conn).get(1)
    assert record.status == VideoStatus.FAILED and record.failure_reason == "interrupted"


@respx.mock
def test_broken_screenshot_is_skipped(pexels_settings, conn, synthetic_video):
    mock_sources()
    mock_pexels(synthetic_video)
    respx.get(url__regex=r".*\.jpg.*").respond(200, content=b"not an image")
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, 2, VideoFormat.NEWS_FLASH, pexels_settings, deps, conn)
    assert r.video_path.exists()


@respx.mock
def test_only_broken_screenshots_is_no_footage(settings, conn):
    mock_sources()
    respx.get(url__regex=r".*\.jpg.*").respond(200, content=b"not an image")
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    with pytest.raises(PipelineError, match="no footage"):
        make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps, conn)


@respx.mock
def test_unexpected_steam_error_falls_back_to_stock(pexels_settings, conn, monkeypatch, synthetic_video):
    mock_sources()
    mock_pexels(synthetic_video)
    monkeypatch.setattr("shorts.pipeline.collect_steam_assets", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, 2, VideoFormat.NEWS_FLASH, pexels_settings, deps, conn)
    kinds = {a.kind for a in AssetRepository(conn).list_for_video(r.video_id)}
    assert kinds == {AssetKind.CARD, AssetKind.STOCK_VIDEO}
