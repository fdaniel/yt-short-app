import random

from shorts.models import AssetKind, RightsBasis
from shorts.music import pick_music


def test_music_without_licence_ignored(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.mp3").write_bytes(b"x")
    (tmp_path / "licenses.yaml").write_text("a.mp3: {source: YouTube Audio Library, licence: free}\n")
    music = pick_music(tmp_path, random.Random(1))
    assert music.local_path.name == "a.mp3"
    assert music.kind == AssetKind.MUSIC and music.rights_basis == RightsBasis.LICENSED
    assert music.rightsholder == "YouTube Audio Library"


def test_no_licences_means_no_music(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "licenses.yaml").write_text("")
    assert pick_music(tmp_path, random.Random(1)) is None


def test_missing_folder_means_no_music(tmp_path):
    assert pick_music(tmp_path / "nope", random.Random(1)) is None


def test_licence_entry_without_file_ignored(tmp_path):
    (tmp_path / "licenses.yaml").write_text("ghost.mp3: {source: X, licence: Y}\n")
    assert pick_music(tmp_path, random.Random(1)) is None


def test_licensed_tracks_lists_only_licensed(tmp_path):
    from shorts.music import licensed_tracks

    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "b.mp3").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / "licenses.yaml").write_text("a.mp3: {source: S, licence: L}\nb.mp3: {source: S}\n")
    assert [p.name for p, _ in licensed_tracks(tmp_path)] == ["a.mp3"]
