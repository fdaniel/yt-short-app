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


def sine_wav(path: Path, seconds: float, sample_rate: int = 24000) -> Path:
    import numpy as np
    import soundfile as sf

    t = np.arange(int(seconds * sample_rate)) / sample_rate
    sf.write(path, (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sample_rate)
    return path


def sine_mp3(path: Path, seconds: float) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         f"sine=frequency=330:duration={seconds}", str(path)],
        check=True,
    )
    return path


def fake_narration(work: Path, seconds: float):
    from shorts.voice.narration import Narration, NarrationLine

    wav = sine_wav(work / "narration.wav", seconds)
    return Narration(audio_path=wav, duration=seconds, lines=(NarrationLine("Hello there", 0.0, seconds),))
