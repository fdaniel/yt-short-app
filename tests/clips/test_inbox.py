from datetime import datetime

from shorts.clips.inbox import parse_clip, ready_clips

from tests.clips.helpers import settle


def test_a_recorder_clip_name_tells_game_kind_and_time(tmp_path):
    clip = parse_clip(tmp_path / "3321460_Crimson-Desert_2026-11-10_21-05-33_auto.mp4")
    assert (clip.app_id, clip.game, clip.kind) == (3321460, "Crimson Desert", "auto")
    assert clip.saved_at == datetime(2026, 11, 10, 21, 5, 33)


def test_a_recording_made_by_hand_is_its_own_kind(tmp_path):
    assert parse_clip(tmp_path / "3321460_Crimson-Desert_2026-11-10_21-05-33_rec.mp4").kind == "rec"


def test_a_second_clip_in_the_same_second_still_parses(tmp_path):
    clip = parse_clip(tmp_path / "3321460_Crimson-Desert_2026-11-10_21-05-33-2_pick.mkv")
    assert clip.kind == "pick" and clip.app_id == 3321460


def test_any_other_video_counts_as_the_owners_pick(tmp_path):
    clip = parse_clip(tmp_path / "Replay 2026-11-10 21-05-33.mp4")
    assert (clip.app_id, clip.game, clip.kind, clip.saved_at) == (None, "", "pick", None)
    old_recording = parse_clip(tmp_path / "1492070_Sker-Ritual_2026-10-26_21-05-33.mp4")
    assert old_recording.kind == "pick" and old_recording.game == "Sker Ritual"


def test_files_that_are_not_videos_are_ignored(tmp_path):
    assert parse_clip(tmp_path / "notes.txt") is None
    assert parse_clip(tmp_path / "~syncthing~clip.mp4.tmp") is None
    assert parse_clip(tmp_path / "1_A_2026-11-10_21-00-00_pick.sync-conflict-20261110-210000-ABCDEFG.mp4") is None


def test_only_settled_videos_are_ready(tmp_path):
    done = settle(_touch(tmp_path / "1_A_2026-11-10_21-00-00_pick.mp4"))
    _touch(tmp_path / "1_A_2026-11-10_21-01-00_pick.mp4")  # Syncthing may still be writing it
    _touch(tmp_path / ".stfolder" / "x.mp4")
    settle(_touch(tmp_path / "~syncthing~2.mp4.tmp"))
    assert [c.path for c in ready_clips(tmp_path, settle_s=30)] == [done]


def test_a_missing_inbox_has_no_clips(tmp_path):
    assert ready_clips(tmp_path / "nowhere", settle_s=30) == []


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path
