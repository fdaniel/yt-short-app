"""One news URL in, one rights-logged, fact-checked vertical video out."""

import logging
import random
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import chain, zip_longest
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
from shorts.media.timeline import Card, plan_timeline, usable_trailer_shots
from shorts.metadata import build_metadata, content_hash, write_metadata
from shorts.models import Asset, AssetKind, RightsBasis, VideoFormat, VideoStatus
from shorts.music import pick_music
from shorts.net import DownloadTooLarge, UnsafeURLError, redact
from shorts.rights import RightsError, assert_usable
from shorts.script.checks import narration_lines
from shorts.script.schema import ScriptDraft
from shorts.script.writer import write_checked_script
from shorts.sources import pexels, pixabay
from shorts.sources.article import Article, fetch_article
from shorts.sources.named_games import named_game_assets, named_in
from shorts.sources.press import collect_press_images
from shorts.sources.press_video import collect_press_clips
from shorts.sources.stock import MAX_CLIPS, StockSource, collect_stock_assets
from shorts.sources.steam import SteamError, collect_steam_assets, fetch_steam_app
from shorts.text import clean_text
from shorts.storage.repositories import AssetRepository, BlocklistRepository, VideoRepository
from shorts.voice.narration import Narration, build_narration, voice_for
from shorts.voice.tts import TTSEngine

log = logging.getLogger(__name__)

