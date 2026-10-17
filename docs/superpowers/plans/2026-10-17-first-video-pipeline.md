# First Video Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given one official news URL (and optionally a Steam app ID), produce a finished, fact-checked, rights-logged 1080×1920 news Short (MP4 + metadata JSON) on disk, with one CLI command.

**Architecture:** A Python package `shorts` with one module per pipeline stage (sources → script → voice/captions → shots/crop/cards → timeline → render → metadata), wired by `pipeline.make_video`. External services (HTTP, LLM, TTS) are injected so the whole pipeline runs in tests with fakes and real FFmpeg. State and the rights log live in SQLite.

**Tech Stack:** Python 3.12 (WSL Ubuntu), FFmpeg (+libass), SQLite, pydantic v2, httpx, trafilatura, google-genai, Kokoro TTS (CPU torch), PySceneDetect + OpenCV headless, Pillow, PyYAML, pytest + respx + pytest-cov.

**Spec:** `docs/superpowers/specs/2026-10-17-tech-news-shorts-design.md` (this plan = spec §10 step 1, "One video by hand"). Later plans: Telegram approval (step 2), discovery/scheduling (3), results (4), YouTube API (5).

## Global Constraints

- €0: only free tiers and open-source tools that allow commercial use; never a paid API call.
- Output: 1080×1920, H.264 + AAC MP4, under 50 MB.
- Narration length 30–55 s.
- `rights_basis` values exactly: `press_kit_editorial`, `store_promo`, `licensed`, `generated`, `unknown`. `unknown` → asset cannot be used, no exceptions.
- Trailer audio always removed. Each trailer shot at most 4 s; trailer footage under 50% of runtime (use 0.49).
- Never download from YouTube. Never re-post another creator's video.
- Every factual claim must come from the official source text; at most one rewrite, else the topic is dropped.
- FFmpeg always invoked with argument lists, never shell strings.
- Secrets only in `.env`; never logged. `.env` and `config.yaml` are git-ignored; `.env.example` and `config.example.yaml` are committed.
- Video states: `scripting → fact_checked → rendering → awaiting_approval → approved | discarded | expired | failed`.
- Immutable data: frozen dataclasses / frozen pydantic models; functions return new objects.
- Files under 400 lines, functions under 50 lines; tests first; coverage ≥ 80%.
- Venv lives at `~/.venvs/tech-shorts` and data at `~/tech-shorts-data` (WSL filesystem — `/mnt/c` is slow for media I/O). All `pytest`/`python` commands assume `source ~/.venvs/tech-shorts/bin/activate` and cwd = repo root.
- Commit messages: `<type>: <description>` (feat, fix, refactor, docs, test, chore); no attribution trailer.

## Review Focus

1. **Steam app with HLS-only trailers or no trailers at all** → uses HLS via FFmpeg, or falls back to screenshots + generated cards; never crashes. (Task 5 parse tests; Task 13 no-movies E2E.)
2. **News page with little or no extractable text** (JS-rendered, cookie wall, paywall) → clear "could not extract text" failure, video marked `failed`, nothing invented. (Task 4; Task 13 failure E2E.)
3. **Gemini unavailable** (quota 429, bad key, region not supported) → falls back to the second free provider, then stops with a clear message; never a paid call. (Task 6.)
4. **Narration outside 30–55 s after TTS** (word count looked fine but voice is slower/faster) → video `failed` with the measured duration in the reason; nothing rendered. (Task 13.)
5. **Hostile characters** — braces, backslashes, quotes, colons, emoji, `<`/`>` in captions/titles, and spaces/apostrophes in work paths → stripped or escaped; render still succeeds; YouTube-invalid characters removed from metadata. (Tasks 8, 12, 13.)

---

### Task 1: Project skeleton, settings and shared types

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `config.example.yaml`, `src/shorts/__init__.py`, `src/shorts/config.py`, `src/shorts/models.py`, `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `shorts.config.load_settings(config_path: Path, env: Mapping[str, str]) -> Settings`; `ConfigError`
  - `Settings` (frozen pydantic): `data_dir: Path`, `music_dir: Path`, `font_file: Path`, `gemini_api_key: str`, `fallback_api_key: str | None`, `llm: LLMSettings(gemini_model="gemini-2.5-flash", fallback_base_url="https://api.groq.com/openai/v1", fallback_model="llama-3.3-70b-versatile")`, `voice: VoiceSettings(kokoro_voice="af_heart", lang_code="a", speed=1.0)`, `video: VideoSettings(min_narration_s=30, max_narration_s=55, min_words=75, max_words=140, max_shot_s=4.0, max_trailer_share=0.49, slot_s=3.5, max_output_mb=50, music_volume=0.12)`, `limits: LimitSettings(max_html_bytes=5_000_000, max_trailer_bytes=300_000_000, max_image_bytes=10_000_000, max_hls_seconds=180, ffmpeg_timeout_s=600, http_timeout_s=20)`
  - Defaults: `data_dir=~/tech-shorts-data`, `music_dir=<repo>/assets/music`, `font_file=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`
  - `shorts.models`: `StrEnum`s `RightsBasis`, `AssetKind` (`trailer`, `screenshot`, `card`, `music`), `VideoFormat` (`news_flash`, `spec_breakdown`, `versus`, `what_changed`, `release_roundup`), `VideoStatus` (the 8 states above); frozen dataclass `Asset(id: int | None, kind: AssetKind, local_path: Path, source_url: str | None, source_platform: str, rightsholder: str, rights_basis: RightsBasis, licence_terms_ref: str, music_stripped: bool, fetched_at: datetime, notes: str = "")`

- [ ] **Step 1: System setup (owner runs once; needs sudo)**

Run: `sudo apt update && sudo apt install -y ffmpeg python3.12-venv espeak-ng fonts-dejavu-core git`
Then: `python3 -m venv ~/.venvs/tech-shorts && source ~/.venvs/tech-shorts/bin/activate && pip install torch --index-url https://download.pytorch.org/whl/cpu`
Expected: `ffmpeg -version` prints a version with `--enable-libass`; `python -c "import torch"` succeeds. (CPU torch keeps the download small — disk is 87% full.)

- [ ] **Step 2: Create repo files**

`git init`. `pyproject.toml` (src layout, package `shorts`, deps: `httpx`, `trafilatura`, `pydantic>=2`, `pyyaml`, `python-dotenv`, `google-genai`, `kokoro`, `soundfile`, `numpy`, `scenedetect`, `opencv-python-headless`, `pillow`; extra `dev`: `pytest`, `pytest-cov`, `respx`; pytest marker `slow`). `.gitignore`: `.env`, `config.yaml`, `__pycache__/`, `*.egg-info`, `assets/music/*` except `assets/music/licenses.example.yaml`. `.env.example`: `GEMINI_API_KEY=` and `FALLBACK_LLM_API_KEY=`. `config.example.yaml`: every Settings field with its default. Run `pip install -e ".[dev]"`.

- [ ] **Step 3: Write the failing tests** in `tests/test_config.py`

```python
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

def test_settings_are_immutable(tmp_path):
    (tmp_path / "c.yaml").write_text("")
    s = load_settings(tmp_path / "c.yaml", {"GEMINI_API_KEY": "k"})
    with pytest.raises(Exception):
        s.gemini_api_key = "x"

def test_unknown_yaml_key_rejected(tmp_path):
    (tmp_path / "c.yaml").write_text("max_videoz: 3\n")
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "c.yaml", {"GEMINI_API_KEY": "k"})
```

