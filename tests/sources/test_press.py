import io

import httpx
import respx
from PIL import Image

from shorts.models import AssetKind, RightsBasis
from shorts.sources.press import MAX_PRESS_IMAGES, brand, collect_press_images, press_image_urls

PAGE = "https://www.apple.com/newsroom/2026/10/iphone-duo-arrives/"
IMG = "https://www.apple.com/newsroom/images/2026/10/iphone-duo-arrives/article"
PROSE = "<p>" + "iPhone Duo arrives at Apple Store locations around the world today with two screens. " * 8 + "</p>"


def page(*images, og=None, sidebar=()):
    meta = f'<meta property="og:image" content="{og}">' if og else ""
    figures = "".join(f'<figure><img src="{src}" alt="photo"></figure><p>{PROSE}</p>' for src in images)
    aside = "".join(f'<li><a href="/x"><img src="{src}"></a> Other story</li>' for src in sidebar)
    return (f"<html><head>{meta}</head><body><nav><ul>{aside}</ul></nav>"
            f"<article><h1>iPhone Duo arrives</h1>{PROSE}{figures}</article></body></html>")


def jpeg(w, h, colour):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="JPEG")
    return buf.getvalue()


def test_share_image_first_then_the_article_photos_in_order():
    html = page(f"{IMG}/a.jpg", f"{IMG}/b.jpg", og=f"{IMG}/share.jpg")
    assert press_image_urls(PAGE, html) == [f"{IMG}/share.jpg", f"{IMG}/a.jpg", f"{IMG}/b.jpg"]


def test_relative_image_paths_are_made_absolute_and_repeats_dropped():
    html = page("/newsroom/images/a.jpg", "/newsroom/images/a.jpg")
    assert press_image_urls(PAGE, html) == ["https://www.apple.com/newsroom/images/a.jpg"]


def test_logos_and_animations_are_not_photos():
    html = page(f"{IMG}/logo.svg", f"{IMG}/spinner.gif", f"{IMG}/a.jpg")
    assert press_image_urls(PAGE, html) == [f"{IMG}/a.jpg"]


def test_brand_comes_from_the_newsroom_address():
    assert brand("https://www.apple.com/newsroom/x") == "Apple"
    assert brand("https://news.samsung.com/global/x") == "Samsung"
    assert brand("https://blog.google/products/pixel/x") == "Google"
    assert brand("https://nvidianews.nvidia.com/news/x") == "NVIDIA"


@respx.mock
def test_big_distinct_photos_become_press_assets(tmp_path, settings):
    urls = [f"{IMG}/{n}.jpg" for n in "abcd"]
    respx.get(urls[0]).respond(200, content=jpeg(1920, 1080, "navy"))
    respx.get(urls[1]).respond(200, content=jpeg(200, 120, "red"))  # a thumbnail
    respx.get(urls[2]).respond(200, content=jpeg(1600, 900, "navy"))  # the first one at another size
    respx.get(urls[3]).respond(200, content=jpeg(1080, 1350, "green"))
    assets = collect_press_images(httpx.Client(), PAGE, page(*urls), tmp_path, settings)
    assert [a.source_url for a in assets] == [urls[0], urls[3]]
    a = assets[0]
    assert a.kind == AssetKind.PRESS_IMAGE and a.rights_basis == RightsBasis.PRESS_KIT_EDITORIAL
    assert a.rightsholder == "Apple" and a.source_platform == "www.apple.com" and a.local_path.is_file()


@respx.mock
def test_a_broken_photo_is_skipped(tmp_path, settings):
    respx.get(f"{IMG}/a.jpg").respond(404)
    respx.get(f"{IMG}/b.jpg").respond(200, content=b"not an image")
    respx.get(f"{IMG}/c.jpg").respond(200, content=jpeg(1920, 1080, "navy"))
    html = page(f"{IMG}/a.jpg", f"{IMG}/b.jpg", f"{IMG}/c.jpg")
    assert [a.source_url for a in collect_press_images(httpx.Client(), PAGE, html, tmp_path, settings)] == [f"{IMG}/c.jpg"]


@respx.mock
def test_at_most_twelve_photos(tmp_path, settings):
    colours = [(i * 15, 255 - i * 15, (i * 70) % 256) for i in range(MAX_PRESS_IMAGES + 3)]
    urls = [f"{IMG}/{i}.jpg" for i in range(len(colours))]
    for url, colour in zip(urls, colours):
        respx.get(url).respond(200, content=jpeg(1920, 1080, colour))
    assets = collect_press_images(httpx.Client(), PAGE, page(*urls), tmp_path, settings)
    assert len(assets) == MAX_PRESS_IMAGES


def test_other_stories_thumbnails_are_not_taken():
    html = page(f"{IMG}/a.jpg", sidebar=["https://www.apple.com/newsroom/images/other-story/tile.jpg"])
    assert press_image_urls(PAGE, html) == [f"{IMG}/a.jpg"]
