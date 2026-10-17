import pytest

from shorts.models import AssetKind, RightsBasis
from shorts.rights import RightsError, assert_usable


def test_unknown_rights_never_usable(make_asset):
    with pytest.raises(RightsError, match="unknown"):
        assert_usable(make_asset(rights_basis=RightsBasis.UNKNOWN), set())


def test_trailer_from_blocked_publisher_rejected(make_asset):
    a = make_asset(kind=AssetKind.TRAILER, rightsholder="Ubisoft")
    with pytest.raises(RightsError, match="blocked"):
        assert_usable(a, {"ubisoft"})


def test_screenshot_from_blocked_publisher_allowed(make_asset):
    assert_usable(make_asset(kind=AssetKind.SCREENSHOT, rightsholder="Ubisoft"), {"ubisoft"})


def test_trailer_with_audio_rejected(make_asset):
    with pytest.raises(RightsError, match="audio"):
        assert_usable(make_asset(kind=AssetKind.TRAILER, music_stripped=False), set())


def test_generated_card_usable(make_asset):
    assert_usable(make_asset(kind=AssetKind.CARD, rights_basis=RightsBasis.GENERATED), set())
