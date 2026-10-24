"""Make tech terms sound right: what the voice reads, never what the captions show.

The voice engine spells out any all-capitals word ("ASUS" -> "A-S-U-S"). Most tech acronyms are
meant to be spelled (AMD, GPU, RTX), so short ones are left alone and only the exceptions are listed
here, with their sound written in the engine's phoneme markup: [word](/phonemes/). Longer names in
capitals with vowels in them (LANCARSE, CAPCOM) are company names, read as words.
"""

import re

# word -> its sound; matched whole-word, ignoring case, with an optional possessive 's
_SOUNDS = {
    "asus": "ˈAsus",  # AY-soos
    "xess": "ˈɛksɛs",  # "excess"
    "ubisoft": "ˈubisˌɔft",  # OO-bee-soft
    "aion": "ˈIɑn",  # EYE-on (AION 2)
}
_POSSESSIVE = "ᵻz"
_WORDS = {
    re.compile(r"\bXBOX\b"): "Xbox",
    re.compile(r"\bAAA\b"): "triple-A",
    re.compile(r"\bGTA VI\b"): "GTA six",
}
# unit -> (singular, plural); singular before a noun ("a 2 terabyte SSD"), plural otherwise
_UNITS = {
    "GB": ("gigabyte", "gigabytes"),
    "TB": ("terabyte", "terabytes"),
    "MB": ("megabyte", "megabytes"),
    "GHz": ("gigahertz", "gigahertz"),
    "MHz": ("megahertz", "megahertz"),
    "Hz": ("hertz", "hertz"),
    "W": ("watt", "watts"),
    "ms": ("millisecond", "milliseconds"),
}
# a name in capitals ("LANCARSE", "CAPCOM'S"): long enough and with enough vowels to be a word, not an acronym
_CAPS_WORD = re.compile(r"\b([A-Z]{5,})('S)?\b")
_ROMAN = re.compile(r"[IVXLCDM]+")
_SOUND = re.compile(r"\b(" + "|".join(_SOUNDS) + r")('s)?\b", re.IGNORECASE)
_UNIT = re.compile(r"(\d)\s?(" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")\b(\s+(\w+))?")


def _sound(match: re.Match) -> str:
    word, possessive = match.group(1), match.group(2) or ""
    phonemes = _SOUNDS[word.lower()] + (_POSSESSIVE if possessive else "")
    return f"[{word}{possessive}](/{phonemes}/)"


def _caps_word(match: re.Match) -> str:
    word, possessive = match.group(1), match.group(2)
    if _ROMAN.fullmatch(word) or sum(letter in "AEIOU" for letter in word) < 2:
        return match.group(0)  # MMORPG, XVIII: spelled, as people say them
    return word.capitalize() + ("'s" if possessive else "")


def _unit(match: re.Match) -> str:
    digit, unit, after, next_word = match.group(1), match.group(2), match.group(3) or "", match.group(4)
    singular, plural = _UNITS[unit]
    before_noun = next_word is not None and next_word != "of"
    return f"{digit} {singular if before_noun else plural}{after}"


def speakable(text: str) -> str:
    text = _CAPS_WORD.sub(_caps_word, text)
    text = _SOUND.sub(_sound, text)
    for pattern, spoken in _WORDS.items():
        text = pattern.sub(spoken, text)
    return _UNIT.sub(_unit, text)
