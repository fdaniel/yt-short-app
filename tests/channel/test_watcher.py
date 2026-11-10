from datetime import timedelta

import pytest

from shorts.channel.fetch import ChannelFetchError
from shorts.channel.watcher import ChannelWatcher
from shorts.publish.youtube import NotConnected, Readers

from tests.channel.helpers import NOW, snapshot, video


class FakeAccount:
    def __init__(self, readers=Readers("data", "analytics"), error=None):
        self._readers, self.error = readers, error

    def readers(self):
        if self.error:
            raise self.error
        return self._readers


class FakeFetch:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result or snapshot(video(1)), error, []

    def __call__(self, data, analytics, *, app_ids, now, analytics_note=""):
        self.calls.append({"data": data, "analytics": analytics, "app_ids": app_ids, "note": analytics_note})
        if self.error:
            raise self.error
        return self.result


def watcher(settings, account=None, fetch=None, now=NOW):
    return ChannelWatcher(settings, account or FakeAccount(), fetch=fetch or FakeFetch(), clock=lambda: now)


def test_refresh_saves_a_snapshot_that_the_report_reads(settings):
    w = watcher(settings)
    assert w.report() is None
    assert "updated" in w.refresh().lower()
    assert w.report().snapshot.videos[0].youtube_id == "vid00000001xx"


def test_refresh_passes_on_why_analytics_are_missing(settings):
    fetch = FakeFetch()
    watcher(settings, FakeAccount(Readers("data", None, "reconnect please")), fetch).refresh()
    assert fetch.calls[0]["analytics"] is None and fetch.calls[0]["note"] == "reconnect please"


def test_not_connected_is_explained(settings):
    message = watcher(settings, FakeAccount(error=NotConnected("run youtube-connect"))).refresh()
    assert "run youtube-connect" in message


def test_a_youtube_failure_is_explained_and_keeps_the_old_numbers(settings):
    w = watcher(settings)
    w.refresh()
    w._fetch = FakeFetch(error=ChannelFetchError("quota exceeded"))
    assert "quota exceeded" in w.refresh()
    assert w.report() is not None


def test_refresh_if_stale_skips_fresh_numbers(settings):
    fetch = FakeFetch()
    w = watcher(settings, fetch=fetch)
    w.refresh_if_stale(timedelta(hours=6))
    w.refresh_if_stale(timedelta(hours=6))
    assert len(fetch.calls) == 1


def test_refresh_if_stale_never_raises(settings):
    w = watcher(settings, FakeAccount(error=NotConnected("no")))
    w.refresh_if_stale(timedelta(hours=6))  # automatic mode must not crash over the watcher


@pytest.mark.parametrize("hours,expected", [(1, False), (7, True)])
def test_stale_after_max_age(settings, hours, expected):
    w = watcher(settings, now=NOW)
    w.refresh()
    later = watcher(settings, now=NOW + timedelta(hours=hours))
    assert later.is_stale(timedelta(hours=6)) is expected
