import json
from dataclasses import replace

from shorts.metadata import VideoMetadata, build_metadata, content_hash, write_metadata
from shorts.models import AssetKind, RightsBasis
from tests.script.drafts import article, draft


def test_metadata_rules(make_asset):
    d = draft(
        title_options=["GO VIRAL with RTX <5090>", "RTX 5090: price and date", "x" * 150],
        hashtags=["#nvidia", "#viral", "rtx5090", "#gpu", "#pc"],
    )
    trailer = make_asset(kind=AssetKind.TRAILER, rightsholder="CD PROJEKT RED")
    m = build_metadata(d, article(url="https://nvidianews.nvidia.com/x"), [trailer])
    assert m.title == "RTX 5090: price and date"
    assert all(len(t) <= 100 and "<" not in t and "viral" not in t.lower() for t in m.title_options)
    assert "#viral" not in m.hashtags and "#rtx5090" in m.hashtags and len(m.hashtags) <= 5
    assert "Source: https://nvidianews.nvidia.com/x" in m.description
    assert "Footage: CD PROJEKT RED (steam)" in m.description
    assert m.sources == ("https://nvidianews.nvidia.com/x",)
    assert m.rights[0]["rights_basis"] == "store_promo"


def test_description_strips_angle_brackets_and_is_bounded(make_asset):
    d = draft(description="<b>Big</b> news " + "y" * 6000)
    m = build_metadata(d, article(), [])
    assert "<" not in m.description and ">" not in m.description
    assert len(m.description) <= 5000
    assert m.description.rstrip().endswith("#gpu") or "Source:" in m.description


def test_music_credit(make_asset):
    music = make_asset(kind=AssetKind.MUSIC, rights_basis=RightsBasis.LICENSED, notes="calm.mp3 — YouTube Audio Library")
    m = build_metadata(draft(), article(), [music])
    assert "Music: calm.mp3 — YouTube Audio Library" in m.description


def test_all_titles_banned_falls_back_to_article_title():
    d = draft(title_options=["viral 1", "viral 2", "guaranteed views"])
    assert build_metadata(d, article(), []).title == "RTX 5090"


def test_hash_changes_with_metadata(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"abc")
    base = build_metadata(draft(), article(), [])
    assert content_hash(f, base) != content_hash(f, replace(base, title="other"))
    assert content_hash(f, base) == content_hash(f, base)


def test_write_metadata_json(tmp_path):
    m = build_metadata(draft(), article(), [])
    path = write_metadata(m, tmp_path / "metadata.json")
    assert json.loads(path.read_text())["title"] == m.title
    assert isinstance(m, VideoMetadata)
