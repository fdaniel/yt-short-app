import httpx
import respx

from shorts.media.ffmpeg import probe_video
from shorts.models import AssetKind, RightsBasis
from shorts.sources.press_video import MAX_PRESS_CLIPS, collect_press_clips, press_video_urls
from tests.helpers import lavfi_video

PAGE = "https://www.apple.com/newsroom/2026/10/developers-bring-new-app-experiences/"
APPLE = "https://www.apple.com/newsroom/videos/2026/autoplay/10/netflix-app"


def page(*sources):
    videos = "".join(f'<video autoplay muted><source src="{src}" type="video/mp4"></video>' for src in sources)
    return f"<html><body><article><h1>Apps</h1>{videos}</article></body></html>"


def test_one_address_per_clip_at_its_biggest_size():
    html = page(f"{APPLE}/small.mp4", f"{APPLE}/large.mp4", "/newsroom/videos/2026/autoplay/10/netflix-app/large_2x.mp4",
                "https://storage.googleapis.com/blog/original_videos/Jet_Engine.mp4?v=2")
    assert press_video_urls(PAGE, html) == [f"{APPLE}/large_2x.mp4",
                                            "https://storage.googleapis.com/blog/original_videos/Jet_Engine.mp4"]


def test_a_page_without_clips_has_none():
    assert press_video_urls(PAGE, "<html><body><p>No video, just a photo.jpg</p></body></html>") == []


@respx.mock
def test_clips_are_muted_and_logged_as_the_companys_own(tmp_path, settings):
    clip = lavfi_video(tmp_path, "testsrc2=size=1280x720:rate=30:duration=4", audio=True)
    respx.get(f"{APPLE}/large_2x.mp4").respond(200, content=clip.read_bytes())
    assets = collect_press_clips(httpx.Client(), PAGE, page(f"{APPLE}/large_2x.mp4"), tmp_path / "work", settings)
    assert len(assets) == 1
    a = assets[0]
    assert a.kind == AssetKind.PRESS_VIDEO and a.rights_basis == RightsBasis.PRESS_KIT_EDITORIAL
    assert a.rightsholder == "Apple" and a.music_stripped and not probe_video(a.local_path).has_audio


@respx.mock
def test_short_tiny_and_broken_clips_are_skipped(tmp_path, settings):
    short = lavfi_video(tmp_path, "testsrc2=size=1280x720:rate=30:duration=1", name="short.mp4")
    tiny = lavfi_video(tmp_path, "testsrc2=size=320x180:rate=30:duration=4", name="tiny.mp4")
    good = lavfi_video(tmp_path, "testsrc2=size=1920x1080:rate=30:duration=3", name="good.mp4")
    urls = [f"https://www.apple.com/v/{n}.mp4" for n in ("short", "tiny", "broken", "missing", "good")]
    for url, body in zip(urls, (short.read_bytes(), tiny.read_bytes(), b"not a video")):
        respx.get(url).respond(200, content=body)
    respx.get(urls[3]).respond(404)
    respx.get(urls[4]).respond(200, content=good.read_bytes())
    assets = collect_press_clips(httpx.Client(), PAGE, page(*urls), tmp_path / "work", settings)
    assert [a.source_url for a in assets] == [urls[4]]


@respx.mock
def test_at_most_four_clips(tmp_path, settings):
    clip = lavfi_video(tmp_path, "testsrc2=size=1280x720:rate=30:duration=3").read_bytes()
    urls = [f"https://www.apple.com/v/{i}.mp4" for i in range(MAX_PRESS_CLIPS + 2)]
    for url in urls:
        respx.get(url).respond(200, content=clip)
    assert len(collect_press_clips(httpx.Client(), PAGE, page(*urls), tmp_path / "work", settings)) == MAX_PRESS_CLIPS
