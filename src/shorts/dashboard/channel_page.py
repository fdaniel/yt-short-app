"""The dashboard's Channel tab: the channel's numbers, read against the 90-day plan. Every value is escaped."""

from datetime import datetime
from html import escape

from shorts.channel.advice import Report, Target, Verdict

GRADE_LABELS = {"top": "Top", "ok": "OK", "weak": "Weak", "early": "Too early"}
LEVEL_CLASS = {"good": "ok", "warn": "", "bad": "bad"}
STUDIO = "https://studio.youtube.com"
DAILY_BARS = 28

CSS = """
.grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px; margin:0 0 22px; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:12px 14px; }
.tile b { display:block; font:700 26px/1.1 var(--hud); }
.tile span { color:var(--steel); font-size:13px; }
.panel { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:16px 18px; margin:0 0 22px; }
.panel h2 { font-size:21px; }
.tips { list-style:none; padding:0; margin:0; }
.tips li { padding:8px 0 8px 14px; border-left:3px solid var(--line); margin:6px 0; }
.tips li.ok { border-left-color:var(--ok); }
.tips li.bad { border-left-color:var(--bad); }
.meter { height:8px; background:var(--line); border-radius:4px; overflow:hidden; margin-top:4px; }
.meter i { display:block; height:100%; background:var(--brand); }
.target { margin:10px 0; }
.target .small { float:right; }
.bars { display:flex; align-items:flex-end; gap:2px; height:90px; }
.bars i { flex:1; background:var(--brand); min-height:1px; border-radius:2px 2px 0 0; }
.table { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { font:600 13px/1.2 var(--hud); color:var(--steel); }
td.n { text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
.grade { font:700 13px/1 var(--hud); padding:3px 8px; border-radius:999px; border:1px solid var(--line);
  white-space:nowrap; }
.grade.top { border-color:var(--ok); color:var(--ok); }
.grade.weak { border-color:var(--bad); color:var(--bad); }
.why-list { margin:4px 0 0; padding-left:18px; color:var(--steel); font-size:13px; }
"""


def _num(value: float | None, unit: str = "") -> str:
    if value is None:
        return "?"
    text = f"{value:,.1f}" if isinstance(value, float) and not value.is_integer() else f"{int(value):,}"
    return f"{text}{unit}"


def _when(moment: datetime) -> str:
    return moment.astimezone().strftime("%d %b %H:%M")


def _refresh(token: str, label: str = "Refresh now") -> str:
    return ('<form method="post" action="/channel/refresh" style="display:inline">'
            f'<input type="hidden" name="token" value="{escape(token)}"><button>{escape(label)}</button></form>')


def _tiles(report: Report) -> str:
    snap = report.snapshot
    last7 = sum(d.views for d in snap.days[-7:]) if snap.days else None
    subs28 = sum(d.subs_gained for d in snap.days) if snap.days else None
    tiles = [("Subscribers", _num(snap.subscribers)), ("Total views", _num(snap.total_views)),
             ("Views, last 7 days", _num(last7)), ("New subscribers, 28 days", _num(subs28)),
             ("Shorts views, 90 days", _num(snap.shorts_views_90d))]
    return '<div class="grid">' + "".join(f'<div class="tile"><b>{v}</b><span>{escape(k)}</span></div>'
                                          for k, v in tiles) + "</div>"


def _daily(report: Report) -> str:
    days = report.snapshot.days[-DAILY_BARS:]
    if not days:
        return ""
    top = max(d.views for d in days) or 1
    bars = "".join(f'<i style="height:{max(1, round(100 * d.views / top))}%" title="{d.day:%d %b}: {d.views:,} views">'
                   "</i>" for d in days)
    return (f'<section class="panel"><h2>Views per day</h2><div class="bars" role="img" aria-label="Views per day,'
            f' last {len(days)} days">{bars}</div><p class="small">{days[0].day:%d %b} to {days[-1].day:%d %b}.'
            " YouTube Analytics run about two days behind.</p></section>")


def _week(report: Report) -> str:
    if report.week is None:
        return '<section class="panel"><h2>The plan</h2><p>Outside the 90-day plan: time to write the next one.</p></section>'
    todo = "".join(f"<li>{escape(item)}</li>" for item in report.week.todo)
    return (f'<section class="panel"><h2>This week in the plan: W{report.week.number}, {escape(report.week.title)}'
            f"</h2><ul>{todo}</ul></section>")


