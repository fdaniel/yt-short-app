from shorts import cli
from shorts.pipeline import PipelineError, VideoResult


def write_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"data_dir: {tmp_path / 'data'}\n")
    return cfg


def test_cli_make_video_reports_failure(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    def boom(*args, **kwargs):
        raise PipelineError("could not extract enough text from https://x")

    monkeypatch.setattr(cli, "make_video", boom)
    code = cli.main(["make-video", "--news-url", "https://x", "--config", str(write_config(tmp_path))])
    assert code == 1
    assert "could not extract enough text" in capsys.readouterr().err


def test_cli_make_video_success_prints_paths(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    result = VideoResult(7, tmp_path / "video.mp4", tmp_path / "metadata.json")
    monkeypatch.setattr(cli, "make_video", lambda *a, **k: result)
    code = cli.main(["make-video", "--news-url", "https://x", "--steam-app-id", "5", "--format", "versus",
                     "--config", str(write_config(tmp_path))])
    assert code == 0
    out = capsys.readouterr().out
    assert "video.mp4" in out and "metadata.json" in out


def test_cli_missing_key_is_friendly(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    assert cli.main(["make-video", "--news-url", "https://x", "--config", str(write_config(tmp_path))]) == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err


def test_check_setup_reports_each_check(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(cli, "probe_gemini", lambda settings: (False, "User location is not supported"))
    code = cli.main(["check-setup", "--config", str(write_config(tmp_path))])
    out = capsys.readouterr().out
    assert code == 1
    assert "ffmpeg" in out and "font" in out.lower() and "location is not supported" in out
