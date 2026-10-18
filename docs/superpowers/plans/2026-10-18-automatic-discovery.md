# Automatic Discovery and Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The app finds fresh official tech/gaming news by itself, picks the best story, and makes the video, every few hours, without the owner pasting URLs.

**Architecture:** A `run-once` command reads a configurable list of official RSS feeds, drops stories already seen or already covered, asks the free LLM to rate the remaining few in one batched call, scores them with a transparent weighted formula (explanation stored per topic), resolves a Steam app ID for game stories, and calls the existing `make_video`. Windows Task Scheduler starts `run-once` every 3 hours; a lock file, a daily cap and a free-space floor keep unattended runs safe. Hardening of the step-1 minors that matter once nobody is watching comes first.

**Tech Stack:** Python 3.12, httpx, feedparser (new, battle-tested RSS/Atom parser), trafilatura, SQLite, google-genai via the existing `FallbackLLM`, pytest + respx.

**Spec:** `docs/superpowers/specs/2026-10-17-tech-news-shorts-design.md` (§6.1 Find topics, §6.2 Score and pick, §9 Safety, §10 step 3). Build order change: the owner asked for discovery before Telegram (2026-10-18: "i don't want to be always me send the url"), so step 3 comes before step 2. Until step 2 exists, finished videos wait in `~/tech-shorts-data/exports/<id>/` for the owner to review and upload by hand; nothing is ever published by this plan.

## Global Constraints

- €0: free tiers only; quota exhausted (`AllProvidersExhausted`) ends the run quietly, never a paid call.
- Official sources only; topics with no official source, rumours and leaks are excluded (§6.2).
- YouTube trend data is **not** used in this plan (needs a second key); interest comes from the LLM rating and from several official feeds covering the same story. Ruling recorded in the plan, revisit in step 4.
- Default schedule: every 3 hours while the PC is on, at most 3 videos per day (local date), 1 per run — all in `config.yaml`.
- Stop making videos when free space under `data_dir` is below 10 GB.
- Every URL fetched, including every redirect hop, passes `validate_public_url`.
- Secrets only in `.env`; nothing new needs a secret.
- Existing rights gate, fact check and word limits are unchanged.
- Files ≤ 400 lines, functions < 50 lines, frozen dataclasses / pydantic models, conventional commits with the attribution trailer.

## Review Focus

1. A feed is down, slow, returns HTML or malformed XML → that feed is skipped with a warning; the run continues with the others.
2. The same story appears in two feeds (NVIDIA newsroom + NVIDIA blog) or was already made last week → at most one video, ever.
3. A game title matches the wrong Steam game ("Modern Warfare 4" vs "Call of Duty 4: Modern Warfare") → no Steam ID (cards only), never another game's footage.
4. Nothing is worth a video (only board appointments, earnings, podcasts) → no video, a one-line log saying why; not a forced weak video.
5. Two scheduled runs overlap, or the PC slept through runs → the second run exits immediately; no double videos, the daily cap still holds.

---

### Task 1: Safe redirects and atomic migrations

**Files:**
- Modify: `src/shorts/net.py`, `src/shorts/storage/db.py`
- Test: `tests/test_net.py`, `tests/storage/test_db.py`

**Interfaces:**
- Produces: `build_http_client(settings)` whose client validates every request URL (initial and redirect) via an httpx `event_hooks={"request": [...]}` hook calling `validate_public_url(str(request.url))`. `connect(db_path)` applies each migration inside one transaction (`BEGIN; <sql>; INSERT INTO schema_version …; COMMIT;` in a single `executescript`, rolling back on error).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_net.py
@respx.mock
def test_redirect_to_private_address_is_refused(settings):
    respx.get("https://example.com/a").respond(302, headers={"Location": "http://127.0.0.1/admin"})
    with build_http_client(settings) as client, pytest.raises(UnsafeURLError):
        fetch_text(client, "https://example.com/a", max_bytes=1000)

# tests/storage/test_db.py
def test_failed_migration_leaves_no_partial_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS + ("CREATE TABLE half (x); THIS IS NOT SQL;",))
    with pytest.raises(sqlite3.Error):
        db.connect(tmp_path / "s.db")
    conn = sqlite3.connect(tmp_path / "s.db")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "half" not in tables
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == len(db.MIGRATIONS) - 1
```

- [ ] **Step 2: Run them** — `pytest tests/test_net.py tests/storage/test_db.py -v` — Expected: both FAIL (redirect followed; `half` table exists).
- [ ] **Step 3: Implement** the request hook and the per-migration transaction.
- [ ] **Step 4: Run** `pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `fix: validate redirect targets and make migrations atomic`

