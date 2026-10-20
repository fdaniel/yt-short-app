"""HTTP helpers with URL safety checks and hard size limits."""

import ipaddress
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from shorts.config import Settings

USER_AGENT = "tech-shorts/0.1 (personal news tool)"
_CHUNK = 64 * 1024
_SECRET_PARAM = re.compile(r"\b((?:api_)?key)=[^&\s'\"]+", re.IGNORECASE)


def redact(text: str) -> str:
    """Hide API keys carried in addresses (Pixabay takes its key as ?key=...)."""
    return _SECRET_PARAM.sub(r"\1=***", text)


class _RedactKeys(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = redact(record.getMessage()), None
        return True


# httpx logs every request address at INFO, and the automatic runs write INFO to a log file
logging.getLogger("httpx").addFilter(_RedactKeys())


class UnsafeURLError(ValueError):
    """The URL is not a public http(s) address."""


class DownloadTooLarge(Exception):
    """The response exceeded the configured size limit."""


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeURLError(f"Only public http(s) URLs are allowed: {url!r}")
    host = parsed.hostname
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeURLError(f"Local addresses are not allowed: {url!r}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
        raise UnsafeURLError(f"Private addresses are not allowed: {url!r}")
    return url


def _check_request(request: httpx.Request) -> None:
    """Runs for every request the client sends, including each redirect hop."""
    validate_public_url(str(request.url))


def build_http_client(settings: Settings) -> httpx.Client:
    return httpx.Client(
        timeout=settings.limits.http_timeout_s,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        event_hooks={"request": [_check_request]},
    )


def _fetch(
    client: httpx.Client, url: str, max_bytes: int, headers: dict[str, str] | None = None
) -> tuple[bytes, str | None]:
    validate_public_url(url)
    with client.stream("GET", url, headers=headers) as response:
        if response.is_error:
            response.read()  # error pages are small, and callers may need to read why the request was refused
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_bytes(_CHUNK):
            body.extend(chunk)
            if len(body) > max_bytes:
                raise DownloadTooLarge(f"{url} is larger than {max_bytes} bytes")
        return bytes(body), response.encoding


def fetch_bytes(client: httpx.Client, url: str, *, max_bytes: int) -> bytes:
    return _fetch(client, url, max_bytes)[0]


def fetch_text(client: httpx.Client, url: str, *, max_bytes: int, headers: dict[str, str] | None = None) -> str:
    body, encoding = _fetch(client, url, max_bytes, headers)
    return body.decode(encoding or "utf-8", errors="replace")


def download_file(client: httpx.Client, url: str, dest: Path, *, max_bytes: int) -> Path:
    validate_public_url(url)
    partial = dest.with_suffix(dest.suffix + ".part")
    try:
        with client.stream("GET", url) as response, partial.open("wb") as fh:
            response.raise_for_status()
            written = 0
            for chunk in response.iter_bytes(_CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    raise DownloadTooLarge(f"{url} is larger than {max_bytes} bytes")
                fh.write(chunk)
        partial.replace(dest)
        return dest
    finally:
        partial.unlink(missing_ok=True)
