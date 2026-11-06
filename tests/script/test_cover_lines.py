from shorts.script.schema import ScriptDraft
from tests.script.drafts import draft


def test_cover_lines_are_tidied_to_short_capital_lines():
    assert draft(cover_lines=[" dual ", "revolvers", "in  apex"]).cover_lines == ["DUAL", "REVOLVERS", "IN APEX"]


def test_cover_lines_too_long_or_odd_are_dropped():
    lines = ["MW4", "a line far too long for a cover", "", 7, "BATTLE PASS", "CATCH-UP", "EXTRA"]
    assert draft(cover_lines=lines).cover_lines == ["MW4", "BATTLE PASS", "CATCH-UP"]


def test_a_single_cover_line_is_no_cover():
    assert draft(cover_lines=["APEX"]).cover_lines == []


def test_a_script_without_cover_lines_still_loads():
    assert draft().cover_lines == []
    assert ScriptDraft.model_validate({**draft().model_dump(), "cover_lines": "APEX"}).cover_lines == []