### Task 2: Pipeline hardening for unattended runs

**Files:**
- Modify: `src/shorts/pipeline.py`
- Test: `tests/test_pipeline_e2e.py`

**Interfaces:**
- Consumes: Task 1 client.
- Produces: `make_video(news_url, steam_app_id, fmt, settings, deps, conn, *, article: Article | None = None) -> VideoResult` — when `article` is given it is used instead of fetching `news_url`. The work dir is removed on success **and** failure. `KeyboardInterrupt` marks the video failed ("interrupted") and is re-raised. A still that cannot be decoded is skipped with a warning. Steam asset collection treats `SteamError, httpx.HTTPError, ValueError, OSError, FFmpegError, DownloadTooLarge, UnsafeURLError` as "no Steam media" (warning, continue).

- [ ] **Step 1: Write the failing tests** (reuse `mock_sources`, `GOOD`, `ALL_OK`)

```python
@respx.mock
def test_given_article_is_not_fetched(settings, conn):
    mock_sources()
    route = respx.get(NEWS)
    given = extract_article(NEWS, (FIXTURES / "article_nvidia.html").read_text())
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    make_video(NEWS, None, VideoFormat.NEWS_FLASH, settings, deps, conn, article=given)
    assert route.call_count == 0

@respx.mock
def test_failure_removes_work_dir(settings, conn):
    mock_sources()
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), BrokenTTS())  # raises RuntimeError; work dir exists by then
    with pytest.raises(PipelineError):
        make_video(NEWS, None, VideoFormat.NEWS_FLASH, settings, deps, conn)
    assert not any((settings.data_dir / "work").glob("*"))

@respx.mock
def test_interrupt_marks_failed(settings, conn):
    mock_sources()
    deps = PipelineDeps(httpx.Client(), Failing(KeyboardInterrupt()), FakeTTS(rate=0.07))
    with pytest.raises(KeyboardInterrupt):
        make_video(NEWS, None, VideoFormat.NEWS_FLASH, settings, deps, conn)
    assert VideoRepository(conn).get(1).status == VideoStatus.FAILED

@respx.mock
def test_broken_screenshot_is_skipped(settings, conn):
    mock_sources()
    respx.get(url__regex=r".*\.jpg.*").respond(200, content=b"not an image")
    deps = PipelineDeps(httpx.Client(), ScriptedLLM([GOOD, ALL_OK]), FakeTTS(rate=0.07))
    r = make_video(NEWS, 2, VideoFormat.NEWS_FLASH, settings, deps, conn)
    assert r.video_path.exists()
```

- [ ] **Step 2: Run** `pytest tests/test_pipeline_e2e.py -v` — Expected: the four new tests FAIL.
- [ ] **Step 3: Implement** (catch `BaseException` in `make_video`, record, `rmtree` in `finally`, re-raise `KeyboardInterrupt` unchanged; `_images` skips `OSError`/`PIL.UnidentifiedImageError` per still; widen the Steam except tuple; thread `article` through `_Job`).
- [ ] **Step 4: Run** `pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `fix: unattended-safe pipeline (cleanup, interrupts, bad stills, steam errors)`

### Task 3: Official feeds

**Files:**
- Create: `src/shorts/discovery/__init__.py`, `src/shorts/discovery/feeds.py`
- Modify: `src/shorts/config.py`, `config.example.yaml`, `pyproject.toml` (add `feedparser>=6`)
- Test: `tests/discovery/test_feeds.py`, fixtures `tests/fixtures/feed_nvidia_blog.xml` (2 items, one with `content:encoded`), `tests/fixtures/feed_amd_ir.xml` (2 items, no content)

**Interfaces:**
- Produces:
  - `FeedSource(name: str, url: str, topic: Literal["hardware", "gaming"])` (frozen pydantic, in `config.py`)
  - `DiscoverySettings` in `config.py`, field `Settings.discovery`, defaults:
    `feeds` = NVIDIA Newsroom `https://nvidianews.nvidia.com/releases.xml` (hardware), NVIDIA Blog `https://blogs.nvidia.com/feed/` (hardware), AMD Press Releases `https://ir.amd.com/news-events/press-releases/rss` (hardware), Xbox Wire `https://news.xbox.com/en-us/feed/` (gaming), PlayStation Blog `https://blog.playstation.com/feed/` (gaming);
    `max_age_h=48`, `max_videos_per_day=3`, `videos_per_run=1`, `max_attempts_per_run=2`, `triage_batch=8`, `min_score=0.55`, `min_free_gb=10`, `history_days=14`, `duplicate_similarity=0.5`,
    `weights = {"freshness": 0.3, "interest": 0.5, "footage": 0.1, "coverage": 0.1}`,
    `exclude_keywords = ("financial results", "quarter", "dividend", "board of directors", "appoints", "conference call", "podcast", "share of the week", "for southeast asia", "earnings")`.
  - `FeedItem(source: str, topic: str, title: str, url: str, published: datetime, content_html: str)` (frozen dataclass; `published` is timezone-aware UTC; `content_html` is `content:encoded` or `""`)
  - `fetch_feed(client, source: FeedSource, *, max_bytes: int) -> list[FeedItem]` — downloads with `fetch_text`, parses with `feedparser.parse(text)`; items without link, title or date are dropped; titles are HTML-unescaped and CDATA-free.
  - `fetch_all(client, sources, *, max_bytes) -> list[FeedItem]` — one failing feed is logged and skipped.
  - `article_from_item(item: FeedItem) -> Article | None` — `extract_article(item.url, item.content_html)` when `content_html` is present; `None` on `SourceTextError` or empty content.

