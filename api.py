"""
FastAPI server for the Vietnamese finance news scraper.

Architecture:
  - GET /news   → reads from Redis cache (fast)
  - Background cron (every 1 h) → scrapes all sources, stores in Redis

Run with:
    uv run uvicorn api:app --host 0.0.0.0 --port 46401 --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from pydantic import BaseModel

load_dotenv()

import cache_client  # noqa: E402
from scrape import SOURCES, scrape_source  # noqa: E402

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ARTICLES_PER_SOURCE = 10  # scrape as many as possible each refresh cycle


# ---------------------------------------------------------------------------
# Background refresh
# ---------------------------------------------------------------------------

async def _refresh_all():
    """Scrape every source and replace its Redis cache entry."""
    log.info("[CRON] News refresh started")
    for source_name in SOURCES:
        try:
            articles = await asyncio.to_thread(scrape_source, source_name, ARTICLES_PER_SOURCE)
            payload = [
                {
                    "title": a.title,
                    "url": a.url,
                    "source": a.source,
                    "published_at": a.published_at,
                    "content": a.content,
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
    """Run refresh immediately on startup, then repeat every hour."""
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

app = FastAPI(
    title="Vietnam Finance News API",
    version="1.0.0",
    lifespan=lifespan,
)


class ArticleOut(BaseModel):
    title: str
    url: str
    source: str
    published_at: Optional[str]
    content: str
    summary: Optional[str]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/news", response_model=list[ArticleOut])
def get_news(
    source: Optional[str] = Query(
        default=None,
        description=(
            "Filter by source name. Omit to get all sources. "
            "Options: cafef, vnexpress, tinnhanhchungkhoan, ndh, baodautu, "
            "vietnambiz, vietstock, dantri, tuoitre, thanhnien."
        ),
    ),
):
    """
    Return cached finance news with LLM summaries.

    Data is served from Redis and refreshed automatically every hour.
    Returns an empty list if the cache hasn't been populated yet
    (first refresh runs in the background on startup).
    """
    sources_to_query = [source] if source and source in SOURCES else list(SOURCES)
    results = []
    for name in sources_to_query:
        results.extend(cache_client.get_news(name))
    return results


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=46401, reload=True)
