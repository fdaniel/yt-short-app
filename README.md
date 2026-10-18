# Tech News Shorts

Makes short vertical videos (YouTube Shorts) about tech and gaming news, automatically and legally:

1. reads an **official** news page (NVIDIA, AMD, publishers, …),
2. writes a 30–55 second script with a free AI, keeping **only facts found in that page** (checked twice, at most one rewrite),
3. reads it with a free, local AI voice (Kokoro),
4. builds a 1080×1920 video from **short Steam trailer excerpts** (≤ 4 s each, under half the video, trailer sound removed), store screenshots and its own spec cards,
5. adds captions, an on-screen credit, and licensed background music,
6. saves `video.mp4` + `metadata.json` (title, description with source and footage credits, hashtags, licence log) for you to review.

Nothing is ever published by this tool. You watch the video and decide.

## What it will never do

- Download or re-upload other creators' videos, or download anything from YouTube.
- Use footage or music without a recorded licence basis (`unknown` is always refused).
- Use a trailer's original audio.
- Say a number or fact that is not in the official source.
- Spend money: only free tiers and open-source tools.

## One-time setup (Windows + WSL Ubuntu)

Open Ubuntu (`wsl` in PowerShell), then:

```bash
sudo apt update && sudo apt install -y ffmpeg python3.12-venv espeak-ng fonts-dejavu-core
python3 -m venv ~/.venvs/tech-shorts
source ~/.venvs/tech-shorts/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
cd /mnt/c/Users/Webcomum/development/app-viral
pip install -e ".[dev]"
cp .env.example .env
cp config.example.yaml config.yaml
```

### Free AI keys (put them in `.env`, never anywhere else)

> **Stay at €0:** create each key in a project **without billing enabled** (no card attached).
> A key from a project with billing turned on can be charged once the free quota runs out, and this app cannot tell the difference.

- `GEMINI_API_KEY`: https://aistudio.google.com → **Get API key**.
- `FALLBACK_LLM_API_KEY` (optional, used when Gemini's free quota runs out): a free key from https://console.groq.com.

### Music (optional)

1. Download tracks from the **YouTube Audio Library** (YouTube Studio → Audio library) into `assets/music/`.
2. Copy `assets/music/licenses.example.yaml` to `assets/music/licenses.yaml` and add one entry per file.
   Files without an entry are never used. No music → videos are made without music.

### Check everything

```bash
source ~/.venvs/tech-shorts/bin/activate
python -m shorts check-setup
```

## Make a video

```bash
# hardware news: spec cards only
python -m shorts make-video --news-url "https://nvidianews.nvidia.com/news/..."

# game news: add the game's Steam app ID (the number in its store URL)
python -m shorts make-video --news-url "https://..." --steam-app-id 1091500 --format news_flash
```

Formats: `news_flash`, `spec_breakdown`, `versus`, `what_changed`, `release_roundup`.

Output goes to `~/tech-shorts-data/exports/<id>/` (`video.mp4`, `metadata.json`). The database
(`~/tech-shorts-data/shorts.db`) keeps every video's status and the licence record of each asset used.

If a publisher ever claims one of your videos, that publisher's trailers can be blocked
(Telegram command coming in the next step; for now: `blocked_publishers` table).

## Automatic mode

Instead of pasting URLs, let the app find the news itself:

```bash
python -m shorts run-once
```

Each run:

1. reads the official feeds (NVIDIA Newsroom, NVIDIA Blog, AMD press releases, Xbox Wire, PlayStation Blog),
2. drops stories already seen or already covered, older than 48 h, or off-topic for gamers (earnings, board news, podcasts…),
3. asks the free AI to rate up to 8 remaining stories **in one call**, and scores them
   (freshness, interest, Steam footage available, covered by several official sources),
4. makes **one** video from the best story, if it scores at least 0.55, finding the game on Steam by its exact name.

It stops by itself at **3 videos per day**, when free disk space drops under 10 GB, or when the free AI quota is used up
(the story is then retried on a later run). Two runs never overlap. Nothing is ever published: videos wait in
`~/tech-shorts-data/exports/<id>/` for you.

See what it considered and why:

```bash
python -m shorts topics --last 10
```

Log: `~/tech-shorts-data/run.log`.

### Run it every 3 hours

```bash
python -m shorts schedule-help
```

prints one `schtasks` command: paste it into **PowerShell** (Windows, not Ubuntu). It runs while you are logged in
to Windows. The same output shows the command to switch it off.

## Settings

`config.yaml` controls voice, narration length (`min_words`/`max_words`, tuned to ~2 words per second),
trailer limits, output size and folders. See `config.example.yaml`.

## Tests

```bash
source ~/.venvs/tech-shorts/bin/activate
pytest                      # fast suite
pytest -m slow              # real Kokoro voice
pytest --cov=shorts --cov-report=term-missing
```
