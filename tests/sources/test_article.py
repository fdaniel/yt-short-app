from pathlib import Path

import httpx
import pytest
import respx

from shorts.sources.article import MIN_TEXT_CHARS, SourceTextError, extract_article, fetch_article

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_extract_article_fixture():
    html = (FIXTURES / "article_nvidia.html").read_text()
    a = extract_article("https://nvidianews.nvidia.com/news/x", html)
    assert a.domain == "nvidianews.nvidia.com"
    assert "RTX 5090" in a.title
    assert "$1,999" in a.text and len(a.text) >= MIN_TEXT_CHARS
    assert "Cookie settings" not in a.text


def test_js_only_page_fails_clearly():
    html = "<html><body><div id='root'></div><script>app()</script></body></html>"
    with pytest.raises(SourceTextError, match="could not extract enough text"):
        extract_article("https://example.com/news", html)


@respx.mock
def test_fetch_article_uses_http():
    html = (FIXTURES / "article_nvidia.html").read_text()
    respx.get("https://nvidianews.nvidia.com/news/x").respond(200, text=html)
    with httpx.Client() as c:
        a = fetch_article(c, "https://nvidianews.nvidia.com/news/x", max_bytes=1_000_000)
    assert a.url == "https://nvidianews.nvidia.com/news/x"


def test_link_post_listing_other_stories_fails():
    # an Xbox Wire post that only links elsewhere: the page's text is its title plus "Keep reading" headlines
    html = (FIXTURES / "article_xbox_link_post.html").read_text()
    with pytest.raises(SourceTextError, match="could not extract enough text"):
        extract_article("https://news.xbox.com/en-us/2026/10/15/asus-announces-availability-of-rog-xbox-ally-x20/",
                        html)


def test_list_of_headlines_is_not_an_article():
    headlines = "".join(f"<p>Spotlight: Another Big Game Gets A Brand New Trailer And Release Date {n}</p>"
                        for n in range(12))
    with pytest.raises(SourceTextError):
        extract_article("https://example.com/news", f"<html><body><article>{headlines}</article></body></html>")


def test_short_paragraphs_add_up():
    # trafilatura drops repeated paragraphs, so each one is different
    paragraphs = "".join(f"<p>Model {n} of the handheld ships on November {n} for $599 in the US and Europe.</p>"
                         for n in range(1, 9))
    a = extract_article("https://example.com/news", f"<html><body><article>{paragraphs}</article></body></html>")
    assert "$599" in a.text
