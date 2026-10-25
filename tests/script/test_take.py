import pytest

from shorts.script.take import MAX_TAKE_WORDS, TakeError, clean_take


def test_a_take_is_tidied_and_ends_like_a_sentence():
    assert clean_take("  Worth it if you   liked Hades ") == "Worth it if you liked Hades."
    assert clean_take("Skip it until it leaves early access!") == "Skip it until it leaves early access!"


@pytest.mark.parametrize("text, why", [
    ("", "Type one sentence"),
    ("Yes", "at least"),
    (" ".join(["word"] * (MAX_TAKE_WORDS + 1)), f"at most {MAX_TAKE_WORDS} words"),
    ("Grab it at https://example.com now", "links"),
    ("Grab it at www.example.com now", "links"),
    ("1234 5678 !!!", "words"),
])
def test_unusable_takes_say_why(text, why):
    with pytest.raises(TakeError, match=why):
        clean_take(text)


def test_angle_brackets_never_reach_the_video():
    assert clean_take("Best <b>horror</b> deal this week") == "Best bhorror/b deal this week."


def test_suggested_takes_keep_only_usable_ones_without_numbers():
    from tests.script.drafts import draft

    d = draft(take_options=["  worth grabbing while it's free ", "Only 5 dollars, buy it", "see www.x.com",
                            "Yes", "Fun with friends, skip it solo!", "Wait for reviews first", "One too many"])
    assert d.take_options == ["worth grabbing while it's free.", "Fun with friends, skip it solo!",
                              "Wait for reviews first."]


def test_a_script_without_suggestions_is_fine():
    from tests.script.drafts import draft

    assert draft().take_options == [] and draft(take_options="nonsense").take_options == []