- [ ] **Step 4: Run tests — expect FAIL** (`ImportError`). Run: `pytest tests/test_config.py -v`
- [ ] **Step 5: Implement `config.py` and `models.py`** — pydantic models with `model_config = ConfigDict(frozen=True, extra="forbid")`; `load_settings` reads YAML (empty file → `{}`), expands `~`, takes keys from `env` only (caller passes `os.environ` after `dotenv.load_dotenv()`), wraps `ValidationError` in `ConfigError`.
- [ ] **Step 6: Run tests — expect PASS.** Run: `pytest tests/test_config.py -v`
- [ ] **Step 7: Commit** — `git add -A && git commit -m "chore: project skeleton, settings and shared types"`

---

### Task 2: SQLite storage, video states and rights gate

**Files:**
- Create: `src/shorts/storage/__init__.py`, `src/shorts/storage/db.py`, `src/shorts/storage/repositories.py`, `src/shorts/rights.py`
- Test: `tests/storage/test_repositories.py`, `tests/test_rights.py`

**Interfaces:**
- Consumes: `shorts.models.*`
- Produces:
  - `db.connect(db_path: Path) -> sqlite3.Connection` — creates file, applies ordered migrations, idempotent; `row_factory = sqlite3.Row`; foreign keys on.
  - Tables: `videos(id, news_url, steam_app_id, format, status, failure_reason, title, script_json, output_path, metadata_path, content_hash, created_at, updated_at)`, `assets(id, video_id FK, kind, local_path, source_url, source_platform, rightsholder, rights_basis, licence_terms_ref, music_stripped, fetched_at, notes)`, `blocked_publishers(name PK, reason, blocked_at)`, `schema_version(version)`.
  - `VideoRepository(conn)`: `create(news_url: str, steam_app_id: int | None, fmt: VideoFormat) -> int` (status `scripting`); `get(video_id: int) -> VideoRecord`; `set_status(video_id: int, status: VideoStatus, failure_reason: str | None = None) -> None`; `save_script(video_id: int, script_json: str, title: str) -> None`; `save_output(video_id: int, output_path: Path, metadata_path: Path, content_hash: str) -> None`. `VideoRecord` frozen dataclass mirroring the row. `InvalidTransition(Exception)`.
  - `AssetRepository(conn)`: `add(asset: Asset, video_id: int) -> Asset` (returns copy with `id`); `list_for_video(video_id: int) -> list[Asset]`.
  - `BlocklistRepository(conn)`: `add(name: str, reason: str) -> None`; `names() -> set[str]` (lower-cased).
  - `rights.assert_usable(asset: Asset, blocked_publishers: set[str]) -> None`; `RightsError(Exception)`.

Allowed transitions (anything else raises `InvalidTransition`):

```python
ALLOWED = {
    "scripting": {"fact_checked", "failed"},
    "fact_checked": {"rendering", "failed"},
    "rendering": {"awaiting_approval", "failed"},
    "awaiting_approval": {"approved", "discarded", "expired"},
}
```

- [ ] **Step 1: Write the failing tests**

```python
def test_connect_is_idempotent(tmp_path):
    db = tmp_path / "s.db"
    connect(db).close(); conn = connect(db)
    assert conn.execute("select max(version) from schema_version").fetchone()[0] >= 1

def test_video_happy_path_transitions(conn):
    repo = VideoRepository(conn)
    vid = repo.create("https://nvidia.com/x", 1091500, VideoFormat.NEWS_FLASH)
    for s in ("fact_checked", "rendering", "awaiting_approval"):
        repo.set_status(vid, VideoStatus(s))
    assert repo.get(vid).status == VideoStatus.AWAITING_APPROVAL

def test_cannot_skip_fact_check(conn):
    repo = VideoRepository(conn); vid = repo.create("https://a.com", None, VideoFormat.NEWS_FLASH)
    with pytest.raises(InvalidTransition):
        repo.set_status(vid, VideoStatus.RENDERING)

def test_failed_stores_reason(conn):
    repo = VideoRepository(conn); vid = repo.create("https://a.com", None, VideoFormat.NEWS_FLASH)
    repo.set_status(vid, VideoStatus.FAILED, "no source text")
    assert repo.get(vid).failure_reason == "no source text"

def test_asset_roundtrip(conn, make_asset):
    vid = VideoRepository(conn).create("https://a.com", None, VideoFormat.NEWS_FLASH)
    saved = AssetRepository(conn).add(make_asset(), vid)
    assert saved.id is not None
    assert AssetRepository(conn).list_for_video(vid) == [saved]

def test_blocklist_case_insensitive(conn):
    BlocklistRepository(conn).add("CD PROJEKT RED", "claim on video 3")
    assert "cd projekt red" in BlocklistRepository(conn).names()
```

```python
# tests/test_rights.py
def test_unknown_rights_never_usable(make_asset):
    with pytest.raises(RightsError, match="unknown"):
        assert_usable(make_asset(rights_basis=RightsBasis.UNKNOWN), set())

def test_trailer_from_blocked_publisher_rejected(make_asset):
    a = make_asset(kind=AssetKind.TRAILER, rightsholder="Ubisoft")
    with pytest.raises(RightsError, match="blocked"):
        assert_usable(a, {"ubisoft"})

def test_screenshot_from_blocked_publisher_allowed(make_asset):
    assert_usable(make_asset(kind=AssetKind.SCREENSHOT, rightsholder="Ubisoft"), {"ubisoft"})

def test_trailer_with_audio_rejected(make_asset):
    with pytest.raises(RightsError, match="audio"):
        assert_usable(make_asset(kind=AssetKind.TRAILER, music_stripped=False), set())

def test_generated_card_usable(make_asset):
    assert_usable(make_asset(kind=AssetKind.CARD, rights_basis=RightsBasis.GENERATED), set())
```

Put `conn` (in-memory-file DB via `tmp_path`) and `make_asset(**overrides)` fixtures in `tests/conftest.py`.

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/storage tests/test_rights.py -v`
- [ ] **Step 3: Implement** `db.py`, `repositories.py` (parameterised SQL only; `updated_at` set on every status change), `rights.py`.
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: sqlite storage, video state machine and rights gate"`

---

### Task 3: FFmpeg wrapper

**Files:**
- Create: `src/shorts/media/__init__.py`, `src/shorts/media/ffmpeg.py`
- Test: `tests/media/test_ffmpeg.py`, `tests/media/conftest.py`

**Interfaces:**
- Produces:
  - `FFmpegError(Exception)` (message includes last 20 stderr lines)
  - `VideoInfo` frozen dataclass `(width: int, height: int, duration: float, has_audio: bool)`
  - `run_ffmpeg(args: list[str], *, timeout_s: int, cwd: Path | None = None) -> None` — prepends `["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]`; `subprocess.run(list, ...)`; timeout → `FFmpegError("ffmpeg timed out after N s")`.
  - `probe_video(path: Path) -> VideoInfo` (ffprobe JSON)
  - `strip_audio(src: Path, dest: Path, *, timeout_s: int) -> Path` (`-an -c:v copy`)
  - `download_hls(url: str, dest: Path, *, max_seconds: int, timeout_s: int) -> Path` (`-i url -t max_seconds -an -c:v copy`; Task 4 adds URL validation to it)
- Test fixture (in `tests/media/conftest.py`): `synthetic_video(tmp_path, *, size="1920x1080", seconds=6, audio=True) -> Path` built with `lavfi` (`testsrc2` + `sine`).

