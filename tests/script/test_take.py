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
