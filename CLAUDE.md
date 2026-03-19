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

# Syntax-check a modified file
python -m py_compile <file.py>
```

Always use `uv run` to execute scripts — never activate the venv manually. Python 3.13 required.

## Environment

Copy `.env` and set these variables before running:

| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | OpenAI-compatible API key |
| `LLM_BASE_URL` | OpenAI-compatible base URL |
| `LLM_MODEL` | Model name (e.g. `gpt-4o`) |
| `REDIS_URL` | Redis connection (default: `redis://localhost:12209`) |

Optional overrides:

| Variable | Default | Purpose |
|---|---|---|
| `ARTICLES_PER_SOURCE` | 10 | Max articles scraped per source |
| `MAX_TOTAL_NEWS` | 200 (CLI: 0=unlimited) | Cap on total articles in API responses |
| `CACHE_ARTICLE_TTL` | 18000 (5h) | Redis TTL for article cache (seconds) |
| `CACHE_SUMMARY_TTL` | 18000 (5h) | Redis TTL for LLM result cache |
| `CACHE_NEWS_TTL` | 7200 (2h) | Redis TTL for news list cache |
| `LLM_MAX_INPUT_CHARS` | 32000 | Max chars sent to LLM per article |
| `LLM_CALL_DELAY` | 2 | Seconds to sleep between LLM calls (rate limiting) |

## Architecture

Two modes: **CLI batch scraper** (`scrape.py`) and **FastAPI server** (`api.py`) backed by Redis.

### Data flow

```
category page → article links (h2/h3/h4 a selectors) → page text + OG thumbnail → LLM extract+summarize → Redis / JSON
```

No per-source parsing logic. The LLM handles all extraction (title, date, summary, content, tickers, relevance) in one call with a Vietnamese-language system prompt. LLM output is validated via Pydantic (`ArticleExtraction` in `llm_client.py`).

### Module roles

- **`scrape.py`** — HTTP fetching, link extraction, page text extraction, CLI entrypoint. Exports `SOURCES` dict and `scrape_source()`.
- **`api.py`** — FastAPI app with background hourly refresh loop. On startup, rebuilds news lists from cached articles via `rebuild_news_from_articles()`. News list endpoint interleaves sources round-robin.
- **`cache_client.py`** — Redis wrapper with graceful degradation (all operations no-op when Redis is unavailable). Three cache layers: article, LLM summary, news list.
- **`llm_client.py`** — OpenAI-compatible client with threading lock for rate limiting, 2-attempt retry, and JSON response parsing with control character sanitization.

### API endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Health check (`{"status": "ok"}`) |
| `GET /news` | List articles. Params: `source`, `limit` (1–100, default 20), `cursor` (pagination by article id) |
| `GET /news/{id}` | Single article detail (includes `content` field) |

- `id`: stable 18-digit numeric string from `sha256(url) % 10^18`
- Articles with `is_relevant: false` are filtered out of API responses
- Response envelope: `{ success, data, pagination, meta: { request_id, took_ms } }`
- Error envelope: `{ success: false, error: { code, message } }`

### Article schema

`{ id, title, url, source, published_at, summary, tickers, thumbnail, content }`

- `published_at`: ISO 8601 with `+07:00` timezone or `null`
- `source`: canonical domain (e.g. `cafef.vn`)
- `thumbnail`: `{ url, width?, height?, alt? }` from Open Graph meta tags
- `content`: markdown-formatted full article text (rewritten by LLM)
- `tickers`: list of Vietnamese stock ticker symbols (2–5 uppercase chars)

### Redis cache keys

| Key pattern | Content | TTL |
|---|---|---|
| `article:<url>` | `{title, published_at, summary, tickers, thumbnail, content, is_relevant}` | 5h |
| `summary:<sha256>` | LLM JSON result (keyed by sha256 of page text) | 5h |
| `news:<source>` | Full article list JSON per source | 2h |

### Docker

`docker-compose.yml` runs two services: `api` (the FastAPI app) and `redis` (Redis 7 Alpine). Redis is exposed on host port 12209 mapping to container port 6379. Inside Docker, the API connects to `redis://redis:6379`.
