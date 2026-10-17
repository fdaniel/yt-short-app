"""The rights gate: every asset passes here before it can appear in a video."""

from shorts.models import Asset, AssetKind, RightsBasis


class RightsError(Exception):
    """The asset must not be used."""


def assert_usable(asset: Asset, blocked_publishers: set[str]) -> None:
    """Raise RightsError if `asset` may not be used in a video."""
    if asset.rights_basis == RightsBasis.UNKNOWN:
        raise RightsError(f"{asset.local_path.name}: rights basis is unknown")
    if asset.kind != AssetKind.TRAILER:
        return
    if asset.rightsholder.strip().lower() in blocked_publishers:
        raise RightsError(f"{asset.local_path.name}: trailers from {asset.rightsholder} are blocked")
    if not asset.music_stripped:
        raise RightsError(f"{asset.local_path.name}: trailer still has its original audio")
