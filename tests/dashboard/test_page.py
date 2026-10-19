from shorts.dashboard.app import Dashboard
from shorts.dashboard.page import render
from shorts.models import VideoStatus

from tests.dashboard.conftest import FakeAccount


def _html(settings, tab="review", account=None, notice=None):
    view = Dashboard(settings, account or FakeAccount(), opener=print).view(tab)
    return render(view, token="TOKEN123", notice=notice)


def test_story_text_cannot_inject_html(settings, make_ready_video):
    make_ready_video('<script>alert("x")</script>')
    html = _html(settings)
    assert '<script>alert("x")' not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)" in html


def test_review_card_has_player_copy_and_actions(settings, make_ready_video):
    vid = make_ready_video("RTX 5090 announced")
    html = _html(settings)
    assert f'src="/videos/{vid}.mp4"' in html
    assert "RTX 5090 announced" in html and "#NVIDIA" in html
    assert f'action="/videos/{vid}/upload"' in html and "Upload to Tech Bits" in html
    assert f'action="/videos/{vid}/discard"' in html and f'action="/videos/{vid}/mark-uploaded"' in html
    assert 'name="token" value="TOKEN123"' in html
    assert "https://www.youtube.com/upload" in html
    assert "0.81" in html and "fresh, 2 sources" in html


def test_without_channel_points_to_connect(settings, make_ready_video):
    make_ready_video()
    html = _html(settings, account=FakeAccount(channel=None))
    assert "/upload\"" not in html.replace("youtube.com/upload\"", "")
    assert "youtube-connect" in html


def test_tabs_show_counts_and_published_link(settings, make_ready_video):
    make_ready_video("A")
    vid = make_ready_video("B", VideoStatus.APPROVED)
    assert "Published (1)" in _html(settings) and "To review (1)" in _html(settings)
    html = _html(settings, "published")
    assert f'action="/videos/{vid}/upload"' not in html


def test_notice_and_daily_count(settings, make_ready_video):
    make_ready_video()
    html = _html(settings, notice="Video #1 discarded.")
    assert "Video #1 discarded." in html and "1 of 3" in html


def test_empty_tab_says_so(settings):
    assert "Nothing here yet" in _html(settings)