- [ ] **Step 1: Write the failing tests**

```python
def test_parses_items_with_full_text(...):     # nvidia blog fixture → 2 items, aware UTC dates, content_html non-empty for item 1
def test_cdata_and_entities_cleaned(...):      # "AMD &#8211; Helion" → "AMD – Helion", no "<![CDATA["
def test_item_without_date_dropped(...):
def test_one_broken_feed_does_not_stop_others(...):   # respx: feed A 500, feed B "<html>…" , feed C ok → only C's items
def test_article_from_item_uses_feed_text(...):       # item 1 → Article with text from content_html
def test_article_from_item_none_when_no_content(...): # AMD item → None
def test_default_feeds_in_settings(tmp_path):         # load_settings(...).discovery.feeds has 5 sources, names as above
```

- [ ] **Step 2: Run** `pytest tests/discovery/test_feeds.py -v` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement**; `pip install -e ".[dev]"` after the `pyproject.toml` change; add the `discovery:` block (commented) to `config.example.yaml`.
- [ ] **Step 4: Run** `pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: read official news feeds`

### Task 4: Steam app lookup by game title

**Files:**
- Modify: `src/shorts/sources/steam.py`
- Test: `tests/sources/test_steam.py`, fixture `tests/fixtures/steam_search_mw4.json` (the real 3-item response for "Call of Duty Modern Warfare 4", captured 2026-10-18)

**Interfaces:**
- Produces: `find_steam_app_id(client, game_title: str) -> int | None` — GET `https://store.steampowered.com/api/storesearch/?term=<title>&l=english&cc=US`; returns the `id` of the first item of `type == "app"` whose normalised name equals the normalised title; normalisation = casefold, remove ®™©, replace any non-alphanumeric run with one space, strip. Any HTTP/JSON error → `None` (logged).

- [ ] **Step 1: Write the failing tests**

```python
def test_exact_title_matches(...):        # "Call of Duty: Modern Warfare 4" → 4435490
def test_partial_title_does_not_match(...):  # "Modern Warfare 4" → None  (never another game's footage)
def test_older_game_not_matched(...):     # "Call of Duty 4" → None
def test_search_failure_returns_none(...):   # 503 → None
```

- [ ] **Step 2: Run** — Expected: FAIL (`find_steam_app_id` missing).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: find a game's steam app id by exact title`

### Task 5: Topic history

**Files:**
- Modify: `src/shorts/storage/db.py` (migration 2), `src/shorts/models.py`
- Create: `src/shorts/storage/topics.py` (new repository; keeps `repositories.py` small)
- Test: `tests/storage/test_topics.py`

