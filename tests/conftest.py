from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shorts.models import Asset, AssetKind, RightsBasis
from shorts.storage.db import connect


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def make_asset():
    base = Asset(
        id=None,
        kind=AssetKind.SCREENSHOT,
        local_path=Path("/tmp/a.jpg"),
        source_url="https://cdn.example.com/a.jpg",
        source_platform="steam",
        rightsholder="Some Publisher",
        rights_basis=RightsBasis.STORE_PROMO,
        licence_terms_ref="steam-store-promo",
        music_stripped=True,
        fetched_at=datetime(2026, 10, 17, tzinfo=UTC),
    )

    def _make(**overrides):
        return replace(base, **overrides)

    return _make


@pytest.fixture
def synthetic_video(tmp_path) -> Path:
    from tests.helpers import lavfi_video

    return lavfi_video(tmp_path, "testsrc2=size=1920x1080:rate=30:duration=6", audio=True)


@pytest.fixture
def settings(tmp_path):
    from shorts.config import load_settings

    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"data_dir: {tmp_path / 'data'}\nmusic_dir: {tmp_path / 'music'}\n")
    return load_settings(cfg, {"GEMINI_API_KEY": "test-key"})


@pytest.fixture
def font_file() -> Path:
    return Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