def _tips(report: Report) -> str:
    if not report.tips:
        return '<section class="panel"><h2>Advice</h2><p class="ok">Nothing to fix right now. Keep the rhythm.</p></section>'
    items = "".join(f'<li class="{LEVEL_CLASS[t.level]}">{escape(t.text)}</li>' for t in report.tips)
    return f'<section class="panel"><h2>Advice</h2><ul class="tips">{items}</ul></section>'


def _target(target: Target) -> str:
    share = target.share
    width = 0 if share is None else round(100 * share)
    return (f'<div class="target"><span>{escape(target.label)}</span><span class="small">'
            f"{_num(target.current, target.unit)} of {_num(target.goal, target.unit)}</span>"
            f'<div class="meter"><i style="width:{width}%"></i></div></div>')


def _targets(report: Report) -> str:
    parts = []
    if report.checkpoint and report.targets:
        parts.append(f"<h2>Day {report.checkpoint.day} checkpoint ({report.checkpoint.date:%d %b %Y})</h2>"
                     + "".join(_target(t) for t in report.targets))
    parts.append("<h2>Partner Program (ad revenue)</h2><p class=\"small\">1,000 subscribers plus either the Shorts"
                 " views or the watch hours. Studio &gt; Earn has the official numbers.</p>"
                 + "".join(_target(t) for t in report.partner))
    return '<section class="panel">' + "".join(parts) + "</section>"


def _row(verdict: Verdict) -> str:
    v = verdict.video
    stayed = "?" if v.stayed is None else f"{v.stayed:.0%}"
    watched = "?" if v.avg_view_pct is None else f"{v.avg_view_pct:.0f}%"
    why = ("<ul class=\"why-list\">" + "".join(f"<li>{escape(r)}</li>" for r in verdict.reasons) + "</ul>"
           if verdict.reasons else "")
    link = f"https://youtube.com/shorts/{escape(v.youtube_id)}"
    kind = "App news" if v.from_app else "Yours"
    return (f'<tr><td><a href="{link}" target="_blank" rel="noopener noreferrer">{escape(v.title)}</a>{why}</td>'
            f"<td>{kind}</td><td>{_when(v.published_at)}</td><td class=\"n\">{v.duration_s // 60}:{v.duration_s % 60:02d}</td>"
            f'<td class="n">{v.views:,}</td><td class="n">{stayed}</td><td class="n">{watched}</td>'
            f'<td><span class="grade {verdict.grade}">{GRADE_LABELS[verdict.grade]}</span>'
            f'<div class="small">usual {verdict.compared_to:,}</div></td></tr>')


def _videos(report: Report) -> str:
    if not report.verdicts:
        return ""
    rows = "".join(_row(v) for v in report.verdicts)
    return ('<section class="panel"><h2>Recent Shorts</h2><p class="small">Each Short against the usual views of its'
            ' kind (yours or the app\'s news). "Kept watching" is the share of views YouTube counts as engaged (people'
            ' who did not swipe straight away); "Watched" is how much of the Short they saw on average. Studio\'s'
            ' "viewed vs swiped away" is the closest number there.</p>'
            '<div class="table"><table><thead><tr><th>Short</th><th>Kind</th><th>Posted</th><th>Length</th>'
            "<th>Views</th><th>Kept watching</th><th>Watched</th><th>Verdict</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></section>")


def render_channel(report: Report | None, watching: bool, token: str) -> str:
    if not watching:
        return '<p class="empty">The channel watcher is not available in this dashboard.</p>'
    if report is None:
        return (f'<section class="panel"><h2>No channel numbers yet</h2><p>Read them from YouTube now; after that'
                f" automatic mode updates them every few hours.</p>{_refresh(token, 'Read the channel now')}</section>")
    snap = report.snapshot
    updated = (f'<p class="small">Numbers from {_when(snap.taken_at)}. {_refresh(token)} '
               f'<a href="{STUDIO}" target="_blank" rel="noopener noreferrer">YouTube Studio ↗</a></p>')
    return (updated + _tiles(report) + _tips(report) + _week(report) + _targets(report) + _daily(report)
            + _videos(report))
