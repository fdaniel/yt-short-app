import json

import httpx
import pytest
import respx

from shorts.models import VideoFormat, VideoStatus
from shorts.pipeline import PipelineDeps, PipelineError, make_video, remake_with_take
from shorts.storage.repositories import AssetRepository, VideoRepository
from tests.fakes import FakeTTS, ScriptedLLM
from tests.test_pipeline_e2e import ALL_OK, GOOD, NEWS, mock_sources

TAKE = "Worth it if you game at 4K."


def made(settings, conn):
    mock_sources()
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    return make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps, conn)


@respx.mock
def test_a_take_becomes_the_closing_line_of_a_new_render(settings, conn):
    first = made(settings, conn)
    videos, assets = VideoRepository(conn), AssetRepository(conn)
    before = videos.get(first.video_id)
    rights_rows = len(assets.list_for_video(first.video_id))

    deps = PipelineDeps(httpx.Client(), ScriptedLLM([]), FakeTTS(rate=0.07))  # no AI call: the script is kept
    r = remake_with_take(first.video_id, TAKE, settings, deps, conn)

    after = videos.get(r.video_id)
    script = json.loads(after.script_json)
    assert script["closing"] == TAKE and script["hook"] == GOOD.hook
    assert after.status == VideoStatus.AWAITING_APPROVAL and after.content_hash != before.content_hash
    assert json.loads(r.metadata_path.read_text())["owner_take"] == TAKE
    assert r.video_path == before.output_path and r.video_path.is_file()
    assert len(assets.list_for_video(r.video_id)) == rights_rows  # the rights log describes the new render only
    assert not list((settings.data_dir / "work").glob("*"))


@respx.mock
def test_a_failed_remake_leaves_the_video_as_it_was(settings, conn):
    first = made(settings, conn)
    videos, assets = VideoRepository(conn), AssetRepository(conn)
    before, rows = videos.get(first.video_id), assets.list_for_video(first.video_id)
    video_bytes = first.video_path.read_bytes()

    slow = PipelineDeps(httpx.Client(), ScriptedLLM([]), FakeTTS(rate=0.2))  # far over the time limit
    with pytest.raises(PipelineError, match="Your take was not added: narration is"):
        remake_with_take(first.video_id, TAKE, settings, slow, conn)

    after = videos.get(first.video_id)
    assert (after.status, after.script_json, after.content_hash) == (before.status, before.script_json, before.content_hash)
    assert first.video_path.read_bytes() == video_bytes
    assert assets.list_for_video(first.video_id) == rows


@respx.mock
def test_only_a_video_waiting_for_review_takes_a_take(settings, conn):
    first = made(settings, conn)
    VideoRepository(conn).set_status(first.video_id, VideoStatus.DISCARDED)
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([]), FakeTTS(rate=0.07))
    with pytest.raises(PipelineError, match="no longer waiting for review"):
        remake_with_take(first.video_id, TAKE, settings, deps, conn)


@respx.mock
def test_a_video_made_before_takes_existed_says_so(settings, conn):
    first = made(settings, conn)
    (first.video_path.parent / "article.json").unlink()
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([]), FakeTTS(rate=0.07))
    with pytest.raises(PipelineError, match="made before takes"):
        remake_with_take(first.video_id, TAKE, settings, deps, conn)
