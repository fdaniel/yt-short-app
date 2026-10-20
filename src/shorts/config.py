"""Settings: YAML for behaviour, environment for secrets."""

import re
from collections.abc import Mapping
from typing import Literal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator


class ConfigError(Exception):
    """Configuration is missing or invalid."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LLMSettings(_Frozen):
    gemini_model: str = "gemini-flash-latest"
    # same free key, lighter model: often answers while the main one is "experiencing high demand"; null = off
    gemini_backup_model: str | None = "gemini-flash-lite-latest"
    fallback_base_url: str = "https://api.groq.com/openai/v1"
    fallback_model: str = "llama-3.3-70b-versatile"


class VoiceSettings(_Frozen):
    # Kokoro voices, taken in turn video by video: a (American) or b (British) English, f/m female/male
    voices: tuple[str, ...] = ("af_heart", "am_michael")
    speed: float = 1.0

    @model_validator(mode="before")
    @classmethod
    def _drop_single_voice_keys(cls, data: object) -> object:
        """Older configs named one voice and its language; the language now comes from each voice's name."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in ("kokoro_voice", "lang_code")}
        return data

    @field_validator("voices")
    @classmethod
    def _known_voice_names(cls, voices: tuple[str, ...]) -> tuple[str, ...]:
        if not voices:
            raise ValueError("list at least one voice")
        for voice in voices:
            if not re.fullmatch(r"[ab][fm]_[a-z]+", voice):
                raise ValueError(f"{voice!r} is not a Kokoro English voice name like af_heart or am_michael")
        return voices


class VideoSettings(_Frozen):
    min_narration_s: float = 30
    max_narration_s: float = 55
    min_words: int = 65
    max_words: int = 100
    max_shot_s: float = 4.0
    max_trailer_share: float = 0.49
    slot_s: float = 3.5
    max_output_mb: int = 50
    music_volume: float = 0.12


class LimitSettings(_Frozen):
    max_html_bytes: int = 5_000_000
    max_trailer_bytes: int = 300_000_000
    max_image_bytes: int = 10_000_000
    max_hls_seconds: int = 180
    ffmpeg_timeout_s: int = 600
    http_timeout_s: int = 20


class FeedSource(_Frozen):
    name: str
    url: str
    topic: Literal["hardware", "gaming"]


DEFAULT_FEEDS = (
    FeedSource(name="NVIDIA Newsroom", url="https://nvidianews.nvidia.com/releases.xml", topic="hardware"),
    FeedSource(name="NVIDIA Blog", url="https://blogs.nvidia.com/feed/", topic="hardware"),
    FeedSource(name="AMD Press Releases", url="https://ir.amd.com/news-events/press-releases/rss", topic="hardware"),
    FeedSource(name="Xbox Wire", url="https://news.xbox.com/en-us/feed/", topic="gaming"),
    FeedSource(name="PlayStation Blog", url="https://blog.playstation.com/feed/", topic="gaming"),
)


class ScoreWeights(_Frozen):
    freshness: float = 0.3
    interest: float = 0.5
    footage: float = 0.1
    coverage: float = 0.1


class DiscoverySettings(_Frozen):
    feeds: tuple[FeedSource, ...] = DEFAULT_FEEDS
    max_age_h: float = 48
    max_videos_per_day: int = 3
    videos_per_run: int = 1
    max_attempts_per_run: int = 2
    triage_batch: int = 8
    min_score: float = 0.55
    min_free_gb: float = 10
    history_days: int = 14
    duplicate_similarity: float = 0.5
    weights: ScoreWeights = ScoreWeights()
    exclude_keywords: tuple[str, ...] = (
        "financial results", "quarter", "dividend", "board of directors", "appoints", "conference call",
        "podcast", "share of the week", "for southeast asia", "earnings",
    )


class YouTubeSettings(_Frozen):
    privacy_status: Literal["public", "unlisted", "private"] = "public"
    category_id: str = "28"  # Science & Technology
    synthetic_media: bool = False  # YouTube's "altered or synthetic content" label


class Settings(_Frozen):
    data_dir: Path = Path("~/tech-shorts-data")
    music_dir: Path = Path("assets/music")
    font_file: Path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    gemini_api_key: str
    fallback_api_key: str | None = None
    # optional: stock footage for stories with no game trailer (Pixabay is tried first)
    pixabay_api_key: str | None = None
    pexels_api_key: str | None = None
    llm: LLMSettings = LLMSettings()
    voice: VoiceSettings = VoiceSettings()
    video: VideoSettings = VideoSettings()
    limits: LimitSettings = LimitSettings()
    discovery: DiscoverySettings = DiscoverySettings()
    youtube: YouTubeSettings = YouTubeSettings()

    @field_validator("data_dir", "music_dir", "font_file")
    @classmethod
    def _expand_home(cls, value: Path) -> Path:
        return value.expanduser()


def load_settings(config_path: Path, env: Mapping[str, str]) -> Settings:
    """Load settings from a YAML file plus secrets from `env`. Fails fast."""
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a YAML mapping")

    gemini_key = (env.get("GEMINI_API_KEY") or "").strip()
    if not gemini_key:
        raise ConfigError("GEMINI_API_KEY is not set (put it in .env)")
    fallback_key = (env.get("FALLBACK_LLM_API_KEY") or "").strip() or None
    pixabay_key = (env.get("PIXABAY_API_KEY") or "").strip() or None
    pexels_key = (env.get("PEXELS_API_KEY") or "").strip() or None

    secrets = {"gemini_api_key": gemini_key, "fallback_api_key": fallback_key, "pixabay_api_key": pixabay_key,
               "pexels_api_key": pexels_key}
    try:
        settings = Settings(**{**raw, **secrets})
    except ValidationError as exc:
        raise ConfigError(f"Invalid config in {config_path}: {exc}") from exc

    if settings.music_dir.is_absolute():
        return settings
    return settings.model_copy(update={"music_dir": config_path.parent / settings.music_dir})
