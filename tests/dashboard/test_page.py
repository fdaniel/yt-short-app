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
    assert "Video #1 discarded." in html and f"1 of {settings.discovery.max_videos_per_day}" in html


def test_empty_tab_says_so(settings):
    assert "Nothing here yet" in _html(settings)


def test_uploading_card_offers_recovery_not_upload(settings, make_ready_video):
    from shorts.storage.db import connect
    from shorts.storage.repositories import VideoRepository

    vid = make_ready_video()
    conn = connect(settings.data_dir / "shorts.db")
    VideoRepository(conn).claim_upload(vid)
    conn.close()
    html = _html(settings)
    assert f'action="/videos/{vid}/upload"' not in html
    assert "YouTube Studio" in html and f'action="/videos/{vid}/back-to-review"' in html
    assert f'action="/videos/{vid}/mark-uploaded"' in html


def test_upload_confirm_states_privacy(settings, make_ready_video):
    make_ready_video()
    assert "as public" in _html(settings)


def test_upload_button_links_youtube_terms_and_guidelines(settings, make_ready_video):
    make_ready_video()
    html = _html(settings)
    assert 'href="https://www.youtube.com/t/terms"' in html
    assert 'href="https://www.youtube.com/howyoutubeworks/policies/community-guidelines/"' in html


def test_schedule_form_once_google_approved_the_app(settings, make_ready_video):
    make_ready_video()
    approved = settings.model_copy(update={"youtube": settings.youtube.model_copy(update={"audit_approved": True})})
    html = _html(approved)
    assert 'type="datetime-local" name="publish_at"' in html and ">Schedule</button>" in html


def test_schedule_explains_it_waits_for_google(settings, make_ready_video):
    make_ready_video()
    html = _html(settings)
    assert 'name="publish_at"' not in html and "Scheduling here works once Google approves" in html


def _take_html(settings, dash):
    return render(dash.view("review"), token="TOKEN123")


def test_review_card_offers_a_take_with_its_word_limit(settings, make_ready_video):
    vid = make_ready_video()
    dash = Dashboard(settings, FakeAccount(), opener=print, remake=lambda *_: None)
    html = _take_html(settings, dash)
    assert f'action="/videos/{vid}/take"' in html and 'name="take"' in html and "up to 12 words" in html


def test_card_shows_a_take_in_progress_and_hides_publishing(settings, make_ready_video):
    vid = make_ready_video()
    dash = Dashboard(settings, FakeAccount(), opener=print, remake=lambda *_: None, background=lambda job: None)
    dash.add_take(vid, "Worth it if you liked <i>Hades</i>")
    html = _take_html(settings, dash)
    assert "Adding your take" in html and f'action="/videos/{vid}/upload"' not in html


def test_card_shows_how_the_last_take_went_and_the_take_itself(settings, make_ready_video):
    vid = make_ready_video()
    meta = settings.data_dir / "exports" / str(vid) / "metadata.json"
    meta.write_text(meta.read_text().replace('"title":', '"owner_take": "Worth it <b>now</b>.", "title":'))
    dash = Dashboard(settings, FakeAccount(), opener=print, remake=lambda *_: None, background=lambda job: job())
    dash.add_take(vid, "Worth it if you liked Hades")
    html = _take_html(settings, dash)
    assert "Your take was added" in html and "Worth it &lt;b&gt;now&lt;/b&gt;." in html


def test_no_take_form_without_a_remaker(settings, make_ready_video):
    vid = make_ready_video()
    assert f'action="/videos/{vid}/take"' not in _html(settings)
