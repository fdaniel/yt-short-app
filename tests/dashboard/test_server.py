import threading

import httpx
import pytest

from shorts.dashboard.app import Dashboard
from shorts.dashboard.server import DashboardServer
from shorts.models import VideoStatus
from shorts.storage.db import connect
from shorts.storage.repositories import VideoRepository

from tests.dashboard.conftest import FakeAccount


@pytest.fixture
def server(settings):
    srv = DashboardServer(Dashboard(settings, FakeAccount(), opener=print), port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def client(server):
    with httpx.Client(base_url=f"http://127.0.0.1:{server.server_address[1]}") as c:
        yield c


def _status(settings, vid):
    conn = connect(settings.data_dir / "shorts.db")
    try:
        return VideoRepository(conn).get(vid).status
    finally:
        conn.close()


def test_home_page(client, make_ready_video):
    make_ready_video("Hello")
    response = client.get("/")
    assert response.status_code == 200 and "Hello" in response.text
    assert response.headers["x-frame-options"] == "DENY"


def test_foreign_host_is_refused(client):
    assert client.get("/", headers={"Host": "evil.example:8000"}).status_code == 403


def test_post_without_token_is_refused(client, settings, make_ready_video):
    vid = make_ready_video()
    assert client.post(f"/videos/{vid}/discard", data={"token": "wrong"}).status_code == 403
    assert _status(settings, vid) == VideoStatus.AWAITING_APPROVAL


def test_post_from_other_site_is_refused(client, server, settings, make_ready_video):
    vid = make_ready_video()
    response = client.post(f"/videos/{vid}/discard", data={"token": server.token},
                           headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert _status(settings, vid) == VideoStatus.AWAITING_APPROVAL


def test_discard_redirects_with_notice(client, server, settings, make_ready_video):
    vid = make_ready_video()
    response = client.post(f"/videos/{vid}/discard", data={"token": server.token, "tab": "review"})
    assert response.status_code == 303 and response.headers["location"] == "/?tab=review"
    assert _status(settings, vid) == VideoStatus.DISCARDED
    assert f"Video #{vid} discarded." in client.get("/").text
    assert f"Video #{vid} discarded." not in client.get("/").text  # shown once


def test_mark_uploaded_form(client, server, settings, make_ready_video):
    vid = make_ready_video()
    client.post(f"/videos/{vid}/mark-uploaded", data={"token": server.token, "link": "https://youtu.be/dQw4w9WgXcQ"})
    assert _status(settings, vid) == VideoStatus.APPROVED


def test_unknown_action_is_404(client, server, make_ready_video):
    vid = make_ready_video()
    assert client.post(f"/videos/{vid}/explode", data={"token": server.token}).status_code == 404


def test_video_streams_with_range(client, make_ready_video):
    vid = make_ready_video()
    full = client.get(f"/videos/{vid}.mp4")
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4" and len(full.content) == 1024
    part = client.get(f"/videos/{vid}.mp4", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == bytes(range(10, 20))
    assert part.headers["content-range"] == "bytes 10-19/1024"
    tail = client.get(f"/videos/{vid}.mp4", headers={"Range": "bytes=1000-"})
    assert tail.content == bytes(range(232, 256))


def test_bad_range_is_416(client, make_ready_video):
    vid = make_ready_video()
    assert client.get(f"/videos/{vid}.mp4", headers={"Range": "bytes=5000-6000"}).status_code == 416


def test_download_sets_attachment(client, make_ready_video):
    vid = make_ready_video()
    response = client.get(f"/videos/{vid}.mp4?download=1")
    assert "attachment" in response.headers["content-disposition"]


def test_missing_video_is_404(client):
    assert client.get("/videos/42.mp4").status_code == 404
    assert client.get("/etc/passwd").status_code == 404


def test_unexpected_error_becomes_notice(client, server, make_ready_video, monkeypatch):
    vid = make_ready_video()

    def boom(video_id):
        raise OSError("disk unplugged")

    monkeypatch.setattr(server.dashboard, "open_folder", boom)
    response = client.post(f"/videos/{vid}/open-folder", data={"token": server.token})
    assert response.status_code == 303
    assert "disk unplugged" in client.get("/").text
