from shorts.config import VideoSettings
from shorts.script.checks import (
    subject_problems,
    repetition_problems,
    card_problems,
    length_problems,
    narration_lines,
    numbers_ungrounded,
    quotes_missing,
    word_count,
)
from shorts.script.schema import CardFact, Claim
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


def test_invented_number_on_card_flagged():
    d = draft(card_facts=[CardFact(label="Boost clock", value="2.9 GHz"), CardFact(label="Price", value="$1,999")])
    assert numbers_ungrounded(d, SOURCE) == ["2.9"]


def test_too_few_card_facts_flagged():
    # a real run returned none and the video was one static card for 40 s
    d = draft(card_facts=[CardFact(label="Price", value="$1,999")])
    assert any("card_facts" in p for p in card_problems(d))


def test_enough_card_facts_pass():
    assert card_problems(draft()) == []


PAD = ["It costs $1,999.", "It has 32GB of GDDR7 memory."]


def test_filler_label_flagged():
    problems = repetition_problems(draft(body=["News flash: it launches January 30.", *PAD]))
    assert len(problems) == 1 and "News flash" in problems[0]


def test_saying_twice_that_the_same_thing_is_out_flagged():
    problems = repetition_problems(draft(hook="Final Fantasy Resonance is out now with a free demo.",
                                         body=["Final Fantasy Resonance is available now on Xbox and PC.", *PAD]))
    assert len(problems) == 1 and "twice" in problems[0]


def test_different_things_available_now_pass():
    # an update and one of its features are two facts, not a repeat
    assert repetition_problems(draft(hook="A free Edgerunners 2 update is now live for Cyberpunk 2077.",
                                     body=["Dual wielding is now available with a pistol in each hand.", *PAD])) == []


def test_body_repeating_the_hook_flagged():
    problems = repetition_problems(draft(hook="Gamers logged millions of hours in AION 2 since launch.",
                                         body=["In the 18 days since launch, players logged more than 108 million hours.", *PAD]))
    assert len(problems) == 1 and "hook" in problems[0]


def test_sharing_a_topic_word_with_the_hook_passes():
    assert repetition_problems(draft(hook="Campaign early access for Modern Warfare 4 is live.",
                                     body=["DMZ early access starts October 20.", *PAD])) == []


def test_plain_draft_has_no_repetition():
    assert repetition_problems(draft()) == []


def test_quote_shortened_with_an_ellipsis_matches_when_every_part_is_verbatim():
    quote = "The RTX 5090 launches January 30... It has 32GB of GDDR7 memory."
    assert quotes_missing(draft(claims=[Claim(text="x", source_quote=quote)]), SOURCE) == []


def test_ellipsis_does_not_excuse_invented_words():
    quote = "The RTX 5090 launches January 30... It has 64GB of memory."
    assert quotes_missing(draft(claims=[Claim(text="x", source_quote=quote)]), SOURCE) == [quote]


def test_length_feedback_says_how_many_words_to_cut_or_add():
    video = VideoSettings(min_words=55, max_words=65)
    long_draft = draft(hook=" ".join(["word"] * 9), body=[" ".join(["word"] * 20)] * 3, closing="last")
    assert "cut at least 5 words" in length_problems(long_draft, video)[0]  # 70 words
    short_draft = draft(hook="a b", body=["c", "d", "e"], closing="f")
    assert "add at least 49 words" in length_problems(short_draft, video)[0]  # 6 words


def test_a_second_game_in_the_narration_is_a_problem():
    roundup = draft(hook="Call of Duty: Modern Warfare 4 arrives today on GeForce NOW.",
                    body=["Ultimate members get ray tracing.", "FINAL FANTASY RESONANCE brings pixel art to the cloud.",
                          "Six new games join this week."],
                    games_named=["Call of Duty: Modern Warfare 4", "FINAL FANTASY RESONANCE"])
    problems = subject_problems(roundup)
    assert len(problems) == 1 and "about Call of Duty: Modern Warfare 4 only" in problems[0]


def test_one_game_named_two_ways_or_only_listed_is_fine():
    focused = draft(hook="Call of Duty: Modern Warfare 4 arrives today on GeForce NOW.",
                    body=["Call of Duty fans can stream it in 4K.", "It runs at 120 frames per second.", "Ray tracing is on."],
                    games_named=["Call of Duty: Modern Warfare 4", "Call of Duty", "Hades"])
    assert subject_problems(focused) == []


def test_a_short_about_a_platform_may_name_the_games_it_adds():
    weekly = draft(hook="GeForce NOW adds six games this week, led by Modern Warfare 4.",
                   body=["Call of Duty: Modern Warfare 4 streams at launch.", "FINAL FANTASY RESONANCE joins too.",
                         "Fire TV Stick owners can now subscribe through Amazon."],
                   subject="GeForce NOW", games_named=["Call of Duty: Modern Warfare 4", "FINAL FANTASY RESONANCE"])
    assert subject_problems(weekly) == []
    about_the_game = weekly.model_copy(update={"subject": "Call of Duty: Modern Warfare 4"})
    assert "leave the others out" in subject_problems(about_the_game)[0]
