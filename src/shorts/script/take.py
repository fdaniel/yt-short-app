"""The owner's own one-sentence take, voiced as a video's closing line."""

import re

MIN_TAKE_WORDS = 3
MAX_TAKE_WORDS = 12  # the AI's closing is 5-8 words: a longer take would push the video past its time limit
_LINK = re.compile(r"https?://|www\.|\b[\w-]+\.(com|net|org|io|gg|ly|tv|pt)\b", re.IGNORECASE)


class TakeError(ValueError):
    """A take that can't be voiced; the message is meant for the owner."""


def clean_take(text: str) -> str:
    take = " ".join(text.replace("<", "").replace(">", "").split())
    if not take:
        raise TakeError("Type one sentence: your own opinion of the story.")
    if _LINK.search(take):
        raise TakeError("No links in the take: the voice would read them out letter by letter.")
    words = [w for w in take.split() if re.search(r"[A-Za-z]", w)]
    if len(words) < MIN_TAKE_WORDS:
        raise TakeError(f"Use at least {MIN_TAKE_WORDS} words, so it reads as a sentence.")
    if len(take.split()) > MAX_TAKE_WORDS:
        raise TakeError(f"Use at most {MAX_TAKE_WORDS} words, so the video stays within its time limit.")
    return take if take[-1] in ".!?" else take + "."
