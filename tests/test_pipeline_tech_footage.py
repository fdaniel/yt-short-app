"""Tech stories: the newsroom's own video clips, and footage of the games the story names."""

import json

import httpx
import respx

from shorts.models import AssetKind, VideoFormat
from shorts.pipeline import PipelineDeps, make_video
from shorts.storage.repositories import AssetRepository
from tests.fakes import FakeTTS, ScriptedLLM
from tests.test_pipeline_e2e import ALL_OK, FIXTURES, GOOD, PHOTOS, TECH, article_with_photos, mock_photos, photo

CLIP = "https://www.apple.com/newsroom/videos/2026/autoplay/10/iphone-duo/large_2x.mp4"
GAME_LINE = "<p>FSR 4.1 is already available in Cyberpunk 2077 and in many other popular games today.</p>"


def page(photos, *, clip=False, extra=""):
    html = article_with_photos(photos)
    video = f'<video autoplay muted><source src="{CLIP}" type="video/mp4"></video>' if clip else ""
    return html.replace("</article>", f"{video}{extra}</article>", 1)


def mock_cyberpunk(synthetic_video, name="Cyberpunk 2077", details=None):
    respx.get(url__startswith="https://store.steampowered.com/api/storesearch/").respond(
        200, json={"items": [{"type": "app", "id": 1091500, "name": name}]})
    respx.get(url__startswith="https://store.steampowered.com/api/appdetails").respond(
        200, json=details or json.loads((FIXTURES / "steam_mp4.json").read_text()))
    respx.get(url__regex=r"https://cdn\.akamai\.steamstatic\.com/.*\.mp4").respond(
        200, content=synthetic_video.read_bytes())
    respx.get(url__startswith="https://shared.akamai.steamstatic.com/").respond(200, content=photo("orange"))


def deps(draft=GOOD):
    return PipelineDeps(httpx.Client(), ScriptedLLM([draft, ALL_OK]), FakeTTS(rate=0.07))


def kinds_of(conn, video_id):
    return [a.kind for a in AssetRepository(conn).list_for_video(video_id)]


@respx.mock
def test_newsroom_clip_is_used_muted_and_credited(settings, conn, synthetic_video):
    respx.get(TECH).respond(200, text=page(PHOTOS[:4], clip=True))
    mock_photos(PHOTOS[:4])
    respx.get(CLIP).respond(200, content=synthetic_video.read_bytes())
    r = make_video(TECH, None, VideoFormat.NEWS_FLASH, settings, deps(), conn)
    kinds = kinds_of(conn, r.video_id)
    assert kinds.count(AssetKind.PRESS_VIDEO) == 1 and AssetKind.STOCK_VIDEO not in kinds
    meta = json.loads(r.metadata_path.read_text())
    assert "Video clips: Apple (www.apple.com)" in meta["description"]


@respx.mock
def test_tech_story_shows_the_game_it_names(settings, conn, synthetic_video):
    respx.get(TECH).respond(200, text=page(PHOTOS[:1], extra=GAME_LINE))
    mock_photos(PHOTOS[:1])
    mock_cyberpunk(synthetic_video)
    stock = respx.get(url__startswith="https://pixabay.com/api/videos/")
    draft = GOOD.model_copy(update={"hook": "FSR 4.1 is now in Cyberpunk 2077.", "games_named": ["Cyberpunk 2077"]})
    r = make_video(TECH, None, VideoFormat.NEWS_FLASH, settings.model_copy(update={"pixabay_api_key": "xk"}),
                   deps(draft), conn)
    assets = AssetRepository(conn).list_for_video(r.video_id)
    kinds = [a.kind for a in assets]
    assert kinds.count(AssetKind.TRAILER) == 1 and 0 < kinds.count(AssetKind.SCREENSHOT) <= 4
    assert not stock.called  # the game's own footage, so no stock
    meta = json.loads(r.metadata_path.read_text())
    assert "Footage: CD PROJEKT RED (steam)" in meta["description"] and "Images: Apple" in meta["description"]


@respx.mock
def test_a_game_the_story_never_names_adds_nothing(settings, conn, synthetic_video):
    respx.get(TECH).respond(200, text=page(PHOTOS))
    mock_photos(PHOTOS)
    search = respx.get(url__startswith="https://store.steampowered.com/api/storesearch/")
    draft = GOOD.model_copy(update={"hook": "Hollow Knight looks sharper than ever.", "games_named": ["Hollow Knight"]})
    r = make_video(TECH, None, VideoFormat.NEWS_FLASH, settings, deps(draft), conn)
    assert not search.called and AssetKind.TRAILER not in kinds_of(conn, r.video_id)


@respx.mock
def test_a_one_word_title_needs_its_maker_named(settings, conn, synthetic_video):
    # "Farlands" was a FragPunk mode; Steam's "Farlands" is another studio's farming game
    respx.get(TECH).respond(200, text=page(PHOTOS, extra="<p>The new Farlands mode arrives in early access soon.</p>"))
    mock_photos(PHOTOS)
    mock_cyberpunk(synthetic_video, name="Farlands", details={"1091500": {"success": True, "data": {
        "name": "Farlands", "developers": ["JanduSoft"], "publishers": ["JanduSoft"],
        "movies": [], "screenshots": [{"path_full": "https://shared.akamai.steamstatic.com/ss.jpg"}]}}})
    draft = GOOD.model_copy(update={"hook": "Farlands mode is coming soon.", "games_named": ["Farlands"]})
    r = make_video(TECH, None, VideoFormat.NEWS_FLASH, settings, deps(draft), conn)
    kinds = kinds_of(conn, r.video_id)
    assert AssetKind.TRAILER not in kinds and AssetKind.SCREENSHOT not in kinds


@respx.mock
def test_game_news_does_not_look_for_other_games(settings, conn):
    from tests.test_pipeline_e2e import NEWS, mock_sources

    mock_sources()
    search = respx.get(url__startswith="https://store.steampowered.com/api/storesearch/")
    draft = GOOD.model_copy(update={"games_named": ["Cyberpunk 2077"]})
    make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps(draft), conn)
    assert not search.called


@respx.mock
def test_a_game_only_listed_after_the_hook_gets_no_footage(settings, conn, synthetic_video):
    # GeForce NOW's weekly list: Final Fantasy footage played while the narration said "Call of Duty"
    respx.get(TECH).respond(200, text=page(PHOTOS, extra=GAME_LINE))
    mock_photos(PHOTOS)
    search = respx.get(url__startswith="https://store.steampowered.com/api/storesearch/")
    draft = GOOD.model_copy(update={"games_named": ["Cyberpunk 2077"]})  # GOOD's hook is about the RTX 5090
    r = make_video(TECH, None, VideoFormat.NEWS_FLASH, settings, deps(draft), conn)
    assert not search.called and AssetKind.TRAILER not in kinds_of(conn, r.video_id)