- [ ] **Step 1: Write the failing tests**

```python
def test_probe_synthetic(synthetic_video):
    info = probe_video(synthetic_video)
    assert (info.width, info.height) == (1920, 1080)
    assert info.has_audio and abs(info.duration - 6) < 0.2

def test_strip_audio(synthetic_video, tmp_path):
    out = strip_audio(synthetic_video, tmp_path / "noaudio.mp4", timeout_s=60)
    assert probe_video(out).has_audio is False

def test_bad_args_raise_with_stderr(tmp_path):
    with pytest.raises(FFmpegError, match="No such file"):
        run_ffmpeg(["-i", str(tmp_path / "missing.mp4"), str(tmp_path / "o.mp4")], timeout_s=30)

def test_timeout_raises(tmp_path):
    with pytest.raises(FFmpegError, match="timed out"):
        run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=duration=600", "-f", "null", "-"], timeout_s=1)
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/media/test_ffmpeg.py -v`
- [ ] **Step 3: Implement `ffmpeg.py`.**
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: safe ffmpeg wrapper with probe, strip-audio and hls download"`

---

### Task 4: Safe HTTP and article extraction

**Files:**
- Create: `src/shorts/net.py`, `src/shorts/sources/__init__.py`, `src/shorts/sources/article.py`
- Modify: `src/shorts/media/ffmpeg.py` (`download_hls` calls `validate_public_url`)
- Test: `tests/test_net.py`, `tests/sources/test_article.py`, `tests/fixtures/article_nvidia.html` (hand-written: `<title>`, nav/footer junk, ≥ 5 paragraphs of plausible GPU-launch text containing "$1,999" and "January 30, 2025")

**Interfaces:**
- Produces:
  - `UnsafeURLError(ValueError)`, `DownloadTooLarge(Exception)`
  - `validate_public_url(url: str) -> str` — only `http`/`https`, host required, rejects `localhost` and private/loopback/link-local IP literals.
  - `fetch_text(client: httpx.Client, url: str, *, max_bytes: int) -> str` — streams, aborts past `max_bytes`, raises `httpx.HTTPStatusError` on 4xx/5xx.
  - `download_file(client: httpx.Client, url: str, dest: Path, *, max_bytes: int) -> Path` — streams to `dest.with_suffix(".part")`, renames on success, deletes partial on failure.
  - `build_http_client(settings: Settings) -> httpx.Client` — timeout `settings.limits.http_timeout_s`, `follow_redirects=True`, `User-Agent: tech-shorts/0.1 (personal news tool)`.
  - `Article` frozen dataclass `(url: str, title: str, text: str, domain: str)`; `SourceTextError(Exception)`; `MIN_TEXT_CHARS = 400`
  - `extract_article(url: str, html: str) -> Article` (trafilatura, no comments/tables)
  - `fetch_article(client: httpx.Client, url: str, *, max_bytes: int) -> Article`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("bad", ["file:///etc/passwd", "ftp://x.com/a", "http://localhost/a",
                                 "http://127.0.0.1/", "http://10.0.0.5/", "http://[::1]/", "notaurl"])
def test_validate_rejects(bad):
    with pytest.raises(UnsafeURLError):
        validate_public_url(bad)

@respx.mock
def test_fetch_text_size_cap():
    respx.get("https://news.example.com/a").respond(200, text="x" * 2000)
    with httpx.Client() as c, pytest.raises(DownloadTooLarge):
        fetch_text(c, "https://news.example.com/a", max_bytes=1000)

@respx.mock
def test_download_file_cleans_partial_on_cap(tmp_path):
    respx.get("https://cdn.example.com/t.mp4").respond(200, content=b"0" * 5000)
    with httpx.Client() as c, pytest.raises(DownloadTooLarge):
        download_file(c, "https://cdn.example.com/t.mp4", tmp_path / "t.mp4", max_bytes=1000)
    assert list(tmp_path.iterdir()) == []
```

```python
def test_extract_article_fixture():
    html = (FIXTURES / "article_nvidia.html").read_text()
    a = extract_article("https://nvidianews.nvidia.com/news/x", html)
    assert a.domain == "nvidianews.nvidia.com"
    assert "$1,999" in a.text and len(a.text) >= MIN_TEXT_CHARS
    assert "Cookie settings" not in a.text  # nav/footer junk removed

def test_js_only_page_fails_clearly():
    html = "<html><body><div id='root'></div><script>app()</script></body></html>"
    with pytest.raises(SourceTextError, match="could not extract enough text"):
        extract_article("https://example.com/news", html)
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/test_net.py tests/sources/test_article.py -v`
- [ ] **Step 3: Implement** `net.py`, `article.py`; add the `validate_public_url` call in `download_hls`.
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: safe http helpers and article extraction"`

---

### Task 5: Steam source and trailer/screenshot assets

**Files:**
- Create: `src/shorts/sources/steam.py`
- Test: `tests/sources/test_steam.py`, `tests/fixtures/steam_mp4.json`, `tests/fixtures/steam_hls_only.json`, `tests/fixtures/steam_no_movies.json`, `tests/fixtures/steam_fail.json` (`{"123": {"success": false}}`)

**Interfaces:**
- Consumes: `net.fetch_text`, `net.download_file`, `net.validate_public_url`, `ffmpeg.strip_audio`, `ffmpeg.download_hls`, `models.Asset`, `config.Settings`
- Produces:
  - `SteamError(Exception)`
  - `SteamMovie` frozen dataclass `(id: int, name: str, mp4_url: str | None, hls_url: str | None, highlight: bool)`
  - `SteamApp` frozen dataclass `(app_id: int, name: str, publishers: tuple[str, ...], movies: tuple[SteamMovie, ...], screenshots: tuple[str, ...])`
  - `parse_appdetails(app_id: int, payload: dict) -> SteamApp` — `mp4_url` from `movies[].mp4.max` (fallback `mp4."480"`); `hls_url` from `movies[].hls_h264` if present; screenshots from `screenshots[].path_full`. Tolerates missing keys.
  - `fetch_steam_app(client: httpx.Client, app_id: int, *, max_bytes: int) -> SteamApp` — `GET https://store.steampowered.com/api/appdetails?appids={id}&cc=us&l=english`
  - `MAX_TRAILERS = 2`, `MAX_SCREENSHOTS = 4`
  - `collect_steam_assets(app: SteamApp, client: httpx.Client, work_dir: Path, settings: Settings, blocked: set[str]) -> list[Asset]` — trailers (highlight first; skipped entirely if any publisher is in `blocked`): download (mp4 via `download_file`, else HLS via `download_hls` with `max_hls_seconds`), then `strip_audio`, asset `kind=trailer, source_platform="steam", rights_basis=store_promo, music_stripped=True, licence_terms_ref="steam-store-promo: short news-coverage excerpts (owner decision, option A)"`, `rightsholder` = first publisher; screenshots downloaded with `max_image_bytes`, `kind=screenshot`. A failed single download is logged and skipped, not fatal.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_mp4_app():
    app = parse_appdetails(1091500, load("steam_mp4.json"))
    assert app.name and app.publishers == ("CD PROJEKT RED",)
    assert app.movies[0].mp4_url.startswith("https://")
    assert len(app.screenshots) >= 1

def test_parse_hls_only_movie():
    m = parse_appdetails(1, load("steam_hls_only.json")).movies[0]
    assert m.mp4_url is None and m.hls_url.endswith(".m3u8")

