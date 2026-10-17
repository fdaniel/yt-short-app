"""Background music: only tracks with a recorded licence are ever used."""

import logging
import random
from datetime import UTC, datetime
from pathlib import Path

import yaml

from shorts.models import Asset, AssetKind, RightsBasis

log = logging.getLogger(__name__)
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def _licences(music_dir: Path) -> dict:
    path = music_dir / "licenses.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data if isinstance(data, dict) else {}


def licensed_tracks(music_dir: Path) -> list[tuple[Path, dict]]:
    """Audio files in `music_dir` that have a complete entry in licenses.yaml."""
    if not music_dir.is_dir():
        return []
    licences = _licences(music_dir)
    tracks = []
    for path in sorted(music_dir.iterdir()):
        if path.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        entry = licences.get(path.name)
        if not isinstance(entry, dict) or not entry.get("source") or not entry.get("licence"):
            log.warning("Ignoring %s: no licence entry in licenses.yaml", path.name)
            continue
        tracks.append((path, entry))
    return tracks


def pick_music(music_dir: Path, rng: random.Random) -> Asset | None:
    tracks = licensed_tracks(music_dir)
    if not tracks:
        return None
    path, entry = rng.choice(tracks)
    return Asset(
        id=None,
        kind=AssetKind.MUSIC,
        local_path=path,
        source_url=None,
        source_platform="music-library",
        rightsholder=str(entry["source"]),
        rights_basis=RightsBasis.LICENSED,
        licence_terms_ref=str(entry["licence"]),
        music_stripped=False,
        fetched_at=datetime.now(UTC),
        notes=f"{path.name} — {entry['source']}",
    )
