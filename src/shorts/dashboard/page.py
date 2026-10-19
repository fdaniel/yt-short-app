"""The dashboard's single HTML page. Every value from feeds, the AI or the database is escaped."""

from datetime import datetime
from html import escape

from shorts.dashboard.app import TABS, DashboardView, VideoCard
from shorts.models import VideoStatus

YOUTUBE_UPLOAD_URL = "https://www.youtube.com/upload"
TAB_LABELS = {
    "review": "To review",
    "published": "Published",
    "making": "Being made",
    "discarded": "Discarded",
    "failed": "Failed",
}

_CSS = """
:root { --bg:#f6f7f9; --card:#fff; --text:#16181d; --muted:#5d6470; --line:#dde1e7; --accent:#2f6fed;
  --accent-text:#fff; --danger:#c62f3d; --ok:#1d7f4e; --notice:#fff7d6; }
@media (prefers-color-scheme: dark) { :root { --bg:#111317; --card:#1b1e24; --text:#e8eaee; --muted:#9aa2ae;
  --line:#2c313a; --accent:#5b8dff; --accent-text:#0b0d12; --danger:#ff6b78; --ok:#4cc38a; --notice:#3a3218; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.45 system-ui, sans-serif; }
header, main, footer { max-width:1100px; margin:0 auto; padding:16px; }
header { display:flex; flex-wrap:wrap; gap:8px 24px; align-items:baseline; justify-content:space-between; }
h1 { font-size:22px; margin:0; }
.muted { color:var(--muted); font-size:13px; }
.notice { background:var(--notice); border:1px solid var(--line); border-radius:8px; padding:10px 14px;
  margin-bottom:16px; overflow-wrap:anywhere; }
nav { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:16px; }
nav a { padding:6px 12px; border-radius:999px; border:1px solid var(--line); color:var(--text); text-decoration:none; }
nav a.on { background:var(--text); color:var(--bg); }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:16px;
  display:grid; grid-template-columns:240px 1fr; gap:20px; }
@media (max-width:700px) { .card { grid-template-columns:1fr; } }
video { width:100%; aspect-ratio:9/16; background:#000; border-radius:8px; }
.nofile { aspect-ratio:9/16; display:grid; place-items:center; border:1px dashed var(--line); border-radius:8px; }
h2 { font-size:17px; margin:0 0 4px; }
label { display:block; font-weight:600; font-size:13px; margin:12px 0 4px; }
textarea, input[type=text] { width:100%; font:inherit; font-size:13px; color:var(--text); background:var(--bg);
  border:1px solid var(--line); border-radius:6px; padding:6px 8px; }
textarea { resize:vertical; }
.row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:8px; }
button, .button { font:inherit; font-size:14px; padding:7px 14px; border-radius:6px; border:1px solid var(--line);
  background:var(--card); color:var(--text); cursor:pointer; text-decoration:none; display:inline-block; }
button.primary { background:var(--accent); color:var(--accent-text); border-color:var(--accent); }
button.danger { color:var(--danger); border-color:var(--danger); }
button.copy { font-size:12px; padding:2px 8px; margin-left:6px; }
form { margin:0; }
.steps { border-top:1px solid var(--line); margin-top:16px; padding-top:8px; }
.steps ol { margin:6px 0; padding-left:20px; }
.steps li { margin:6px 0; }
.ok { color:var(--ok); }
.bad { color:var(--danger); }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; background:var(--card); border:1px solid var(--line);
  border-radius:8px; padding:10px; }
a { color:var(--accent); }
"""

_JS = """
document.addEventListener('click', async (e) => {
  const button = e.target.closest('button.copy');
  if (!button) return;
  const field = document.getElementById(button.dataset.target);
  try { await navigator.clipboard.writeText(field.value); }
  catch { field.select(); document.execCommand('copy'); }
  button.textContent = 'Copied'; setTimeout(() => { button.textContent = 'Copy'; }, 1500);
});
document.addEventListener('submit', (e) => {
  const question = e.target.dataset.confirm;
  if (question && !confirm(question)) e.preventDefault();
});
"""


def _when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d %b %H:%M")
    except ValueError:
        return escape(iso)


def _form(video_id: int, action: str, token: str, tab: str, inner: str, confirm: str = "") -> str:
    ask = f' data-confirm="{escape(confirm)}"' if confirm else ""
    return (f'<form method="post" action="/videos/{video_id}/{action}"{ask}>'
            f'<input type="hidden" name="token" value="{escape(token)}">'
            f'<input type="hidden" name="tab" value="{escape(tab)}">{inner}</form>')


def _copy_field(field_id: str, label: str, value: str, rows: int) -> str:
    return (f'<label for="{field_id}">{escape(label)}<button type="button" class="copy" data-target="{field_id}">'
            f'Copy</button></label><textarea id="{field_id}" rows="{rows}" readonly>{escape(value)}</textarea>')


def _texts(card: VideoCard) -> str:
    vid, meta = card.record.id, card.meta
    if not meta:
        return '<p class="bad">metadata.json is missing or damaged.</p>'
    others = [t for t in meta.get("title_options", []) if t != meta.get("title")]
    alt = "".join(f"<li>{escape(str(t))}</li>" for t in others)
    return (_copy_field(f"title-{vid}", "Title", str(meta.get("title", "")), 2)
            + (f'<p class="muted">Other titles:</p><ul class="muted">{alt}</ul>' if alt else "")
            + _copy_field(f"desc-{vid}", "Description", str(meta.get("description", "")), 7)
            + _copy_field(f"tags-{vid}", "Hashtags", " ".join(map(str, meta.get("hashtags", []))), 1))