def test_parse_no_movies():
    assert parse_appdetails(2, load("steam_no_movies.json")).movies == ()

def test_parse_failure_raises():
    with pytest.raises(SteamError, match="123"):
        parse_appdetails(123, load("steam_fail.json"))

def test_blocked_publisher_gets_no_trailers(tmp_path, settings, monkeypatch):
    app = parse_appdetails(1091500, load("steam_mp4.json"))
    monkeypatch.setattr(steam, "download_file", fake_download)   # writes a tiny file
    assets = collect_steam_assets(app, httpx.Client(), tmp_path, settings, {"cd projekt red"})
    assert {a.kind for a in assets} == {AssetKind.SCREENSHOT}

def test_trailer_assets_are_audio_free_and_logged(tmp_path, settings, monkeypatch, synthetic_video):
    monkeypatch.setattr(steam, "download_file", copy_from(synthetic_video))
    assets = collect_steam_assets(parse_appdetails(1091500, load("steam_mp4.json")),
                                  httpx.Client(), tmp_path, settings, set())
    trailers = [a for a in assets if a.kind == AssetKind.TRAILER]
    assert 1 <= len(trailers) <= MAX_TRAILERS
    assert all(a.music_stripped and a.rights_basis == RightsBasis.STORE_PROMO for a in trailers)
    assert all(probe_video(a.local_path).has_audio is False for a in trailers)
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/sources/test_steam.py -v`
- [ ] **Step 3: Implement `steam.py`.**
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: steam store source with rights-logged trailer and screenshot assets"`

---

### Task 6: LLM providers with free fallback

**Files:**
- Create: `src/shorts/llm/__init__.py`, `src/shorts/llm/base.py`, `src/shorts/llm/gemini.py`, `src/shorts/llm/openai_compat.py`, `src/shorts/llm/chain.py`
- Test: `tests/llm/test_chain.py`, `tests/llm/test_openai_compat.py`, `tests/llm/test_gemini.py`

**Interfaces:**
- Produces:
  - `base.py`: `ProviderUnavailable(Exception)` (quota, auth, region, network, 5xx), `InvalidOutput(Exception)` (not JSON / fails schema), `AllProvidersExhausted(Exception)`; `class LLMProvider(Protocol): name: str; def generate_json(self, prompt: str, schema: type[T]) -> T` where `T` bound to `pydantic.BaseModel`.
  - `GeminiProvider(api_key: str, model: str, client: genai.Client | None = None)` — `client.models.generate_content(model=..., contents=prompt, config={"response_mime_type": "application/json", "response_schema": schema, "temperature": 0.4})`, parse `response.text` with `schema.model_validate_json`. `google.genai.errors.APIError` with code 429/401/403/5xx or a "location is not supported" message → `ProviderUnavailable`.
  - `OpenAICompatProvider(base_url: str, api_key: str, model: str, http: httpx.Client)` — `POST {base_url}/chat/completions` with `response_format={"type": "json_object"}`; the JSON schema (`schema.model_json_schema()`) appended to the prompt; 401/403/429/5xx/network → `ProviderUnavailable`.
  - `FallbackLLM(providers: list[LLMProvider])` implements `LLMProvider` (`name="fallback"`): tries in order; on `ProviderUnavailable` or `InvalidOutput` moves on; all fail → `AllProvidersExhausted` listing each provider's error. Never logs prompts or keys.
  - `build_llm(settings: Settings, http: httpx.Client) -> FallbackLLM` — Gemini first; fallback provider only if `settings.fallback_api_key` is set.

- [ ] **Step 1: Write the failing tests**

```python
class Out(BaseModel):
    answer: str

def test_fallback_used_when_first_unavailable():
    llm = FallbackLLM([Failing(ProviderUnavailable("429")), Returning(Out(answer="ok"))])
    assert llm.generate_json("p", Out).answer == "ok"

def test_fallback_on_invalid_output():
    llm = FallbackLLM([Failing(InvalidOutput("not json")), Returning(Out(answer="ok"))])
    assert llm.generate_json("p", Out).answer == "ok"

def test_all_exhausted_message_names_providers():
    llm = FallbackLLM([Failing(ProviderUnavailable("quota"), name="gemini"),
                       Failing(ProviderUnavailable("quota"), name="groq")])
    with pytest.raises(AllProvidersExhausted, match="gemini.*groq"):
        llm.generate_json("p", Out)

@respx.mock
@pytest.mark.parametrize("status", [401, 429, 503])
def test_openai_compat_unavailable(status):
    respx.post("https://api.groq.com/openai/v1/chat/completions").respond(status)
    p = OpenAICompatProvider("https://api.groq.com/openai/v1", "k", "m", httpx.Client())
    with pytest.raises(ProviderUnavailable):
        p.generate_json("p", Out)

@respx.mock
def test_openai_compat_bad_json_is_invalid_output():
    respx.post(...).respond(200, json={"choices": [{"message": {"content": "{nope"}}]})
    with pytest.raises(InvalidOutput): ...

@respx.mock
def test_openai_compat_parses_valid():
    respx.post(...).respond(200, json={"choices": [{"message": {"content": '{"answer": "hi"}'}}]})
    assert ....generate_json("p", Out).answer == "hi"

def test_gemini_429_is_unavailable():
    p = GeminiProvider("k", "gemini-2.5-flash", client=FakeGenaiClient(raises=APIError(429, ...)))
    with pytest.raises(ProviderUnavailable): p.generate_json("p", Out)

def test_gemini_region_error_is_unavailable(): ...  # message "User location is not supported"

def test_build_llm_without_fallback_key(settings_no_fallback):
    assert [p.name for p in build_llm(settings_no_fallback, httpx.Client()).providers] == ["gemini"]
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/llm -v`
- [ ] **Step 3: Implement the four modules.** Construct `APIError` for tests the way the installed `google-genai` version defines it (check its signature).
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: gemini and openai-compatible llm providers with free fallback chain"`

---

### Task 7: Script writer with fact checks

**Files:**
- Create: `src/shorts/script/__init__.py`, `src/shorts/script/schema.py`, `src/shorts/script/prompts.py`, `src/shorts/script/checks.py`, `src/shorts/script/writer.py`
- Test: `tests/script/test_checks.py`, `tests/script/test_writer.py`, `tests/script/test_prompts.py`

**Interfaces:**
- Consumes: `Article`, `LLMProvider`, `VideoFormat`, `VideoSettings`
- Produces:
  - `schema.py` (frozen pydantic): `Claim(text: str, source_quote: str)`, `CardFact(label: str, value: str)`, `ScriptDraft(hook: str, body: list[str] (3–6), closing: str, title_options: list[str] (exactly 3), description: str, hashtags: list[str] (3–5), claims: list[Claim] (≥1), card_facts: list[CardFact] (0–6))`, `ClaimVerdict(claim: str, supported: bool, reason: str)`, `FactCheckResult(verdicts: list[ClaimVerdict])`
  - `prompts.build_script_prompt(article: Article, fmt: VideoFormat, feedback: list[str]) -> str` and `prompts.build_factcheck_prompt(draft: ScriptDraft, article: Article) -> str`
  - `checks.narration_lines(draft) -> list[str]` (`[hook, *body, closing]`), `checks.word_count(draft) -> int`, `checks.length_problems(draft, video: VideoSettings) -> list[str]`, `checks.quotes_missing(draft, source_text: str) -> list[str]`, `checks.numbers_ungrounded(draft, source_text: str) -> list[str]`
  - `writer.MAX_REWRITES = 1`; `ScriptRejected(Exception)` with `.problems: list[str]`; `write_checked_script(article: Article, fmt: VideoFormat, llm: LLMProvider, video: VideoSettings) -> ScriptDraft`

