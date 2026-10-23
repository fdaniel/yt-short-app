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
    monkeypatch.chdir(tmp_path)  # not the owner's real .env, which may hold stock video keys
    for name in ("PIXABAY_API_KEY", "PEXELS_API_KEY", "FALLBACK_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "probe_gemini", lambda settings: (False, "User location is not supported"))
    code = cli.main(["check-setup", "--config", str(write_config(tmp_path))])
    out = capsys.readouterr().out
    assert code == 1
    assert "ffmpeg" in out and "font" in out.lower() and "location is not supported" in out
    assert "! stock video key (PIXABAY_API_KEY or PEXELS_API_KEY)" in out


# --- automatic mode -------------------------------------------------------------------------

from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from shorts import auto_cli  # noqa: E402
from shorts.discovery.runner import RunLocked, RunReport  # noqa: E402
from shorts.models import TopicStatus  # noqa: E402
from shorts.storage.db import connect  # noqa: E402
from shorts.storage.topics import TopicRepository  # noqa: E402


def _run_once_with(monkeypatch, tmp_path, outcome):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(auto_cli, "KokoroTTS", lambda *a: None)

    def fake(*args, **kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(auto_cli, "run_once", fake)
    return cli.main(["run-once", "--config", str(write_config(tmp_path))])


def test_run_once_reports_made_video(tmp_path, capsys, monkeypatch):
    made = VideoResult(4, tmp_path / "exports/4/video.mp4", tmp_path / "exports/4/metadata.json")
    assert _run_once_with(monkeypatch, tmp_path, RunReport((made,), None, 12)) == 0
    assert "Made video #4" in capsys.readouterr().out


def test_run_once_reports_why_no_video(tmp_path, capsys, monkeypatch):
    assert _run_once_with(monkeypatch, tmp_path, RunReport((), "daily limit reached", 0)) == 0
    assert "No video this run: daily limit reached" in capsys.readouterr().out


def test_run_once_locked_is_not_an_error(tmp_path, capsys, monkeypatch):
    assert _run_once_with(monkeypatch, tmp_path, RunLocked("busy")) == 0
    assert "Another run is still working" in capsys.readouterr().out


def test_run_once_writes_log_file(tmp_path, monkeypatch):
    _run_once_with(monkeypatch, tmp_path, RunReport((), "nothing new", 3))
    log = tmp_path / "data" / "run.log"
    assert log.exists() and "nothing new" in log.read_text()


def test_schedule_help(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-24.04")
    cfg = write_config(tmp_path)
    assert cli.main(["schedule-help", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "schtasks /Create" in out and "/SC HOURLY /MO 2" in out and "-d Ubuntu-24.04" in out
    assert f"--cd {tmp_path}" in out and "-m shorts run-once" in out and "schtasks /Delete" in out


def test_topics_lists_latest_with_explanations(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    cfg = write_config(tmp_path)
    repo = TopicRepository(connect(tmp_path / "data" / "shorts.db"))
    when = datetime(2026, 10, 18, tzinfo=UTC)
    repo.record("https://a/1", "NVIDIA Blog", "Old story", when, TopicStatus.SKIPPED, 0.2, "below 0.55: dull")
    repo.record("https://a/2", "Xbox Wire", "MW4 launches", when, TopicStatus.MADE, 0.91, "interest 1.00x0.5")
    repo.record("https://a/3", "Xbox Wire", "Newest", when, TopicStatus.PICKED, 0.7, "freshness 1.00x0.3")
    assert cli.main(["topics", "--last", "2", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "Newest" in out and "MW4 launches" in out and "Old story" not in out
    assert "interest 1.00x0.5" in out and "made" in out


def test_run_once_crash_is_logged(tmp_path, monkeypatch):
    import sqlite3
    assert _run_once_with(monkeypatch, tmp_path, sqlite3.OperationalError("database is locked")) == 1
    log = (tmp_path / "data" / "run.log").read_text()
    assert "Run crashed" in log and "database is locked" in log


def test_run_once_made_path_and_lock_are_logged(tmp_path, monkeypatch):
    made = VideoResult(4, tmp_path / "exports/4/video.mp4", tmp_path / "exports/4/metadata.json")
    _run_once_with(monkeypatch, tmp_path, RunReport((made,), None, 12))
    _run_once_with(monkeypatch, tmp_path, RunLocked("busy"))
    log = (tmp_path / "data" / "run.log").read_text()
    assert "exports/4/video.mp4" in log and "Another run is still working" in log


def test_run_once_setup_problem_is_logged(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    log = tmp_path / "fallback.log"
    assert cli.main(["run-once", "--config", str(write_config(tmp_path)), "--log-file", str(log)]) == 1
    assert "GEMINI_API_KEY" in log.read_text()


# --- dashboard and YouTube ------------------------------------------------------------------

from shorts import publish_cli  # noqa: E402


class _FakeServer:
    instances: list = []

    def __init__(self, dashboard, host="127.0.0.1", port=8000):
        self.dashboard, self.port, self.served = dashboard, port, False
        _FakeServer.instances.append(self)

    def serve_forever(self):
        self.served = True
        raise KeyboardInterrupt

    def server_close(self):
        pass


def test_dashboard_command_serves_until_ctrl_c(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    opened = []
    monkeypatch.setattr(publish_cli, "DashboardServer", _FakeServer)
    monkeypatch.setattr(publish_cli, "open_on_windows", opened.append)
    code = cli.main(["dashboard", "--port", "8123", "--config", str(write_config(tmp_path))])
    assert code == 0
    server = _FakeServer.instances[-1]
    assert server.port == 8123 and server.served
    assert opened == ["http://localhost:8123/"]
    assert "http://localhost:8123/" in capsys.readouterr().out


def test_dashboard_port_busy_is_friendly(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    def busy(*args, **kwargs):
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(publish_cli, "DashboardServer", busy)
    assert cli.main(["dashboard", "--no-open", "--config", str(write_config(tmp_path))]) == 1
    assert "--port" in capsys.readouterr().err


def test_youtube_connect_without_client_file_explains(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert cli.main(["youtube-connect", "--config", str(write_config(tmp_path))]) == 1
    assert "client_secret.json" in capsys.readouterr().err


def test_youtube_connect_reports_channel(tmp_path, capsys, monkeypatch):
    from shorts.publish.youtube import Channel

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(publish_cli.YouTubeAccount, "connect", lambda self: Channel("UC1", "Tech Bits"))
    assert cli.main(["youtube-connect", "--config", str(write_config(tmp_path))]) == 0
    assert "Tech Bits" in capsys.readouterr().out


def test_open_on_windows_converts_linux_paths(monkeypatch, tmp_path):
    calls = []

    class Done:
        stdout = "\\\\wsl.localhost\\Ubuntu\\tmp\\x\n"

    monkeypatch.setattr(publish_cli.subprocess, "run", lambda args, **kw: calls.append(args) or Done())
    monkeypatch.setattr(publish_cli.subprocess, "Popen", lambda args, **kw: calls.append(args))
    publish_cli.open_on_windows(tmp_path)
    assert calls == [["wslpath", "-w", str(tmp_path)], ["explorer.exe", "\\\\wsl.localhost\\Ubuntu\\tmp\\x"]]


def test_youtube_connect_ctrl_c_is_calm(tmp_path, capsys, monkeypatch):
    def interrupted(self):
        raise KeyboardInterrupt

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(publish_cli.YouTubeAccount, "connect", interrupted)
    assert cli.main(["youtube-connect", "--config", str(write_config(tmp_path))]) == 1
    assert "cancelled" in capsys.readouterr().err.lower()
