import subprocess

import pytest

from shorts.media.shots import detect_shots


@pytest.fixture
def three_scene_video(tmp_path):
    out = tmp_path / "three.mp4"
    graph = (
        "testsrc2=size=1920x1080:rate=30:duration=4[a];"
        "color=c=blue:size=1920x1080:rate=30:duration=4[b];"
        "mandelbrot=size=640x360:rate=30,scale=1920:1080,trim=duration=4,setpts=PTS-STARTPTS[c];"
        "[a][b][c]concat=n=3:v=1:a=0,format=yuv420p[v]"
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-filter_complex", graph,
         "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", str(out)],
        check=True,
    )
    return out


def test_finds_cuts_and_respects_min_len(three_scene_video):
    shots = detect_shots(three_scene_video, 7, skip_head_s=0, skip_tail_s=0)
    assert len(shots) >= 3
    assert all(s.end - s.start >= 1.5 and s.asset_id == 7 for s in shots)
    assert all(s.source == three_scene_video for s in shots)


def test_sorted_by_score_and_static_lowest(three_scene_video):
    shots = detect_shots(three_scene_video, 7, skip_head_s=0, skip_tail_s=0)
    assert [s.score for s in shots] == sorted((s.score for s in shots), reverse=True)
    static = shots[-1]
    assert 4.0 - 0.3 <= static.start <= 4.0 + 0.3


def test_head_and_tail_skipped(three_scene_video):
    shots = detect_shots(three_scene_video, 7, skip_head_s=3, skip_tail_s=3)
    assert shots
    assert min(s.start for s in shots) >= 3 and max(s.end for s in shots) <= 9 + 0.05


def test_too_short_video_returns_empty(synthetic_video):
    assert detect_shots(synthetic_video, 1) == []


def test_dark_scenes_are_left_out(tmp_path):
    # dark trailer moments read as a black screen on a phone
    out = tmp_path / "dark.mp4"
    graph = (
        "testsrc2=size=1920x1080:rate=30:duration=4[a];"
        "mandelbrot=size=640x360:rate=30,scale=1920:1080,trim=duration=4,setpts=PTS-STARTPTS,"
        "colorlevels=romax=0.08:gomax=0.08:bomax=0.08[b];"
        "testsrc2=size=1920x1080:rate=30:duration=4,hue=h=90[c];"
        "[a][b][c]concat=n=3:v=1:a=0,format=yuv420p[v]"
    )
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-filter_complex", graph,
         "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", str(out)],
        check=True,
    )
    shots = detect_shots(out, 7, skip_head_s=0, skip_tail_s=0)
    assert shots
    assert not any(s.start < 6.0 and s.end > 6.0 for s in shots)


def test_half_dark_scene_counts_as_dark(tmp_path):
    # the black half is part of the picture, not letterbox bars, so it counts towards the darkness
    v = tmp_path / "half.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "color=c=0x3c3c3c:size=1920x1080:rate=30:duration=4,drawbox=x=0:y=0:w=1920:h=540:color=black:t=fill",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(v)],
        check=True,
    )
    assert detect_shots(v, 1, skip_head_s=0, skip_tail_s=0) == []
