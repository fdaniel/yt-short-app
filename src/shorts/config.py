"""Settings: YAML for behaviour, environment for secrets."""

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


class ConfigError(Exception):
    """Configuration is missing or invalid."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LLMSettings(_Frozen):
    gemini_model: str = "gemini-2.5-flash"
    fallback_base_url: str = "https://api.groq.com/openai/v1"
    fallback_model: str = "llama-3.3-70b-versatile"


class VoiceSettings(_Frozen):
    kokoro_voice: str = "af_heart"
    lang_code: str = "a"
    speed: float = 1.0


class VideoSettings(_Frozen):
    min_narration_s: float = 30
    max_narration_s: float = 55
    min_words: int = 75
    max_words: int = 140
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


class Settings(_Frozen):
    data_dir: Path = Path("~/tech-shorts-data")
    music_dir: Path = Path("assets/music")
    font_file: Path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    gemini_api_key: str
    fallback_api_key: str | None = None
    llm: LLMSettings = LLMSettings()
    voice: VoiceSettings = VoiceSettings()
    video: VideoSettings = VideoSettings()
    limits: LimitSettings = LimitSettings()

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

    secrets = {"gemini_api_key": gemini_key, "fallback_api_key": fallback_key}
    try:
        settings = Settings(**{**raw, **secrets})
    except ValidationError as exc:
        raise ConfigError(f"Invalid config in {config_path}: {exc}") from exc

    if settings.music_dir.is_absolute():
        return settings
    return settings.model_copy(update={"music_dir": config_path.parent / settings.music_dir})
