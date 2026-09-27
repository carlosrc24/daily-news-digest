# Daily News Digest

**English** | [Español](README.es.md)

[![CI](https://github.com/carlosrc24/daily-news-digest/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![Daily digest](https://github.com/carlosrc24/daily-news-digest/actions/workflows/daily_digest.yml/badge.svg)](../../actions/workflows/daily_digest.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)

An automated daily briefing on **economics, geopolitics and technology**. It reads RSS feeds
from international outlets, uses **Google Gemini** to select and analyse the most relevant
stories, and emails a newsletter-style HTML digest. It runs for free every morning on
**GitHub Actions**.

<p align="center"><img src="docs/preview.png" alt="Digest preview" width="480"></p>

## Features

- **6 sections**: United States, Europe, Asia & Japan, Markets & Economy, Geopolitics and
  Technology, from ~30 verified feeds (FT, BBC, The Economist, Nikkei Asia, SCMP...).
- **Structured analysis** per story: *Context*, economic/geopolitical *Impact* and
  *Takeaway*, plus an opening **"The day in brief"** block that connects the sections.
- **Relevance-based selection**: Gemini receives ~3× candidates per section, picks the most
  significant ones and drops duplicate coverage of the same story across outlets.
- **Multilingual**: `DIGEST_LANGUAGE=en|es|fr|...` sets the language of the analysis and the
  template.
- **Fault tolerant**: a dead feed or a failed section never blocks delivery.
- **Zero cost**: Gemini free tier (~7 calls/day) + GitHub Actions + Gmail SMTP.
- **Fallback model**: if the primary model is overloaded (503) or out of daily quota (429),
  a second model with its own quota takes over automatically.

## Architecture

```
                ┌────────────┐     ┌──────────────┐     ┌────────────┐
 RSS feeds ───▶ │ fetcher.py │ ──▶ │ summarizer.py│ ──▶ │ mailer.py  │ ──▶ Gmail
 (~30, in       │ download,  │     │ Gemini: 1    │     │ Jinja2 →   │     (SMTP
  parallel)     │ 24h filter,│     │ call per     │     │ HTML + txt │      587 TLS)
                │ dedupe     │     │ section + 1  │     │            │
                └────────────┘     │ daily brief  │     └────────────┘
                                   └──────────────┘
                main.py orchestrates · config.py loads .env and feeds
```

| File | Responsibility |
|---|---|
| `src/config.py` | Environment variables (validated per mode) and the feed catalogue by category |
| `src/fetcher.py` | Download with timeout, feedparser parsing, time filter, cleaning, deduplication |
| `src/summarizer.py` | Prompts, Gemini calls with typed JSON output, retries, join with RSS metadata |
| `src/mailer.py` | HTML/text rendering and SMTP delivery over STARTTLS |
| `src/models.py` | Pydantic models (LLM schemas and the digest) |
| `src/i18n.py` | Localised labels and dates |
| `src/templates/digest.html.j2` | Email template (tables + inline CSS, 600px, responsive) |
| `main.py` | CLI and pipeline orchestration |

### Design decisions

- **Structured output instead of LLM-generated HTML.** Gemini returns JSON validated against
  a Pydantic schema (`response_schema`). The HTML comes from our own template with
  *autoescape*, so formatting is consistent and model text is never injected as HTML.
- **The model cannot invent links.** Gemini is only asked for an `article_id` plus analysis;
  the original headline, source and URL come from the RSS data. Unknown or repeated IDs are
  discarded.
- **One call per section.** Lets the model compare and rank stories across sources, fits
  comfortably within free-tier limits, and isolates failures (if one section fails, the rest
  is still sent and the email footer says so).
- **Selective retries and a fallback model.** Backoff (tenacity) only for `5xx` and
  per-minute `429`s, honouring the API's *"retry in Ns"* hint. A **daily** quota `429` is not
  retried (it would only burn requests): the model is marked as exhausted and the fallback
  takes over. `400/403` errors fail fast.
- **Own download before feedparser.** feedparser has no timeout and some outlets block its
  User-Agent, so feeds are fetched with `urllib` and the bytes are parsed.
- **Undated sources.** Nikkei Asia publishes no dates in its RSS: undated entries are
  accepted, bounded by `MAX_PER_FEED` (feeds list newest first).
- **No side effects at import.** `load_settings()` only requires the variables each mode
  needs, so tests and `--demo` run without any secrets.

## Getting started

### 1. Gemini API key

1. Go to [Google AI Studio → API keys](https://aistudio.google.com/apikey).
2. Click **Create API key** (create or pick a Google Cloud project).
3. Copy it: this is `GEMINI_API_KEY`. The free tier is enough.

> The default model is `gemini-3.8-flash`, with `gemini-3.5-flash-lite` as fallback.
> On the free tier `gemini-3.8-flash` allows only **~20 requests/day**: one digest uses 7,
> but several test runs in a row will exhaust it (the fallback then takes over). Check your
> limits at <https://ai.dev/rate-limit> and the model list at
> <https://ai.google.dev/gemini-api/docs/models>.

### 2. Gmail App Password

Gmail does not accept your regular password over SMTP; you need an **App Password**:

1. Enable **2-Step Verification**: <https://myaccount.google.com/security>.
2. Go to <https://myaccount.google.com/apppasswords>.
3. Create one named e.g. `news-digest`. Google shows 16 characters
   (`abcd efgh ijkl mnop`): this is `EMAIL_PASSWORD`.

> If the App Passwords option is missing, 2-Step Verification is not enabled or your
> Workspace administrator has disabled it.

### 3. Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # then fill in the values
```

```bash
python main.py --demo        # render a sample digest, no credentials needed
python main.py --fetch-only  # list RSS candidates, no Gemini calls
python main.py --dry-run     # build the real digest into output/digest.html, don't send it
python main.py               # full run: build and send the email
```

### 4. Automate with GitHub Actions

1. Push the repository to GitHub.
2. Under **Settings → Secrets and variables → Actions → Secrets**, create:

   | Secret | Value |
   |---|---|
   | `GEMINI_API_KEY` | Your AI Studio key |
   | `EMAIL_SENDER` | Sending Gmail account |
   | `EMAIL_PASSWORD` | The 16-character App Password |
   | `EMAIL_RECEIVER` | Recipient(s), comma-separated |

3. (Optional) In the **Variables** tab, set `DIGEST_LANGUAGE` (e.g. `es`), `GEMINI_MODEL` or
   `ARTICLES_PER_CATEGORY`.
4. Try it from **Actions → Daily digest → Run workflow** (tick *dry_run* to build without
   sending; the HTML is kept as a downloadable run artifact).

The workflow starts at **07:30 Madrid time all year round**, so the email is in the inbox
before 08:00 despite GitHub's usual scheduling delays.

GitHub's `cron` only understands UTC and Spain observes daylight saving time, so there are
two entries (`30 5` for summer, UTC+2, and `30 6` for winter, UTC+1). A `gate` job compares
the cron that fired with the current `Europe/Madrid` offset and lets only the matching one
through; the other shows as *skipped*. Because it checks the cron rather than the wall clock,
a late start never causes a missed or duplicated email.

For another time or time zone, change both `cron` entries and `LOCAL_TZ` in
`.github/workflows/daily_digest.yml`.

> **Keep in mind**
> - GitHub may delay scheduled runs by several minutes at busy times.
> - In public repositories, GitHub **disables scheduled workflows after 60 days without
>   repository activity**. A commit, or re-enabling it from the Actions tab, fixes it.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | **Required** (except `--fetch-only` / `--demo`) |
| `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECEIVER` | — | **Required** to send |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Primary Gemini model |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | Fallback model (`none` disables it) |
| `DIGEST_LANGUAGE` | `en` | Language of the analysis and template (`en`, `es`; other codes use English labels) |
| `LOOKBACK_HOURS` | `24` | News time window |
| `ARTICLES_PER_CATEGORY` | `4` | Stories per section in the email |
| `CANDIDATES_PER_CATEGORY` | `3 × ARTICLES` | Candidates sent to Gemini per section |
| `MAX_PER_FEED` | `8` | Maximum entries read from each feed |

Feeds are defined in `DEFAULT_FEEDS` (`src/config.py`); adding a section means adding a key
there and its label in `src/i18n.py`.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Digest built (and sent) successfully |
| `1` | Configuration error, no feeds available or every section failed: **nothing is sent** |
| `2` | Sent, but a section failed (the Actions run turns red so you notice) |

## Tests and quality

```bash
pytest            # 36 tests; no network or secrets (RSS, Gemini and SMTP are mocked)
ruff check .      # lint (including flake8-bandit security rules)
ruff format .     # formatting
```

The `ci.yml` workflow runs lint and tests on every push and pull request.

## Limitations

- The analysis is based on the RSS headline and summary, not the full article (many sources
  are paywalled). Some feeds (Nikkei Asia) only provide headlines; the prompt tells the model
  not to invent details in those cases.
- Reuters discontinued its public RSS feeds in 2020, so it is not included.
- The Economist publishes weekly; on most days it contributes few stories within 24h.
- Summaries are LLM-generated and may contain errors: the email always links to the
  original source.
