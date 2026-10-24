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


def build_script_prompt(
    article: Article, fmt: VideoFormat, feedback: list[str], video: VideoSettings
) -> str:
    rules = f"""You write narration for a YouTube Short about tech and gaming news.

Rules:
- Write in English.
- Use only facts from the SOURCE below. Do not add anything you know from elsewhere.
- Total narration (hook + body + closing) must be {video.min_words}-{video.max_words} words.
- The hook is at most 12 words and makes people want to keep watching without exaggerating.
- Every sentence adds a new fact. Never repeat or reword the hook or an earlier sentence, and say only once
  that something is out or available.
- No labels or filler such as "News flash", "Breaking news" or "In other news": start with the news.
- Every number you say must appear in the SOURCE.
- For every factual claim, add an entry to "claims" whose source_quote is copied verbatim from the SOURCE.
- Plain text only: no emoji, no hashtags inside the narration.
- Do not call anything "viral", promise results, or use clickbait that distorts the facts.
- Titles: 3 honest options under 100 characters. Hashtags: 3 to 5, relevant only.
- card_facts: 2 to 6 short label/value pairs (specs, prices, dates, partners) taken from the SOURCE.
- footage_queries: 2 to 4 stock-video search terms of 2-3 words that show what the story itself is about
  (the kind of product, its use, its setting), generic objects or scenes only: no brand or product names,
  no people. Never use terms that have nothing to do with this story.
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
