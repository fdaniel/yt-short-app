"""The dashboard's single HTML page. Every value from feeds, the AI or the database is escaped."""

import base64
import hashlib
from datetime import datetime
from html import escape

from shorts.dashboard.app import TABS, DashboardView, VideoCard
from shorts.models import VideoStatus
from shorts.script.take import MAX_TAKE_WORDS

YOUTUBE_UPLOAD_URL = "https://www.youtube.com/upload"
YOUTUBE_STUDIO_URL = "https://studio.youtube.com"
YOUTUBE_TERMS_URL = "https://www.youtube.com/t/terms"
YOUTUBE_GUIDELINES_URL = "https://www.youtube.com/howyoutubeworks/policies/community-guidelines/"
CHANNEL_NAME = "Loadout Daily"
TAB_LABELS = {
    "review": "To review",
    "published": "Published",
    "making": "Being made",
    "discarded": "Discarded",
    "failed": "Failed",
}

# Bahnschrift ships with Windows (where the page is viewed): a narrow DIN face that reads like a game HUD.
_CSS = """
:root { --paper:#eef0ec; --card:#fbfcfa; --ink:#1a2128; --steel:#5e6a72; --line:#cdd3d1; --brand:#f4511e;
  --brand-ink:#fff; --marker:#fff1b8; --marker-edge:#e2c55a; --ok:#1e7f53; --bad:#c2332f; --notice:#e3efe8;
  --hud:"Bahnschrift", "DIN Alternate", "Barlow Semi Condensed", "Arial Narrow", sans-serif;
  --text:"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif; }
@media (prefers-color-scheme: dark) { :root { --paper:#1b2229; --card:#232c34; --ink:#e6eaec; --steel:#9aa6ae;
  --line:#35414b; --brand:#ff6a3d; --brand-ink:#1b2229; --marker:#3d3720; --marker-edge:#8a7630; --ok:#5cc595;
  --bad:#ff7b72; --notice:#24372d; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:15px/1.5 var(--text); }
a { color:inherit; text-underline-offset:3px; }
:focus-visible { outline:3px solid var(--brand); outline-offset:2px; }
.wrap { max-width:1180px; margin:0 auto; padding:0 16px; }
header { border-bottom:1px solid var(--line); background:var(--card); }
header .wrap { display:flex; flex-wrap:wrap; align-items:center; gap:10px 28px; padding-top:14px; padding-bottom:14px; }
.brand { display:flex; align-items:center; gap:12px; margin-right:auto; text-decoration:none; }
.mark { width:40px; height:40px; border-radius:50%; background:#f4511e; color:#fff; display:grid;
  place-items:center; font:700 17px/1 var(--hud); letter-spacing:.02em; }
.brand strong { font:600 22px/1 var(--hud); font-stretch:semi-condensed; display:block; }
.brand span { color:var(--steel); font-size:13px; }
.stat { font:400 15px/1.2 var(--hud); color:var(--steel); }
.stat b { font-weight:700; color:var(--ink); font-size:20px; }
.dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--steel); margin-right:6px; }
.dot.on { background:var(--ok); }
nav { display:flex; flex-wrap:wrap; gap:4px 22px; margin:20px 0 18px; border-bottom:1px solid var(--line); }
nav a { padding:8px 0 10px; text-decoration:none; color:var(--steel); font:500 16px/1 var(--hud);
  border-bottom:3px solid transparent; margin-bottom:-1px; }
nav a.on { color:var(--ink); border-bottom-color:var(--ink); }
nav a b { font-weight:700; }
.notice { background:var(--notice); border-left:4px solid var(--ok); padding:10px 14px; margin-bottom:18px;
  overflow-wrap:anywhere; }
.card { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:18px; margin-bottom:22px;
  display:grid; grid-template-columns:260px minmax(0, 1fr); gap:24px; }
@media (max-width:760px) { .card { grid-template-columns:1fr; } .player { max-width:300px; } }
.player video, .nofile { width:100%; aspect-ratio:9/16; background:#000; border-radius:4px; display:block; }
.nofile { display:grid; place-items:center; background:transparent; border:1px dashed var(--line); color:var(--steel); }
h2 { font:600 25px/1.15 var(--hud); font-stretch:semi-condensed; margin:0 0 6px; }
.facts { display:flex; flex-wrap:wrap; gap:4px 16px; color:var(--steel); font-size:13px; margin:0 0 4px; }
.why { color:var(--steel); font-size:13px; margin:0; }
.script { margin:16px 0 4px; padding:0 0 0 14px; border-left:3px solid var(--line); list-style:none; max-width:70ch; }
.script li { margin:3px 0; }
.script li:first-child { font-weight:600; }
.script li.take { background:var(--marker); box-shadow:0 0 0 3px var(--marker); }
.step { display:grid; grid-template-columns:30px minmax(0, 1fr); gap:12px; margin-top:18px; }
.num { width:28px; height:28px; border-radius:50%; border:2px solid var(--ink); display:grid; place-items:center;
  font:700 14px/1 var(--hud); }
.step h3 { font:600 17px/28px var(--hud); margin:0; }
.step p { margin:2px 0 8px; }
.step.mine { background:var(--marker); border:1px solid var(--marker-edge); border-radius:6px; padding:12px; margin-left:-12px; }
.row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.grow { flex:1 1 260px; }
input[type=text], input[type=datetime-local], textarea { font:inherit; color:var(--ink); background:var(--card);
  border:1px solid var(--line); border-radius:4px; padding:7px 10px; width:100%; }
input[type=datetime-local] { width:auto; }
textarea { font-size:13px; resize:vertical; }
label { display:block; font-weight:600; font-size:13px; margin:12px 0 4px; }
button, .button { font:500 15px/1 var(--hud); padding:9px 16px; border-radius:4px; border:1px solid var(--ink);
  background:transparent; color:var(--ink); cursor:pointer; text-decoration:none; display:inline-block; }
button.primary { background:var(--brand); border-color:var(--brand); color:var(--brand-ink); font-weight:700; }
button.danger { border-color:var(--bad); color:var(--bad); }
button.quiet { border-color:var(--line); }
button.suggest { font:400 14px/1.3 var(--text); border-color:var(--marker-edge); background:var(--card);
  border-radius:999px; padding:6px 12px; text-align:left; }
button.copy { font-size:12px; padding:3px 9px; margin-left:8px; border-color:var(--line); }
.small { font-size:13px; color:var(--steel); }
.ok { color:var(--ok); }
.bad { color:var(--bad); }
form { margin:0; }
details { margin-top:18px; border-top:1px solid var(--line); padding-top:10px; }
summary { cursor:pointer; font:500 15px/1.4 var(--hud); color:var(--steel); }
details ol { padding-left:20px; }
details li { margin:8px 0; }
.empty { padding:48px 0; color:var(--steel); font:400 18px/1.4 var(--hud); }
footer { margin:28px auto 40px; }
footer h2 { font-size:17px; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; background:var(--card); border:1px solid var(--line);
  border-radius:4px; padding:10px; color:var(--steel); }
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
document.addEventListener('click', (e) => {
  const button = e.target.closest('button.suggest');
  if (!button) return;
  const field = document.getElementById(button.dataset.target);
  field.value = button.dataset.text; field.focus();
});
document.addEventListener('submit', (e) => {
  const question = e.target.dataset.confirm;
  if (question && !confirm(question)) e.preventDefault();
});
"""

