"""The owner's YouTube channel: one-time connection, then uploads through the official API."""

import json
import os
import shutil
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow

from shorts.config import YouTubeSettings

SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)
MAX_TITLE = 100
MAX_DESCRIPTION = 5000
MAX_TAGS_CHARS = 500
CLIENT_SECRET = "client_secret.json"
TOKEN = "token.json"
CHANNEL = "channel.json"


class YouTubeError(Exception):
    """YouTube refused or failed an upload."""


class NotConnected(YouTubeError):
    """No usable connection to the owner's channel yet."""


@dataclass(frozen=True)
class Channel:
    id: str
    title: str


@dataclass(frozen=True)
class UploadResult:
    video_id: str
    privacy_status: str


def _plain(text: str) -> str:
    return text.replace("<", "").replace(">", "")


def _tags(hashtags: list[str]) -> list[str]:
    tags: list[str] = []
    for tag in (_plain(h).lstrip("#") for h in hashtags):
        if tag and sum(len(t) + 1 for t in [*tags, tag]) - 1 <= MAX_TAGS_CHARS:
            tags.append(tag)
    return tags


def upload_body(meta: dict[str, Any], settings: YouTubeSettings) -> dict[str, Any]:
    """The videos.insert request body for one exported video's metadata.json."""
    return {
        "snippet": {
            "title": " ".join(_plain(meta["title"]).split())[:MAX_TITLE],
            "description": _plain(meta["description"])[:MAX_DESCRIPTION],
            "tags": _tags(meta.get("hashtags", [])),
            "categoryId": settings.category_id,
        },
        "status": {
            "privacyStatus": settings.privacy_status,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": settings.synthetic_media,
        },
    }


def _use_windows_browser() -> None:
    """Inside WSL there is no Linux browser: hand links to Windows instead."""
    if shutil.which("explorer.exe"):
        webbrowser.register("windows", None, webbrowser.GenericBrowser("explorer.exe"), preferred=True)


def _authorize(secrets_path: Path) -> Credentials:
    _use_windows_browser()
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes=list(SCOPES))
    return flow.run_local_server(port=0, open_browser=True)


def _load_credentials(token_path: Path) -> Credentials:
    creds = Credentials.from_authorized_user_file(str(token_path), list(SCOPES))
    if not creds.valid:
        creds.refresh(Request())
    return creds


def _service(creds: Credentials) -> Any:
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _http_message(exc: HttpError) -> str:
    try:
        return json.loads(exc.content)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return str(exc)


class YouTubeAccount:
    """Files in `folder`: client_secret.json (from Google Cloud), token.json and channel.json (written here)."""

    def __init__(
        self,
        folder: Path,
        *,
        service_factory: Callable[[Any], Any] = _service,
        authorize: Callable[[Path], Any] = _authorize,
        load_credentials: Callable[[Path], Any] = _load_credentials,
    ) -> None:
        self._folder = folder
        self._service_factory = service_factory
        self._authorize = authorize
        self._load_credentials = load_credentials

    def channel(self) -> Channel | None:
        """The connected channel, or None if connect() has not run."""
        path = self._folder / CHANNEL
        if not (path.is_file() and (self._folder / TOKEN).is_file()):
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Channel(id=data["id"], title=data["title"])

    def connect(self) -> Channel:
        """Ask the owner (in the browser) to allow uploads to the channel they pick, and remember it."""
        secrets = self._folder / CLIENT_SECRET
        if not secrets.is_file():
            raise NotConnected(f"put the Google Cloud OAuth file at {secrets} (see README: YouTube upload)")
        creds = self._authorize(secrets)
        items = self._service_factory(creds).channels().list(part="snippet", mine=True).execute().get("items", [])
        if not items:
            raise NotConnected("that Google account has no YouTube channel yet: create one, then connect again")
        channel = Channel(id=items[0]["id"], title=items[0]["snippet"]["title"])
        self._write_private(TOKEN, creds.to_json())
        self._write_private(CHANNEL, json.dumps({"id": channel.id, "title": channel.title}))
        return channel

    def upload(self, video_path: Path, body: dict[str, Any]) -> UploadResult:
        if self.channel() is None:
            raise NotConnected("YouTube is not connected: run python -m shorts youtube-connect")
        try:
            creds = self._load_credentials(self._folder / TOKEN)
        except RefreshError as exc:
            raise NotConnected(f"YouTube access was revoked or expired, connect again: {exc}") from exc
        except TransportError as exc:
            raise YouTubeError(f"could not reach Google: {exc}") from exc
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
        request = self._service_factory(creds).videos().insert(part="snippet,status", body=body, media_body=media)
        try:
            response = None
            while response is None:
                _, response = request.next_chunk()
        except HttpError as exc:
            raise YouTubeError(f"YouTube refused the upload: {_http_message(exc)}") from exc
        except (OSError, httplib2.HttpLib2Error) as exc:
            raise YouTubeError(f"upload interrupted (check YouTube Studio before retrying): {exc}") from exc
        return UploadResult(video_id=response["id"], privacy_status=response.get("status", {}).get("privacyStatus", ""))

    def _write_private(self, name: str, text: str) -> None:
        """Owner-only file: token.json holds a refresh token that can upload to the channel."""
        self._folder.mkdir(parents=True, exist_ok=True)
        path = self._folder / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(path, 0o600)
