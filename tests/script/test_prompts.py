from shorts.config import VideoSettings
from shorts.models import VideoFormat
from shorts.script.prompts import build_factcheck_prompt, build_script_prompt
from tests.script.drafts import SOURCE, article, draft


def test_script_prompt_rules():
    video = VideoSettings()
    p = build_script_prompt(article(), VideoFormat.SPEC_BREAKDOWN, [], video)
    assert "English" in p
    assert "only facts from the SOURCE" in p
    assert f"{video.min_words}-{video.max_words} words" in p
    assert "12 words" in p
    assert "verbatim" in p
    assert "viral" in p and "clickbait" in p
    assert SOURCE in p
    assert "spec" in p.lower()


def test_each_format_has_its_own_guide():
    prompts = {build_script_prompt(article(), f, [], VideoSettings()) for f in VideoFormat}
    assert len(prompts) == len(VideoFormat)


def test_feedback_included_when_present():
    p = build_script_prompt(article(), VideoFormat.NEWS_FLASH, ["unsupported claim: X"], VideoSettings())
    assert "unsupported claim: X" in p


def test_factcheck_prompt_lists_claims_and_source():
    p = build_factcheck_prompt(draft(), article())
    assert "launches January 30, 2025 at $1,999" in p and SOURCE in p


def test_prompt_forbids_emoji():
    assert "emoji" in build_script_prompt(article(), VideoFormat.NEWS_FLASH, [], VideoSettings())


def test_prompt_asks_for_generic_footage_search_terms():
    p = build_script_prompt(article(), VideoFormat.NEWS_FLASH, [], VideoSettings())
    assert "footage_queries" in p and "no brand" in p


def test_footage_queries_are_cleaned():
    from shorts.script.schema import ScriptDraft

    d = draft().model_copy(update={"footage_queries": ["  gaming   laptop ", "", "x" * 80]})
    assert ScriptDraft.model_validate(d.model_dump()).footage_queries == ["gaming laptop", "x" * 40]


def test_odd_footage_queries_never_fail_the_script():
    from shorts.script.schema import ScriptDraft

    data = draft().model_dump()
    assert ScriptDraft.model_validate({**data, "footage_queries": None}).footage_queries == []
    assert ScriptDraft.model_validate({**data, "footage_queries": ["laptop", 7, None]}).footage_queries == ["laptop"]
    assert ScriptDraft.model_validate({**data, "footage_queries": "laptop"}).footage_queries == []


def test_script_prompt_forbids_repeats_and_labels_the_ai_would_copy():
    p = build_script_prompt(article(), VideoFormat.NEWS_FLASH, [], VideoSettings())
    assert "Never repeat or reword the hook" in p
    assert "News flash:" not in p.split("No labels")[0] and "Format: What was announced" in p


def test_footage_queries_have_no_examples_to_copy():
    # the AI copied "gaming laptop", "circuit board closeup", "server room" into a cat game's video
    p = build_script_prompt(article(), VideoFormat.NEWS_FLASH, [], VideoSettings())
    assert "circuit board" not in p and "server room" not in p
    assert "what the story itself is about" in p
