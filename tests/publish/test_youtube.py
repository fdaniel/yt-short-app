import json
import stat

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from shorts.config import YouTubeSettings
from shorts.publish.youtube import (
    NotConnected,
    UploadResult,
    YouTubeAccount,
    YouTubeError,
    upload_body,
)

META = {
    "title": "RTX 5090 <Ti> announced",
    "description": "Specs inside.\n\nSource: https://nvidianews.nvidia.com/x\n\n#NVIDIA #RTX",
    "hashtags": ["#NVIDIA", "#RTX"],
}


def test_upload_body_maps_metadata_and_settings():
    body = upload_body(META, YouTubeSettings(privacy_status="unlisted", synthetic_media=True))
    assert body["snippet"]["title"] == "RTX 5090 Ti announced"
    assert body["snippet"]["description"].startswith("Specs inside.")
    assert body["snippet"]["tags"] == ["NVIDIA", "RTX"]
    assert body["snippet"]["categoryId"] == "28"
    assert body["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False,
                              "containsSyntheticMedia": True}


def test_upload_body_respects_youtube_limits():
    meta = {"title": "x" * 150, "description": "d" * 6000, "hashtags": [f"#tag{i:03d}" + "y" * 40 for i in range(30)]}
    snippet = upload_body(meta, YouTubeSettings())["snippet"]
    assert len(snippet["title"]) == 100 and len(snippet["description"]) == 5000
    assert sum(len(t) for t in snippet["tags"]) + len(snippet["tags"]) - 1 <= 500


class FakeRequest:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, 0

    def next_chunk(self):
        self.calls += 1
        if self.error:
            raise self.error
        return (None, None) if self.calls == 1 else (None, self.response)

    def execute(self):
        return self.response


class FakeService:
    def __init__(self, insert=None, channels=None):
        self._insert, self._channels, self.inserted = insert, channels, []

    def videos(self):
        return self

    def channels(self):
        return self

    def insert(self, **kwargs):
        self.inserted.append(kwargs)
        return self._insert

    def list(self, **kwargs):
        return self._channels


def _connected(tmp_path, service):
    folder = tmp_path / "youtube"
    folder.mkdir()
    (folder / "token.json").write_text("{}")
    (folder / "channel.json").write_text(json.dumps({"id": "UC123", "title": "Tech Bits"}))
    return YouTubeAccount(folder, service_factory=lambda creds: service, load_credentials=lambda path: object())


def test_not_connected_without_token(tmp_path):
    account = YouTubeAccount(tmp_path / "youtube")
    assert account.channel() is None
    with pytest.raises(NotConnected):
        account.upload(tmp_path / "v.mp4", {})


def test_upload_returns_video_id_and_privacy(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 10)
    service = FakeService(insert=FakeRequest({"id": "abc123XYZ_-", "status": {"privacyStatus": "private"}}))
    account = _connected(tmp_path, service)
    assert account.channel().title == "Tech Bits"
    result = account.upload(video, {"snippet": {}})
    assert result == UploadResult(video_id="abc123XYZ_-", privacy_status="private")
    assert service.inserted[0]["part"] == "snippet,status"


def test_upload_error_is_readable(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    error = HttpError(Response({"status": 403}), b'{"error": {"message": "quota exceeded"}}')
    account = _connected(tmp_path, FakeService(insert=FakeRequest(error=error)))
    with pytest.raises(YouTubeError, match="quota exceeded"):
        account.upload(video, {})


class FakeCreds:
    def to_json(self):
        return '{"refresh_token": "secret"}'


def test_connect_saves_private_token_and_channel(tmp_path):
    folder = tmp_path / "youtube"
    folder.mkdir()
    (folder / "client_secret.json").write_text("{}")
    channels = FakeRequest({"items": [{"id": "UC9", "snippet": {"title": "My Channel"}}]})
    account = YouTubeAccount(folder, service_factory=lambda creds: FakeService(channels=channels),
                             authorize=lambda secrets_path: FakeCreds())
    channel = account.connect()
    assert (channel.id, channel.title) == ("UC9", "My Channel")
    token = folder / "token.json"
    assert json.loads(token.read_text()) == {"refresh_token": "secret"}
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert account.channel() == channel


def test_connect_without_client_secret_explains(tmp_path):
    with pytest.raises(NotConnected, match="client_secret.json"):
        YouTubeAccount(tmp_path / "youtube").connect()


def test_network_failure_is_readable(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    account = _connected(tmp_path, FakeService(insert=FakeRequest(error=TimeoutError("timed out"))))
    with pytest.raises(YouTubeError, match="timed out"):
        account.upload(video, {})


def test_token_refresh_network_failure_is_readable(tmp_path):
    from google.auth.exceptions import TransportError

    def offline(path):
        raise TransportError("no internet")

    account = _connected(tmp_path, FakeService())
    account._load_credentials = offline
    with pytest.raises(YouTubeError, match="no internet"):
        account.upload(tmp_path / "v.mp4", {})
