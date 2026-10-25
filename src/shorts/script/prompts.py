"""Prompt text for script writing and fact checking."""

from shorts.config import VideoSettings
from shorts.models import VideoFormat
from shorts.script.schema import ScriptDraft
from shorts.sources.article import Article

FORMAT_GUIDES: dict[VideoFormat, str] = {
    VideoFormat.NEWS_FLASH: "What was announced, when, and why it matters, in that order.",
    VideoFormat.SPEC_BREAKDOWN: "Walk through the key specs and numbers, one per line.",
    VideoFormat.VERSUS: "Compare the new product or game with its predecessor or rival, using only "
    "comparisons stated in the SOURCE.",
    VideoFormat.WHAT_CHANGED: "List the concrete differences from before, most important first.",
    VideoFormat.RELEASE_ROUNDUP: "Dates, platforms and prices, clearly separated.",
}
BODY_SENTENCES = 4
HOOK_WORDS = 10  # typical: at most 12
CLOSING_WORDS = 6


def sentence_plan(video: VideoSettings) -> str:
    """A shape that adds up to the lower part of the word range: a model keeps to sentence counts far
    better than to a word count, and still runs a little long (asked for 55-65 words, it wrote 63-90)."""
    target = video.min_words + (video.max_words - video.min_words) // 4
    per = round((target - HOOK_WORDS - CLOSING_WORDS) / BODY_SENTENCES)
    return (f"a hook of at most 12 words, exactly {BODY_SENTENCES} body sentences of {per - 1} to {per + 1} "
            f"words each, and a closing of {CLOSING_WORDS - 1} to {CLOSING_WORDS + 2} words")


def build_script_prompt(
    article: Article, fmt: VideoFormat, feedback: list[str], video: VideoSettings
) -> str:
    rules = f"""You write narration for a YouTube Short about tech and gaming news.

Rules:
- Write in English.
- Use only facts from the SOURCE below. Do not add anything you know from elsewhere.
- Total narration (hook + body + closing) must be {video.min_words}-{video.max_words} words. Shape it as
  {sentence_plan(video)}.
- One subject, named in the hook, and every body sentence and the closing tell the viewer more about it:
  - a game: the whole Short stays on that game (what is new, how it plays, when, where, price); never
    mention another game.
  - a platform, service or product (GeForce NOW, Game Pass, PlayStation Plus, a phone, a graphics card):
    the Short may cover what it offers or adds, such as this week's games or new features.
  A weekly roundup or list post is a Short about its platform or service, built from its highlights. Any
  other item that does not belong to the subject is left out, in the titles and description too.
- The hook and every title open with the subject's name, so the viewer knows at once what the Short is
  about (a roundup: "GeForce NOW adds ...", never "Call of Duty ... arrives on GeForce NOW").
- Write correct English: check grammar and plurals in every sentence.
- The closing stays on the same subject (what to look forward to, or a short question to viewers about it).
- The hook is at most 12 words, names the game or product (for an expansion or update, the main game too,
  e.g. its full name), and leads with the most striking concrete fact in the SOURCE (a new feature, a
  number, a surprise), not just that it is out or announced. No exaggeration.
- Every sentence adds a new fact. Never repeat or reword the hook or an earlier sentence, and say only once
  that something is out or available.
- No labels or filler such as "News flash", "Breaking news" or "In other news": start with the news.
- Talk like a gamer telling a friend, not like a press release: every sentence carries a concrete detail
  (a name, number, date, price or feature). No empty corporate lines such as "officially unveiled",
  "expands support across a broad range of platforms", "a new gameplay pillar" or "delivers an experience".
- Every number you say must appear in the SOURCE.
- For every factual claim, add an entry to "claims" whose source_quote is copied verbatim from the SOURCE.
- Plain text only: no emoji, no hashtags inside the narration.
- Do not call anything "viral", promise results, or use clickbait that distorts the facts.
- Titles: 3 honest options under 100 characters. Hashtags: 3 to 5, relevant only.
- card_facts: 2 to 6 short label/value pairs (specs, prices, dates, partners) taken from the SOURCE.
- footage_queries: 2 to 4 stock-video search terms of 2-3 words that show what the story itself is about
  (the kind of product, its use, its setting), generic objects or scenes only: no brand or product names,
  no people. Never use terms that have nothing to do with this story.
- subject: the game, platform, service or product this Short is about, as the hook names it.
- take_options: 3 short opinions (4 to 10 words each) a gamer might give about this news, each from a different
  angle (e.g. grab it now, who it suits or not, wait and see). Opinions only: no numbers, no new facts, and no
  other game unless the SOURCE names it. The channel owner picks one only if they agree.
- games_named: the video games your narration names, the hook's game first, up to 3, each title copied
  exactly as the SOURCE writes it; [] if it names none. Never a feature, mode, map, update or product name,
  and an expansion or DLC is not a separate game.
- Format: {FORMAT_GUIDES[fmt]}
"""
    fixes = ""
    if feedback:
        fixes = "\nYour previous attempt had these problems. Fix all of them:\n" + "\n".join(
            f"- {problem}" for problem in feedback
        )
    return f"{rules}{fixes}\n\nSOURCE ({article.url}):\n{article.text}\n"


def build_factcheck_prompt(draft: ScriptDraft, article: Article) -> str:
    claims = "\n".join(f"- {c.text}" for c in draft.claims)
    narration = "\n".join([draft.hook, *draft.body, draft.closing])
    return f"""You are a strict fact checker. For each claim, and for any other factual statement in
the narration, decide whether the SOURCE directly supports it. Anything not stated in the SOURCE
is unsupported, even if it is true elsewhere.

CLAIMS:
{claims}

NARRATION:
{narration}

SOURCE ({article.url}):
{article.text}
"""
