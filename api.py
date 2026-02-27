"""
FastAPI server for the Vietnamese finance news scraper.

  - GET /news          → list (id, title, url, source, published_at, summary)
  - GET /news/{id}     → same fields, single article
  - Background cron (every 1h) → scrapes all sources, stores in Redis

Run with:
    uv run uvicorn api:app --host 0.0.0.0 --port 46401 --reload
"""

import asyncio
import hashlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

load_dotenv()

import cache_client  # noqa: E402
from scrape import SOURCES, scrape_source  # noqa: E402

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ARTICLES_PER_SOURCE = 10


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _make_id(url: str) -> str:
    """Stable 18-digit numeric string derived from URL."""
    digest = int(hashlib.sha256(url.encode()).hexdigest(), 16)
    return str(digest % (10 ** 18))


def _normalize_article(raw: dict) -> dict:
    url = raw.get("url", "")
    return {
        "id": _make_id(url),
        "title": raw.get("title", ""),
        "url": url,
        "source": raw.get("source", ""),
        "published_at": raw.get("published_at"),
        "summary": raw.get("summary"),
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ArticleItem(BaseModel):
    id: str
    title: str
    url: str
    source: str
    published_at: Optional[str] = None
    summary: Optional[str] = None


class Pagination(BaseModel):
    next_cursor: Optional[str] = None
    has_more: bool
    limit: int
    total: int


class Meta(BaseModel):
    request_id: str
    took_ms: int


class NewsListResponse(BaseModel):
    success: bool = True
    data: list[ArticleItem]
    pagination: Pagination
    meta: Meta


class NewsDetailResponse(BaseModel):
    success: bool = True
    data: ArticleItem
    meta: Meta


# ---------------------------------------------------------------------------
# Background refresh
# ---------------------------------------------------------------------------

async def _refresh_all():
    log.info("[CRON] News refresh started")
    for source_name, source in SOURCES.items():
        try:
            articles = await asyncio.to_thread(scrape_source, source_name, ARTICLES_PER_SOURCE)
            payload = [
                {
                    "title": a.title,
                    "url": a.url,
                    "source": a.source,
                    "published_at": a.published_at,
                    "summary": a.summary,
                }
                for a in articles
            ]
            cache_client.set_news(source_name, payload)
            log.info(f"[CRON] {source_name}: {len(payload)} articles stored")
        except Exception as e:
            log.error(f"[CRON] {source_name} failed: {e}")
    log.info("[CRON] News refresh done")


async def _refresh_loop():
    while True:
        await _refresh_all()
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_refresh_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Vietnam Finance News API", version="3.0.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    code_map = {404: "NOT_FOUND", 422: "VALIDATION_ERROR", 400: "BAD_REQUEST"}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {"code": code_map.get(exc.status_code, "ERROR"), "message": exc.detail},
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/news", response_model=NewsListResponse)
def get_news(
    source: Optional[str] = Query(default=None, description="Filter by source name."),
    limit: int = Query(default=20, ge=1, le=100, description="Max items per page."),
    cursor: Optional[str] = Query(default=None, description="Pagination cursor (id of last item)."),
):
    t0 = time.monotonic()
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    if source and source not in SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source}'.")

    sources_to_query = [source] if source else list(SOURCES)
    raw_articles: list[dict] = []
    for name in sources_to_query:
        raw_articles.extend(cache_client.get_news(name))

    normalized = [_normalize_article(a) for a in raw_articles]
    total = len(normalized)

    start = 0
    if cursor:
        for i, item in enumerate(normalized):
            if item["id"] == cursor:
                start = i + 1
                break

    page = normalized[start: start + limit]
    has_more = (start + limit) < total
    next_cursor = page[-1]["id"] if has_more and page else None

    data = [ArticleItem(**a) for a in page]
    took_ms = int((time.monotonic() - t0) * 1000)

    return NewsListResponse(
        data=data,
        pagination=Pagination(next_cursor=next_cursor, has_more=has_more, limit=limit, total=total),
        meta=Meta(request_id=request_id, took_ms=took_ms),
    )


@app.get("/news/{article_id}", response_model=NewsDetailResponse)
def get_news_detail(article_id: str):
    t0 = time.monotonic()
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    for name in SOURCES:
        for raw in cache_client.get_news(name):
            if _make_id(raw.get("url", "")) == article_id:
                article = _normalize_article(raw)
                took_ms = int((time.monotonic() - t0) * 1000)
                return NewsDetailResponse(
                    data=ArticleItem(**article),
                    meta=Meta(request_id=request_id, took_ms=took_ms),
                )

    raise HTTPException(status_code=404, detail=f"Article '{article_id}' not found.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=46401, reload=True)