SCRIPT_HASH = "sha256-" + base64.b64encode(hashlib.sha256(_JS.encode()).digest()).decode()  # pinned in the CSP


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
            + (f'<p class="small">Other titles:</p><ul class="small">{alt}</ul>' if alt else "")
            + _copy_field(f"desc-{vid}", "Description", str(meta.get("description", "")), 7)
            + _copy_field(f"tags-{vid}", "Hashtags", " ".join(map(str, meta.get("hashtags", []))), 1))


def _script(card: VideoCard) -> str:
    """What the video says, so a wandering or wrong script shows before anyone presses play."""
    if not card.script_lines:
        return ""
    take = card.meta.get("owner_take")
    last = len(card.script_lines) - 1
    marked = ' class="take"'
    lines = "".join(f"<li{marked if take and i == last else ''}>{escape(line)}</li>"
                    for i, line in enumerate(card.script_lines))
    return f'<ol class="script" aria-label="What the video says">{lines}</ol>'


def _step(number: int, title: str, body: str, extra_class: str = "") -> str:
    cls = f"step {extra_class}".strip()
    return (f'<section class="{cls}"><span class="num" aria-hidden="true">{number}</span>'
            f"<div><h3>{escape(title)}</h3>{body}</div></section>")


def _take(card: VideoCard, view: DashboardView, token: str) -> str:
    """The owner's own closing line: real human input in every video, which YouTube's monetization review looks for."""
    vid = card.record.id
    current = card.meta.get("owner_take")
    shown = f'<p>In this video: <strong>{escape(str(current))}</strong></p>' if current else ""
    note = (f'<p class="{"ok" if "was added" in card.take_note else "bad"}">{escape(card.take_note)}</p>'
            if card.take_note else "")
    if not view.takes:
        return shown
    form = _form(vid, "take", token, view.tab,
                 f'<p>One sentence of your own opinion, up to {MAX_TAKE_WORDS} words. It replaces the last line'
                 " and the video is made again.</p>"
                 f'<span class="row"><input class="grow" type="text" id="take-{vid}" name="take" maxlength="120"'
                 ' aria-label="Your take" placeholder="Worth it if you liked Hades" required style="width:auto">'
                 "<button>Add my take</button></span>")
    if card.take_options:
        chips = "".join(f'<button type="button" class="suggest" data-target="take-{vid}" data-text="{escape(option)}">'
                        f"{escape(option)}</button>" for option in card.take_options)
        form += ('<p class="small" style="margin-top:12px">Suggestions: click one to fill the box, then edit it.'
                 f' Pick one only if you agree, because it should be your opinion.</p><div class="row">{chips}</div>')
    return shown + note + form


