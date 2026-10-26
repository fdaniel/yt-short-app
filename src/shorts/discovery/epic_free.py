"""This week's free games on the Epic Games Store: official offer facts, and the game's Steam footage."""

import json
import logging
import re
from datetime import datetime
from html import escape
from urllib.parse import urlencode

import httpx

from shorts.config import DiscoverySettings
from shorts.discovery.feeds import FeedItem
from shorts.net import DownloadTooLarge, UnsafeURLError, fetch_bytes
from shorts.sources.steam import SteamApp, SteamError, fetch_steam_app, find_steam_app_id, normalise_title

log = logging.getLogger(__name__)

EPIC_SOURCE = "Epic Games Store"
PROMOTIONS_URL = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?"
STORE_PAGE = "https://store.epicgames.com/en-US/p/{slug}"
# company-name endings that differ between stores: "Skybound Game Studios, Inc." on Epic is "Skybound Games" on Steam
_COMPANY_ENDINGS = re.compile(r"\b(inc|llc|ltd|limited|gmbh|co|corp|sa|game|games|studio|studios|interactive|entertainment|publishing|digital)\b")
_ERRORS = (httpx.HTTPError, ValueError, KeyError, TypeError, DownloadTooLarge, UnsafeURLError)


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _free_offer(element: dict, now: datetime) -> tuple[datetime, datetime] | None:
    """(start, end) of a running 100%-off offer; Epic writes a free game's discount as 0 percent of the price."""
    if element.get("price", {}).get("totalPrice", {}).get("discountPrice") != 0:
        return None
    for group in (element.get("promotions") or {}).get("promotionalOffers") or ():
        for offer in group.get("promotionalOffers") or ():
            start, end = _when(offer["startDate"]), _when(offer["endDate"])
            if offer.get("discountSetting", {}).get("discountPercentage") == 0 and start <= now < end:
                return start, end
    return None


def _slug(element: dict) -> str | None:
    mappings = (element.get("catalogNs") or {}).get("mappings") or ()
    slug = next((m.get("pageSlug") for m in mappings if m.get("pageSlug")), None)
    return slug or (element.get("productSlug") or "").removesuffix("/home") or None


def _brand(company: str) -> str:
    return " ".join(_COMPANY_ENDINGS.sub(" ", normalise_title(company)).split())


def _makers(element: dict) -> set[str]:
    attrs = {a.get("key"): a.get("value") for a in element.get("customAttributes") or ()}
    names = (element.get("seller", {}).get("name"), attrs.get("developerName"), attrs.get("publisherName"))
    return {_brand(name) for name in names if name} - {""}


def _steam_app(client: httpx.Client, title: str, makers: set[str], max_bytes: int) -> SteamApp | None:
    """The game's Steam page, for footage: only when its developer or publisher is the one selling it on Epic."""
    try:
        app_id = find_steam_app_id(client, title)
        app = fetch_steam_app(client, app_id, max_bytes=max_bytes) if app_id else None
    except (*_ERRORS, SteamError) as exc:
        log.warning("No Steam page found for %s: %s", title, exc)
        return None
    return app if app and makers & {_brand(name) for name in app.developers + app.publishers} else None


def _story(title: str, element: dict, end: datetime, app: SteamApp) -> str:
    price = element["price"]["totalPrice"].get("fmtPrice", {}).get("originalPrice")
    lines = [f"{title} is free to keep on the Epic Games Store until {end:%A, %B} {end.day} at {end:%H:%M} UTC.",
             "Players who claim it before the offer ends keep the game for good."]
    if price:
        lines.append(f"Its normal price on the Epic Games Store is {price}.")
    if app.developers or app.publishers:
        makers = ", ".join(dict.fromkeys(app.developers + app.publishers))
        lines.append(f"{title} is made and published by {makers}.")
    lines += [element.get("description", ""), app.about]
    return "".join(f"<p>{escape(line)}</p>" for line in lines if line)


def free_now(client: httpx.Client, *, country: str, now: datetime, max_bytes: int) -> list[FeedItem]:
    query = urlencode({"locale": "en-US", "country": country, "allowCountries": country})
    elements = json.loads(fetch_bytes(client, PROMOTIONS_URL + query, max_bytes=max_bytes))[
        "data"]["Catalog"]["searchStore"]["elements"]
    items = []
    for element in elements:
        title, offer, slug = " ".join(str(element.get("title", "")).split()), _free_offer(element, now), _slug(element)
        # before its reveal, next week's game is listed as "Mystery Game"
        if not (title and offer and slug) or "mystery game" in title.lower():
            continue
        _, end = offer
        app = _steam_app(client, title, _makers(element), max_bytes)
        if app is None:
            # without the game's own trailer the Short would be a slideshow of stock clips
            log.info("Leaving out free game %s: not found on Steam by the same studio", title)
            continue
        # dated now, not from the offer's first day: the game is news for as long as it is free
        items.append(FeedItem(
            source=EPIC_SOURCE, topic="gaming", url=STORE_PAGE.format(slug=slug), published=now,
            title=f"{title} is free on the Epic Games Store until {end:%B} {end.day}",
            content_html=_story(title, element, end, app), steam_app_id=app.app_id,
        ))
    return items


def fetch_free_games(client: httpx.Client, d: DiscoverySettings, *, now: datetime, max_bytes: int) -> list[FeedItem]:
    """The free games, or none when turned off or when Epic's answer can't be read."""
    if not d.epic_free_games:
        return []
    try:
        return free_now(client, country=d.epic_country, now=now, max_bytes=max_bytes)
    except _ERRORS as exc:
        log.warning("Skipping Epic free games: %s", exc)
        return []
