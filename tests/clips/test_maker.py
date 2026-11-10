import json

import pytest

from shorts.clips.inbox import parse_clip
from shorts.clips.maker import ClipError, make_clip
from shorts.clips.moments import Moment
from shorts.models import VideoFormat, VideoStatus
from shorts.storage.repositories import VideoRepository

from tests.clips.helpers import FakeVision, clip_text, gameplay


def test_a_clip_becomes_a_short_waiting_for_review(tmp_path, settings, conn):
    clip = parse_clip(gameplay(tmp_path / "inbox", seconds=8))
    vision = FakeVision(result=clip_text())
    result = make_clip(clip, Moment(1.0, 7.0, 0.0), settings, conn, [vision])
    record = VideoRepository(conn).get(result.video_id)
    assert record.status == VideoStatus.AWAITING_APPROVAL and record.format == VideoFormat.GAMEPLAY
    assert record.title == "Crimson Desert: one combo boss kill"
    assert record.news_url == f"clip:{clip.path.name}" and record.steam_app_id == 3321460
    export = settings.data_dir / "exports" / str(result.video_id)
    assert {p.name for p in export.iterdir()} == {"video.mp4", "cover.png", "metadata.json"}
    meta = json.loads((export / "metadata.json").read_text())
    assert meta["category_id"] == "20"  # Gaming
    assert meta["hashtags"] == ["#CrimsonDesert", "#gaming", "#shorts"] and meta["title_options"][0] == record.title
    assert json.loads(record.script_json)["hook"] == "Boss down in one combo"
    assert len(vision.calls[0][1]) == 3  # three frames from the moment
    assert not (settings.data_dir / "work").exists() or not any((settings.data_dir / "work").iterdir())


def test_a_broken_clip_is_marked_failed(tmp_path, settings, conn):
    broken = tmp_path / "inbox" / "1_A_2026-11-10_21-00-00_pick.mp4"
    broken.parent.mkdir()
    broken.write_bytes(b"not a video")
    with pytest.raises(ClipError):
        make_clip(parse_clip(broken), Moment(0.0, 5.0, 0.0), settings, conn, [FakeVision(result=clip_text())])
    (record,) = VideoRepository(conn).list_recent(5)
    assert record.status == VideoStatus.FAILED and record.failure_reason


def test_a_long_recording_gets_more_frames_for_the_writer():
    from shorts.clips.maker import frame_count

    assert frame_count(35.0) == 3 and frame_count(170.0) == 6