**Interfaces:**
- Produces:
  - Migration 2: `topics(id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL UNIQUE, source TEXT NOT NULL, title TEXT NOT NULL, published_at TEXT NOT NULL, score REAL, explanation TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, video_id INTEGER REFERENCES videos(id), created_at TEXT NOT NULL)`.
  - `TopicStatus(StrEnum)`: `skipped`, `picked`, `made`, `failed` (in `models.py`).
  - `TopicRepository(conn)`: `seen_urls() -> set[str]`; `record(item: FeedItem, status: TopicStatus, score: float | None, explanation: str) -> int` (insert; existing URL → update status/score/explanation); `link_video(topic_id, video_id, status)`; `recent_titles(days: int, now: datetime) -> list[str]` (titles with status `picked`/`made`, plus `videos.title` from the same window); `videos_made_on(day: date) -> int` (rows in `videos` whose local `created_at` date is `day` and status ≠ `failed`).

- [ ] **Step 1: Write the failing tests** — record/seen roundtrip; re-record same URL updates instead of duplicating; `recent_titles` excludes older than `days` and `skipped`; `videos_made_on` ignores failed and other days; an existing step-1 database (created with migration 1 only) upgrades and keeps its videos.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: remember topics and daily output`

### Task 6: Triage and scoring

**Files:**
- Create: `src/shorts/discovery/triage.py`, `src/shorts/discovery/score.py`
- Test: `tests/discovery/test_triage.py`, `tests/discovery/test_score.py`

**Interfaces:**
- Consumes: `FeedItem`, `DiscoverySettings`, `LLMProvider.generate_json`.
- Produces:
  - `similarity(a: str, b: str) -> float` — Jaccard over lowercase word sets with stop words (`the a an and or of to for in on with is are new now`) removed.
  - `cheap_filter(items, *, seen_urls, recent_titles, settings, now) -> tuple[list[FeedItem], list[tuple[FeedItem, str]]]` — returns (kept, rejected-with-reason): already seen URL; older than `max_age_h` or published > 1 h in the future; title contains an `exclude_keywords` entry; `similarity ≥ duplicate_similarity` with a recent title; within the batch, near-duplicates collapse to the freshest item.
  - `coverage(item, all_items) -> float` — `min(1.0, (number of *other sources* with similarity ≥ duplicate_similarity) / 2)`.
  - `Triage` (pydantic): `index: int`, `interest: int (0–10)`, `rumour_or_leak: bool`, `on_topic: bool`, `game_title: str | None`, `format: VideoFormat`, `reason: str (≤ 200 chars)`; `TriageBatch(verdicts: list[Triage])`.
  - `triage(items: list[FeedItem], llm) -> dict[int, Triage]` — ONE `generate_json` call for the whole batch (prompt lists `index, source, title, first 600 chars of text`, asks for interest to a gaming/PC-hardware audience, rumour/leak flag, on-topic flag, the full official game title exactly as written in the item or null, best format). Verdicts with unknown indexes are ignored; items with no verdict count as not picked.
  - `ScoredTopic(item, score: float, explanation: str, triage: Triage, footage: bool)`; `score_topic(item, verdict, *, footage: bool, coverage: float, settings, now) -> ScoredTopic` — freshness = `max(0, 1 − age_h / max_age_h)`; score = Σ weight·factor with interest/10; `rumour_or_leak` or not `on_topic` → score 0. Explanation lists each factor, e.g. `"freshness 0.92×0.3 + interest 0.80×0.5 + footage 1×0.1 + coverage 0.5×0.1 = 0.83"`.

- [ ] **Step 1: Write the failing tests** — keyword exclusion (AMD "Appoints … Board of Directors"); near-duplicate across NVIDIA newsroom/blog keeps the freshest; similar to a recent video title → rejected with reason; future-dated item rejected; coverage counts other sources only; rumour scores 0; explanation sums to the score (±0.01); triage sends one prompt containing every title (ScriptedLLM) and ignores an out-of-range index.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: filter, rate and score news topics`

### Task 7: The run-once runner

**Files:**
- Create: `src/shorts/discovery/runner.py`
- Test: `tests/discovery/test_runner.py`

