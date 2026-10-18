import pytest

from shorts.captions import CaptionChunk, chunk_captions, sanitize_caption_text, write_ass
from shorts.voice.narration import build_narration
from tests.fakes import FakeTTS


def test_chunks_stay_inside_their_line(tmp_path):
    n = build_narration(
        ["NVIDIA just announced DLSS 5 for every RTX card today.", "Big news."], FakeTTS(), tmp_path / "n.wav"
    )
    chunks = chunk_captions(n)
    first_line = [c for c in chunks if c.end <= n.lines[0].end + 1e-6]
    assert first_line[0].start == n.lines[0].start
    assert first_line[-1].end == pytest.approx(n.lines[0].end)
    assert chunks[-1].end == pytest.approx(n.lines[1].end)
    assert all(len(c.text) <= 28 and len(c.text.split()) <= 4 for c in chunks)
    assert all(a.end <= b.start + 1e-6 for a, b in zip(chunks, chunks[1:]))


def test_long_single_word_kept_whole(tmp_path):
    word = "Supercalifragilisticexpialidocious-Edition"
    n = build_narration([word], FakeTTS(), tmp_path / "n.wav")
    assert [c.text for c in chunk_captions(n)] == [word]


def test_sanitize_hostile_text():
    assert sanitize_caption_text("Wow {\\b1}fast\\N 🚀  now") == "Wow b1fastN now"


def test_ass_file(tmp_path):
    p = write_ass(
        [CaptionChunk("Hi", 0, 1.5), CaptionChunk("there {x}", 1.5, 3)],
        "Footage: CD PROJEKT RED / Steam",
        tmp_path / "c.ass",
    )
    txt = p.read_text()
    assert "PlayResX: 1080" in txt and "PlayResY: 1920" in txt
    assert txt.count("Dialogue:") == 3
    assert "0:00:01.50" in txt and "0:00:03.00" in txt
    assert "{x}" not in txt
    assert "Footage: CD PROJEKT RED / Steam" in txt


def test_captions_sit_below_card_text(tmp_path):
    # captions used to land on top of the hook card's text
    from shorts.captions import CAPTION_MARGIN_V, CAPTION_SIZE
    from shorts.media.cards import CANVAS, SAFE_BOX

    two_lines_top = CANVAS[1] - CAPTION_MARGIN_V - 2 * CAPTION_SIZE * 1.25
    assert two_lines_top > SAFE_BOX[3]
    txt = write_ass([CaptionChunk("Hi", 0, 1)], "c", tmp_path / "c.ass").read_text()
    assert f",{CAPTION_MARGIN_V},1" in txt.split("Style: Caption")[1].splitlines()[0]
    assert CANVAS[1] - CAPTION_MARGIN_V <= 1450  # stays clear of the Shorts title/buttons overlay
