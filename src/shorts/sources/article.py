"""Fetch an official news page and extract its main text."""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import trafilatura

from shorts.net import fetch_text

MIN_TEXT_CHARS = 400
MIN_PROSE_WORDS = 10
# a sentence end: two lowercase letters or digits, then . or ?, then a space or the end of the line
_SENTENCE_END = re.compile(r"[a-z0-9]{2}[.?][\"”’)]?(\s|$)")


class SourceTextError(Exception):
    """The page did not yield enough article text to write from."""


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    text: str
    domain: str


def _prose_chars(text: str) -> int:
    """Characters in lines that read as sentences, not headlines: a page that only links to
    other stories ("Keep reading", "Spotlight") has plenty of text but none of it is prose."""
    return sum(len(line) for line in text.splitlines()
               if len(line.split()) >= MIN_PROSE_WORDS and _SENTENCE_END.search(line))


def extract_article(url: str, html: str) -> Article:
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    if _prose_chars(text) < MIN_TEXT_CHARS:
        raise SourceTextError(
            f"could not extract enough text from {url} "
            "(the page may need JavaScript, a login or a cookie consent)"
        )
    metadata = trafilatura.extract_metadata(html)
    title = (metadata.title if metadata and metadata.title else "").strip()
    return Article(url=url, title=title, text=text, domain=urlparse(url).hostname or "")


def fetch_article(client: httpx.Client, url: str, *, max_bytes: int) -> Article:
    return extract_article(url, fetch_text(client, url, max_bytes=max_bytes))
