import subprocess
from pathlib import Path


def lavfi_video(tmp_path: Path, source: str, *, audio: bool = False, name: str = "v.mp4") -> Path:
    """Render a synthetic test clip with FFmpeg's lavfi sources."""
    out = tmp_path / name
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", source]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440", "-shortest"]
    args += ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(out)]
    subprocess.run(args, check=True)
    return out
