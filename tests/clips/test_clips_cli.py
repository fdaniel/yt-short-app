import threading

from shorts import cli, clips_cli
from shorts.dashboard.app import _RUN_LOGGERS


def _config(tmp_path, inbox=True):
    cfg = tmp_path / "config.yaml"
    text = f"data_dir: {tmp_path / 'data'}\n"
    if inbox:
        text += f"clips:\n  inbox: {tmp_path / 'inbox'}\n"
    cfg.write_text(text)
    return cfg


def test_clips_are_off_until_the_inbox_is_set(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert cli.main(["clips", "--config", str(_config(tmp_path, inbox=False))]) == 1
    assert "clips:" in capsys.readouterr().err


def test_one_look_at_the_inbox_says_what_happened(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(clips_cli.ClipDesk, "tick", lambda self: ["Gameplay clip a.mp4 is video #7, waiting for review."])
    assert cli.main(["clips", "--config", str(_config(tmp_path))]) == 0
    assert "video #7" in capsys.readouterr().out


def test_an_empty_inbox_is_said_plainly(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(clips_cli.ClipDesk, "tick", lambda self: [])
    assert cli.main(["clips", "--config", str(_config(tmp_path))]) == 0
    assert "No new clips" in capsys.readouterr().out


def test_the_loop_keeps_looking_and_survives_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    from shorts.config import load_settings

    settings = load_settings(_config(tmp_path), {"GEMINI_API_KEY": "k"})
    calls, stop = [], threading.Event()

    def tick(self):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        stop.set()
        return []

    monkeypatch.setattr(clips_cli.ClipDesk, "tick", tick)
    loop = clips_cli.ClipLoop(settings, stop=stop, every_s=0.01)
    loop.run()
    assert len(calls) == 2


def test_no_loop_without_an_inbox(tmp_path):
    from shorts.config import load_settings

    assert clips_cli.start_clip_loop(load_settings(_config(tmp_path, inbox=False), {"GEMINI_API_KEY": "k"})) is None


def test_the_dashboard_footer_shows_what_the_clips_did():
    assert " shorts.clips.desk: " in _RUN_LOGGERS and " shorts.clips.loop: " in _RUN_LOGGERS
    assert clips_cli.log.name.startswith("shorts.clips.")
