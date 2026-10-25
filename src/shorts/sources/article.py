"""Fetch an official news page and extract its main text."""

import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import trafilatura

from shorts.net import fetch_text

MIN_TEXT_CHARS = 400
MIN_PROSE_WORDS = 10
# a sentence end: two letters or digits ("PS5.", "4K.", "été."), then . or ?, then a space or the end of the line;
# "!" is left out because headlines end with it ("Play Now!")
_TAG = re.compile(r"<[^>]+>")
_LABEL_PREFIX = re.compile(r"^\[[^\]]{1,20}\]\s*")
_SITE_SUFFIX = re.compile(r"\s+[|\u2013\u2014-]\s+(?:\S+\s+){0,2}\S+$")  # " | Site Name", 1-3 words
_SENTENCE_END = re.compile(r"\w{2}[.?][\"”’)]?(\s|$)")


class SourceTextError(Exception):
    """The page did not yield enough article text to write from."""


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    text: str
    domain: str
    html: str = ""  # the page (or the feed's own text) it came from: its photos are the story's footage


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
    raw_title = metadata.title if metadata and metadata.title else ""
    # some newsrooms (GamesPress) put <em> tags in their titles, and the title goes on a card
    title = " ".join(_TAG.sub("", html_lib.unescape(raw_title)).split())
    # "[Notices] Headline | Site Name": the labels are the website's, not part of the news
    title = _SITE_SUFFIX.sub("", _LABEL_PREFIX.sub("", title)).strip()
    return Article(url=url, title=title, text=text, domain=urlparse(url).hostname or "", html=html)


def fetch_article(client: httpx.Client, url: str, *, max_bytes: int) -> Article:
    return extract_article(url, fetch_text(client, url, max_bytes=max_bytes))
