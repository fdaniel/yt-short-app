"""Watches the inbox: the owner's picks become Shorts at once; of the recorder's automatic clips only the
best few of each play session do, once the session is over. Every clip leaves the inbox once handled, so
Syncthing deletes it on the gaming PC too and neither disk fills up.

Safe against interruptions: the session is saved after every clip, a clip whose Short exists is never
made again (even if Windows will not let it be deleted yet), and half-made videos are marked failed."""

import json
import logging
import shutil
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from shorts.clips.inbox import ClipFile, ready_clips
from shorts.clips.maker import make_clip
from shorts.clips.moments import Moment, find_moment
from shorts.clips.text import VisionLLM
from shorts.config import Settings
from shorts.discovery.runner import RunLocked, _run_lock
from shorts.models import VideoFormat, VideoStatus
from shorts.storage.repositories import VideoRepository

log = logging.getLogger(__name__)
SAME_MOMENT_S = 60  # an automatic clip saved this close to a pick shows the same moment
PER_LOOK = 5  # clips handled per look, so a backlog never holds the news run's lock for long
FAILED_KEPT = 5  # failed picks kept in the inbox's failed folder for the owner to see
_UNFINISHED = (VideoStatus.SCRIPTING, VideoStatus.FACT_CHECKED, VideoStatus.RENDERING)


@dataclass(frozen=True)
class Candidate:
    name: str
    score: float
    start: float
    end: float
    app_id: int | None
    game: str
    saved_at: str | None


@dataclass(frozen=True)
class Session:
    candidates: tuple[Candidate, ...] = ()
    picks: tuple[str, ...] = ()  # when the owner's picks were saved (gaming PC time, ISO)
    last_seen_at: float = 0.0  # when the latest clip of the session was handled (this PC's clock)


def _same_moment(saved_at: str | None, picks: Sequence[str]) -> bool:
    if not saved_at:
        return False
    saved = datetime.fromisoformat(saved_at)
    return any(abs((saved - datetime.fromisoformat(p)).total_seconds()) <= SAME_MOMENT_S for p in picks)


