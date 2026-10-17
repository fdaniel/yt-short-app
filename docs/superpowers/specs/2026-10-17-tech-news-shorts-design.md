# Tech News Shorts — Design

Date: 2026-10-17
Replaces: `viral_shorts_studio_spec_claude_code.md` (original idea, kept for reference)

## 1. Intent and why

The owner wants a small, legal, zero-cost side income. The idea: software on
their own PC that runs a **faceless, English-language YouTube Shorts channel
about tech and gaming news** (AMD, NVIDIA, GPUs, new games, trailers, releases).

Original idea was to clip other people's trending videos and re-upload them.
That was dropped: it is copyright infringement and gets channels claimed,
struck and demonetised. The new idea keeps the trend-chasing and automation
but changes the **source**: the app makes *original news Shorts about trending
topics*, using press-kit material provided for media coverage, its own
generated visuals, and short excerpts of official game trailers used as news
coverage (see §6.3 for the limits and the accepted risk).

Success, in the owner's words: spending €0 for a chance at extra cash; "$30 a
month is a win". Growth later is welcome, but the first goal is a working,
free, legal pipeline.

Honest expectation (recorded so nobody is misled later): Shorts ads only pay
after YouTube Partner Program entry (1,000 subscribers + 10M Shorts views in
90 days at time of writing; may rise in 2027 — verify). Shorts pay roughly
$0.01–$0.15 per 1,000 views. Earnings may be zero for months.

## 2. Goals

- Fully automatic pipeline from "news happened" to "finished vertical video",
  a few times a day, with **one human tap** (Publish / Discard) before anything
  goes public.
- Every video brings real information (specs, prices, dates, what changed) and
  cites its official source.
- €0 running cost on the owner's current PC.
- Rights log for every piece of footage and music used.
- Easy to grow later: auto-publish, TikTok, other languages, paid server.

## 3. Non-goals (for now)

- No web dashboard. Telegram is the UI for the MVP.
- No TikTok, no other languages, no long-form videos, no affiliate links.
- No fully unattended public publishing (until YouTube audit + proven quality).
- No 24/7 operation — it runs while the PC is on.

## 4. Anti-goals (failure even if it "works")

- **Never** re-uploads or clips another creator's video. Topics are free;
  videos are not.
