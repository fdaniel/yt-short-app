from shorts.config import VideoSettings
from shorts.script.checks import (
    length_problems,
    narration_lines,
    numbers_ungrounded,
    quotes_missing,
    word_count,
)
from shorts.script.schema import Claim
from tests.script.drafts import SOURCE, draft


def test_narration_lines_order():
    d = draft()
    assert narration_lines(d) == [d.hook, *d.body, d.closing]


def test_word_count():
    assert word_count(draft(hook="one two", body=["three", "four", "five six"], closing="seven")) == 7


def test_quote_must_be_verbatim():
    d = draft(claims=[Claim(text="costs $1,999", source_quote="priced at $1,999")])
    assert quotes_missing(d, SOURCE) == ["priced at $1,999"]


def test_quote_match_ignores_case_and_whitespace():
    d = draft(claims=[Claim(text="x", source_quote="the rtx 5090  launches")])
    assert quotes_missing(d, SOURCE) == []


def test_invented_number_flagged():
    d = draft(body=["It is 2x faster", "It costs $1,999.", "It has 32GB of memory"])
    assert numbers_ungrounded(d, SOURCE) == ["2"]


def test_grounded_numbers_pass():
    assert numbers_ungrounded(draft(), SOURCE) == []


def test_too_short_flagged():
    d = draft(hook="a b", body=["c", "d", "e"], closing="f")
    assert any("too short" in p for p in length_problems(d, VideoSettings()))


def test_too_long_flagged():
    long_line = " ".join(["word"] * 110)
    d = draft(body=[long_line, "x", "y"])
    assert any("too long" in p for p in length_problems(d, VideoSettings()))


def test_length_in_range_ok():
    line = " ".join(["word"] * 25)
    d = draft(hook="a b", body=[line, line, line], closing="c")
    assert length_problems(d, VideoSettings()) == []


def test_typographic_quotes_and_dashes_match_ascii():
    source = "NVIDIA’s new card – the “RTX 5090” is here."
    d = draft(claims=[Claim(text="x", source_quote='NVIDIA\'s new card - the "RTX 5090" is here')])
    assert quotes_missing(d, source) == []


def test_narration_lines_strip_emoji_and_markup():
    d = draft(hook="DLSS 5 \U0001F680 {is} here\\")
    assert narration_lines(d)[0] == "DLSS 5 is here"
