import os
from datetime import datetime

from shorts.clips.desk import ClipDesk
from shorts.clips.maker import ClipError, ClipResult
from shorts.clips.moments import Moment
from shorts.discovery.runner import _run_lock
from shorts.models import VideoFormat, VideoStatus
from shorts.storage.repositories import VideoRepository

NOW = datetime(2026, 11, 10, 22, 0).timestamp()


class Recorder:
    """Stands in for find_moment and make_clip; scores come from the file name."""

    def __init__(self, scores=None, fail=()):
        self.scores, self.fail, self.made = scores or {}, set(fail), []

    def find(self, path, length_s, *, favour_end, timeout_s):
        return Moment(0.0, float(length_s), self.scores.get(path.name, 1.0))

    def make(self, clip, moment, settings, conn, vision):
        if clip.path.name in self.fail:
            raise ClipError("could not render")
        assert clip.path.exists()
        self.made.append(clip.path.name)
        repo = VideoRepository(conn)  # like make_clip: a finished video waiting for review
        vid = repo.create(f"clip:{clip.path.name}", None, VideoFormat.GAMEPLAY)
        for step in (VideoStatus.FACT_CHECKED, VideoStatus.RENDERING, VideoStatus.AWAITING_APPROVAL):
            repo.set_status(vid, step)
        return ClipResult(vid, clip.path)


def _desk(settings, conn, rec, clock=lambda: NOW, **extra):
    return ClipDesk(settings, conn, vision=[], clock=clock, find=rec.find, make=rec.make,
                    free_bytes=extra.pop("free_bytes", lambda path: 10**12), **extra)


def _clip(inbox, name):
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_bytes(b"x")
    old = NOW - 300
    os.utime(path, (old, old))
    return path


def test_a_pick_becomes_a_short_and_leaves_the_inbox(clip_settings, conn):
    settings, inbox = clip_settings
    pick = _clip(inbox, "1_Game_2026-11-10_21-00-00_pick.mp4")
    rec = Recorder()
    messages = _desk(settings, conn, rec).tick()
    assert rec.made == [pick.name] and not pick.exists()
    assert any("waiting for review" in m for m in messages)


def test_a_clip_still_arriving_waits(clip_settings, conn):
    settings, inbox = clip_settings
    fresh = _clip(inbox, "1_Game_2026-11-10_21-00-00_pick.mp4")
    os.utime(fresh, (NOW, NOW))
    rec = Recorder()
    _desk(settings, conn, rec).tick()
    assert rec.made == [] and fresh.exists()


def test_only_the_best_automatic_clips_are_kept_until_the_session_ends(clip_settings, conn):
    settings, inbox = clip_settings
    names = [f"1_Game_2026-11-10_21-0{i}-00_auto.mp4" for i in range(3)]
    for name in names:
        _clip(inbox, name)
    rec = Recorder(scores={names[0]: 1.0, names[1]: 5.0, names[2]: 3.0})
    _desk(settings, conn, rec).tick()
    assert rec.made == [] and not any(inbox.iterdir())  # all left the inbox: kept aside or deleted
    later = NOW + settings.clips.session_gap_min * 60 + 1
    _desk(settings, conn, rec, clock=lambda: later).tick()
    assert rec.made == [names[1], names[2]]  # auto_keep=2, best first
    rec.made.clear()
    _desk(settings, conn, rec, clock=lambda: later + 600).tick()
    assert rec.made == []  # nothing kept twice


def test_a_session_still_going_keeps_its_automatic_clips(clip_settings, conn):
    settings, inbox = clip_settings
    _clip(inbox, "1_Game_2026-11-10_21-00-00_auto.mp4")
    rec = Recorder()
    _desk(settings, conn, rec).tick()
    _desk(settings, conn, rec, clock=lambda: NOW + 60).tick()
    assert rec.made == []


def test_an_automatic_clip_of_the_same_moment_as_a_pick_is_dropped(clip_settings, conn):
    settings, inbox = clip_settings
    _clip(inbox, "1_Game_2026-11-10_21-00-00_pick.mp4")
    _clip(inbox, "1_Game_2026-11-10_21-00-20_auto.mp4")  # saved 20 s after the pick: the same fight
    _clip(inbox, "1_Game_2026-11-10_21-30-00_auto.mp4")
    rec = Recorder()
    _desk(settings, conn, rec).tick()
    _desk(settings, conn, rec, clock=lambda: NOW + 3600).tick()
    assert rec.made == ["1_Game_2026-11-10_21-00-00_pick.mp4", "1_Game_2026-11-10_21-30-00_auto.mp4"]


def test_a_pick_that_fails_is_set_aside_in_the_inbox_not_retried(clip_settings, conn):
    settings, inbox = clip_settings
    bad = _clip(inbox, "1_Game_2026-11-10_21-00-00_pick.mp4")
    rec = Recorder(fail={bad.name})
    messages = _desk(settings, conn, rec).tick()
    assert not bad.exists() and (inbox / "failed" / bad.name).exists()  # same drive: a rename, no copy
    assert any("could not render" in m for m in messages)
    _desk(settings, conn, rec).tick()
    assert rec.made == []


def test_only_the_newest_failed_picks_are_kept(clip_settings, conn):
    settings, inbox = clip_settings
    names = [f"1_Game_2026-11-10_21-0{i}-00_pick.mp4" for i in range(7)]
    for name in names:
        _clip(inbox, name)
    rec = Recorder(fail=set(names))
    for _ in range(3):
        _desk(settings, conn, rec).tick()
    assert len(list((inbox / "failed").iterdir())) == 5