def _publish(card: VideoCard, view: DashboardView, token: str) -> str:
    vid, tab = card.record.id, view.tab
    if view.channel:
        upload = _form(vid, "upload", token, tab,
                       f'<button class="primary">Upload to {escape(view.channel.title)}</button>',
                       f"Upload video #{vid} to {view.channel.title} as {view.privacy} now?")
        # YouTube's API policies: an upload tool must show its users YouTube's terms
        terms = (f'<p class="small">Uploading means you agree to YouTube\'s '
                 f'<a href="{YOUTUBE_TERMS_URL}" target="_blank" rel="noopener noreferrer">Terms of Service</a> and '
                 f'<a href="{YOUTUBE_GUIDELINES_URL}" target="_blank" rel="noopener noreferrer">Community Guidelines</a>.'
                 "</p>")
    else:
        upload = ('<span class="small">One-click upload: connect your channel first with '
                  '<code>python -m shorts youtube-connect</code>.</span>')
        terms = ""
    discard = _form(vid, "discard", token, tab, '<button class="danger">Discard</button>',
                    f"Discard video #{vid}? Its video file will be deleted.")
    return f'<div class="row">{upload}{discard}</div>{terms}{_schedule_form(vid, token, tab, view)}'


def _by_hand(card: VideoCard, view: DashboardView, token: str) -> str:
    vid, tab = card.record.id, view.tab
    return (
        "<details><summary>YouTube texts and uploading by hand</summary>"
        f"{_texts(card)}<ol>"
        f'<li><span class="row">{_form(vid, "open-folder", token, tab, "<button class=quiet>Open the video folder</button>")}'
        f'<a class="button" href="/videos/{vid}.mp4?download=1">Download video</a></span></li>'
        f'<li><a class="button" href="{YOUTUBE_UPLOAD_URL}" target="_blank" rel="noopener noreferrer">'
        "Open YouTube upload ↗</a> Drag the video in, then paste the title, description and hashtags.</li>"
        f"<li>{_mark_form(vid, token, tab)}</li></ol></details>"
    )


def _review_actions(card: VideoCard, view: DashboardView, token: str) -> str:
    if card.take_busy:
        return _step(2, "Your take", '<p class="small">Adding your take: the video is being voiced and rendered again.'
                     " This takes several minutes (up to 15). Reload this page to check.</p>", "mine")
    watched = '<p class="small">Play it to the end: footage, voice and captions should all match the story.</p>'
    return (_step(1, "Watch it", watched)
            + _step(2, "Your take", _take(card, view, token), "mine")
            + _step(3, "Publish", _publish(card, view, token))
            + _by_hand(card, view, token))


def _schedule_form(vid: int, token: str, tab: str, view: DashboardView) -> str:
    if not view.can_schedule:
        return ('<p class="small">Scheduling here works once Google approves your app (see README); until then'
                " upload by hand and pick Schedule in YouTube Studio.</p>")
    return _form(vid, "schedule", token, tab,
                 f'<label for="when-{vid}">Publish at</label>'
                 f'<span class="row"><input type="datetime-local" name="publish_at" id="when-{vid}" required>'
                 "<button>Schedule</button></span>",
                 f"Upload video #{vid} to {view.channel.title} now and make it public at the time you picked?")


def _mark_form(vid: int, token: str, tab: str) -> str:
    return _form(vid, "mark-uploaded", token, tab,
                 f'<label for="link-{vid}">YouTube link (optional)</label>'
                 f'<span class="row"><input class="grow" type="text" id="link-{vid}" name="link"'
                 ' placeholder="https://youtube.com/shorts/…" style="width:auto">'
                 "<button>Mark as published</button></span>")


def _uploading_actions(card: VideoCard, view: DashboardView, token: str) -> str:
    vid = card.record.id
    return (f'<p class="bad">An upload started {_when(card.record.updated_at)} but was not confirmed. Check '
            f'<a href="{YOUTUBE_STUDIO_URL}" target="_blank" rel="noopener noreferrer">YouTube Studio ↗</a>: if the'
            " video is there, paste its link and press Mark as published; if not, put it back to review.</p>"
            + _mark_form(vid, token, view.tab)
            + f'<div class="row" style="margin-top:10px">'
            f'{_form(vid, "back-to-review", token, view.tab, "<button>Back to review</button>")}</div>')


