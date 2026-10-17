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