class ClipDesk:
    def __init__(self, settings: Settings, conn: sqlite3.Connection, vision: Sequence[VisionLLM], *,
                 clock: Callable[[], float] = time.time, find: Callable[..., Moment] = find_moment,
                 make: Callable[..., object] = make_clip, should_stop: Callable[[], bool] = lambda: False,
                 free_bytes: Callable[[Path], int] = lambda p: shutil.disk_usage(p).free) -> None:
        self._settings, self._conn, self._vision = settings, conn, vision
        self._clock, self._find, self._make = clock, find, make
        self._should_stop, self._free_bytes = should_stop, free_bytes
        self._folder = settings.data_dir / "clips"
        self._held = self._folder / "candidates"

    def tick(self) -> list[str]:
        """One look at the inbox; what happened, in plain words. Waits for its turn behind a news run."""
        if self._settings.clips.inbox is None:
            return []
        try:
            with _run_lock(self._settings.data_dir):
                messages = self._work()
        except RunLocked:
            return []
        for message in messages:
            log.info(message)
        return messages

    def _work(self) -> list[str]:
        self._sweep_unfinished()
        session = self._tidy(self._load())
        self._settings.data_dir.mkdir(parents=True, exist_ok=True)
        if self._free_bytes(self._settings.data_dir) < self._settings.discovery.min_free_gb * 1024**3:
            return [f"Gameplay clips wait: less than {self._settings.discovery.min_free_gb} GB free on the disk."]
        messages: list[str] = []
        clips = self._settings.clips
        for clip in ready_clips(clips.inbox, clips.settle_s, now=self._clock())[:PER_LOOK]:
            if self._should_stop():
                break
            session, message = self._handle(clip, session)
            self._save(session)
            messages += [message] if message else []
        if self._clock() - session.last_seen_at >= clips.session_gap_min * 60:  # the play session is over
            messages += self._finish(session) if session.candidates else []
            session = Session()
        self._save(session)
        return messages

    def _handle(self, clip: ClipFile, session: Session) -> tuple[Session, str | None]:
        """One clip; whatever goes wrong stays with this clip."""
        seen = replace(session, last_seen_at=self._clock())
        try:
            if self._already_made(clip.path.name):
                self._remove(clip.path)
                return seen, None
            if clip.kind == "pick":
                return self._pick(clip, seen)
            return self._keep_if_good(clip, seen)
        except Exception as exc:  # a broken clip must not stop the others
            log.exception("Gameplay clip %s", clip.path.name)
            return seen, self._set_aside(clip, exc)

    def _pick(self, clip: ClipFile, session: Session) -> tuple[Session, str]:
        moment = self._find(clip.path, self._settings.clips.length_s, favour_end=True,
                            timeout_s=self._settings.limits.ffmpeg_timeout_s)
        message = self._made(clip, moment)
        if not clip.saved_at:
            return session, message
        picks = (*session.picks, clip.saved_at.isoformat())
        twins = [c for c in session.candidates if _same_moment(c.saved_at, picks)]
        for twin in twins:  # the owner chose this moment: its automatic copy gives up its place
            (self._held / twin.name).unlink(missing_ok=True)
        kept = tuple(c for c in session.candidates if c not in twins)
        return replace(session, candidates=kept, picks=picks), message

    def _made(self, clip: ClipFile, moment: Moment) -> str:
        result = self._make(clip, moment, self._settings, self._conn, self._vision)
        self._remove(clip.path)
        return f"Gameplay clip {clip.path.name} is video #{result.video_id}, waiting for review."

    def _keep_if_good(self, clip: ClipFile, session: Session) -> tuple[Session, str | None]:
        saved = clip.saved_at.isoformat() if clip.saved_at else None
        if _same_moment(saved, session.picks):
            self._remove(clip.path)  # the owner already picked this moment
            return session, None
        moment = self._find(clip.path, self._settings.clips.length_s, favour_end=False,
                            timeout_s=self._settings.limits.ffmpeg_timeout_s)
        self._held.mkdir(parents=True, exist_ok=True)
        shutil.move(str(clip.path), self._held / clip.path.name)
        new = Candidate(clip.path.name, moment.score, moment.start, moment.end, clip.app_id, clip.game, saved)
        ranked = sorted((*session.candidates, new), key=lambda c: c.score, reverse=True)
        keep = ranked[: self._settings.clips.auto_keep]
        for dropped in ranked[len(keep):]:
            (self._held / dropped.name).unlink(missing_ok=True)
        return replace(session, candidates=tuple(keep)), None

    def _finish(self, session: Session) -> list[str]:
        messages = []
        for candidate in session.candidates:
            path = self._held / Path(candidate.name).name
            if not path.exists() or _same_moment(candidate.saved_at, session.picks):
                path.unlink(missing_ok=True)
                continue
            saved = datetime.fromisoformat(candidate.saved_at) if candidate.saved_at else None
            clip = ClipFile(path, candidate.app_id, candidate.game, "auto", saved)
            try:
                messages.append(self._made(clip, Moment(candidate.start, candidate.end, candidate.score)))
            except Exception as exc:
                log.exception("Gameplay clip %s", candidate.name)
                messages.append(self._set_aside(clip, exc))
        return messages

    def _already_made(self, name: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM videos WHERE news_url = ? AND status != ? LIMIT 1",
                                 (f"clip:{name}", VideoStatus.FAILED.value)).fetchone()
        return row is not None

    def _remove(self, path: Path) -> None:
        """Gone from the inbox; if Windows still holds it open, the next look tries again."""
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not remove %s yet: %s", path.name, exc)

    def _set_aside(self, clip: ClipFile, exc: Exception) -> str:
        """A failed pick waits in the inbox's failed folder (same drive: no copy); a failed automatic clip goes."""
        if clip.kind == "auto" or clip.path.parent == self._held:
            self._remove(clip.path)
            return f"Automatic clip {clip.path.name} was skipped ({exc})."
        failed = self._settings.clips.inbox / "failed"
        try:
            failed.mkdir(exist_ok=True)
            clip.path.replace(failed / clip.path.name)
            for old in sorted(failed.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[FAILED_KEPT:]:
                old.unlink(missing_ok=True)
        except OSError as move_error:
            log.warning("Could not set %s aside: %s", clip.path.name, move_error)
        return f"Gameplay clip {clip.path.name} could not be made ({exc}); it is in {failed}."

    def _sweep_unfinished(self) -> None:
        """Videos this desk left half-made (the dashboard closed mid-render) are marked failed."""
        repo = VideoRepository(self._conn)
        rows = self._conn.execute(
            f"SELECT id FROM videos WHERE format = ? AND status IN ({','.join('?' * len(_UNFINISHED))})",
            (VideoFormat.GAMEPLAY.value, *(s.value for s in _UNFINISHED))).fetchall()
        for (video_id,) in rows:
            repo.set_status(video_id, VideoStatus.FAILED, "interrupted: the dashboard closed while making it")

    def _tidy(self, session: Session) -> Session:
        """Kept clips the session does not list (an interrupted look) are deleted, and missing ones forgotten."""
        listed = {c.name for c in session.candidates}
        if self._held.is_dir():
            for path in self._held.iterdir():
                if path.name not in listed:
                    path.unlink(missing_ok=True)
        present = tuple(c for c in session.candidates if (self._held / c.name).exists())
        return replace(session, candidates=present)

    def _load(self) -> Session:
        path = self._folder / "session.json"
        try:
            data = json.loads(path.read_text())
            return Session(tuple(Candidate(**{**c, "name": Path(c["name"]).name}) for c in data["candidates"]),
                           tuple(data["picks"]), float(data["last_seen_at"]))
        except FileNotFoundError:
            return Session()
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("Clip session file was damaged, starting a new one: %s", exc)
            return Session()

    def _save(self, session: Session) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        temp = self._folder / "session.json.tmp"
        temp.write_text(json.dumps({"candidates": [asdict(c) for c in session.candidates],
                                    "picks": list(session.picks), "last_seen_at": session.last_seen_at}))
        temp.replace(self._folder / "session.json")
