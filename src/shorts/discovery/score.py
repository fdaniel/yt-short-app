"""Cheap filters and a transparent weighted score for candidate stories."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from shorts.config import DiscoverySettings
from shorts.discovery.feeds import FeedItem
from shorts.discovery.triage import Triage

STOP_WORDS = frozenset("the a an and or of to for in on with is are new now".split())
FUTURE_TOLERANCE = timedelta(hours=1)


@dataclass(frozen=True)
class ScoredTopic:
    item: FeedItem
    score: float
    explanation: str
    triage: Triage
    footage: bool


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9.]+", text.lower()) if w not in STOP_WORDS}


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def _reject_reason(it: FeedItem, seen_urls: set[str], recent_titles: list[str], s: DiscoverySettings, now: datetime) -> str | None:
    if it.url in seen_urls:
        return "already seen"
    if now - it.published > timedelta(hours=s.max_age_h):
        return f"older than {s.max_age_h:g} h"
    if it.published - now > FUTURE_TOLERANCE:
        return "dated in the future"
    keyword = next((k for k in s.exclude_keywords if k in it.title.lower()), None)
    if keyword:
        return f"excluded topic: {keyword}"
    covered = next((t for t in recent_titles if similarity(it.title, t) >= s.duplicate_similarity), None)
    if covered:
        return f"already covered: {covered}"
    return None


def cheap_filter(
    items: list[FeedItem], *, seen_urls: set[str], recent_titles: list[str], settings: DiscoverySettings, now: datetime
) -> tuple[list[FeedItem], list[tuple[FeedItem, str]]]:
    """(kept, rejected with reason). Near-duplicates inside the batch collapse to the freshest item."""
    kept: list[FeedItem] = []
    rejected: list[tuple[FeedItem, str]] = []
    for it in sorted(items, key=lambda i: i.published, reverse=True):
        reason = _reject_reason(it, seen_urls, recent_titles, settings, now)
        if reason is None:
            twin = next((k for k in kept if similarity(it.title, k.title) >= settings.duplicate_similarity), None)
            reason = f"duplicate of: {twin.title}" if twin else None
        if reason:
            rejected.append((it, reason))
        else:
            kept.append(it)
    return kept, rejected


def coverage(it: FeedItem, all_items: list[FeedItem], settings: DiscoverySettings) -> float:
    """How many *other* official sources carry the same story (0, 0.5, 1)."""
    others = {o.source for o in all_items
              if o.source != it.source and similarity(it.title, o.title) >= settings.duplicate_similarity}
    return min(1.0, len(others) / 2)


def score_topic(
    it: FeedItem, verdict: Triage, *, footage: bool, coverage: float, settings: DiscoverySettings, now: datetime
) -> ScoredTopic:
    if verdict.rumour_or_leak or not verdict.on_topic or verdict.same_story_as_recent:
        why = ("rumour or leak" if verdict.rumour_or_leak
               else "off topic" if not verdict.on_topic else "already covered (same story)")
        return ScoredTopic(it, 0.0, f"{why} ({verdict.reason}) = 0", verdict, footage)
    w = settings.weights
    age_h = max(0.0, (now - it.published).total_seconds() / 3600)
    factors = {
        "freshness": (max(0.0, 1 - age_h / settings.max_age_h), w.freshness),
        "interest": (verdict.interest / 10, w.interest),
        "footage": (1.0 if footage else 0.0, w.footage),
        "coverage": (coverage, w.coverage),
    }
    score = sum(value * weight for value, weight in factors.values())
    parts = " + ".join(f"{name} {value:.2f}x{weight:g}" for name, (value, weight) in factors.items())
    return ScoredTopic(it, score, f"{parts} ({verdict.reason}) = {score:.2f}", verdict, footage)