Prompt must state (assert these phrases in `test_prompts.py`): English; use only facts from the SOURCE; narration `{min_words}–{max_words}` words; hook ≤ 12 words; every claim's `source_quote` copied verbatim from SOURCE; no "viral", no guarantees, no clickbait that distorts; format-specific instruction per `VideoFormat`; the feedback list when non-empty.

Writer loop (decides call budget — at most 4 LLM calls per video):

```python
feedback: list[str] = []
for attempt in range(1 + MAX_REWRITES):
    draft = llm.generate_json(build_script_prompt(article, fmt, feedback), ScriptDraft)
    problems = (length_problems(draft, video) + quotes_missing(draft, article.text)
                + numbers_ungrounded(draft, article.text))
    if not problems:  # only pay for the LLM fact check when cheap checks pass
        result = llm.generate_json(build_factcheck_prompt(draft, article), FactCheckResult)
        problems = [f"unsupported claim: {v.claim} ({v.reason})" for v in result.verdicts if not v.supported]
    if not problems:
        return draft
    feedback = problems
raise ScriptRejected(feedback)
```

Number grounding: tokens matching `\d[\d,.]*\d|\d` in narration lines, trailing `.`/`,` stripped, commas removed; each must appear in the source text with commas removed.

- [ ] **Step 1: Write the failing tests**

```python
SOURCE = "The RTX 5090 launches January 30, 2025 at $1,999. It has 32GB of GDDR7 memory."

def test_quote_must_be_verbatim():
    d = draft(claims=[Claim(text="costs $1,999", source_quote="priced at $1,999")])
    assert quotes_missing(d, SOURCE) == ["priced at $1,999"]

def test_quote_match_ignores_case_and_whitespace():
    d = draft(claims=[Claim(text="x", source_quote="the rtx 5090  launches")])
    assert quotes_missing(d, SOURCE) == []

def test_invented_number_flagged():
    d = draft(body=["It is 2x faster", "It costs $1,999", "It has 32GB of memory"])
    assert numbers_ungrounded(d, SOURCE) == ["2"]

def test_too_short_flagged(video_settings):
    assert any("too short" in p for p in length_problems(draft_with_words(60), video_settings))

def test_too_long_flagged(video_settings):
    assert any("too long" in p for p in length_problems(draft_with_words(150), video_settings))

def test_rewrite_once_then_success(video_settings):
    llm = ScriptedLLM([bad_quote_draft, good_draft, FactCheckResult(verdicts=[ok])])
    assert write_checked_script(article(SOURCE), VideoFormat.NEWS_FLASH, llm, video_settings) == good_draft
    assert llm.calls == 3
    assert "priced at" in llm.prompts[1]          # feedback reached the rewrite prompt

def test_rejected_after_one_rewrite(video_settings):
    llm = ScriptedLLM([bad_quote_draft, bad_quote_draft])
    with pytest.raises(ScriptRejected) as e:
        write_checked_script(article(SOURCE), VideoFormat.NEWS_FLASH, llm, video_settings)
    assert llm.calls == 2 and e.value.problems

def test_llm_fact_check_rejection_counts(video_settings):
    no = ClaimVerdict(claim="c", supported=False, reason="not in source")
    llm = ScriptedLLM([good_draft, FactCheckResult(verdicts=[no]), good_draft, FactCheckResult(verdicts=[no])])
    with pytest.raises(ScriptRejected): write_checked_script(...)
    assert llm.calls == 4
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/script -v`
- [ ] **Step 3: Implement the five modules.**
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: fact-checked script writer with one rewrite"`

---

### Task 8: Voice and captions

**Files:**
- Create: `src/shorts/voice/__init__.py`, `src/shorts/voice/tts.py`, `src/shorts/voice/narration.py`, `src/shorts/captions.py`
- Test: `tests/voice/test_narration.py`, `tests/voice/test_kokoro.py` (marked `slow`), `tests/test_captions.py`

**Interfaces:**
- Produces:
  - `class TTSEngine(Protocol): def synthesize(self, text: str) -> tuple[np.ndarray, int]` (mono float32, sample rate)
  - `KokoroTTS(voice: str, lang_code: str, speed: float)` — lazily builds `kokoro.KPipeline(lang_code=...)`, concatenates the audio of all yielded results; sample rate 24000.
  - `NarrationLine(text: str, start: float, end: float)`, `Narration(audio_path: Path, duration: float, lines: tuple[NarrationLine, ...])` (frozen)
  - `build_narration(lines: list[str], tts: TTSEngine, out_wav: Path, gap_s: float = 0.15) -> Narration` — synthesizes **each line separately** (this is how caption timing is known exactly), joins with `gap_s` silence, writes WAV via `soundfile`.
  - `CaptionChunk(text: str, start: float, end: float)` (frozen)
  - `sanitize_caption_text(text: str) -> str` — removes `{`, `}`, `\`, and characters outside the Basic Multilingual Plane (emoji); collapses whitespace.
  - `chunk_captions(narration: Narration, max_chars: int = 28, max_words: int = 4) -> list[CaptionChunk]` — splits each line into word groups; each chunk's time is proportional to its character count within its line.
  - `write_ass(chunks: list[CaptionChunk], credit_text: str, out_path: Path, font_name: str = "DejaVu Sans") -> Path` — `PlayResX: 1080`, `PlayResY: 1920`; style `Caption` (size 78, bold, white, black outline 6, Alignment 2, MarginL 120, MarginR 200, MarginV 700 — clear of Shorts UI); style `Credit` (size 34, Alignment 7, MarginL 60, MarginV 120, outline 3) shown for the full duration; times `H:MM:SS.cc`; all text through `sanitize_caption_text`.

- [ ] **Step 1: Write the failing tests**

```python
class FakeTTS:  # 0.05 s per character, 24 kHz
    def synthesize(self, text): return np.zeros(int(len(text) * 0.05 * 24000), np.float32), 24000

def test_narration_timing(tmp_path):
    n = build_narration(["Hello there.", "Second line here."], FakeTTS(), tmp_path / "n.wav")
    assert n.lines[0].start == 0 and n.lines[1].start == pytest.approx(n.lines[0].end + 0.15)
    assert n.duration == pytest.approx(n.lines[-1].end, abs=0.01)
    assert sf.info(n.audio_path).duration == pytest.approx(n.duration, abs=0.01)

def test_chunks_stay_inside_their_line(tmp_path):
    n = build_narration(["NVIDIA just announced DLSS 5 for every RTX card today."], FakeTTS(), tmp_path / "n.wav")
    chunks = chunk_captions(n)
    assert chunks[0].start == n.lines[0].start and chunks[-1].end == pytest.approx(n.lines[0].end)
    assert all(len(c.text) <= 28 and len(c.text.split()) <= 4 for c in chunks)

def test_sanitize_hostile_text():
    assert sanitize_caption_text("Wow {\\b1}fast\\N 🚀  now") == "Wow b1fastN now"

def test_ass_file(tmp_path):
    p = write_ass([CaptionChunk("Hi", 0, 1.5), CaptionChunk("there", 1.5, 3)], "Footage: CD PROJEKT RED / Steam", tmp_path / "c.ass")
    txt = p.read_text()
    assert "PlayResX: 1080" in txt and "PlayResY: 1920" in txt
    assert txt.count("Dialogue:") == 3                    # 2 captions + 1 credit
    assert "0:00:01.50" in txt

