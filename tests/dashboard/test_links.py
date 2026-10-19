import pytest

from shorts.dashboard.links import youtube_id_from


@pytest.mark.parametrize("text", [
    "https://youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3",
    "https://studio.youtube.com/video/dQw4w9WgXcQ/edit",
    "  dQw4w9WgXcQ ",
])
def test_accepts_common_link_shapes(text):
    assert youtube_id_from(text) == "dQw4w9WgXcQ"


def test_empty_means_no_link():
    assert youtube_id_from("   ") is None


@pytest.mark.parametrize("text", ["https://evil.example/shorts/dQw4w9WgXcQ", "hello", "https://youtu.be/short"])
def test_rejects_anything_else(text):
    with pytest.raises(ValueError):
        youtube_id_from(text)
