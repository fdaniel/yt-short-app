from datetime import UTC

from shorts.channel.advice import build_report
from shorts.dashboard.app import Dashboard
from shorts.dashboard.page import render

from tests.channel.helpers import days, snapshot, video
from tests.dashboard.conftest import FakeAccount, FakeWatcher


def _html(settings, watcher):
    view = Dashboard(settings, FakeAccount(), opener=print, watcher=watcher).view("channel")
    return render(view, token="TOKEN123")


def _report(**extra):
    snap = snapshot(video(1, views=1400), video(2, views=1500), video(3, views=1300),
                    video(4, views=380, engaged_views=150, analytics_views=380, title="Where to Find the <Feral> Claw"),
                    video(5, views=2600, days_old=1, from_app=True, title="Dark Heresy LAUNCHES"),
                    subscribers=13, days=days(740, 0), shorts_views_90d=33000, long_hours_365d=0.4, **extra)
    return build_report(snap, tz=UTC)


def test_every_tab_links_to_the_channel_page(settings):
    html = render(Dashboard(settings, FakeAccount(), opener=print).view("review"), token="T")
    assert 'href="/?tab=channel"' in html


def test_without_numbers_yet_the_page_offers_a_refresh(settings):
    html = _html(settings, FakeWatcher(report=None))
    assert 'action="/channel/refresh"' in html and 'name="token" value="TOKEN123"' in html
    assert "No channel numbers yet" in html


def test_without_a_watcher_the_page_says_so(settings):
    html = _html(settings, None)
    assert "not available" in html


def test_the_page_shows_numbers_plan_advice_and_each_video(settings):
    html = _html(settings, FakeWatcher(_report()))
    assert "13" in html and "33,000" in html
    assert "New identity and setup" in html  # this week in the plan
    assert "subscribe" in html  # a tip
    assert "Where to Find the &lt;Feral&gt; Claw" in html  # titles escaped
    assert "Weak" in html and "kept watching" in html.lower()  # the verdict and its reason
    assert "Too early" in html


def test_the_page_tracks_the_checkpoint_and_partner_program(settings):
    html = _html(settings, FakeWatcher(_report()))
    assert "Day 30" in html and "Subscribers" in html
    assert "10,000,000" in html and "4,000" in html


def test_missing_analytics_shows_how_to_reconnect(settings):
    html = _html(settings, FakeWatcher(_report(analytics_note="no access yet")))
    assert "python -m shorts youtube-connect" in html
