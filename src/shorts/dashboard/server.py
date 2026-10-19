"""A small web server for the dashboard, reachable only from this computer.

Buttons change things, so every POST must carry a per-run secret token and come from
this page; requests addressed to any other host name are refused (DNS rebinding).
"""

import hmac
import logging
import re
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from shorts.dashboard.app import Dashboard
from shorts.dashboard.page import render

log = logging.getLogger(__name__)

MAX_FORM_BYTES = 10_000
CHUNK = 256 * 1024
_VIDEO = re.compile(r"/videos/(\d{1,9})\.mp4")
_ACTION = re.compile(r"/videos/(\d{1,9})/(upload|mark-uploaded|discard|open-folder)")
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "form-action 'self'; frame-ancestors 'none'",
}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, dashboard: Dashboard, host: str = "127.0.0.1", port: int = 8000) -> None:
        super().__init__((host, port), _Handler)
        self.dashboard = dashboard
        self.token = secrets.token_urlsafe(32)
        self._notice: str | None = None
        self._notice_lock = threading.Lock()

    @property
    def allowed_hosts(self) -> set[str]:
        port = self.server_address[1]
        return {f"localhost:{port}", f"127.0.0.1:{port}"}

    def set_notice(self, text: str) -> None:
        with self._notice_lock:
            self._notice = text

    def pop_notice(self) -> str | None:
        with self._notice_lock:
            text, self._notice = self._notice, None
        return text


class _Handler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (stdlib signature)
        log.debug("%s " + format, self.address_string(), *args)

    def _send(self, status: HTTPStatus, body: bytes = b"", content_type: str = "text/plain; charset=utf-8",
              headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in {**_SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        if self.headers.get("Host", "") in self.server.allowed_hosts:
            return True
        self._send(HTTPStatus.FORBIDDEN, b"Open the dashboard at http://localhost")
        return False

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == "/":
            view = self.server.dashboard.view(query.get("tab", ["review"])[0])
            html = render(view, self.server.token, self.server.pop_notice())
            self._send(HTTPStatus.OK, html.encode(), "text/html; charset=utf-8", {"Cache-Control": "no-store"})
            return
        match = _VIDEO.fullmatch(url.path)
        video = self.server.dashboard.video_file(int(match.group(1))) if match else None
        if video is None:
            self._send(HTTPStatus.NOT_FOUND, b"Not found")
            return
        self._stream(video, download="download" in query)

    def _stream(self, video: Path, download: bool) -> None:
        size = video.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        match = _RANGE.fullmatch(self.headers.get("Range", "").strip())
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            if start > end or start >= size:
                self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, headers={"Content-Range": f"bytes */{size}"})
                return
            status = HTTPStatus.PARTIAL_CONTENT
        self.send_response(status)
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="tech-short-{video.parent.name}.mp4"')
        self.end_headers()
        try:
            with video.open("rb") as fh:
                fh.seek(start)
                remaining = end - start + 1
                while remaining > 0 and (chunk := fh.read(min(CHUNK, remaining))):
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser stopped playing or seeked elsewhere

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{host}" for host in self.server.allowed_hosts}

    def do_POST(self) -> None:
        if not self._host_ok():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_FORM_BYTES:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"Form too large")
            return
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", errors="replace")).items()}
        if not self._origin_ok() or not hmac.compare_digest(form.get("token", ""), self.server.token):
            self._send(HTTPStatus.FORBIDDEN, b"Refused: reload the dashboard and try again")
            return
        match = _ACTION.fullmatch(urlsplit(self.path).path)
        if match is None:
            self._send(HTTPStatus.NOT_FOUND, b"Not found")
            return
        video_id, action = int(match.group(1)), match.group(2)
        dashboard = self.server.dashboard
        actions = {
            "upload": lambda: dashboard.upload(video_id),
            "mark-uploaded": lambda: dashboard.mark_uploaded(video_id, form.get("link", "")),
            "discard": lambda: dashboard.discard(video_id),
            "open-folder": lambda: dashboard.open_folder(video_id),
        }
        try:
            self.server.set_notice(actions[action]())
        except Exception as exc:  # a button must never leave the owner on a broken page
            log.exception("Dashboard action %s on video #%d failed", action, video_id)
            self.server.set_notice(f"Video #{video_id}: {action} failed unexpectedly: {exc}")
        tab = form.get("tab", "review")
        tab = tab if re.fullmatch(r"[a-z]{1,20}", tab) else "review"
        self._send(HTTPStatus.SEE_OTHER, headers={"Location": f"/?tab={tab}"})