**Interfaces:**
- Consumes: everything above, `make_video(..., article=...)`, `PipelineError` (its `__cause__` tells quota exhaustion apart).
- Produces:
  - `RunReport(made: tuple[int, ...], skipped_reason: str | None, considered: int)` (frozen dataclass). "Today" is `now.astimezone().date()`; `videos.created_at` is converted to local time before comparing.
  - `RunLocked(Exception)`.
  - `run_once(settings, deps, conn, *, now: datetime, free_bytes: Callable[[Path], int] = lambda p: shutil.disk_usage(p).free) -> RunReport`. Order:
    1. take an exclusive non-blocking `fcntl.flock` on `data_dir/run.lock` (held → `RunLocked`);
    2. `videos_made_on(today) ≥ max_videos_per_day` → report `"daily limit reached"`;
    3. free space < `min_free_gb` → report `"low disk space"`;
    4. `fetch_all` → `cheap_filter` (rejected items recorded as `skipped` with their reason) → newest `triage_batch` kept go to `triage`;
    5. for gaming items with a `game_title`: `find_steam_app_id`; `footage = id is not None`;
    6. score, record every scored topic (`skipped` below `min_score`), sort by score;
    7. for the best topics, up to `max_attempts_per_run` tries and `videos_per_run` successes (and never past the daily cap): record `picked`, call `make_video(item.url, steam_id, verdict.format, settings, deps, conn, article=article_from_item(item))`, then `link_video(... made)`; `PipelineError` → `failed` and try the next; a `PipelineError` caused by `AllProvidersExhausted` stops the run with `"AI quota used up, trying again next run"`;
    8. nothing above `min_score` → `"nothing worth a video"`.

- [ ] **Step 1: Write the failing tests** (respx for feeds/Steam, `ScriptedLLM` for triage + script + fact check, `FakeTTS(rate=0.07)`, fixed `now`)

```python
def test_makes_one_video_from_best_topic(...):        # 2 feeds, 3 items → 1 video, topic status made, video linked
def test_second_run_does_not_redo_same_story(...):    # run twice (same feeds) → still 1 video
def test_daily_cap(...):                               # 3 non-failed videos today already → 0 LLM calls, reason "daily limit reached"
def test_low_disk(...):                                # free_bytes → 1 GB → reason "low disk space"
def test_overlapping_run_refused(...):                 # hold the lock in the test → RunLocked
def test_nothing_good(...):                            # triage interest 2 for all → reason "nothing worth a video", topics skipped
def test_failed_story_falls_through_to_next(...):      # first script rejected twice → second topic made
def test_quota_exhausted_stops_quietly(...):           # Failing(AllProvidersExhausted) after triage → no exception, reason mentions quota
def test_game_story_gets_steam_id(...):                # gaming item, triage game_title, storesearch fixture → make_video got 4435490
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: run-once picks the best fresh story and makes the video`

### Task 8: CLI, schedule, README, real run

**Files:**
- Modify: `src/shorts/cli.py`, `README.md`, `config.example.yaml`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `python -m shorts run-once [--config]` — builds deps like `make-video`, prints the `RunReport` in plain words (e.g. `Made video #4: ~/tech-shorts-data/exports/4/video.mp4` or `No video this run: daily limit reached`), exit 0 for a normal "no video" outcome, 1 for config errors, 0 with a message for `RunLocked` ("another run is still working").
  - `python -m shorts schedule-help [--config]` — prints the exact PowerShell command for Windows Task Scheduler, built from `WSL_DISTRO_NAME`, the repo path and the venv python:
    `schtasks /Create /F /TN "TechShorts" /SC HOURLY /MO 3 /TR "wsl.exe -d <distro> --cd <repo> -- <venv>/bin/python -m shorts run-once"` and the matching `schtasks /Delete /TN "TechShorts" /F` to stop it. Output appended to `~/tech-shorts-data/run.log` via a `--log-file` option on `run-once` (default `data_dir/run.log`, rotated at 5 MB with `RotatingFileHandler`, 2 backups).
  - README: "Automatic mode" section (what it does, how to switch on/off, where videos appear, how to see why a story was picked: `topics` table explanation via `python -m shorts topics --last 10`).
  - `python -m shorts topics [--last N]` — prints recent topics: status, score, explanation, title.

- [ ] **Step 1: Write the failing tests** — `run-once` with a stubbed `run_once` returning each report kind prints the right line and exit code; `RunLocked` → message, exit 0; `schedule-help` output contains `schtasks /Create`, `--cd`, `run-once`, the distro from a monkeypatched env; `topics --last 2` prints two rows with their explanations.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `pytest -q` and `pytest --cov=shorts -q` — Expected: all pass, coverage ≥ 80%.
- [ ] **Step 5: Real run (owner's key, real feeds):** `python -m shorts run-once` twice in a row. Expected: first run makes one video from a story published in the last 48 h and prints its path; second run either makes a *different* story's video or says why not; `python -m shorts topics --last 10` shows readable explanations. Watch the video's contact sheet for layout problems.
- [ ] **Step 6: Commit** `feat: run-once, schedule help and topics commands`
