"""One news URL in, one rights-logged, fact-checked vertical video out."""

import logging
import random
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from PIL import UnidentifiedImageError

from shorts.captions import chunk_captions, write_ass
from shorts.config import Settings
from shorts.llm.base import LLMProvider
from shorts.media.cards import render_fact_card, render_hook_card, render_still
from shorts.media.ffmpeg import FFmpegError
from shorts.media.render import render_video
from shorts.media.shots import Shot, detect_shots
from shorts.media.timeline import plan_timeline
from shorts.metadata import build_metadata, content_hash, write_metadata
from shorts.models import Asset, AssetKind, RightsBasis, VideoFormat, VideoStatus
from shorts.music import pick_music
from shorts.net import DownloadTooLarge, UnsafeURLError
from shorts.rights import RightsError, assert_usable
from shorts.script.checks import narration_lines
from shorts.script.schema import ScriptDraft
from shorts.script.writer import write_checked_script
from shorts.sources.article import Article, fetch_article
from shorts.sources.steam import SteamError, collect_steam_assets, fetch_steam_app
from shorts.text import clean_text
from shorts.storage.repositories import AssetRepository, BlocklistRepository, VideoRepository
from shorts.voice.narration import Narration, build_narration
from shorts.voice.tts import TTSEngine

log = logging.getLogger(__name__)

# anything that goes wrong getting Steam media means "no Steam media", never "no video"
_STEAM_ERRORS = (SteamError, httpx.HTTPError, ValueError, OSError, FFmpegError, DownloadTooLarge, UnsafeURLError)


class PipelineError(Exception):
    """A video could not be made; the message is meant for the owner."""


@dataclass(frozen=True)
class PipelineDeps:
    http: httpx.Client
    llm: LLMProvider
    tts: TTSEngine


@dataclass(frozen=True)
class VideoResult:
    video_id: int
    video_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class _Job:
    video_id: int
    news_url: str
    steam_app_id: int | None
    fmt: VideoFormat
    settings: Settings
    deps: PipelineDeps
    conn: sqlite3.Connection
    work: Path
    article: Article | None = None


def make_video(
    news_url: str,
    steam_app_id: int | None,
    fmt: VideoFormat,
    settings: Settings,
    deps: PipelineDeps,
    conn: sqlite3.Connection,
    *,
    article: Article | None = None,
) -> VideoResult:
    """Make one video. `article`, when given (e.g. full text from a feed), is used instead of fetching `news_url`."""
    videos = VideoRepository(conn)
    video_id = videos.create(news_url, steam_app_id, fmt)
    work = settings.data_dir / "work" / str(video_id)
    job = _Job(video_id, news_url, steam_app_id, fmt, settings, deps, conn, work, article)
    try:
        return _produce(job)
    except KeyboardInterrupt:
        videos.set_status(video_id, VideoStatus.FAILED, "interrupted")
        raise
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        log.exception("Video %s failed", video_id)
        videos.set_status(video_id, VideoStatus.FAILED, reason)
        raise PipelineError(reason) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _produce(job: _Job) -> VideoResult:
    videos = VideoRepository(job.conn)
    s = job.settings
    article = job.article or fetch_article(job.deps.http, job.news_url, max_bytes=s.limits.max_html_bytes)
    draft = write_checked_script(article, job.fmt, job.deps.llm, s.video)
    videos.save_script(job.video_id, draft.model_dump_json(), draft.title_options[0])
    videos.set_status(job.video_id, VideoStatus.FACT_CHECKED)

    videos.set_status(job.video_id, VideoStatus.RENDERING)
    narration = _narrate(draft, job)
    assets = _gather_assets(draft, article, job)
    images = _images(draft, article, assets, job)
    shots = _shots(assets)
    items = plan_timeline(
        narration.duration, shots, images,
        slot_s=s.video.slot_s, max_shot_s=s.video.max_shot_s, max_trailer_share=s.video.max_trailer_share,
    )
    ass = write_ass(chunk_captions(narration), _credit(assets, article), job.work / "captions.ass")
    export = s.data_dir / "exports" / str(job.video_id)
    export.mkdir(parents=True, exist_ok=True)
    music = next((a.local_path for a in assets if a.kind == AssetKind.MUSIC), None)
    video_path = render_video(items, narration, ass, music, export / "video.mp4", s)

    meta = build_metadata(draft, article, assets)
    metadata_path = write_metadata(meta, export / "metadata.json")
    videos.save_output(job.video_id, video_path, metadata_path, content_hash(video_path, meta))
    videos.set_status(job.video_id, VideoStatus.AWAITING_APPROVAL)
    return VideoResult(job.video_id, video_path, metadata_path)


