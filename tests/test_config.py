import pytest

from shorts.config import ConfigError, load_settings


def test_load_settings_reads_yaml_and_env(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"data_dir: {tmp_path}\n")
    s = load_settings(cfg, {"GEMINI_API_KEY": "k"})
    assert s.gemini_api_key == "k"
    assert s.fallback_api_key is None
    assert s.data_dir == tmp_path
    assert (s.video.min_narration_s, s.video.max_narration_s) == (30, 55)
    assert s.video.max_shot_s == 4.0 and s.video.max_trailer_share == 0.49
    assert s.video.max_output_mb == 50


def test_missing_gemini_key_fails_fast(tmp_path):
    (tmp_path / "c.yaml").write_text("")
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        load_settings(tmp_path / "c.yaml", {})


def test_blank_gemini_key_fails_fast(tmp_path):
    (tmp_path / "c.yaml").write_text("")
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        load_settings(tmp_path / "c.yaml", {"GEMINI_API_KEY": "  "})


def test_settings_are_immutable(tmp_path):
    (tmp_path / "c.yaml").write_text("")
    s = load_settings(tmp_path / "c.yaml", {"GEMINI_API_KEY": "k"})
    with pytest.raises(Exception):
        s.gemini_api_key = "x"


def test_unknown_yaml_key_rejected(tmp_path):
    (tmp_path / "c.yaml").write_text("max_videoz: 3\n")
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "c.yaml", {"GEMINI_API_KEY": "k"})


def test_nested_override_and_home_expansion(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("data_dir: ~/somewhere\nvideo:\n  max_output_mb: 40\n")
    s = load_settings(cfg, {"GEMINI_API_KEY": "k", "FALLBACK_LLM_API_KEY": "f"})
    assert "~" not in str(s.data_dir)
    assert s.video.max_output_mb == 40 and s.video.max_shot_s == 4.0
    assert s.fallback_api_key == "f"


def test_missing_config_file_fails_clearly(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "nope.yaml", {"GEMINI_API_KEY": "k"})


def test_default_gemini_model_follows_current_flash(tmp_path):
    # pinned versions get retired for new keys (2.5-flash returned 404 on 2026-10-18)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("")
    assert load_settings(cfg, {"GEMINI_API_KEY": "k"}).llm.gemini_model == "gemini-flash-latest"


def test_pexels_key_is_optional_and_read_from_env(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("")
    assert load_settings(cfg, {"GEMINI_API_KEY": "k"}).pexels_api_key is None
    assert load_settings(cfg, {"GEMINI_API_KEY": "k", "PEXELS_API_KEY": " p "}).pexels_api_key == "p"



def test_videos_alternate_a_female_and_a_male_voice_by_default(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("")
    assert load_settings(cfg, {"GEMINI_API_KEY": "k"}).voice.voices == ("af_heart", "am_michael")


def test_older_single_voice_config_still_loads(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("voice:\n  kokoro_voice: af_heart\n  lang_code: a\n  speed: 1.1\n")
    voice = load_settings(cfg, {"GEMINI_API_KEY": "k"}).voice
    assert voice.voices == ("af_heart", "am_michael") and voice.speed == 1.1


@pytest.mark.parametrize("voices", ["[]", "['../../etc/passwd']", "['xx_nobody']"])
def test_bad_voice_names_fail_fast(tmp_path, voices):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"voice:\n  voices: {voices}\n")
    with pytest.raises(ConfigError, match="voice"):
        load_settings(cfg, {"GEMINI_API_KEY": "k"})
