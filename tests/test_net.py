import httpx
import pytest
import respx

from shorts.media.ffmpeg import download_hls
from shorts.net import (
    DownloadTooLarge,
    UnsafeURLError,
    build_http_client,
    download_file,
    fetch_text,
    validate_public_url,
)


@pytest.mark.parametrize(
    "bad",
    [
        "file:///etc/passwd",
        "ftp://x.com/a",
        "http://localhost/a",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest",
        "http://[::1]/",
        "notaurl",
    ],
)
def test_validate_rejects(bad):
    with pytest.raises(UnsafeURLError):
        validate_public_url(bad)


def test_validate_accepts_public_https():
    url = "https://nvidianews.nvidia.com/news/x?a=1"
    assert validate_public_url(url) == url


@respx.mock
def test_fetch_text_returns_body():
    respx.get("https://news.example.com/a").respond(200, text="hello")
    with httpx.Client() as c:
        assert fetch_text(c, "https://news.example.com/a", max_bytes=1000) == "hello"


@respx.mock
def test_fetch_text_size_cap():
    respx.get("https://news.example.com/a").respond(200, text="x" * 2000)
    with httpx.Client() as c, pytest.raises(DownloadTooLarge):
        fetch_text(c, "https://news.example.com/a", max_bytes=1000)


@respx.mock
def test_fetch_text_http_error():
    respx.get("https://news.example.com/a").respond(404)
    with httpx.Client() as c, pytest.raises(httpx.HTTPStatusError):
        fetch_text(c, "https://news.example.com/a", max_bytes=1000)


@respx.mock
def test_download_file_writes(tmp_path):
    respx.get("https://cdn.example.com/t.mp4").respond(200, content=b"0" * 500)
    with httpx.Client() as c:
        out = download_file(c, "https://cdn.example.com/t.mp4", tmp_path / "t.mp4", max_bytes=1000)
    assert out.read_bytes() == b"0" * 500
    assert [p.name for p in tmp_path.iterdir()] == ["t.mp4"]


@respx.mock
def test_download_file_cleans_partial_on_cap(tmp_path):
    respx.get("https://cdn.example.com/t.mp4").respond(200, content=b"0" * 5000)
    with httpx.Client() as c, pytest.raises(DownloadTooLarge):
        download_file(c, "https://cdn.example.com/t.mp4", tmp_path / "t.mp4", max_bytes=1000)
    assert list(tmp_path.iterdir()) == []


def test_download_hls_rejects_unsafe_url(tmp_path):
    with pytest.raises(UnsafeURLError):
        download_hls("file:///etc/passwd", tmp_path / "x.mp4", max_seconds=5, timeout_s=10)


@respx.mock
def test_redirect_to_private_address_is_refused(settings):
    respx.get("https://example.com/a").respond(302, headers={"Location": "http://127.0.0.1/admin"})
    admin = respx.get("http://127.0.0.1/admin").respond(200, text="secret")
    with build_http_client(settings) as client, pytest.raises(UnsafeURLError):
        fetch_text(client, "https://example.com/a", max_bytes=1000)
    assert admin.call_count == 0


@respx.mock
def test_fetch_text_sends_extra_headers():
    route = respx.get("https://api.example.com/x").respond(200, text="ok")
    assert fetch_text(httpx.Client(), "https://api.example.com/x", max_bytes=100, headers={"Authorization": "k"}) == "ok"
    assert route.calls.last.request.headers["Authorization"] == "k"
