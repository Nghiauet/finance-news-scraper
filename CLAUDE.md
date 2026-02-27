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

- **`scrape.py`** — generic scraping + CLI entrypoint. Exports `SOURCES` and `scrape_source()`.
- **`api.py`** — FastAPI app. Background task refreshes all sources every hour; serves list/detail endpoints from Redis.
- **`cache_client.py`** — Redis wrapper with graceful degradation (no-ops when Redis is unavailable).
- **`llm_client.py`** — OpenAI-compatible client; extracts title, date, and summary from raw page text via LLM.

### Data flow

```
category page → article links (generic CSS) → page text → LLM extract+summarize → Redis / JSON
```

No per-source parsing logic or regex. The LLM handles all article parsing and summarization in one call.

### API endpoints

- `GET /news` — list. Query params: `source`, `limit` (default 20), `cursor` (pagination).
- `GET /news/{id}` — single article detail.
- Response envelope: `{ success, data, pagination, meta: { request_id, took_ms } }`
- Error envelope: `{ success: false, error: { code, message } }`
- `id` is a stable 18-digit numeric string derived from `sha256(url)`.
- `published_at` is ISO 8601 (normalized by LLM) or `null`.
- `source` is the canonical domain (e.g. `cafef.vn`).
- `summary` is plain text.

### Article schema

`{ id, title, url, source, published_at, summary }`

### Core abstractions in scrape.py

- `Article` dataclass — `title`, `url`, `source`, `published_at`, `summary`
- `fetch_html(url, weak_ssl)` — shared HTTP fetcher
- `get_article_links(url, domain)` — generic link extraction via `h2 a, h3 a` CSS selectors
- `get_page_text(url)` — strips scripts/styles/nav and returns visible text
- `SOURCES` dict — `{url, domain, weak_ssl?}` per source
- `scrape_source(source_name, limit)` → `list[Article]`

### Source status

| Source | Notes |
|---|---|
| cafef, vnexpress, tinnhanhchungkhoan, vietnambiz, vietstock, dantri, tuoitre, thanhnien | Working |
| ndh | Broken root cert — `weak_ssl=True` required |
| baodautu | JS-rendered body — links found but content may be empty |

### Redis cache keys

| Key pattern | Content | TTL |
|---|---|---|
| `article:<url>` | `{title, published_at, summary}` JSON | 5h |
| `summary:<sha256>` | LLM JSON result | 5h |
| `news:<source>` | Article list JSON | 2h |

### CLI output

Saved to `data/articles_YYYYMMDD_HHMMSS.json`. Each entry: `{title, url, source, published_at, summary}`.