@pytest.mark.slow
def test_kokoro_real():
    audio, sr = KokoroTTS("af_heart", "a", 1.0).synthesize("Hello world.")
    assert sr == 24000 and len(audio) / sr > 0.3
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/voice tests/test_captions.py -v`
- [ ] **Step 3: Implement.** First Kokoro run downloads its model weights (~330 MB) and a spaCy English model.
- [ ] **Step 4: Run — expect PASS**, including `pytest -m slow tests/voice -v` once.
- [ ] **Step 5: Commit** — `git commit -m "feat: per-line kokoro narration and ass captions"`

---

### Task 9: Shot detection and scoring

**Files:**
- Create: `src/shorts/media/shots.py`
- Test: `tests/media/test_shots.py`

**Interfaces:**
- Consumes: `probe_video`
- Produces:
  - `Shot` frozen dataclass `(source: Path, asset_id: int, start: float, end: float, score: float)`
  - `detect_shots(video: Path, asset_id: int, *, skip_head_s: float = 3.0, skip_tail_s: float = 8.0, min_len_s: float = 1.5) -> list[Shot]` — PySceneDetect `detect(str(video), ContentDetector())`; whole video as one scene if none found; scenes clipped to `[skip_head_s, duration - skip_tail_s]` (skips rating boards, logos and end cards); drops scenes shorter than `min_len_s`; `score` = mean absolute grey-level difference between frames sampled at 2 fps (OpenCV); returned sorted by score, highest first.

- [ ] **Step 1: Write the failing tests** — fixture builds a 12 s video by concatenating three 4 s lavfi segments: `testsrc2` (moving), `color=c=blue` (static), `mandelbrot` (moving).

```python
def test_finds_cuts_and_respects_min_len(three_scene_video):
    shots = detect_shots(three_scene_video, 7, skip_head_s=0, skip_tail_s=0)
    assert len(shots) >= 3
    assert all(s.end - s.start >= 1.5 and s.asset_id == 7 for s in shots)

def test_static_scene_scores_lowest(three_scene_video):
    shots = detect_shots(three_scene_video, 7, skip_head_s=0, skip_tail_s=0)
    static = min(shots, key=lambda s: s.score)
    assert 4.0 - 0.3 <= static.start <= 4.0 + 0.3        # the blue segment

def test_head_and_tail_skipped(three_scene_video):
    shots = detect_shots(three_scene_video, 7, skip_head_s=3, skip_tail_s=3)
    assert min(s.start for s in shots) >= 3 and max(s.end for s in shots) <= 9 + 0.05

def test_too_short_video_returns_empty(synthetic_video):  # 6 s, default skips 3 + 8
    assert detect_shots(synthetic_video, 1) == []
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/media/test_shots.py -v`
- [ ] **Step 3: Implement `shots.py`.**
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: trailer shot detection with motion scoring"`

---

### Task 10: Crop decision and generated cards

**Files:**
- Create: `src/shorts/media/crop.py`, `src/shorts/media/cards.py`
- Test: `tests/media/test_crop.py`, `tests/media/test_cards.py`

**Interfaces:**
- Produces:
  - `CropMode(StrEnum)`: `smart`, `center`, `blurred`; `CropPlan` frozen dataclass `(mode: CropMode, x: int | None)` (`x` = left edge in source pixels, only for `smart`)
  - `choose_crop(video: Path, start: float, end: float) -> CropPlan`
  - `CANVAS = (1080, 1920)`; `render_hook_card(text: str, out: Path, font_file: Path) -> Path`; `render_fact_card(title: str, facts: list[CardFact], out: Path, font_file: Path) -> Path` (raises `ValueError` on empty `facts`); `render_still(image: Path, out: Path) -> Path` (image fitted to width on a blurred, darkened copy of itself)
  - Cards: dark background, large readable text auto-wrapped and auto-shrunk to fit, all text inside x 80–900 and y 250–1350 (Shorts UI safe zone). Exact colours/layout left to the implementer.

`choose_crop` rule (not determined by the signature):

```python
# source aspect already ≤ 9:16 × 1.05  -> CENTER
# else: sample 5 frames evenly in [start, end]; grey Sobel magnitude; sum per column; average frames;
#       slide a window of width round(h * 9 / 16); best = max window energy, mean = mean window energy
#       best / mean >= 1.15 -> SMART with x = best window left edge; otherwise (or mean == 0) -> BLURRED
```

- [ ] **Step 1: Write the failing tests**

```python
def test_portrait_source_is_center(tmp_path):
    v = lavfi_video(tmp_path, "testsrc2=size=1080x1920:duration=2")
    assert choose_crop(v, 0, 2).mode == CropMode.CENTER

def test_subject_on_left_is_smart(tmp_path):
    v = lavfi_video(tmp_path, "color=c=black:size=1920x1080:duration=2,drawbox=x=150:y=300:w=300:h=400:color=white:t=fill")
    plan = choose_crop(v, 0, 2)
    assert plan.mode == CropMode.SMART and 0 <= plan.x <= 300

def test_flat_frame_is_blurred(tmp_path):
    v = lavfi_video(tmp_path, "color=c=gray:size=1920x1080:duration=2")
    assert choose_crop(v, 0, 2).mode == CropMode.BLURRED

def test_cards_are_canvas_sized(tmp_path, font_file):
    hook = render_hook_card("NVIDIA just announced DLSS 5 " * 8, tmp_path / "h.png", font_file)
    facts = render_fact_card("RTX 5090", [CardFact("Price", "$1,999"), CardFact("Memory", "32GB GDDR7")], tmp_path / "f.png", font_file)
    assert Image.open(hook).size == CANVAS == Image.open(facts).size

def test_fact_card_needs_facts(tmp_path, font_file):
    with pytest.raises(ValueError): render_fact_card("x", [], tmp_path / "f.png", font_file)

def test_still_fits_canvas(tmp_path):
    src = tmp_path / "s.jpg"; Image.new("RGB", (1920, 1080), "red").save(src)
    assert Image.open(render_still(src, tmp_path / "o.png")).size == CANVAS
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/media/test_crop.py tests/media/test_cards.py -v`
- [ ] **Step 3: Implement `crop.py` and `cards.py`.**
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: vertical crop decision and generated cards"`

---

### Task 11: Timeline planner (enforces trailer limits)

**Files:**
- Create: `src/shorts/media/timeline.py`
- Test: `tests/media/test_timeline.py`

**Interfaces:**
- Consumes: `Shot`
- Produces:
  - `TimelineItem` frozen dataclass `(kind: Literal["shot", "image"], duration: float, shot: Shot | None, image: Path | None)` — for `shot` items, `shot.start`/`shot.end` are already trimmed to the used span.
  - `TimelineError(Exception)`
  - `plan_timeline(duration: float, shots: list[Shot], images: list[Path], *, slot_s: float, max_shot_s: float, max_trailer_share: float) -> list[TimelineItem]` — pure, no I/O.

Rule:

```python
n = ceil(duration / slot_s); slot = duration / n          # equal slots, each ≤ slot_s ≤ max_shot_s
budget = max_trailer_share * duration
for i in range(n):
    if i % 2 == 0 and next unused shot exists and used + slot <= budget and shot length >= slot:
        use shot trimmed to [shot.start, shot.start + slot]; used += slot
    else:
        use images[k % len(images)]; k += 1               # images may repeat; shots never repeat
no images and a slot can't take a shot -> TimelineError("no visuals available")
```

