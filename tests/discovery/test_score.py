import pytest

from shorts.config import DiscoverySettings
from shorts.discovery.score import cheap_filter, coverage, score_topic, similarity
from shorts.discovery.triage import Triage
from shorts.models import VideoFormat
from tests.discovery.items import NOW, item

S = DiscoverySettings()


def verdict(interest=8, rumour=False, on_topic=True, game=None):
    return Triage(index=0, interest=interest, rumour_or_leak=rumour, on_topic=on_topic, game_title=game,
                  format=VideoFormat.NEWS_FLASH, reason="big launch")


def test_similarity_ignores_stop_words_and_case():
    assert similarity("NVIDIA RTX Spark PCs Available Today", "RTX Spark PCs are available now") >= 0.5
    assert similarity("DLSS 4.5 for GeForce NOW", "AMD Helion rack scale") == 0


def test_keyword_exclusion():
    kept, rejected = cheap_filter([item("AMD Appoints Tim Ryan to Board of Directors")], seen_urls=set(),
                                  recent_titles=[], settings=S, now=NOW)
    assert kept == [] and "board of directors" in rejected[0][1]


def test_seen_url_rejected():
    it = item("DLSS 4.5 controls arrive")
    kept, rejected = cheap_filter([it], seen_urls={it.url}, recent_titles=[], settings=S, now=NOW)
    assert kept == [] and "already seen" in rejected[0][1]


def test_too_old_and_future_rejected():
    old, future = item("Old news", hours_old=60), item("Future news", hours_old=-3)
    kept, rejected = cheap_filter([old, future], seen_urls=set(), recent_titles=[], settings=S, now=NOW)
    assert kept == [] and {r[0].title for r in rejected} == {"Old news", "Future news"}


def test_near_duplicate_across_feeds_keeps_freshest():
    a = item("NVIDIA RTX Spark PCs Available Today", source="NVIDIA Newsroom", hours_old=5)
    b = item("RTX Spark PCs Available Today Worldwide", source="NVIDIA Blog", hours_old=1)
    kept, rejected = cheap_filter([a, b], seen_urls=set(), recent_titles=[], settings=S, now=NOW)
    assert kept == [b] and rejected[0][0] == a and "duplicate" in rejected[0][1]


def test_similar_to_recent_video_rejected():
    it = item("RTX Spark laptops available today")
    kept, rejected = cheap_filter([it], seen_urls=set(), recent_titles=["NVIDIA RTX Spark laptops available"],
                                  settings=S, now=NOW)
    assert kept == [] and "already covered" in rejected[0][1]


def test_coverage_counts_other_sources_only():
    a = item("RTX Spark PCs available today", source="NVIDIA Newsroom")
    same_source = item("RTX Spark PCs available today in Europe", source="NVIDIA Newsroom")
    other = item("RTX Spark PCs now available today", source="NVIDIA Blog")
    assert coverage(a, [a, same_source, other], S) == 0.5


def test_score_explanation_adds_up():
    t = score_topic(item("DLSS 5", hours_old=4.8), verdict(interest=8), footage=True, coverage=0.5, settings=S, now=NOW)
    # freshness 1 - 4.8/48 = 0.9
    assert t.score == pytest.approx(0.9 * 0.3 + 0.8 * 0.5 + 1 * 0.1 + 0.5 * 0.1)
    total = float(t.explanation.rsplit("=", 1)[1])
    assert total == pytest.approx(t.score, abs=0.01)
    assert "freshness" in t.explanation and "interest" in t.explanation


@pytest.mark.parametrize("v", [verdict(rumour=True), verdict(on_topic=False)])
def test_rumours_and_off_topic_score_zero(v):
    t = score_topic(item("Leak"), v, footage=True, coverage=1, settings=S, now=NOW)
    assert t.score == 0 and ("rumour" in t.explanation or "off topic" in t.explanation)
