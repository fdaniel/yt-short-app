import subprocess
from pathlib import Path

import pytest


def lavfi_video(tmp_path: Path, source: str, *, audio: bool = False, name: str = "v.mp4") -> Path:
    """Render a synthetic test clip with FFmpeg's lavfi sources."""
    out = tmp_path / name
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", source]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440", "-shortest"]
    args += ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(out)]
    subprocess.run(args, check=True)
    return out


@pytest.fixture
def synthetic_video(tmp_path) -> Path:
    return lavfi_video(tmp_path, "testsrc2=size=1920x1080:rate=30:duration=6", audio=True)
