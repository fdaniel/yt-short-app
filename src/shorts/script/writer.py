"""Write a script and keep it only if every claim is grounded in the source."""

from shorts.config import VideoSettings
from shorts.llm.base import LLMProvider
from shorts.models import VideoFormat
from shorts.script.checks import (
    card_problems,
    length_problems,
    numbers_ungrounded,
    quotes_missing,
    repetition_problems,
)
from shorts.script.prompts import build_factcheck_prompt, build_script_prompt
from shorts.script.schema import FactCheckResult, ScriptDraft
from shorts.sources.article import Article

MAX_REWRITES = 1


class ScriptRejected(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("script rejected: " + "; ".join(problems))
        self.problems = problems


def _cheap_problems(draft: ScriptDraft, article: Article, video: VideoSettings) -> list[str]:
    missing = [f"source_quote not found verbatim in SOURCE: {q!r}" for q in quotes_missing(draft, article.text)]
    numbers = [f"number not in SOURCE: {n}" for n in numbers_ungrounded(draft, article.text)]
    return length_problems(draft, video) + card_problems(draft) + repetition_problems(draft) + missing + numbers


def _verdict_problems(draft: ScriptDraft, result: FactCheckResult) -> list[str]:
    problems = [f"unsupported claim: {v.claim} ({v.reason})" for v in result.verdicts if not v.supported]
    if len(result.verdicts) < len(draft.claims):
        problems.append(
            f"fact check did not judge every claim ({len(result.verdicts)} of {len(draft.claims)})"
        )
    return problems


def write_checked_script(
    article: Article, fmt: VideoFormat, llm: LLMProvider, video: VideoSettings
) -> ScriptDraft:
    feedback: list[str] = []
    for _ in range(1 + MAX_REWRITES):
        draft = llm.generate_json(build_script_prompt(article, fmt, feedback, video), ScriptDraft)
        problems = _cheap_problems(draft, article, video)
        if not problems:  # only spend an LLM call on the fact check when cheap checks pass
            result = llm.generate_json(build_factcheck_prompt(draft, article), FactCheckResult)
            problems = _verdict_problems(draft, result)
        if not problems:
            return draft
        feedback = problems
    raise ScriptRejected(feedback)
