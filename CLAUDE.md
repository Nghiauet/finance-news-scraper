# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the scraper (all sources, saves to data/)
uv run scrape.py

# Test mode: scrapes only the first source with 3 articles
uv run scrape.py --test

# Run the FastAPI server (dev mode with reload)
uv run uvicorn api:app --host 0.0.0.0 --port 46401 --reload

# Docker: build and start API + Redis
docker compose up --build
```

Always use `uv run` to execute scripts — never activate the venv manually.

## Environment

Copy `.env` and set these variables before running:

| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | OpenAI-compatible API key |
| `LLM_BASE_URL` | OpenAI-compatible base URL |
| `LLM_MODEL` | Model name (e.g. `gpt-4o`) |
| `REDIS_URL` | Redis connection (default: `redis://localhost:12209`) |

TTL overrides (optional): `CACHE_ARTICLE_TTL`, `CACHE_SUMMARY_TTL`, `CACHE_NEWS_TTL`.

## Architecture

The project has two modes: a **CLI batch scraper** and a **FastAPI server** backed by Redis.

### Module overview

- **`scrape.py`** — core scraping logic + CLI entrypoint. Exports `SOURCES` and `scrape_source()`.
- **`api.py`** — FastAPI app. Background task refreshes all sources every hour; serves list/detail endpoints from Redis.
- **`cache_client.py`** — Redis wrapper with graceful degradation (no-ops when Redis is unavailable).
- **`llm_client.py`** — OpenAI-compatible client; generates Vietnamese finance summaries.

### Data flow

```
category page → article list → full article → LLM summary → Redis / JSON file
```

First refresh runs at startup; Redis is optional (scraping still works without it).

### API endpoints

- `GET /news` — list (no content body). Query params: `source`, `limit` (default 20), `cursor` (pagination).
- `GET /news/{id}` — full detail including `content`.
- Response envelope: `{ success, data, pagination, meta: { request_id, took_ms } }`
- Error envelope: `{ success: false, error: { code, message } }`
- `id` is a stable 18-digit numeric string derived from `sha256(url)`.
- `published_at` is normalized to ISO 8601 (`2026-02-24T10:40:00+07:00`) or `null`.
- `source` is always the canonical domain (e.g. `cafef.vn`, never `cafef`).
- `summary` is plain text — emojis and markdown stripped at the API layer.

### Core abstractions in scrape.py

- `Article` dataclass — `title`, `url`, `source`, `published_at`, `content`, `summary`
- `fetch_html(url, weak_ssl)` — shared HTTP fetcher; `weak_ssl=True` lowers cipher security for sites with broken DH keys (e.g. ndh.vn)
- `SOURCES` dict — registry mapping source name → `{list_fn, extract_fn, default_url, domain}`
- `scrape_source(source_name, limit)` → `list[Article]` — orchestrates list → extract → cache → summarize

### Per-source pattern

Each source implements two functions:
- `get_<source>_list(category_url)` → `list[dict]` — scrapes article links from a category page
- `extract_<source>(url)` → `Optional[Article]` — fetches and parses a single article

### Source status

| Source | Notes |
|---|---|
| cafef, vnexpress, tinnhanhchungkhoan, vietnambiz, vietstock, dantri, tuoitre, thanhnien | Working |
| ndh | Broken root cert — `weak_ssl=True` required |
| baodautu | JS-rendered body — list works, article content empty |

### Link detection strategies

Most sources: `h2 a, h3 a` CSS selectors
- **baodautu**: regex `baodautu\.vn/.+-d\d+\.html`
- **vietstock**: regex `vietstock\.vn/\d{4}/\d{2}/.+\.htm`

### Redis cache keys

| Key pattern | Content | TTL |
|---|---|---|
| `article:<url>` | Raw article text | 5h |
| `summary:<sha256>` | LLM summary | 5h |
| `news:<source>` | Full article list JSON | 2h |

### CLI output

Saved to `data/articles_YYYYMMDD_HHMMSS.json`. Each entry: `{title, url, source, published_at, content, summary}`.
