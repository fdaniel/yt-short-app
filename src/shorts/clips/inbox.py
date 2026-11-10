"""Clips waiting in the inbox folder that Syncthing fills from the gaming PC."""

import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

# pick: the owner pressed Save Replay; auto: the recorder saved it by itself; rec: the owner started and
# stopped a recording by hand, so all of it is wanted
ClipKind = Literal["pick", "auto", "rec"]
VIDEO_SUFFIXES = frozenset({".mp4", ".mkv", ".mov"})
# <steam app id>_<Game-Name>_<yyyy-mm-dd_HH-MM-SS>[-<n>][_auto|_pick], as the Loadout Recorder names them
_NAME = re.compile(r"^(\d+)_([A-Za-z0-9-]+)_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:-\d+)?(?:_(auto|pick|rec))?$")


@dataclass(frozen=True)
class ClipFile:
    path: Path
    app_id: int | None
    game: str  # "" when the name does not say
    kind: ClipKind
    saved_at: datetime | None  # the gaming PC's local time, from the name


def parse_clip(path: Path) -> ClipFile | None:
    """What the file name says about a clip; None for anything that is not a finished video."""
    if (path.suffix.lower() not in VIDEO_SUFFIXES or path.name.startswith(("~syncthing~", ".syncthing.", "."))
            or ".sync-conflict-" in path.name):  # Syncthing's leftovers and conflict copies are not new clips
        return None
    match = _NAME.match(path.stem)
    if not match:
        return ClipFile(path, None, "", "pick", None)  # dropped in by hand: treat it as the owner's choice
    app_id, game, stamp, kind = match.groups()
    return ClipFile(path, int(app_id), game.replace("-", " "), kind or "pick",
                    datetime.strptime(stamp, "%Y-%m-%d_%H-%M-%S"))


def ready_clips(inbox: Path, settle_s: int, now: float | None = None) -> list[ClipFile]:
    """Clips in the inbox (not its subfolders) unchanged for `settle_s`, oldest first."""
    if not inbox.is_dir():
        return []
    moment = time.time() if now is None else now
    found = []
    for path in inbox.iterdir():
        clip = parse_clip(path)
        try:
            info = path.stat()
        except FileNotFoundError:  # Syncthing or the owner removed it meanwhile
            continue
        if clip and path.is_file() and moment - info.st_mtime >= settle_s:
            found.append((info.st_mtime, path.name, clip))
    return [clip for _, _, clip in sorted(found, key=lambda f: (f[0], f[1]))]
