"""Running the clip desk: once from the command line, or every minute inside the dashboard."""

import logging
import sys
import threading
from logging.handlers import WatchedFileHandler

from shorts.clips.desk import ClipDesk
from shorts.config import Settings
from shorts.llm.gemini import GeminiProvider
from shorts.storage.db import connect

log = logging.getLogger("shorts.clips.loop")  # under shorts.clips, so its problems reach run.log too
_LOGGER = "shorts.clips"


def build_vision(settings: Settings) -> list[GeminiProvider]:
    """Gemini reads the clip's frames; the lighter model is the backup. The other AI services cannot see pictures."""
    models = [GeminiProvider(settings.gemini_api_key, settings.llm.gemini_model)]
    if settings.llm.gemini_backup_model:
        models.append(GeminiProvider(settings.gemini_api_key, settings.llm.gemini_backup_model, name="gemini-lite"))
    return models


def _one_look(settings: Settings, stop: threading.Event | None = None) -> list[str]:
    conn = connect(settings.data_dir / "shorts.db")
    try:
        should_stop = stop.is_set if stop else (lambda: False)
        return ClipDesk(settings, conn, build_vision(settings), should_stop=should_stop).tick()
    finally:
        conn.close()


def clips_command(settings: Settings) -> int:
    if settings.clips.inbox is None:
        print("Clips are off: in config.yaml add\nclips:\n  inbox: /mnt/c/Users/<you>/Loadout Inbox", file=sys.stderr)
        return 1
    messages = _one_look(settings)
    print("\n".join(messages) if messages else f"No new clips in {settings.clips.inbox} (or a news run is busy).")
    return 0


class ClipLoop:
    """Looks in the inbox every `every_s` seconds until stopped; a failed look is logged, never fatal."""

    def __init__(self, settings: Settings, *, stop: threading.Event | None = None, every_s: float | None = None):
        self._settings = settings
        self._stop = stop or threading.Event()
        self._every_s = settings.clips.every_s if every_s is None else every_s

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                _one_look(self._settings, self._stop)
            except Exception:  # the dashboard must keep serving whatever a clip does
                log.exception("Looking at the clip inbox failed")
            self._stop.wait(self._every_s)

    def stop(self) -> None:
        self._stop.set()


def _log_clips(settings: Settings) -> None:
    """Clip news goes to run.log too, where the dashboard footer shows it."""
    logger = logging.getLogger(_LOGGER)
    if any(isinstance(h, WatchedFileHandler) for h in logger.handlers):
        return
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    handler = WatchedFileHandler(settings.data_dir / "run.log", encoding="utf-8")  # reopens after a run rotates it
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def start_clip_loop(settings: Settings) -> ClipLoop | None:
    if settings.clips.inbox is None:
        return None
    _log_clips(settings)
    loop = ClipLoop(settings)
    threading.Thread(target=loop.run, name="clip-desk", daemon=True).start()
    if settings.clips.inbox.is_dir():
        log.info("Watching %s for gameplay clips", settings.clips.inbox)
    else:
        log.warning("The clip inbox %s does not exist yet: set up Syncthing (docs/first-look-recorder.md)",
                    settings.clips.inbox)
    return loop
