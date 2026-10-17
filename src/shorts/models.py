"""Types shared across pipeline stages."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class RightsBasis(StrEnum):
    PRESS_KIT_EDITORIAL = "press_kit_editorial"
    STORE_PROMO = "store_promo"
    LICENSED = "licensed"
    GENERATED = "generated"
    UNKNOWN = "unknown"


class AssetKind(StrEnum):
    TRAILER = "trailer"
    SCREENSHOT = "screenshot"
    CARD = "card"
    MUSIC = "music"


class VideoFormat(StrEnum):
    NEWS_FLASH = "news_flash"
    SPEC_BREAKDOWN = "spec_breakdown"
    VERSUS = "versus"
    WHAT_CHANGED = "what_changed"
    RELEASE_ROUNDUP = "release_roundup"


class VideoStatus(StrEnum):
    SCRIPTING = "scripting"
    FACT_CHECKED = "fact_checked"
    RENDERING = "rendering"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DISCARDED = "discarded"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(frozen=True)
class Asset:
    """A piece of media plus the rights record that allows (or forbids) its use."""

    id: int | None
    kind: AssetKind
    local_path: Path
    source_url: str | None
    source_platform: str
    rightsholder: str
    rights_basis: RightsBasis
    licence_terms_ref: str
    music_stripped: bool
    fetched_at: datetime
    notes: str = ""
