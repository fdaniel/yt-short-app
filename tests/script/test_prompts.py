from shorts.config import VideoSettings
from shorts.models import VideoFormat
from shorts.script.prompts import build_factcheck_prompt, build_script_prompt
from tests.script.drafts import SOURCE, article, draft


def test_script_prompt_rules():
    p = build_script_prompt(article(), VideoFormat.SPEC_BREAKDOWN, [], VideoSettings())
    assert "English" in p
    assert "only facts from the SOURCE" in p
    assert "65" in p and "100" in p
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
