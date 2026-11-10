import os
import subprocess
from pathlib import Path

from shorts.clips.text import ClipText

PICK = "3321460_Crimson-Desert_2026-11-10_21-05-33_pick.mp4"


def gameplay(folder: Path, name: str = PICK, seconds: int = 8, size: str = "1280x720") -> Path:
    """A small landscape clip with sound, like an OBS replay."""
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / name
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-shortest", str(out)],
                   check=True)
    return out


def settle(path: Path, seconds_ago: int = 300) -> Path:
    old = path.stat().st_mtime - seconds_ago
    os.utime(path, (old, old))
    return path


def clip_text(**overrides) -> ClipText:
    values = dict(hook="Boss down in one combo", lines=["Dodge first", "Then the heavy hit"],
                  title_options=["Crimson Desert: one combo boss kill", "This combo wrecks bosses",
                                 "Crimson Desert boss in seconds"],
                  description="A clean boss kill in Crimson Desert.", hashtags=["#CrimsonDesert", "#gaming", "#shorts"],
                  cover_lines=["ONE", "COMBO"])
    return ClipText(**{**values, **overrides})


class FakeVision:
    name = "fake-vision"

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def generate_json_with_images(self, prompt, images, schema):
        self.calls.append((prompt, images))
        if self.error:
            raise self.error
        return self.result