- [ ] **Step 1: Write the failing tests**

```python
def shot(i, length=6.0): return Shot(Path(f"t{i}.mp4"), i, 10.0, 10.0 + length, 1.0)
KW = dict(slot_s=3.5, max_shot_s=4.0, max_trailer_share=0.49)

def test_total_duration_exact():
    items = plan_timeline(41.3, [shot(i) for i in range(10)], [Path("c.png")], **KW)
    assert sum(i.duration for i in items) == pytest.approx(41.3, abs=0.01)

def test_trailer_limits():
    items = plan_timeline(50.0, [shot(i) for i in range(20)], [Path("c.png")], **KW)
    shots = [i for i in items if i.kind == "shot"]
    assert all(i.duration <= 4.0 for i in shots)
    assert sum(i.duration for i in shots) < 0.5 * 50.0
    assert len({(i.shot.source, i.shot.start) for i in shots}) == len(shots)

def test_images_only_when_no_shots():
    items = plan_timeline(30.0, [], [Path("a.png"), Path("b.png")], **KW)
    assert {i.kind for i in items} == {"image"}

def test_short_shots_skipped():
    items = plan_timeline(30.0, [shot(1, length=1.0)], [Path("a.png")], **KW)
    assert all(i.kind == "image" for i in items)

def test_nothing_to_show_raises():
    with pytest.raises(TimelineError, match="no visuals"):
        plan_timeline(30.0, [], [], **KW)
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/media/test_timeline.py -v`
- [ ] **Step 3: Implement `timeline.py`.**
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: timeline planner enforcing trailer shot and share limits"`

---

### Task 12: Renderer

**Files:**
- Create: `src/shorts/media/render.py`
- Test: `tests/media/test_render.py`

**Interfaces:**
- Consumes: `run_ffmpeg`, `probe_video`, `choose_crop`, `TimelineItem`, `Narration`, `Settings`
- Produces: `RenderError(Exception)`; `render_video(items: list[TimelineItem], narration: Narration, ass_path: Path, music: Path | None, out: Path, settings: Settings) -> Path`

