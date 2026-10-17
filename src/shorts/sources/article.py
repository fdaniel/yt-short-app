"""Fetch an official news page and extract its main text."""

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import trafilatura

from shorts.net import fetch_text

MIN_TEXT_CHARS = 400


class SourceTextError(Exception):
    """The page did not yield enough article text to write from."""


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    text: str
    domain: str


def extract_article(url: str, html: str) -> Article:
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    if len(text) < MIN_TEXT_CHARS:
        raise SourceTextError(
            f"could not extract enough text from {url} "
            "(the page may need JavaScript, a login or a cookie consent)"
        )
    metadata = trafilatura.extract_metadata(html)
    title = (metadata.title if metadata and metadata.title else "").strip()
    return Article(url=url, title=title, text=text, domain=urlparse(url).hostname or "")


def fetch_article(client: httpx.Client, url: str, *, max_bytes: int) -> Article:
    return extract_article(url, fetch_text(client, url, max_bytes=max_bytes))
