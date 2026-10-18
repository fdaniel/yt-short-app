import io
import json
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image

from shorts.media.ffmpeg import probe_video
from shorts.models import AssetKind, VideoFormat, VideoStatus
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
def test_e2e_steam_failure_falls_back_to_cards(settings, conn):
    respx.get(NEWS).respond(200, text=(FIXTURES / "article_nvidia.html").read_text())
    respx.get(url__startswith="https://store.steampowered.com/api/appdetails").respond(503)
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, 999, VideoFormat.NEWS_FLASH, settings, deps, conn)
    kinds = {a.kind for a in AssetRepository(conn).list_for_video(r.video_id)}
    assert kinds == {AssetKind.CARD}


@respx.mock
def test_given_article_is_not_fetched(settings, conn):
    mock_sources()
    route = respx.get(NEWS)
    given = extract_article(NEWS, (FIXTURES / "article_nvidia.html").read_text())
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    make_video(NEWS, None, VideoFormat.NEWS_FLASH, settings, deps, conn, article=given)
    assert route.call_count == 0


@respx.mock
def test_failure_removes_work_dir(settings, conn, monkeypatch):
    mock_sources()
    monkeypatch.setattr("shorts.pipeline.render_video", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("render crashed")))
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    with pytest.raises(PipelineError, match="render crashed"):
        make_video(NEWS, None, VideoFormat.NEWS_FLASH, settings, deps, conn)
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
def test_broken_screenshot_is_skipped(settings, conn):
    mock_sources()
    respx.get(url__regex=r".*\.jpg.*").respond(200, content=b"not an image")
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps, conn)
    assert r.video_path.exists()


@respx.mock
def test_unexpected_steam_error_falls_back_to_cards(settings, conn, monkeypatch):
    mock_sources()
    monkeypatch.setattr("shorts.pipeline.collect_steam_assets", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps, conn)
    kinds = {a.kind for a in AssetRepository(conn).list_for_video(r.video_id)}
    assert kinds == {AssetKind.CARD}