Steps the function performs (FFmpeg filter strings fixed here; everything else is the implementer's):

1. Each item → `seg_NNN.mp4` in `out.parent / "segments"` (1080×1920, 30 fps, yuv420p, libx264 `-preset veryfast -crf 18`, no audio):
   - shot `smart`: `crop=w=ih*9/16:h=ih:x={x}:y=0,scale=1080:1920`
   - shot `center`: `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920`
   - shot `blurred`: `split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2`
   - image: `-loop 1 -t {duration} -i image.png`, `fps=30`
2. Concat with the concat demuxer (`-f concat -safe 0`).
3. Final pass, run with `cwd=ass_path.parent` so the filter references the bare filename (avoids escaping paths with spaces, quotes or colons): video `subtitles={ass_path.name}:fontsdir={font_file.parent}`; audio: narration, plus music if given — `[2:a]volume={music_volume},afade=t=out:st={D-1}:d=1[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]` with music input `-stream_loop -1`; `-t {D}`; `-c:v libx264 -preset medium -crf 23 -maxrate 6M -bufsize 12M -c:a aac -b:a 128k -ar 48000 -movflags +faststart`.
4. If the output is over `max_output_mb`, re-encode once with `-crf 28 -maxrate 4M`; still too big → `RenderError`.
5. Delete `segments/` on success.

- [ ] **Step 1: Write the failing tests**

```python
def test_render_mixed_timeline(tmp_path, synthetic_video, font_file, settings):
    work = tmp_path / "it's a dir: with spaces"; work.mkdir()       # hostile path
    narration = fake_narration(work, seconds=10)                    # sine WAV + one line
    ass = write_ass([CaptionChunk("Hello {there}", 0, 10)], "Footage: Test / Steam", work / "c.ass")
    card = render_hook_card("DLSS 5 is here", work / "card.png", font_file)
    items = [TimelineItem("shot", 3.3, Shot(synthetic_video, 1, 0.5, 3.8, 1.0), None),
             TimelineItem("image", 3.3, None, card), TimelineItem("shot", 3.4, Shot(synthetic_video, 1, 1.0, 4.4, 1.0), None)]
    out = render_video(items, narration, ass, None, work / "video.mp4", settings)
    info = probe_video(out)
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio and info.duration == pytest.approx(10, abs=0.2)
    assert out.stat().st_size < 50 * 1024 * 1024
    assert not (work / "segments").exists()

def test_render_with_music(tmp_path, ...):
    out = render_video(items, narration, ass, sine_mp3(tmp_path, seconds=3), ...)   # loops music
    assert probe_video(out).duration == pytest.approx(10, abs=0.2)
```

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/media/test_render.py -v`
- [ ] **Step 3: Implement `render.py`.**
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: ffmpeg renderer with captions, credits and music"`

---

### Task 13: Metadata, music, pipeline, CLI and README

**Files:**
- Create: `src/shorts/metadata.py`, `src/shorts/music.py`, `src/shorts/pipeline.py`, `src/shorts/cli.py`, `src/shorts/__main__.py`, `assets/music/licenses.example.yaml`, `README.md`
- Test: `tests/test_metadata.py`, `tests/test_music.py`, `tests/test_pipeline_e2e.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `VideoMetadata` frozen dataclass `(title: str, title_options: tuple[str, ...], description: str, hashtags: tuple[str, ...], sources: tuple[str, ...], rights: tuple[dict, ...])`; `build_metadata(draft: ScriptDraft, article: Article, assets: list[Asset]) -> VideoMetadata`; `write_metadata(meta: VideoMetadata, path: Path) -> Path` (JSON); `content_hash(video_path: Path, meta: VideoMetadata) -> str` (sha256 of file bytes + `json.dumps(asdict(meta), sort_keys=True)`)
  - Metadata rules: remove `<` and `>` everywhere (YouTube rejects them); titles ≤ 100 chars; description ≤ 5000 chars and ends with `Source: {article.url}` plus one `Footage: {rightsholder} ({source_platform})` line per distinct trailer/screenshot rightsholder and `Music: {notes}` for music; hashtags start with `#`, max 5; drop title options and hashtags containing "viral" or "guarantee" (case-insensitive); `title` = first remaining option.
  - `pick_music(music_dir: Path, rng: random.Random) -> Asset | None` — reads `music_dir/licenses.yaml` (`filename: {source: ..., licence: ...}`); audio files without an entry are ignored with a warning; returns a `kind=music, rights_basis=licensed` asset or `None`.
  - `PipelineDeps` frozen dataclass `(http: httpx.Client, llm: LLMProvider, tts: TTSEngine)`; `VideoResult(video_id: int, video_path: Path, metadata_path: Path)`; `PipelineError(Exception)` (user-readable message)
  - `make_video(news_url: str, steam_app_id: int | None, fmt: VideoFormat, settings: Settings, deps: PipelineDeps, conn: sqlite3.Connection) -> VideoResult`
  - `cli.main(argv: list[str] | None = None) -> int` with subcommands `make-video --news-url URL [--steam-app-id N] [--format news_flash] [--config config.yaml]` and `check-setup [--config config.yaml]`.

`make_video` flow (each arrow updates `videos.status`; any exception → `failed` with a readable reason, work dir kept, `PipelineError` raised):

1. `create` video row (`scripting`); work dir `data_dir/work/{id}`.
2. `fetch_article` → `write_checked_script` → `save_script` → `fact_checked`.
3. `rendering`: `build_narration(narration_lines(draft))`; if duration outside 30–55 s → fail with `"narration is {d:.1f}s, allowed 30–55s"` before any video work.
4. Steam assets (if app ID) via `collect_steam_assets` with `BlocklistRepository.names()`; cards: hook card always, fact card if `card_facts`; stills from screenshots; music via `pick_music(settings.music_dir, random.Random(video_id))`. Every asset passes `assert_usable` before use (rejected ones are logged and dropped) and is saved with `AssetRepository.add`.
5. `detect_shots` on each trailer → `plan_timeline` → `chunk_captions` + `write_ass` (credit = `"Footage: {publisher} / Steam"` when trailers are used, else `"Source: {article.domain}"`) → `render_video`.
6. Output to `data_dir/exports/{id}/video.mp4` + `metadata.json`; `save_output` with `content_hash`; status `awaiting_approval`; delete work dir.

`check-setup` prints one line per check with ✓/✗: ffmpeg found and has libass; font file exists; `GEMINI_API_KEY` set; one tiny Gemini call succeeds (reports region/quota errors plainly); fallback key set (warning only); Kokoro imports; music licences count; free space on the data dir's drive (warn under 10 GB).

- [ ] **Step 1: Write the failing tests**

```python
def test_metadata_rules():
    d = draft(title_options=["GO VIRAL with RTX <5090>", "RTX 5090: price and date", "x" * 150],
              hashtags=["#nvidia", "#viral", "#rtx5090", "#gpu", "#pc", "#tech"])
    m = build_metadata(d, article(url="https://nvidianews.nvidia.com/x"), [trailer_asset("CD PROJEKT RED")])
    assert m.title == "RTX 5090: price and date"
    assert all(len(t) <= 100 and "<" not in t and "viral" not in t.lower() for t in m.title_options)
    assert "#viral" not in m.hashtags and len(m.hashtags) <= 5
    assert "Source: https://nvidianews.nvidia.com/x" in m.description
    assert "Footage: CD PROJEKT RED (steam)" in m.description

def test_hash_changes_with_metadata(tmp_path):
    f = tmp_path / "v.mp4"; f.write_bytes(b"abc")
    assert content_hash(f, meta(title="a")) != content_hash(f, meta(title="b"))

def test_music_without_licence_ignored(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"x"); (tmp_path / "b.mp3").write_bytes(b"x")
    (tmp_path / "licenses.yaml").write_text("a.mp3: {source: YouTube Audio Library, licence: free}\n")
    assert pick_music(tmp_path, random.Random(1)).local_path.name == "a.mp3"
    (tmp_path / "licenses.yaml").write_text("")
    assert pick_music(tmp_path, random.Random(1)) is None

@respx.mock
def test_e2e_no_trailers(tmp_path, settings, conn, font_file):
    respx.get("https://nvidianews.nvidia.com/x").respond(200, text=fixture("article_nvidia.html"))
    respx.get(url__startswith="https://store.steampowered.com/api/appdetails").respond(200, json=fixture_json("steam_no_movies.json"))
    respx.get(url__regex=r".*\.jpg.*").respond(200, content=png_bytes(1920, 1080))
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([good_draft_from_fixture, all_supported]), FakeTTS(rate=0.06))
    r = make_video("https://nvidianews.nvidia.com/x", 2, VideoFormat.NEWS_FLASH, settings, deps, conn)
    assert probe_video(r.video_path).height == 1920
    assert json.loads(r.metadata_path.read_text())["sources"][0] == "https://nvidianews.nvidia.com/x"
    assert VideoRepository(conn).get(r.video_id).status == VideoStatus.AWAITING_APPROVAL
    kinds = {a.kind for a in AssetRepository(conn).list_for_video(r.video_id)}
    assert AssetKind.TRAILER not in kinds and AssetKind.CARD in kinds

@respx.mock
def test_e2e_empty_article_fails_cleanly(tmp_path, settings, conn):
    respx.get("https://example.com/n").respond(200, text="<html><body><script>x()</script></body></html>")
    with pytest.raises(PipelineError, match="could not extract enough text"):
        make_video("https://example.com/n", None, VideoFormat.NEWS_FLASH, settings, deps_unused(), conn)
    assert VideoRepository(conn).get(1).status == VideoStatus.FAILED

@respx.mock
def test_e2e_narration_too_long_fails_before_render(tmp_path, settings, conn):
    ...  # same as first E2E but FakeTTS(rate=0.2) -> > 55 s
    with pytest.raises(PipelineError, match=r"narration is \d+\.\ds, allowed 30–55s"): ...
    assert not (settings.data_dir / "exports").exists()

def test_cli_make_video_reports_failure(capsys, monkeypatch):
    monkeypatch.setattr(cli, "make_video", raising(PipelineError("could not extract enough text from https://x")))
    assert cli.main(["make-video", "--news-url", "https://x", "--config", str(cfg)]) == 1
    assert "could not extract enough text" in capsys.readouterr().err
```

(`good_draft_from_fixture`: a valid `ScriptDraft` whose quotes and numbers come verbatim from `article_nvidia.html`, ~100 words.)

- [ ] **Step 2: Run — expect FAIL.** `pytest tests/test_metadata.py tests/test_music.py tests/test_pipeline_e2e.py tests/test_cli.py -v`
- [ ] **Step 3: Implement** `metadata.py`, `music.py`, `pipeline.py` (only orchestration; each step a small helper ≤ 50 lines), `cli.py` (`dotenv.load_dotenv()`, `load_settings(..., os.environ)`, `connect(data_dir / "shorts.db")`, `build_http_client`, `build_llm`, `KokoroTTS`), `__main__.py`.
- [ ] **Step 4: Run — expect PASS.**
- [ ] **Step 5: Write `README.md`** — what it does and does not do (legal rules from the spec §4); system setup (Task 1 Step 1); `cp .env.example .env`, `cp config.example.yaml config.yaml`; getting a free Gemini key (aistudio.google.com) and a free fallback key (console.groq.com); music: download tracks from YouTube Audio Library into `assets/music/` and list each in `licenses.yaml` (copy the example); `python -m shorts check-setup`; `python -m shorts make-video --news-url ... --steam-app-id ...`; where outputs go; running tests.
- [ ] **Step 6: Full suite with coverage.** Run: `pytest --cov=shorts --cov-report=term-missing --cov-fail-under=80` — Expected: all pass, coverage ≥ 80%. Then `pytest -m slow` — Expected: pass.
- [ ] **Step 7: Commit** — `git commit -m "feat: end-to-end make-video pipeline, cli and readme"`

- [ ] **Step 8: Manual acceptance with real services (owner present)**

1. `python -m shorts check-setup` → all ✓ (fallback key may warn).
2. `python -m shorts make-video --news-url <a real NVIDIA or AMD newsroom article> ` → hardware video made of cards only.
3. `python -m shorts make-video --news-url <a real game-news article> --steam-app-id <that game's ID>` → video with trailer shots.
4. Watch both on a phone. Check: captions readable and in sync; no trailer sound; no shot longer than ~4 s; trailer under half the video; every number said appears in the article; credit line visible; description has source + footage credit; length 30–55 s; file under 50 MB.
5. Record what looked bad — it feeds the next plan.
