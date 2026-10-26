from datetime import UTC, datetime

import httpx
import respx

from shorts.config import DiscoverySettings
from shorts.discovery.epic_free import EPIC_SOURCE, PROMOTIONS_URL, fetch_free_games, free_now
from shorts.discovery.feeds import article_from_item
from shorts.sources.steam import APPDETAILS_URL, SEARCH_URL

NOW = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
DESCRIPTION = ("The round-based co-op survival FPS and spin-off to the award-winning British horror, Maid of Sker. "
               "Play solo or up to 4 players to survive the supernatural onslaught of the Quiet Ones.")


def offer(start, end, percent=0):
    return {"promotionalOffers": [{"startDate": start, "endDate": end, "discountSetting": {"discountPercentage": percent}}]}


def element(title, *, now=(), upcoming=(), discount_price=0, slug="sker-ritual-aac702", seller="Skybound Game Studios, Inc."):
    return {
        "title": title,
        "description": DESCRIPTION,
        "seller": {"name": seller},
        "productSlug": None,
        "catalogNs": {"mappings": [{"pageSlug": slug}]},
        "customAttributes": [],
        "price": {"totalPrice": {"discountPrice": discount_price, "originalPrice": 2239,
                                 "fmtPrice": {"originalPrice": "$22.39"}}},
        "promotions": {"promotionalOffers": list(now), "upcomingPromotionalOffers": list(upcoming)},
    }


def mock_promotions(*elements):
    payload = {"data": {"Catalog": {"searchStore": {"elements": list(elements)}}}}
    respx.get(url__startswith=PROMOTIONS_URL).respond(200, json=payload)


def mock_steam(name, app_id, developers=("Wales Interactive",), publishers=("Skybound Games",)):
    respx.get(url__startswith=SEARCH_URL).respond(200, json={"items": [{"type": "app", "id": app_id, "name": name}]})
    respx.get(APPDETAILS_URL.format(app_id=app_id)).respond(200, json={str(app_id): {"success": True, "data": {
        "name": name, "developers": list(developers), "publishers": list(publishers),
        "short_description": "Survive waves of the Quiet Ones with up to four friends in this co-op shooter."}}})


FREE = offer("2026-10-22T15:00:00.000Z", "2026-10-29T15:00:00.000Z")


@respx.mock
def test_a_game_free_right_now_becomes_a_story_with_its_offer_facts():
    mock_promotions(element("Sker Ritual", now=[FREE]))
    mock_steam("Sker Ritual", 1492070)
    [it] = free_now(httpx.Client(), country="US", now=NOW, max_bytes=1_000_000)
    assert it.title == "Sker Ritual is free on the Epic Games Store until October 29"
    assert it.source == EPIC_SOURCE and it.topic == "gaming"
    assert it.url == "https://store.epicgames.com/en-US/p/sker-ritual-aac702"
    assert it.published == NOW  # still free, so still news: not dated from the offer's first day
    assert it.steam_app_id == 1492070
    text = article_from_item(it).text
    for fact in ("until Thursday, October 29 at 15:00 UTC", "$22.39", "Wales Interactive", "Maid of Sker",
                 "Quiet Ones with up to four friends"):
        assert fact in text


@respx.mock
def test_discounted_upcoming_and_mystery_games_are_left_out():
    mock_promotions(
        element("Castlevania Anniversary Collection", now=[offer("2026-10-19T15:00:00.000Z", "2026-11-02T16:00:00.000Z", 40)],
                discount_price=799),
        element("Sorry We're Closed", upcoming=[offer("2026-10-29T15:00:00.000Z", "2026-11-05T15:00:00.000Z")]),
        element("Mystery Game", now=[FREE]),
    )
    assert free_now(httpx.Client(), country="US", now=NOW, max_bytes=1_000_000) == []


@respx.mock
def test_a_game_without_its_own_steam_footage_is_left_out():
    mock_promotions(element("Home", now=[FREE], seller="BancyCo"))
    mock_steam("Home", 999, developers=("Someone Else",), publishers=("Other Publisher",))
    assert free_now(httpx.Client(), country="US", now=NOW, max_bytes=1_000_000) == []


@respx.mock
def test_a_broken_epic_answer_gives_no_stories():
    respx.get(url__startswith=PROMOTIONS_URL).respond(503)
    assert fetch_free_games(httpx.Client(), DiscoverySettings(), now=NOW, max_bytes=1_000_000) == []


def test_free_games_can_be_turned_off():
    assert fetch_free_games(httpx.Client(), DiscoverySettings(epic_free_games=False), now=NOW, max_bytes=1) == []
