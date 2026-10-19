"""Assemble timeline segments, narration, music and captions into the final MP4."""

import shutil
from pathlib import Path

from shorts.config import Settings
from shorts.media.crop import CropMode, CropPlan, choose_crop
from shorts.media.ffmpeg import run_ffmpeg
from shorts.media.timeline import TimelineItem
from shorts.voice.narration import Narration

_SEGMENT_ENCODE = ["-r", "30", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an"]
_COVER = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
_FPS = 30
_STILL_ZOOM = 0.08  # a still zooms in this much over its slot, so nothing on screen is frozen


class RenderError(Exception):
    """The video could not be rendered within the limits."""


def _shot_filter(plan: CropPlan) -> str:
    bars = f"crop=iw:{plan.height}:0:{plan.top}," if plan.height else ""
    if plan.mode == CropMode.SMART:
        return f"{bars}crop=w=ih*9/16:h=ih:x={plan.x}:y=0,scale=1080:1920,setsar=1,fps=30"
    return f"{bars}{_COVER},setsar=1,fps=30"


def _still_filter(duration: float) -> str:
    # zoompan on a 2x picture: zooming at 1080x1920 visibly jitters
    frames = max(1, round(duration * _FPS))
    return (
        f"{_COVER},scale=2160:3840,zoompan=z='1+{_STILL_ZOOM}*on/{frames}':x='iw/2-iw/zoom/2':"
        f"y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps={_FPS},setsar=1"
    )


def _render_segment(item: TimelineItem, out: Path, timeout_s: int) -> None:
    length = f"{item.duration:.3f}"
    if item.kind == "shot":
        shot = item.shot
        plan = choose_crop(shot.source, shot.start, shot.end)
        inputs = ["-ss", f"{shot.start:.3f}", "-t", length, "-i", str(shot.source)]
        background = _shot_filter(plan)
    else:
        inputs = ["-loop", "1", "-framerate", str(_FPS), "-t", length, "-i", str(item.image)]
        background = _still_filter(item.duration)
    graph = f"[0:v]{background}[v]"
    if item.overlay is not None:
        inputs += ["-loop", "1", "-framerate", str(_FPS), "-t", length, "-i", str(item.overlay)]
        graph = f"[0:v]{background}[bg];[1:v]format=rgba[card];[bg][card]overlay=0:0:shortest=1[v]"
    run_ffmpeg([*inputs, "-filter_complex", graph, "-map", "[v]", *_SEGMENT_ENCODE, str(out)], timeout_s=timeout_s)


def _concat(items: list[TimelineItem], segments: Path, timeout_s: int) -> Path:
    names = []
    for index, item in enumerate(items):
        name = f"seg_{index:03d}.mp4"
        _render_segment(item, segments / name, timeout_s)
        names.append(name)
    listing = segments / "list.txt"
    listing.write_text("".join(f"file '{name}'\n" for name in names))
    visual = segments / "visual.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(visual)], timeout_s=timeout_s)
    return visual


def _final_args(visual: Path, narration: Narration, ass_path: Path, music: Path | None, settings: Settings) -> list[str]:
    duration = narration.duration
    subtitles = f"[0:v]subtitles={ass_path.name}:fontsdir={settings.font_file.parent}[v]"
    inputs = ["-i", str(visual), "-i", str(narration.audio_path)]
    if music is None:
        graph, audio_map = subtitles, "1:a"
    else:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        fade_at = max(0.0, duration - 1)
        graph = (
            f"{subtitles};[2:a]volume={settings.video.music_volume},afade=t=out:st={fade_at:.2f}:d=1[m];"
            "[1:a][m]amix=inputs=2:duration=first:normalize=0[a]"
        )
        audio_map = "[a]"
    return [
        *inputs, "-filter_complex", graph, "-map", "[v]", "-map", audio_map, "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-maxrate", "6M", "-bufsize", "12M",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart",
    ]


def _shrink_if_needed(out: Path, settings: Settings) -> None:
    limit = settings.video.max_output_mb * 1024 * 1024
    if out.stat().st_size <= limit:
        return
    smaller = out.with_name(out.stem + "_small.mp4")
    run_ffmpeg(
        ["-i", str(out), "-c:v", "libx264", "-preset", "medium", "-crf", "28", "-maxrate", "4M",
         "-bufsize", "8M", "-c:a", "copy", "-movflags", "+faststart", str(smaller)],
        timeout_s=settings.limits.ffmpeg_timeout_s,
    )
    smaller.replace(out)
    if out.stat().st_size > limit:
        raise RenderError(f"video is still larger than {settings.video.max_output_mb} MB after re-encoding")


def render_video(
    items: list[TimelineItem], narration: Narration, ass_path: Path, music: Path | None, out: Path, settings: Settings
) -> Path:
    timeout_s = settings.limits.ffmpeg_timeout_s
    segments = out.parent / "segments"
    segments.mkdir(parents=True, exist_ok=True)
    try:
        visual = _concat(items, segments, timeout_s)
        args = _final_args(visual, narration, ass_path, music, settings)
        # cwd = the captions folder, so the subtitles filter sees a bare filename (no path escaping).
        run_ffmpeg([*args, str(out)], timeout_s=timeout_s, cwd=ass_path.parent)
        _shrink_if_needed(out, settings)
    finally:
        shutil.rmtree(segments, ignore_errors=True)
    return out