def _review_actions(card: VideoCard, view: DashboardView, token: str) -> str:
    vid, tab = card.record.id, view.tab
    if view.channel:
        auto = _form(vid, "upload", token, tab,
                     f'<button class="primary">Upload to {escape(view.channel.title)}</button>',
                     f"Upload video #{vid} to {view.channel.title} now?")
    else:
        auto = ('<span class="muted">One-click upload: connect your channel first with '
                '<code>python -m shorts youtube-connect</code>.</span>')
    by_hand = (
        '<div class="steps"><strong>Or upload by hand</strong><ol>'
        f'<li><span class="row">{_form(vid, "open-folder", token, tab, "<button>Open the video folder</button>")}'
        f'<a class="button" href="/videos/{vid}.mp4?download=1">Download video</a></span></li>'
        f'<li><a class="button" href="{YOUTUBE_UPLOAD_URL}" target="_blank" rel="noopener noreferrer">'
        "Open YouTube upload ↗</a> drag the video in, then paste the title, description and hashtags.</li>"
        "<li>"
        + _form(vid, "mark-uploaded", token, tab,
                '<label for="link-{0}">YouTube link (optional)</label>'
                '<span class="row"><input type="text" id="link-{0}" name="link" placeholder="https://youtube.com/shorts/…">'
                "<button>Mark as published</button></span>".format(vid))
        + "</li></ol></div>"
    )
    discard = _form(vid, "discard", token, tab, '<button class="danger">Discard</button>',
                    f"Discard video #{vid}? Its video file will be deleted.")
    return f'<div class="row">{auto}{discard}</div>{by_hand}'


def _status_line(card: VideoCard) -> str:
    r = card.record
    if r.status == VideoStatus.APPROVED:
        link = (f' <a href="https://youtube.com/shorts/{escape(r.youtube_id)}" target="_blank" rel="noopener noreferrer">'
                "Open on YouTube ↗</a>") if r.youtube_id else ""
        return f'<p class="ok">Published {_when(r.published_at)}{link}</p>'
    if r.status == VideoStatus.FAILED:
        return f'<p class="bad">Failed: {escape(r.failure_reason or "unknown reason")}</p>'
    if r.status in (VideoStatus.DISCARDED, VideoStatus.EXPIRED):
        return f'<p class="muted">{escape(r.status.value.capitalize())} {_when(r.updated_at)}</p>'
    if r.status != VideoStatus.AWAITING_APPROVAL:
        return f'<p class="muted">Being made: {escape(r.status.value.replace("_", " "))}</p>'
    return ""


def _card(card: VideoCard, view: DashboardView, token: str) -> str:
    r = card.record
    player = (f'<video controls preload="metadata" src="/videos/{r.id}.mp4"></video>' if card.has_file
              else '<div class="nofile muted">No video file</div>')
    facts = [f"#{r.id}", _when(r.created_at)]
    if card.source:
        facts.append(escape(card.source))
    if card.score is not None:
        facts.append(f"score {card.score:.2f}")
    why = f'<p class="muted">{escape(card.explanation)}</p>' if card.explanation else ""
    story = (f'<a href="{escape(r.news_url)}" target="_blank" rel="noopener noreferrer">Source story ↗</a>'
             if r.news_url.startswith("https://") else "")
    actions = _review_actions(card, view, token) if r.status == VideoStatus.AWAITING_APPROVAL else ""
    return (f'<article class="card"><div>{player}</div><div>'
            f'<h2>{escape(r.title or card.meta.get("title") or "Untitled")}</h2>'
            f'<p class="muted">{" · ".join(facts)} · {story}</p>{why}{_status_line(card)}'
            f"{_texts(card)}{actions}</div></article>")


def _header(view: DashboardView) -> str:
    channel = (f'<span class="ok">YouTube: {escape(view.channel.title)}</span>' if view.channel
               else '<span class="muted">YouTube not connected</span>')
    return (f'<header><h1>Tech Shorts</h1><span>Today: <strong>{view.made_today} of {view.daily_limit}</strong>'
            f" videos</span>{channel}</header>")


def render(view: DashboardView, token: str, notice: str | None = None) -> str:
    tabs = "".join(
        f'<a href="/?tab={name}" class="{"on" if name == view.tab else ""}">{TAB_LABELS[name]} ({view.counts[name]})</a>'
        for name in TABS
    )
    cards = "".join(_card(c, view, token) for c in view.cards) or '<p class="muted">Nothing here yet.</p>'
    banner = f'<div class="notice" role="status">{escape(notice)}</div>' if notice else ""
    runs = escape("\n".join(view.run_lines)) or "No automatic runs logged yet."
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22%3E'
        '%3Crect width=%2216%22 height=%2216%22 rx=%223%22 fill=%22%232f6fed%22/%3E%3Cpath d=%22M6 4l6 4-6 4z%22 fill=%22white%22/%3E%3C/svg%3E">'
        f"<title>Tech Shorts</title><style>{_CSS}</style></head><body>"
        f"{_header(view)}<main>{banner}<nav>{tabs}</nav>{cards}</main>"
        f'<footer><h2>Automatic runs</h2><pre>{runs}</pre></footer><script>{_JS}</script></body></html>'
    )
