import pytest

from shorts.voice.pronounce import speakable


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("ASUS and Dell", "[ASUS](/ˈAsus/) and Dell"),
        ("Asus laptops", "[Asus](/ˈAsus/) laptops"),
        ("ASUS's new handheld", "[ASUS's](/ˈAsusᵻz/) new handheld"),
        ("Intel XeSS support", "Intel [XeSS](/ˈɛksɛs/) support"),
        ("Ubisoft confirmed", "[Ubisoft](/ˈubisˌɔft/) confirmed"),
        ("play AAA games", "play triple-A games"),
        ("GTA VI arrives", "GTA six arrives"),
        ("16GB of memory", "16 gigabytes of memory"),
        ("up to 128 GB", "up to 128 gigabytes"),
        ("a 2TB SSD", "a 2 terabyte SSD"),
        ("3.5GHz boost", "3.5 gigahertz boost"),
        ("a 120Hz screen", "a 120 hertz screen"),
        ("a 450W card", "a 450 watt card"),
        ("8 ms latency", "8 millisecond latency"),
    ],
)
def test_tech_words_are_read_the_way_people_say_them(written, spoken):
    assert speakable(written) == spoken


def test_plain_text_and_acronyms_people_spell_out_are_untouched():
    text = "NVIDIA, AMD and MSI ship RTX GPUs with DLSS in 4K, says the CEO. Wow!"
    assert speakable(text) == text


def test_words_that_merely_contain_a_unit_are_untouched():
    assert speakable("GBA games and the WWE show at 5 PM") == "GBA games and the WWE show at 5 PM"


def test_the_voice_engine_reads_asus_as_a_word():
    from kokoro import KPipeline

    phonemes, _ = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", model=False).g2p(speakable("ASUS"))
    assert phonemes == "ˈAsus"
