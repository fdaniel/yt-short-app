"""A gameplay clip as a vertical Short: the whole picture in the middle over a blurred copy of itself,
the hook above it, short captions under it, and the game's own sound."""

from pathlib import Path

from shorts.captions import sanitize_caption_text
from shorts.clips.moments import Moment
from shorts.clips.text import ClipText
from shorts.config import Settings
from shorts.media.ffmpeg import probe_video, run_ffmpeg
from shorts.media.render import BRAND_FONTS, shrink_if_needed

WIDTH, HEIGHT = 1080, 1920
GAME_HEIGHT = 810  # the 4:3 middle of a 16:9 picture, scaled to the full width
GAME_TOP = (HEIGHT - GAME_HEIGHT) // 2
LINES_FROM_S = 1.5  # the first caption comes in once the hook has been read
FADE_S = 0.8
FRAME_WIDTH = 768  # frames for the text writer: enough to read on-screen names, small to send

_ASS = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,Anton,104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,8,0,8,70,70,210,1
Style: Line,Anton,92,&H0000A5FF,&H0000A5FF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,7,0,8,70,70,{GAME_TOP + GAME_HEIGHT + 40},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _time(seconds: float) -> str:
    centis = int(round(seconds * 100))
    hours, rest = divmod(centis, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _event(style: str, start: float, end: float, text: str) -> str:
    return f"Dialogue: 0,{_time(start)},{_time(end)},{style},,0,0,0,,{sanitize_caption_text(text).upper()}"


def write_clip_ass(text: ClipText, duration: float, out: Path) -> Path:
    events = [_event("Hook", 0.0, duration, text.hook)]
    if text.lines:
        start = min(LINES_FROM_S, duration / 2)
        step = (duration - start) / len(text.lines)
        events += [_event("Line", start + i * step, start + (i + 1) * step, line) for i, line in enumerate(text.lines)]
    out.write_text(_ASS + "\n".join(events) + "\n", encoding="utf-8")
    return out


def _picture(landscape: bool, ass_name: str) -> str:
    subtitles = f"subtitles={ass_name}:fontsdir={BRAND_FONTS}"
    if not landscape:
        return f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps=30,setsar=1,{subtitles}[v]"
    return (f"[0:v]split=2[a][b];"
            f"[a]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
            f"boxblur=24:2,eq=brightness=-0.15[bg];"
            f"[b]crop='min(iw,ih*4/3)':ih,scale={WIDTH}:{GAME_HEIGHT}[game];"
            f"[bg][game]overlay=0:{GAME_TOP},fps=30,setsar=1,{subtitles}[v]")


def render_clip(source: Path, moment: Moment, ass: Path, out: Path, settings: Settings) -> Path:
    info = probe_video(source)
    length = moment.end - moment.start
    inputs = ["-ss", f"{moment.start:.3f}", "-t", f"{length:.3f}", "-i", str(source)]
    if info.has_audio:
        sound = (f"[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=in:d=0.2,"
                 f"afade=t=out:st={max(0.0, length - FADE_S):.3f}:d={FADE_S}[a]")
    else:  # YouTube wants a sound track; silence keeps the file valid
        inputs += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        sound = "[1:a]anull[a]"
    graph = f"{_picture(info.width > info.height, ass.name)};{sound}"
    run_ffmpeg([*inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
                "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
                str(out)], timeout_s=settings.limits.ffmpeg_timeout_s, cwd=ass.parent)
    shrink_if_needed(out, settings, output_limit_mb(settings))
    return out


def output_limit_mb(settings: Settings) -> int:
    return settings.clips.max_output_mb


def grab_frames(source: Path, moment: Moment, work: Path, count: int = 3) -> list[Path]:
    """Evenly spread frames from the moment, as JPEGs for the text writer."""
    step = (moment.end - moment.start) / count
    frames = []
    for index in range(count):
        out = work / f"frame_{index}.jpg"
        at = moment.start + (index + 0.5) * step
        run_ffmpeg(["-ss", f"{at:.3f}", "-i", str(source), "-frames:v", "1", "-vf", f"scale={FRAME_WIDTH}:-2",
                    "-q:v", "4", str(out)], timeout_s=120)
        frames.append(out)
    return frames
