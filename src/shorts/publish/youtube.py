"""The owner's YouTube channel: one-time connection, then uploads through the official API."""

import json
import logging
import os
import shutil
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

from shorts.config import YouTubeSettings

log = logging.getLogger(__name__)

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


def _description(text: str) -> str:
    """YouTube counts the description limit in bytes, not characters."""
    return _plain(text).encode()[:MAX_DESCRIPTION].decode(errors="ignore")


def upload_body(meta: dict[str, Any], settings: YouTubeSettings, publish_at: datetime | None = None) -> dict[str, Any]:
    """The videos.insert request body for one exported video's metadata.json.

    With `publish_at`, YouTube keeps the video private and makes it public at that time by itself.
    """
    status: dict[str, Any] = {
        "privacyStatus": "private" if publish_at else settings.privacy_status,
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": settings.synthetic_media,
    }
    if publish_at:
        status["publishAt"] = publish_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "snippet": {
            "title": " ".join(_plain(str(meta.get("title", ""))).split())[:MAX_TITLE] or "Tech news",
            "description": _description(str(meta.get("description", ""))),
            "tags": _tags([str(h) for h in meta.get("hashtags") or []]),
            "categoryId": settings.category_id,
        },
        "status": status,
    }


def _use_windows_browser() -> None:
    """Inside WSL there is no Linux browser: hand links to Windows instead.

    Windows' URL handler, not explorer.exe: explorer drops long links with "&" in them and opens Documents.
    """
    if shutil.which("rundll32.exe"):
        browser = webbrowser.GenericBrowser(["rundll32.exe", "url.dll,FileProtocolHandler", "%s"])
        webbrowser.register("windows", None, browser, preferred=True)


def _authorize(secrets_path: Path) -> Credentials:
    _use_windows_browser()
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes=list(SCOPES))
    # prompt=consent: Google only hands out the lasting (refresh) token when asked to show consent again.
    return flow.run_local_server(port=0, open_browser=True, prompt="consent")


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
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Channel(id=str(data["id"]), title=str(data["title"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None  # damaged file: treat as not connected, connect() rewrites it

    def connect(self) -> Channel:
        """Ask the owner (in the browser) to allow uploads to the channel they pick, and remember it."""
        secrets = self._folder / CLIENT_SECRET
        if not secrets.is_file():
            raise NotConnected(f"put the Google Cloud OAuth file at {secrets} (see README: YouTube upload)")
        try:
            creds = self._authorize(secrets)
        except OAuth2Error as exc:
            raise NotConnected(f"access was not allowed on the Google page ({exc.error}); run this again and"
                               " press Allow") from exc
        except ValueError as exc:
            raise NotConnected(f"{secrets} is not a Desktop app OAuth client (README step 4): {exc}") from exc
        if not getattr(creds, "refresh_token", None):
            raise NotConnected("Google did not grant lasting access: remove the app at"
                               " https://myaccount.google.com/permissions and connect again")
        try:
            items = self._service_factory(creds).channels().list(part="snippet", mine=True).execute().get("items", [])
        except HttpError as exc:
            raise NotConnected(f"Google refused: {_http_message(exc)}. Did you enable YouTube Data API v3"
                               " (README step 2)?") from exc
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
        except (RefreshError, ValueError) as exc:
            log.warning("Saved YouTube connection unusable: %s", exc)
            raise NotConnected("Google no longer accepts the saved connection (revoked, expired or damaged):"
                               " run python -m shorts youtube-connect to connect again") from exc
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
        tmp = self._folder / f".{name}.tmp"
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, self._folder / name)  # never a half-written file, even if the PC dies mid-write
