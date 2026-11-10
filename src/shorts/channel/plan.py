"""The owner's 90-day monetization plan (written 6 Nov 2026), so the watcher can check the channel against it."""

from dataclasses import dataclass
from datetime import date, timedelta

PLAN_START = date(2026, 11, 9)
PLAN_DAYS = 91
YPP_RULES_CHANGE = date(2027, 2, 1)  # new applicants need twice the watch hours or Shorts views from this day


@dataclass(frozen=True)
class PlanWeek:
    number: int
    title: str
    todo: tuple[str, ...]


@dataclass(frozen=True)
class Checkpoint:
    day: int
    subscribers: int
    shorts_over_5k: int
    watch_hours: int
    stayed_pct: int  # "viewed" share of Shorts in Studio
    own_share_pct: int  # share of uploads that are the owner's own gameplay or long guides

    @property
    def date(self) -> date:
        return PLAN_START + timedelta(days=self.day)


WEEKS: tuple[PlanWeek, ...] = (
    PlanWeek(1, "New identity and setup", (
        'New banner and bio: "Crimson Desert secrets + big game news".',
        "Two playlists: Crimson Desert Guides, Big Game News.",
        "Apply to Humble, Fanatical, Green Man Gaming and Amazon; make Keymailer and Lurkit profiles.")),
    PlanWeek(2, "First long guide", (
        "Long video #1: the complete version of your best Short topic (e.g. every ship or weapon location).",
        'Link every new Short to it with "Related video".')),
    PlanWeek(3, "Start a series", (
        '"Crimson Desert Secrets #1-7", one a day.',
        'Black Friday: one "best deals on games you\'d actually play" long video with affiliate links.')),
    PlanWeek(4, "First review", ("Which hooks hold 70%+ viewed? Copy them.", "Long video #3.")),
    PlanWeek(5, "Two long videos a week", (
        "Only if the first ones keep 30%+ of viewers to the end.",
        "Pick the next game to play after Crimson Desert.")),
    PlanWeek(6, "The Game Awards", ("The one week where more news makes sense: the biggest reveals, same day.",)),
    PlanWeek(7, "Holidays and the Steam winter sale", (
        '"Best games in the Steam sale" and "gifts for gamers" long videos with affiliate links.',)),
    PlanWeek(8, "Best of 2026", ('"Every Crimson Desert secret of 2026" compilation (long, from existing footage).',)),
    PlanWeek(9, "The Partner Program decision", (
        "Check Studio > Earn. If 1,000 subs + 4,000 hours by 31 Jan is in reach, go all-in on long videos.",
        "If not, aim for 500 subs and the fan-funding tier instead.")),
    PlanWeek(10, "Clean the shop window", (
        "Review the latest public uploads as a reviewer would. Make weak auto-news private.",)),
    PlanWeek(11, "Keep the rhythm", ("Part 2s of the month's winners. New game series starts.",)),
    PlanWeek(12, "Apply, if eligible", ("Last week of the old thresholds.",)),
    PlanWeek(13, "New rules, next 90 days", ("Compare results with the targets and write the next plan.",)),
)

CHECKPOINTS: tuple[Checkpoint, ...] = (
    Checkpoint(30, subscribers=100, shorts_over_5k=1, watch_hours=50, stayed_pct=65, own_share_pct=60),
    Checkpoint(60, subscribers=300, shorts_over_5k=4, watch_hours=400, stayed_pct=70, own_share_pct=70),
    Checkpoint(90, subscribers=500, shorts_over_5k=10, watch_hours=1200, stayed_pct=70, own_share_pct=70),
)


def plan_week(today: date) -> PlanWeek | None:
    offset = (today - PLAN_START).days
    if not 0 <= offset < PLAN_DAYS:
        return None
    return WEEKS[offset // 7]


def next_checkpoint(today: date) -> Checkpoint | None:
    return next((c for c in CHECKPOINTS if c.date >= today), None)
