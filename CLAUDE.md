# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies and set up venv
uv sync

# Run the scraper
uv run scrape.py
```

Always use `uv run` to execute scripts — never activate the venv manually.

## Architecture

This is a single-file scraper (`scrape.py`) that collects Vietnamese finance news.

**Flow:** category page → article list → full article content → `data/articles_YYYYMMDD_HHMMSS.json`

### Core abstractions

- `Article` dataclass — holds `title`, `url`, `source`, `published_at`, `content`
- `fetch_html(url, weak_ssl)` — shared HTTP fetcher; `weak_ssl=True` lowers cipher security for sites with broken DH keys (e.g. ndh.vn)
- `SOURCES` dict — registry mapping source name → `{list_fn, extract_fn, default_url}`

### Per-source pattern

Each source implements two functions:
- `get_<source>_list(category_url)` → `list[dict]` — scrapes article links from a category page
- `extract_<source>(url)` → `Optional[Article]` — fetches and parses a single article

### Active sources (8/10 working)

| Source | Category URL | Notes |
|---|---|---|
| cafef | `/thi-truong-chung-khoan.chn` | |
| vnexpress | `/kinh-doanh` | Cleanest date extraction |
| tinnhanhchungkhoan | `/chung-khoan/` | |
| vietnambiz | `/tai-chinh.htm` | Content in `div.vnbcbc-body` |
| vietstock | `/chung-khoan.htm` | Links use `/YEAR/MONTH/` pattern; content in `div#vst_detail` |
| dantri | `/kinh-doanh.htm` | |
| tuoitre | `/kinh-te.htm` | |
| thanhnien | `/kinh-te.htm` | |
| ndh | `/chung-khoan.htm` | Broken root cert — SSL fails |
| baodautu | `/chung-khoan-d1.html` | JS-rendered content — list works, body empty |

### Link detection strategies

Most sources: `h2 a, h3 a` CSS selectors
- **baodautu**: regex pattern `baodautu\.vn/.+-d\d+\.html` (no h2/h3 wrappers)
- **vietstock**: regex pattern `vietstock\.vn/\d{4}/\d{2}/.+\.htm`

### Output

Saved to `data/articles_YYYYMMDD_HHMMSS.json` — timestamped so runs don't overwrite each other. Each entry: `{title, url, source, published_at, content}`.
