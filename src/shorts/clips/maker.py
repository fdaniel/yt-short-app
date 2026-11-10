"""One clip from the inbox into a Short waiting for review, with the same files a news video has."""

import hashlib
import json
import logging
import shutil
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from shorts.clips.inbox import ClipFile
from shorts.clips.moments import Moment
from shorts.clips.render import grab_frames, render_clip, write_clip_ass
from shorts.clips.text import ClipText, VisionLLM, write_clip_text
from shorts.config import Settings
from shorts.media.cover import cover_frame, render_cover
from shorts.media.shots import Shot
from shorts.models import VideoFormat, VideoStatus
from shorts.storage.repositories import VideoRepository

log = logging.getLogger(__name__)
GAMING_CATEGORY = "20"  # YouTube's Gaming category; the news videos use the settings' category
FRAMES = 3


class ClipError(Exception):
    """The clip could not be made into a Short."""


@dataclass(frozen=True)
class ClipResult:
    video_id: int
    video_path: Path


def _metadata(text: ClipText, settings: Settings) -> dict:
    footer = settings.youtube.description_footer.strip()
    description = text.description + (f"\n\n{footer}" if footer else "") + "\n\n" + " ".join(text.hashtags)
    return {"title": text.title_options[0], "title_options": text.title_options, "description": description,
            "hashtags": text.hashtags, "sources": [], "owner_take": "", "category_id": GAMING_CATEGORY,
            "rights": [{"kind": "gameplay", "source_url": None, "rightsholder": "the channel owner",
                        "rights_basis": "own_recording", "licence_terms_ref": "Recorded by the channel owner"}]}


def _hash(video: Path, meta: dict) -> str:
    digest = hashlib.sha256()
    with video.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(json.dumps(meta, sort_keys=True).encode())
    return digest.hexdigest()


def _build(clip: ClipFile, moment: Moment, work: Path, settings: Settings, vision: Sequence[VisionLLM],
           repo: VideoRepository, video_id: int) -> tuple[dict, list[Path]]:
    frames = grab_frames(clip.path, moment, work, count=FRAMES)
    text = write_clip_text([frame.read_bytes() for frame in frames], clip.game, vision)
    repo.save_script(video_id, text.model_dump_json(), text.title_options[0])
    repo.set_status(video_id, VideoStatus.FACT_CHECKED)  # nothing to fact-check: the words describe the frames
    repo.set_status(video_id, VideoStatus.RENDERING)
    ass = write_clip_ass(text, moment.end - moment.start, work / "clip.ass")
    video = render_clip(clip.path, moment, ass, work / "video.mp4", settings)
    picture = cover_frame(Shot(clip.path, 0, moment.start, moment.end, 1.0), work / "cover_frame.png")
    cover = render_cover(picture, text.cover_lines, work / "cover.png")
    meta = _metadata(text, settings)
    (work / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta, [video, cover, work / "metadata.json"]


def make_clip(clip: ClipFile, moment: Moment, settings: Settings, conn: sqlite3.Connection,
              vision: Sequence[VisionLLM]) -> ClipResult:
    """Leaves the source clip where it is: the caller decides when it may go."""
    repo = VideoRepository(conn)
    video_id = repo.create(f"clip:{clip.path.name}", clip.app_id, VideoFormat.GAMEPLAY)
    work = settings.data_dir / "work" / f"clip-{video_id}"
    try:
        work.mkdir(parents=True, exist_ok=True)
        meta, files = _build(clip, moment, work, settings, vision, repo, video_id)
        export = settings.data_dir / "exports" / str(video_id)
        export.mkdir(parents=True, exist_ok=True)
        for path in files:
            shutil.move(str(path), export / path.name)
        repo.save_output(video_id, export / "video.mp4", export / "metadata.json", _hash(export / "video.mp4", meta))
        repo.set_status(video_id, VideoStatus.AWAITING_APPROVAL)
        return ClipResult(video_id, export / "video.mp4")
    except Exception as exc:  # any failure leaves a FAILED row with the reason, never a half-made video
        log.exception("Clip %s could not be made into a Short", clip.path.name)
        repo.set_status(video_id, VideoStatus.FAILED, str(exc)[-500:] or type(exc).__name__)
        raise ClipError(str(exc).strip().splitlines()[-1] if str(exc).strip() else type(exc).__name__) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