def _narrate(draft: ScriptDraft, job: _Job) -> Narration:
    narration = build_narration(narration_lines(draft), job.deps.tts, job.work / "narration.wav")
    low, high = job.settings.video.min_narration_s, job.settings.video.max_narration_s
    if not low <= narration.duration <= high:
        raise ValueError(f"narration is {narration.duration:.1f}s, allowed {low:g}–{high:g}s")
    return narration


def _steam_assets(job: _Job, blocked: set[str]) -> list[Asset]:
    if job.steam_app_id is None:
        return []
    try:
        app = fetch_steam_app(job.deps.http, job.steam_app_id, max_bytes=job.settings.limits.max_html_bytes)
        return collect_steam_assets(app, job.deps.http, job.work / "steam", job.settings, blocked)
    except _STEAM_ERRORS as exc:
        log.warning("Steam media unavailable for app %s, using generated visuals: %s", job.steam_app_id, exc)
        return []


def _card(path: Path) -> Asset:
    return Asset(
        id=None, kind=AssetKind.CARD, local_path=path, source_url=None, source_platform="generated",
        rightsholder="tech-shorts", rights_basis=RightsBasis.GENERATED,
        licence_terms_ref="generated by this app", music_stripped=False, fetched_at=datetime.now(UTC),
    )


def _cards(draft: ScriptDraft, article: Article, job: _Job) -> list[Asset]:
    font = job.settings.font_file
    job.work.mkdir(parents=True, exist_ok=True)
    cards = [_card(render_hook_card(narration_lines(draft)[0], job.work / "card_hook.png", font))]
    if not draft.card_facts:
        return cards
    title = clean_text(article.title or draft.title_options[0])
    cards.append(_card(render_fact_card(title, draft.card_facts, job.work / "card_facts.png", font)))
    for i, fact in enumerate(draft.card_facts):
        cards.append(_card(render_fact_card(title, [fact], job.work / f"card_fact_{i}.png", font)))
    return cards


def _gather_assets(draft: ScriptDraft, article: Article, job: _Job) -> list[Asset]:
    blocked = BlocklistRepository(job.conn).names()
    candidates = _steam_assets(job, blocked) + _cards(draft, article, job)
    music = pick_music(job.settings.music_dir, random.Random(job.video_id))
    candidates += [music] if music else []
    repo = AssetRepository(job.conn)
    usable = []
    for asset in candidates:
        try:
            assert_usable(asset, blocked)
        except RightsError as exc:
            log.warning("Not using asset: %s", exc)
            continue
        usable.append(repo.add(asset, job.video_id))
    return usable


def _images(draft: ScriptDraft, article: Article, assets: list[Asset], job: _Job) -> list[Path]:
    cards = [a.local_path for a in assets if a.kind == AssetKind.CARD]
    stills = []
    for a in assets:
        if a.kind != AssetKind.SCREENSHOT:
            continue
        try:
            stills.append(render_still(a.local_path, job.work / f"still_{a.id}.png"))
        except (OSError, UnidentifiedImageError) as exc:
            log.warning("Skipping screenshot %s that could not be read: %s", a.source_url, exc)
    return cards + stills


def _shots(assets: list[Asset]) -> list[Shot]:
    shots = [shot for a in assets if a.kind == AssetKind.TRAILER for shot in detect_shots(a.local_path, a.id)]
    return sorted(shots, key=lambda s: s.score, reverse=True)


def _credit(assets: list[Asset], article: Article) -> str:
    steam = next((a for a in assets if a.kind in (AssetKind.TRAILER, AssetKind.SCREENSHOT)), None)
    if steam:
        return f"Footage: {steam.rightsholder} / Steam"
    return f"Source: {article.domain}"
