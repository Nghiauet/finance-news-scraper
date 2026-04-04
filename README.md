# scrape-news

Vietnamese finance news scraper + FastAPI server. Pulls articles from 13 Vietnamese financial news sites, uses an LLM to extract and summarize them, and serves the results over a JSON API backed by Redis.

## What it does

- Scrapes category pages from 13 sources (cafef, vnexpress, tinnhanhchungkhoan, vietnambiz, vietstock, dantri, thanhnien, vneconomy, kinhtechungkhoan, thoibaonganhang, cafebiz, nguoiquansat, stockbiz)
- Sends each article's page text to an OpenAI-compatible LLM, which returns title, publish date, summary, full markdown content, tickers, and a relevance flag in one call
- Caches articles, LLM results, and per-source news lists in Redis (3-day TTL by default)
- Serves a paginated `/news` endpoint with round-robin interleaving across sources
- Refreshes in the background every 30 minutes
- Ships with an admin portal (React/Vite, in `portal/`) for monitoring and settings

## Quick start

```bash
# 1. Install Python deps (requires Python 3.13)
uv sync

# 2. Set env vars (see below), then:

# Run the FastAPI server
uv run uvicorn api:app --host 0.0.0.0 --port 46401 --reload

# Or run the CLI scraper once (writes JSON to data/)
uv run scrape.py

# Test mode: scrape only the first source with 3 articles
uv run scrape.py --test
```

Always use `uv run` — do not activate the venv manually.

## Docker

```bash
docker compose up --build
```

Runs two services:

- `api` — FastAPI app on host port `46401`
- `redis` — Redis 7 Alpine on host port `12209` (container port 6379)

Inside Docker, the API connects to `redis://redis:6379`.

## Environment

Copy `.env` and set:

| Variable | Purpose |
|---|---|
| `LLM_API_KEY` | OpenAI-compatible API key |
| `LLM_BASE_URL` | OpenAI-compatible base URL |
| `LLM_MODEL` | Model name (e.g. `gpt-4o`) |
| `REDIS_URL` | Redis connection (default `redis://localhost:12209`) |

Optional overrides:

| Variable | Default | Purpose |
|---|---|---|
| `ARTICLES_PER_SOURCE` | 23 (API) / 30 (CLI) | Max articles scraped per source |
| `MAX_TOTAL_NEWS` | 300 (API) / 0 (CLI, unlimited) | Cap on total articles in API responses |
| `REFRESH_TIMEOUT` | 1800 | Max seconds for a single refresh cycle |
| `CACHE_ARTICLE_TTL` | 259200 | Redis TTL for article cache (seconds) |
| `CACHE_SUMMARY_TTL` | 259200 | Redis TTL for LLM result cache |
| `CACHE_NEWS_TTL` | 259200 | Redis TTL for news list cache |
| `LLM_MAX_INPUT_CHARS` | 32000 | Max chars sent to LLM per article |
| `LLM_CALL_DELAY` | 2 | Sleep seconds between LLM calls (rate limiting) |

## API

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `GET /news` | List articles. Params: `source`, `limit` (1–100, default 20), `cursor` |
| `GET /news/{id}` | Single article, including full `content` |
| `POST /auth/login` | JWT login for admin portal |
| `GET/PUT /admin/*` | Admin endpoints (auth required) |

Response envelope:

```json
{ "success": true, "data": ..., "pagination": ..., "meta": { "request_id": "...", "took_ms": 42 } }
```

Error envelope:

```json
{ "success": false, "error": { "code": "...", "message": "..." } }
```

### Article schema

```
{ id, title, url, source, published_at, summary, tickers, thumbnail, content }
```

- `id` — 18-digit numeric string from `sha256(url) % 10^18`
- `published_at` — ISO 8601 with `+07:00` timezone, or `null`
- `source` — canonical domain (e.g. `cafef.vn`)
- `thumbnail` — `{ url, width?, height?, alt? }` from Open Graph tags
- `content` — markdown-formatted full article text (rewritten by LLM)
- `tickers` — Vietnamese stock ticker symbols (2–5 uppercase chars)

Articles with `is_relevant: false` are filtered out of API responses.

## Architecture

```
category page  →  article links  →  page text + OG thumbnail  →  LLM extract+summarize  →  Redis / JSON
```

No per-source parsing logic — the LLM handles extraction (title, date, summary, content, tickers, relevance) in one call with a Vietnamese-language system prompt. Output is validated with Pydantic (`ArticleExtraction` in `llm_client.py`).

### Modules

- **`scrape.py`** — HTTP fetching, link extraction, page text extraction, CLI entrypoint. Exports `SOURCES` and `scrape_source()`.
- **`api.py`** — FastAPI app with background 30-minute refresh loop. Rebuilds news lists from cached articles on startup.
- **`cache_client.py`** — Redis wrapper with graceful degradation (no-ops when Redis is unavailable). Three cache layers: article, LLM summary, news list.
- **`llm_client.py`** — OpenAI-compatible client with threading lock for rate limiting, 2-attempt retry, JSON parsing with control character sanitization.
- **`settings.py`** — Runtime-mutable settings (TTLs, LLM config) backed by Redis.
- **`auth.py`** — JWT login for the admin portal.
- **`portal/`** — React/Vite admin UI.

### Redis keys

| Key | Content | TTL |
|---|---|---|
| `article:<url>` | `{title, published_at, summary, tickers, thumbnail, content, is_relevant}` | 3d |
| `summary:<sha256>` | LLM JSON result, keyed by sha256 of page text | 3d |
| `news:<source>` | Full article list JSON per source | 3d |

## Development

```bash
# Syntax-check a modified file
python -m py_compile <file.py>
```

See `CLAUDE.md` for the same info written for AI coding assistants.
