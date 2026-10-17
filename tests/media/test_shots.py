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
