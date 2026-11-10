import pytest

from shorts.config import load_settings


@pytest.fixture
def clip_settings(tmp_path):
    inbox = tmp_path / "Loadout Inbox"
    cfg = tmp_path / "clips.yaml"
    cfg.write_text(f"data_dir: {tmp_path / 'data'}\nmusic_dir: {tmp_path / 'music'}\n"
                   f"clips:\n  inbox: {inbox}\n  auto_keep: 2\n  session_gap_min: 20\n")
    return load_settings(cfg, {"GEMINI_API_KEY": "test-key"}), inbox
