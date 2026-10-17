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