- **Never** publishes a factual claim that isn't in an official source.
- **Never** mass-produces near-identical videos (YouTube's "inauthentic
  content" policy targets exactly this: AI voice + footage + template + volume).
- Never downloads from YouTube (against YouTube's terms even for permitted
  content). YouTube is used for *trend signals and our own uploads only*.
- Never uses trailer music or any music without a recorded licence.
- Never spends money or requires a paid service.

## 5. Constraints

- **Hardware:** laptop, GTX 1650 Max-Q (4 GB VRAM), ~10 GB RAM visible to WSL,
  8 cores, ~67 GB free on C: (disk 87% full — the app must clean up after
  itself and cap its storage).
- **OS:** Windows with WSL2 (Ubuntu, Python 3.12). FFmpeg not yet installed.
- **Budget:** €0. Only free tiers and open-source tools with licences that
  allow commercial use.
- **Language:** English output.
- **YouTube API audit:** videos uploaded through the API by an unaudited
  Google Cloud project are locked to private and *cannot* be made public.
  Audit takes weeks. Therefore the MVP does **not** depend on API upload (see
  §6.7). Verify this rule against current Google docs before Phase 4.

## 6. How it works

Each run (default: every 3 hours while the PC is on, max 3 videos/day — both
configurable):

### 6.1 Find topics

- Sources (all free): official RSS/news feeds — NVIDIA Newsroom, AMD press
  releases, Steam news / upcoming releases via the public Steam store API,
  major publisher blogs (Xbox Wire, PlayStation Blog). List is a config file
  so sources can be added/removed.
- Trend signal: YouTube Data API `videos.list` with `chart=mostPopular` for
  Gaming and Science & Technology categories (US region), plus search counts
  for candidate keywords. **Used only to measure interest in a topic — never
  as footage.**
- Group items into topics (e.g. "DLSS 5 announced"). Drop topics already
  covered (similarity against history, not just exact match).

### 6.2 Score and pick

Transparent score, weights in config, explanation stored with each topic:

- freshness (hours since official announcement)
- trend interest (YouTube / multiple outlets covering it)
- **footage available** with a recorded licence (no footage → can still use
  generated visuals, but scored lower)
- novelty vs. what the channel posted recently (format and topic variety)
- hard exclusions: no official source; rumours/leaks only; sensitive or
  controversial topics outside tech/gaming.

### 6.3 Gather footage (rights-gated)

- Allowed sources, in order:
  1. Steam store trailers for the game in question (via Steam store API).
  2. Official press-kit / media pages on an **allowlist of domains**, each
     with its terms recorded once (e.g. "NVIDIA press assets: editorial
     use"). The builder researches and proposes the starter list (NVIDIA,
     AMD, Xbox Wire, PlayStation Blog, major publishers) with their terms
     for the owner to confirm. Pages whose terms forbid automated download
     or commercial use, or that need a login, are not fetched automatically;
     instead the owner can drop files into an `inbox/` folder with a
     one-line rights note.
  3. Official product images from those press kits.
  4. Generated visuals: text cards, spec tables, charts, comparison layouts.
     These are **first-class, not a fallback**: hardware news often has
     little usable footage, so a video made only of generated visuals +
     product images must still look good. Built in step 1.
- Every asset gets a rights record (persisted): `source_url`,
  `source_platform`, `rightsholder`, `rights_basis` (`press_kit_editorial`,
  `store_promo`, `licensed`, `generated`, `unknown`), `licence_terms_ref`,
  `music_stripped`, `fetched_at`, `notes`.
- `unknown` → asset cannot be used. No exceptions.
- Trailer audio is always removed.
- **Steam trailers (owner's decision, option A):** they carry no reuse
  licence; they are used as short news-coverage excerpts with an accepted risk
  of occasional Content ID claims. Limits, enforced by the renderer:
  - each trailer shot at most ~4 s; trailer footage under 50% of a video's
    runtime, the rest press-kit images or generated visuals;
  - always under narration, never the trailer's own sound;
  - the video must be about that game's news (never trailer-as-content).
- **Claim handling:** the owner reports a claim with a Telegram command
  (YouTube's API does not expose Content ID claims to ordinary channels).
  The app then blocklists that publisher's trailers, records it, and
  includes claims in the weekly summary.

### 6.4 Write the script

- LLM: **Google Gemini free tier** (owner's PC is too weak for a good local
  model). Provider behind an interface so it can be swapped, with a second
  free provider configured as fallback (builder picks one with a free tier
  usable from Portugal/EU; verify Gemini's free tier works there too).
- Budget LLM calls per run (script + fact check + at most one rewrite per
  video, only for the top-scored topic). If all free quota is used up, the
  run stops for the day and says so in Telegram — never a degraded local
  model, never a paid call.
- Input: the official source text(s). Output (structured JSON): hook line,
  3–6 body lines, closing line, title options, description, hashtags, and a
  **claims list** where each claim points to the source sentence it came from.
- **Fact check pass:** a second step verifies every claim against the source
  text. Any unsupported claim → rewrite once; still unsupported → topic
  dropped and logged.
- Formats rotate so videos don't look templated: news flash, spec
  breakdown, "X vs Y", "what changed", release-date roundup. The app avoids
  repeating the same format back to back.
- Target narration length 30–55 s.
- Description always credits sources and footage owners.

### 6.5 Voice

- **Kokoro** TTS (open source, runs on CPU, commercial use allowed). One
  consistent channel voice (configurable).
- Captions synced to the narration (exact method left to the builder; the
  script text is known, so only timing is needed).

### 6.6 Edit and render

- Pick shots from trailers: scene detection + motion/visual-interest
  heuristics; avoid shots dominated by the trailer's own text/logos; no
  shot reused within a video.
- Vertical framing: smart crop when a clear subject exists, otherwise
  centred crop or blurred-background layout. Never stretch.
- Layers: footage/visuals, burned-in captions (kept clear of Shorts UI zones),
  small on-screen source credit, background music from a local folder of
  YouTube Audio Library tracks (owner downloads once; licence noted per
  track), ducked under the voice.
- Output: 1080×1920, H.264 + AAC MP4, under 50 MB (Telegram bot upload limit).
- FFmpeg invoked with argument lists, never shell strings.

### 6.7 Approve and publish

- The finished video is sent to the owner's **Telegram** (private bot that only
  answers the owner's chat ID) with: title, description, sources, licence
  summary, format, and buttons **Publish / Discard**.
- Approval is tied to a hash of the exact rendered file + metadata; any
  change invalidates it.
- Unanswered after 24 h → expires (news goes stale).
- **Phase A (MVP, no audit needed):** on Publish, the bot replies with the
  video file and copy-ready title/description; the owner uploads it from the
  YouTube phone app (~1 minute). The app records it as published once the
  owner pastes the video link or taps "Done".
- **Phase B (after audit):** on Publish, the app uploads via the YouTube Data
  API (OAuth, resumable upload, quota handling, no duplicates) and sets it
  public. Later, an `auto_publish` setting can skip the tap entirely.

### 6.8 Track results

- Daily: fetch public stats (views, likes, comments) for the channel's videos
  via YouTube Data API.
- Weekly Telegram summary: videos posted, views, subscribers, best/worst
  formats and topics, discards and why, failures.
- 3–4 month checkpoint: owner decides continue / change niche / stop.

## 7. States

Separate, simple state machines:

- **Topic:** `found → scored → picked | skipped`
- **Asset:** `found → rights_checked → usable | rejected`
- **Video:** `scripting → fact_checked → rendering → awaiting_approval →
  approved | discarded | expired | failed`
- **Publication (per platform):** `pending → published | failed`

Jobs persisted in SQLite and resumable after the PC restarts.

## 8. Tech choices (builder may adjust with reason)

- Python 3.12 in WSL, SQLite, FFmpeg.
- Gemini via Google's official SDK; Kokoro; python-telegram-bot;
  PySceneDetect; OpenCV/MediaPipe for subject detection; YouTube Data API
  client.
- Config: one YAML file (sources, schedule, limits, voice, formats, weights)
  + `.env` for secrets (`.env.example` committed, `.env` ignored).
- CLI entry points so each stage can be run alone for testing
  (e.g. `make-video --topic-url <url>`).
- How it starts automatically (Windows Task Scheduler launching WSL, or a
  long-running process) is left to the builder; it must survive restarts.

## 9. Safety, secrets, storage

- Secrets only in `.env`; never logged; Telegram bot ignores everyone but the
  owner.
- Gemini free tier may use prompts for training — acceptable, inputs are
  public news.
- Downloads validated (type, size, duration); unique internal filenames;
  path-traversal safe; timeouts on media jobs.
- Storage cap (default 10 GB) with automatic cleanup of footage and renders
  older than N days; published videos' metadata kept.
- Free-tier rate limits respected with backoff; a failed run never retries
  endlessly.

## 10. Build order

1. **One video by hand:** given an official news URL + a Steam app ID →
   script, fact check, voice, edit, MP4 on disk. (Proves quality first.)
2. **Telegram approval** + Phase A manual upload flow.
3. **Automatic discovery, scoring and scheduling** (few videos/day).
4. **Results tracking** + weekly summary.
5. **YouTube API upload** (start the audit application early, in parallel).
6. Later: auto-publish, TikTok, languages, affiliate links, server.

Each step: tests (unit + integration with mocked external APIs), README
updates, real test results reported.

## 11. Calls made by Claude (owner can override)

- Telegram as the only UI for the MVP (no web dashboard).
- Manual phone upload until YouTube audit (because of the private-lock rule).
- Gemini free tier for scripts; Kokoro for voice.
- Default schedule every 3 h, max 3 videos/day, 24 h approval expiry.
- 10 GB storage cap.
- Narration 30–55 s.
- No downloads from YouTube at all, including Creative Commons videos.
- Builder researches the starter press-kit list; login/no-scrape pages go
  through a manual `inbox/` folder.
- Second free LLM provider as fallback; quota exhausted → stop for the day.
- Generated visuals are a first-class video style, built in step 1.
- Trailer limits (~4 s per shot, under 50% of runtime) and claim reporting
  via Telegram command.

## 13. Owner decisions

- Legal channel only; no re-uploading other creators' videos.
- English first; other languages later.
- Fully automatic, with one Publish/Discard tap at the start; auto-publish
  later.
- €0 budget; runs on the owner's PC; a few videos a day.
- AI voice (not the owner's voice).
- Trailers: option A — limited excerpts, occasional claim risk accepted.

## 12. Left to the builder

- Exact libraries/versions, folder structure, test framework.
- Caption timing method, crop heuristics, shot selection details.
- Scoring formula details within §6.2's factors.
- How startup/scheduling works on Windows + WSL.