# anything that goes wrong getting Steam media means "no Steam media", never "no video"
_STEAM_ERRORS = (SteamError, httpx.HTTPError, ValueError, OSError, FFmpegError, DownloadTooLarge, UnsafeURLError)
_STOCK_ERRORS = (httpx.HTTPError, ValueError, OSError, FFmpegError, DownloadTooLarge, UnsafeURLError)
# when the script suggests no search terms of its own
DEFAULT_FOOTAGE_QUERIES = ("computer hardware", "gaming setup", "circuit board closeup")
STOCK_TAIL_S = 0.3
MIN_SCENE_S = 0.4
MIN_PRESS_IMAGES = 4  # fewer official photos and clips than this: licensed stock video fills in
_MOVING = (AssetKind.STOCK_VIDEO, AssetKind.PRESS_VIDEO)


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
class _Visuals:
    assets: list[Asset]  # every asset used, already in the rights log
    trailer: list[Shot]  # only shots the timeline can use
    stock: list[Shot]
    stills: list[Path]


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
    visuals = _gather_visuals(draft, article, job, narration.duration)
    assets = visuals.assets
    items = plan_timeline(
        narration.duration, trailer=visuals.trailer, stock=visuals.stock, stills=visuals.stills,
        cards=_card_pairs(assets),
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
    voice = voice_for(job.video_id, job.settings.voice.voices)
    narration = build_narration(narration_lines(draft), job.deps.tts, job.work / "narration.wav", voice)
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


def _stock_sources(settings: Settings) -> list[tuple[StockSource, str]]:
    keyed = [(pixabay.SOURCE, settings.pixabay_api_key), (pexels.SOURCE, settings.pexels_api_key)]
    return [(source, key) for source, key in keyed if key]


def _stock_assets(draft: ScriptDraft, job: _Job) -> list[Asset]:
    """Licensed stock video from each site with a key, in turn, until there are enough clips."""
    queries = draft.footage_queries or list(DEFAULT_FOOTAGE_QUERIES)
    used = frozenset(AssetRepository(job.conn).used_source_urls(AssetKind.STOCK_VIDEO))
    assets: list[Asset] = []
    for source, key in _stock_sources(job.settings):
        if len(assets) >= MAX_CLIPS:
            break
        try:
            assets += collect_stock_assets(source, job.deps.http, key, queries, job.work / "stock", job.settings,
                                           wanted=MAX_CLIPS - len(assets), used=used)
        except _STOCK_ERRORS as exc:
            log.warning("%s stock footage unavailable: %s", source.name, redact(str(exc)))
    return assets


def _press_assets(article: Article, job: _Job) -> list[Asset]:
    """The official article's own photos and video clips."""
    if job.steam_app_id is not None or not article.html:
        return []
    work = job.work / "press"
    try:
        images = collect_press_images(job.deps.http, article.url, article.html, work, job.settings)
    except (ValueError, OSError) as exc:
        log.warning("Newsroom photos unavailable for %s: %s", article.url, exc)
        images = []
    return images + collect_press_clips(job.deps.http, article.url, article.html, work, job.settings)


def _named_game_assets(draft: ScriptDraft, article: Article, job: _Job, blocked: set[str]) -> list[Asset]:
    """Footage of the game a tech story is about: one the hook names ("FSR 4.1 now in Cyberpunk 2077").
    A game only listed later gets none: its footage would play while the narration talks about another.
    Game news already has its own game's footage."""
    hook = narration_lines(draft)[0]
    names = [name for name in draft.games_named if named_in(name, hook)]
    if job.steam_app_id is not None or not names:
        return []
    return named_game_assets(names, f"{article.title} {article.text}", job.deps.http,
                             job.work / "games", job.settings, blocked)


def _no_footage_reason(settings: Settings, game: bool) -> str:
    if game:
        return "no footage for this game: no usable trailer scenes or screenshots (game news never uses stock video)"
    sites = " or ".join(source.name for source, _ in _stock_sources(settings))
    if sites:
        return f"no footage for this story: no photos in the official article, and {sites} had no usable stock video"
    return "no footage for this story: no photos in the official article (add PIXABAY_API_KEY to .env for stock video)"


def _overlay_path(card: Path) -> Path:
    return card.with_name(f"{card.stem}_overlay{card.suffix}")


def _card(path: Path) -> Asset:
    return Asset(
        id=None, kind=AssetKind.CARD, local_path=path, source_url=None, source_platform="generated",
        rightsholder="tech-shorts", rights_basis=RightsBasis.GENERATED,
        licence_terms_ref="generated by this app", music_stripped=False, fetched_at=datetime.now(UTC),
    )


def _cards(draft: ScriptDraft, article: Article, job: _Job) -> list[Asset]:
    font = job.settings.font_file
    job.work.mkdir(parents=True, exist_ok=True)
    hook = narration_lines(draft)[0]
    paths = [render_hook_card(hook, job.work / "card_hook.png", font)]
    render_hook_card(hook, _overlay_path(paths[0]), font, overlay=True)
    if draft.card_facts:
        title = clean_text(article.title or draft.title_options[0])
        # the all-facts table is full screen only: as a panel it would cover most of the footage
        paths.append(render_fact_card(title, draft.card_facts, job.work / "card_facts.png", font))
        for i, fact in enumerate(draft.card_facts):
            paths.append(render_fact_card(title, [fact], job.work / f"card_fact_{i}.png", font))
            render_fact_card(title, [fact], _overlay_path(paths[-1]), font, overlay=True)
    return [_card(path) for path in paths]  # an overlay is the same generated card, logged once


def _gather_visuals(draft: ScriptDraft, article: Article, job: _Job, duration: float) -> _Visuals:
    """Game news: only the game's own trailer and screenshots. Other news: the official article's own
    photos and clips, footage of the games it names, and licensed stock video only when that is too little."""
    blocked = BlocklistRepository(job.conn).names()
    video = job.settings.video
    steam = _log_usable(_steam_assets(job, blocked) + _named_game_assets(draft, article, job, blocked), blocked, job)
    trailer = usable_trailer_shots(_trailer_shots(steam), duration, slot_s=video.slot_s, max_shot_s=video.max_shot_s)
    press = _log_usable(_press_assets(article, job), blocked, job)
    stills = _stills(steam + press, job)
    # game news shows only the game's own footage: generic stock put a motherboard in a cat game's video
    wants_stock = job.steam_app_id is None and not steam and len(press) < MIN_PRESS_IMAGES
    stock_assets = _log_usable(_stock_assets(draft, job), blocked, job) if wants_stock else []
    # the company's own clips first, so they come before any stock clip
    stock = _stock_shots([a for a in press if a.kind == AssetKind.PRESS_VIDEO] + stock_assets, video.slot_s)
    if not (trailer or stock or stills):
        raise ValueError(_no_footage_reason(job.settings, job.steam_app_id is not None))
    music = pick_music(job.settings.music_dir, random.Random(job.video_id))
    rest = _log_usable(_cards(draft, article, job) + ([music] if music else []), blocked, job)
    return _Visuals(steam + press + stock_assets + rest, trailer, stock, stills)


def _log_usable(candidates: list[Asset], blocked: set[str], job: _Job) -> list[Asset]:
    """The rights gate: assets that pass are written to the rights log, the rest are dropped."""
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


def _card_pairs(assets: list[Asset]) -> list[Card]:
    cards = [a.local_path for a in assets if a.kind == AssetKind.CARD]
    return [Card(path, _overlay_path(path) if _overlay_path(path).is_file() else None) for path in cards]


def _stills(assets: list[Asset], job: _Job) -> list[Path]:
    stills = []
    for a in assets:
        if a.kind not in (AssetKind.SCREENSHOT, AssetKind.PRESS_IMAGE):
            continue
        try:
            stills.append(render_still(a.local_path, job.work / f"still_{a.id}.png"))
        except (OSError, UnidentifiedImageError) as exc:
            log.warning("Skipping image %s that could not be read: %s", a.source_url, exc)
    return stills


def _trailer_shots(assets: list[Asset]) -> list[Shot]:
    # short scenes too: back to back they make continuous pieces of a fast-cut trailer
    shots = [shot for a in assets if a.kind == AssetKind.TRAILER
             for shot in detect_shots(a.local_path, a.id, min_len_s=MIN_SCENE_S)]
    return sorted(shots, key=lambda s: s.score, reverse=True)


def _pieces(shot: Shot, length: float) -> list[Shot]:
    count = int((shot.end - shot.start) // length)
    return [Shot(shot.source, shot.asset_id, shot.start + k * length, shot.start + (k + 1) * length, shot.score)
            for k in range(count)]


def _clip_pieces(asset: Asset, length: float) -> list[Shot]:
    try:
        # a small tail margin: a clip's video often ends a few frames before its container does
        shots = detect_shots(asset.local_path, asset.id, skip_head_s=0, skip_tail_s=STOCK_TAIL_S)
    except (FFmpegError, OSError, ValueError) as exc:
        log.warning("Skipping stock clip %s that could not be read: %s", asset.source_url, exc)
        return []
    return [piece for shot in shots for piece in _pieces(shot, length)]


def _stock_shots(assets: list[Asset], length: float) -> list[Shot]:
    """Every clip cut into slot-sized pieces, taken in turn from each clip so the same one never runs twice."""
    per_clip = [_clip_pieces(a, length) for a in assets if a.kind in _MOVING]
    return [piece for piece in chain.from_iterable(zip_longest(*per_clip)) if piece is not None]


def _credit(assets: list[Asset], article: Article) -> str:
    official = (AssetKind.PRESS_IMAGE, AssetKind.PRESS_VIDEO)
    press = list(dict.fromkeys(a.rightsholder for a in assets if a.kind in official))
    steam = dict.fromkeys(a.rightsholder for a in assets if a.kind in (AssetKind.TRAILER, AssetKind.SCREENSHOT))
    owners = press + [f"{holder} / Steam" for holder in steam]
    owners += list(dict.fromkeys(a.source_platform.capitalize() for a in assets if a.kind == AssetKind.STOCK_VIDEO))
    return f"Footage: {', '.join(owners)}" if owners else f"Source: {article.domain}"