def _status_line(card: VideoCard) -> str:
    r = card.record
    if r.status == VideoStatus.APPROVED:
        link = (f' <a href="https://youtube.com/shorts/{escape(r.youtube_id)}" target="_blank" rel="noopener noreferrer">'
                "Open on YouTube ↗</a>") if r.youtube_id else ""
        return f'<p class="ok">Published {_when(r.published_at)}{link}</p>'
    if r.status == VideoStatus.FAILED:
        return f'<p class="bad">Failed: {escape(r.failure_reason or "unknown reason")}</p>'
    if r.status in (VideoStatus.DISCARDED, VideoStatus.EXPIRED):
        return f'<p class="small">{escape(r.status.value.capitalize())} {_when(r.updated_at)}</p>'
    if r.status not in (VideoStatus.AWAITING_APPROVAL, VideoStatus.UPLOADING):
        return f'<p class="small">Being made: {escape(r.status.value.replace("_", " "))}</p>'
    return ""


def _card(card: VideoCard, view: DashboardView, token: str) -> str:
    r = card.record
    player = (f'<video controls preload="metadata" src="/videos/{r.id}.mp4"></video>' if card.has_file
              else '<div class="nofile">No video file</div>')
    facts = [f"<span>#{r.id}</span>", f"<span>Made {_when(r.created_at)}</span>"]
    if card.source:
        facts.append(f"<span>{escape(card.source)}</span>")
    if card.score is not None:
        facts.append(f"<span>Score {card.score:.2f}</span>")
    if r.news_url.startswith("https://"):
        facts.append(f'<a href="{escape(r.news_url)}" target="_blank" rel="noopener noreferrer">Source story ↗</a>')
    why = f'<p class="why">{escape(card.explanation)}</p>' if card.explanation else ""
    actions = {
        VideoStatus.AWAITING_APPROVAL: _review_actions,
        VideoStatus.UPLOADING: _uploading_actions,
    }.get(r.status, lambda *_: "")(card, view, token)
    texts = "" if r.status == VideoStatus.AWAITING_APPROVAL else _texts_folded(card)
    return (f'<article class="card"><div class="player">{player}</div><div>'
            f'<h2>{escape(r.title or card.meta.get("title") or "Untitled")}</h2>'
            f'<p class="facts">{"".join(facts)}</p>{why}{_status_line(card)}{_script(card)}'
            f"{actions}{texts}</div></article>")


def _texts_folded(card: VideoCard) -> str:
    return f"<details><summary>YouTube texts</summary>{_texts(card)}</details>"


def _header(view: DashboardView) -> str:
    channel = (f'<span class="stat"><span class="dot on"></span>YouTube: {escape(view.channel.title)}</span>'
               if view.channel else '<span class="stat"><span class="dot"></span>YouTube not connected</span>')
    return (f'<header><div class="wrap"><a class="brand" href="/"><span class="mark">LD</span>'
            f"<span><strong>{CHANNEL_NAME}</strong><span>Review desk</span></span></a>"
            f'<span class="stat">Made today <b>{view.made_today} of {view.daily_limit}</b></span>{channel}'
            "</div></header>")


def render(view: DashboardView, token: str, notice: str | None = None) -> str:
    tabs = "".join(
        f'<a href="/?tab={name}" class="{"on" if name == view.tab else ""}">{TAB_LABELS[name]} ({view.counts[name]})</a>'
        for name in TABS
    )
    empty = {"review": "Nothing here yet. New videos arrive after the next automatic run."}
    cards = ("".join(_card(c, view, token) for c in view.cards)
             or f'<p class="empty">{empty.get(view.tab, "Nothing here yet.")}</p>')
    banner = f'<div class="notice" role="status">{escape(notice)}</div>' if notice else ""
    runs = escape("\n".join(view.run_lines)) or "No automatic runs logged yet."
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22%3E'
        '%3Ccircle cx=%2216%22 cy=%2216%22 r=%2216%22 fill=%22%23f4511e%22/%3E%3Ctext x=%2216%22 y=%2221.5%22'
        ' font-family=%22Bahnschrift,Arial%22 font-weight=%22700%22 font-size=%2214%22 text-anchor=%22middle%22'
        ' fill=%22white%22%3ELD%3C/text%3E%3C/svg%3E">'
        f"<title>{CHANNEL_NAME} review desk</title><style>{_CSS}</style></head><body>"
        f'{_header(view)}<main class="wrap">{banner}<nav aria-label="Videos">{tabs}</nav>{cards}</main>'
        f'<footer class="wrap"><h2>Automatic runs</h2><pre>{runs}</pre></footer><script>{_JS}</script></body></html>'
    )