def test_an_automatic_clip_that_fails_is_simply_deleted(clip_settings, conn):
    settings, inbox = clip_settings
    auto = _clip(inbox, "1_Game_2026-11-10_21-00-00_auto.mp4")
    rec = Recorder()

    def broken(path, length_s, *, favour_end, timeout_s):
        raise ValueError("unreadable")

    rec.find = broken
    _desk(settings, conn, rec).tick()
    assert not auto.exists() and not (inbox / "failed").exists()


def test_a_short_that_was_made_is_never_made_again_when_its_clip_cannot_be_deleted(clip_settings, conn):
    settings, inbox = clip_settings
    pick = _clip(inbox, "1_Game_2026-11-10_21-00-00_pick.mp4")
    rec = Recorder()
    inbox.chmod(0o555)  # like Windows refusing to delete a clip a player has open
    try:
        messages = _desk(settings, conn, rec).tick() + _desk(settings, conn, rec).tick()
    finally:
        inbox.chmod(0o755)
    assert rec.made == [pick.name] and pick.exists()
    assert not any("could not be made" in m for m in messages)
    _desk(settings, conn, rec).tick()
    assert rec.made == [pick.name] and not pick.exists()


def test_a_pick_then_its_automatic_twin_in_a_later_look_is_dropped(clip_settings, conn):
    settings, inbox = clip_settings
    rec = Recorder()
    _clip(inbox, "1_Game_2026-11-10_21-00-00_pick.mp4")
    _desk(settings, conn, rec).tick()
    _clip(inbox, "1_Game_2026-11-10_21-00-30_auto.mp4")
    _desk(settings, conn, rec, clock=lambda: NOW + 60).tick()
    _desk(settings, conn, rec, clock=lambda: NOW + 3600).tick()
    assert rec.made == ["1_Game_2026-11-10_21-00-00_pick.mp4"]


def test_twins_of_picks_do_not_take_the_places_of_other_automatic_clips(clip_settings, conn):
    settings, inbox = clip_settings
    twin, other = "1_Game_2026-11-10_21-00-30_auto.mp4", "1_Game_2026-11-10_21-10-00_auto.mp4"
    _clip(inbox, "1_Game_2026-11-10_21-00-00_pick.mp4")
    _clip(inbox, twin)
    _clip(inbox, other)
    rec = Recorder(scores={twin: 9.0, other: 2.0})
    settings = settings.model_copy(update={"clips": settings.clips.model_copy(update={"auto_keep": 1})})
    _desk(settings, conn, rec).tick()
    _desk(settings, conn, rec, clock=lambda: NOW + 3600).tick()
    assert rec.made == ["1_Game_2026-11-10_21-00-00_pick.mp4", other]


def test_videos_left_half_made_by_a_crash_are_marked_failed(clip_settings, conn):
    settings, _ = clip_settings
    repo = VideoRepository(conn)
    stuck = repo.create("clip:x.mp4", None, VideoFormat.GAMEPLAY)
    repo.set_status(stuck, VideoStatus.FACT_CHECKED)
    repo.set_status(stuck, VideoStatus.RENDERING)
    news = repo.create("https://news", None, VideoFormat.NEWS_FLASH)  # a news run's video is not the desk's
    _desk(settings, conn, Recorder()).tick()
    assert repo.get(stuck).status == VideoStatus.FAILED and "interrupted" in repo.get(stuck).failure_reason
    assert repo.get(news).status == VideoStatus.SCRIPTING


def test_kept_clips_are_saved_one_by_one_and_strays_removed(clip_settings, conn):
    settings, inbox = clip_settings
    first, second = "1_Game_2026-11-10_21-00-00_auto.mp4", "1_Game_2026-11-10_21-01-00_auto.mp4"
    _clip(inbox, first)
    _clip(inbox, second)
    stray = settings.data_dir / "clips" / "candidates" / "lost.mp4"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"x")
    looked = []
    rec = Recorder()
    desk = _desk(settings, conn, rec, should_stop=lambda: bool(looked) or looked.append(1))
    desk.tick()  # stopped after the first clip, as when the dashboard closes
    assert (inbox / second).exists() and not stray.exists()
    later = NOW + 3600
    _desk(settings, conn, rec, clock=lambda: later).tick()
    _desk(settings, conn, rec, clock=lambda: later + 3600).tick()
    assert rec.made == [first, second]


def test_a_look_handles_a_few_clips_at_a_time(clip_settings, conn):
    settings, inbox = clip_settings
    for i in range(7):
        _clip(inbox, f"1_Game_2026-11-10_21-0{i}-00_pick.mp4")
    rec = Recorder()
    _desk(settings, conn, rec).tick()
    assert len(rec.made) == 5
    _desk(settings, conn, rec).tick()
    assert len(rec.made) == 7


def test_nothing_is_made_when_the_disk_is_nearly_full(clip_settings, conn):
    settings, inbox = clip_settings
    pick = _clip(inbox, "1_Game_2026-11-10_21-00-00_pick.mp4")
    rec = Recorder()
    messages = _desk(settings, conn, rec, free_bytes=lambda path: 1024).tick()
    assert rec.made == [] and pick.exists() and any("disk" in m for m in messages)


def test_nothing_happens_while_a_news_run_renders(clip_settings, conn):
    settings, inbox = clip_settings
    pick = _clip(inbox, "1_Game_2026-11-10_21-00-00_pick.mp4")
    rec = Recorder()
    with _run_lock(settings.data_dir):
        assert _desk(settings, conn, rec).tick() == []
    assert pick.exists()


def test_without_an_inbox_the_desk_is_off(settings, conn):
    rec = Recorder()
    assert _desk(settings, conn, rec).tick() == []
