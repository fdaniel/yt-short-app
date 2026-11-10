import pytest
from pydantic import ValidationError

from shorts.clips.text import ClipText, build_clip_prompt, fallback_text, write_clip_text
from shorts.llm.base import ProviderUnavailable

from tests.clips.helpers import FakeVision, clip_text


def test_the_prompt_names_the_game_and_forbids_guessing():
    prompt = build_clip_prompt("Crimson Desert")
    assert "Crimson Desert" in prompt
    assert "only what" in prompt.lower() and "readable" in prompt.lower()


def test_the_frames_and_game_go_to_the_vision_model():
    vision = FakeVision(result=clip_text())
    text = write_clip_text([b"jpg1", b"jpg2"], "Crimson Desert", [vision])
    assert text.hook == "Boss down in one combo"
    assert vision.calls[0][1] == [b"jpg1", b"jpg2"]


def test_the_next_model_is_tried_and_then_a_plain_text_is_used():
    broken = FakeVision(error=ProviderUnavailable("quota"))
    backup = FakeVision(result=clip_text(hook="Backup"))
    assert write_clip_text([b"x"], "Crimson Desert", [broken, backup]).hook == "Backup"
    plain = write_clip_text([b"x"], "Crimson Desert", [broken])
    assert plain == fallback_text("Crimson Desert")
    assert "Crimson Desert" in plain.title_options[0] and "#CrimsonDesert" in plain.hashtags


def test_a_clip_from_an_unknown_game_still_gets_a_title():
    assert fallback_text("").title_options[0]


def test_text_is_kept_short_enough_for_the_screen():
    with pytest.raises(ValidationError):
        clip_text(hook="word " * 30)
    with pytest.raises(ValidationError):
        clip_text(lines=["a", "b", "c", "d", "e"])
    assert ClipText.model_validate(clip_text().model_dump()) == clip_text()


def test_titles_that_clean_away_to_nothing_are_refused():
    with pytest.raises(ValidationError):
        clip_text(title_options=["\U0001F525\U0001F525", "Fine title", "Another"])
