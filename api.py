"""
FastAPI server for the Vietnamese finance news scraper.

  - GET /news          → list (id, title, url, source, published_at, summary, tickers, thumbnail)
  - GET /news/{id}     → same fields + content (full article text)
  - POST /auth/login   → JWT token for admin portal
  - GET/PUT /admin/*   → admin endpoints (auth required)
  - Background cron (every 30m) → scrapes all sources, stores in Redis

Run with:
    uv run uvicorn api:app --host 0.0.0.0 --port 46401 --reload
"""

import asyncio
import hashlib
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

load_dotenv()

import cache_client  # noqa: E402
import llm_client  # noqa: E402
import settings as settings_mod  # noqa: E402
from auth import login as auth_login, require_admin  # noqa: E402
from scrape import SOURCES, scrape_source  # noqa: E402

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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
        "tickers": raw.get("tickers", []),
        "thumbnail": raw.get("thumbnail"),
        "content": raw.get("content"),
        "scraped_at": raw.get("scraped_at"),
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class Thumbnail(BaseModel):
    url: str
    width: Optional[int] = None
    height: Optional[int] = None
    alt: Optional[str] = None


class ArticleItem(BaseModel):
    id: str
    title: str
    url: str
    source: str
    published_at: Optional[str] = None
    summary: Optional[str] = None
    tickers: list[str] = []
    thumbnail: Optional[Thumbnail] = None
    content: Optional[str] = None
    scraped_at: Optional[str] = None


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

_refresh_running = False


async def _refresh_all():
    global _refresh_running
    if _refresh_running:
        log.warning("[CRON] refresh already running — skipping")
        return
    _refresh_running = True
    try:
        await _do_refresh()
    finally:
        _refresh_running = False


async def _do_refresh():
    sources = list(SOURCES)
    total = len(sources)
    t_all = time.monotonic()
    started_at = time.time()
    refresh_timeout = settings_mod.get_setting("refresh_timeout")
    articles_per = settings_mod.get_setting("articles_per_source")
    log.info("[CRON] refresh started — %d sources, timeout %ds", total, refresh_timeout)
    ok = 0
    articles_total = 0
    timed_out = False
    for idx, source_name in enumerate(sources, 1):
        elapsed = time.monotonic() - t_all
        if elapsed >= refresh_timeout:
            log.warning("[CRON] timeout reached (%.0fs >= %ds) — stopping after %d/%d sources",
                        elapsed, refresh_timeout, idx - 1, total)
            timed_out = True
            cache_client.record_error("cron", f"Global timeout after {idx - 1}/{total} sources")
            break
        t_src = time.monotonic()
        log.info("[CRON] [%d/%d] %s — starting", idx, total, source_name)
        try:
            remaining = refresh_timeout - elapsed
            articles = await asyncio.wait_for(
                asyncio.to_thread(scrape_source, source_name, articles_per),
                timeout=remaining,
            )
            payload = [
                {
                    "title": a.title,
                    "url": a.url,
                    "source": a.source,
                    "published_at": a.published_at,
                    "summary": a.summary,
                    "tickers": a.tickers,
                    "thumbnail": a.thumbnail,
                    "content": a.content,
                    "is_relevant": a.is_relevant,
                    "scraped_at": a.scraped_at,
                }
                for a in articles
            ]
            cache_client.set_news(source_name, payload)
            ok += 1
            articles_total += len(payload)
            log.info("[CRON] [%d/%d] %s — stored %d articles in %.1fs",
                     idx, total, source_name, len(payload), time.monotonic() - t_src)
        except asyncio.TimeoutError:
            log.warning("[CRON] [%d/%d] %s — timed out (refresh timeout reached)", idx, total, source_name)
            cache_client.record_error("cron", f"Source timeout: {source_name}", source=source_name)
        except Exception as e:
            log.error("[CRON] [%d/%d] %s — failed: %s", idx, total, source_name, e)
            cache_client.record_error("scrape", str(e), source=source_name)
    duration = time.monotonic() - t_all
    cache_client.record_cron_run(started_at, duration, total, ok, articles_total, timed_out)
    log.info("[CRON] refresh done — %d/%d sources ok in %.1fs", ok, total, duration)


async def _refresh_loop():
    while True:
        await _refresh_all()
        await asyncio.sleep(1800)


@asynccontextmanager
async def lifespan(app: FastAPI):
    rebuilt = cache_client.rebuild_news_from_articles(SOURCES)
    if rebuilt:
        log.info("Rebuilt %d news lists from cached articles on startup", rebuilt)
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

app = FastAPI(title="Vietnam Finance News API", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    code_map = {401: "UNAUTHORIZED", 404: "NOT_FOUND", 422: "VALIDATION_ERROR", 400: "BAD_REQUEST"}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {"code": code_map.get(exc.status_code, "ERROR"), "message": exc.detail},
        },
    )


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/news", response_model=NewsListResponse)
def get_news(
    source: Optional[str] = Query(default=None, description="Filter by source name."),
    limit: int = Query(default=20, ge=1, le=100, description="Max items per page."),
    cursor: Optional[str] = Query(default=None, description="Pagination cursor (id of last item)."),
    sort: Optional[str] = Query(default="newest", description="Sort: newest, oldest, recent (by scrape time)."),
    q: Optional[str] = Query(default=None, description="Search query (title, summary, tickers)."),
):
    t0 = time.monotonic()
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    if source and source not in SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source}'.")

    sources_to_query = [source] if source else list(SOURCES)

    if source:
        raw_articles: list[dict] = cache_client.get_news(source)
    else:
        buckets = [cache_client.get_news(name) for name in sources_to_query]
        raw_articles = [
            article
            for i in range(max((len(b) for b in buckets), default=0))
            for bucket in buckets
            if i < len(bucket)
            for article in [bucket[i]]
        ]

    normalized = [_normalize_article(a) for a in raw_articles if a.get("is_relevant", True)]

    # Search filter
    if q:
        q_lower = q.lower()
        normalized = [
            a for a in normalized
            if q_lower in (a.get("title") or "").lower()
            or q_lower in (a.get("summary") or "").lower()
            or any(q_lower in t.lower() for t in a.get("tickers", []))
        ]

    # Sort
    if sort == "recent":
        normalized.sort(key=lambda a: a.get("scraped_at") or "", reverse=True)
    elif sort in ("newest", "oldest"):
        normalized.sort(
            key=lambda a: a.get("published_at") or "",
            reverse=(sort == "newest"),
        )

    max_total = settings_mod.get_setting("max_total_news")
    if max_total > 0:
        normalized = normalized[:max_total]
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
            if _make_id(raw.get("url", "")) == article_id and raw.get("is_relevant", True):
                article = _normalize_article(raw)
                took_ms = int((time.monotonic() - t0) * 1000)
                return NewsDetailResponse(
                    data=ArticleItem(**article),
                    meta=Meta(request_id=request_id, took_ms=took_ms),
                )

    raise HTTPException(status_code=404, detail=f"Article '{article_id}' not found.")


# ---------------------------------------------------------------------------
# Auth endpoint (public)
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def login_endpoint(body: LoginRequest):
    token = auth_login(body.username, body.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"success": True, "data": {"token": token}}


# ---------------------------------------------------------------------------
# Admin endpoints (auth required)
# ---------------------------------------------------------------------------

def _admin_meta(t0: float) -> dict:
    return {"request_id": f"req_{uuid.uuid4().hex[:12]}", "took_ms": int((time.monotonic() - t0) * 1000)}


def _build_sources_info() -> tuple[list[dict], dict]:
    """Build sources info list and cache stats (shared by stats/sources endpoints)."""
    cache = cache_client.get_cache_stats()
    sources_info = [
        {"name": name, "url": cfg["url"], "domain": cfg["domain"],
         "article_count": cache.get("source_counts", {}).get(name, 0)}
        for name, cfg in SOURCES.items()
    ]
    return sources_info, cache


def _mask_api_key(key: str) -> str:
    """Mask API key for safe display — show only last 4 chars."""
    if len(key) <= 4:
        return "****"
    return "*" * (len(key) - 4) + key[-4:]


def _enrich_models(models: list[dict], active_id: str | None) -> list[dict]:
    """Annotate models with is_active flag, per-model stats, and masked API keys."""
    for m in models:
        m["is_active"] = m["id"] == active_id
        model_stats = cache_client.get_llm_stats(recent_limit=0, model_id=m["id"])
        m["stats"] = model_stats.get("totals", {})
        if "api_key" in m:
            m["api_key"] = _mask_api_key(m["api_key"])
    return models


@app.get("/admin/stats")
def admin_stats(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    sources_info, cache = _build_sources_info()
    llm = cache_client.get_llm_stats(recent_limit=0)
    return {
        "success": True,
        "data": {
            "cache": cache,
            "llm_totals": llm.get("totals", {}),
            "sources": sources_info,
        },
        "meta": _admin_meta(t0),
    }


@app.get("/admin/llm")
def admin_llm(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    model_info = llm_client.get_model_info()
    stats = cache_client.get_llm_stats(recent_limit=100)
    models = cache_client.list_models()
    active_id = cache_client.get_active_model_id()
    _enrich_models(models, active_id)
    return {
        "success": True,
        "data": {
            "model": model_info,
            "totals": stats.get("totals", {}),
            "recent_calls": stats.get("recent_calls", []),
            "models": models,
            "active_model_id": active_id,
        },
        "meta": _admin_meta(t0),
    }


@app.get("/admin/sources")
def admin_sources(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    sources_info, _cache = _build_sources_info()
    return {
        "success": True,
        "data": sources_info,
        "meta": _admin_meta(t0),
    }


@app.get("/admin/cache")
def admin_cache(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    return {
        "success": True,
        "data": cache_client.get_cache_stats(),
        "meta": _admin_meta(t0),
    }


# ---------------------------------------------------------------------------
# Monitoring endpoints (auth required)
# ---------------------------------------------------------------------------

@app.get("/admin/cron")
def admin_cron(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    runs = cache_client.get_cron_runs(limit=50)
    return {"success": True, "data": {"runs": runs}, "meta": _admin_meta(t0)}


@app.get("/admin/errors")
def admin_errors(
    hours: int = Query(default=24, ge=1, le=168, description="Hours of error history."),
    _user: str = Depends(require_admin),
):
    t0 = time.monotonic()
    since = int(time.time()) - (hours * 3600)
    errors = cache_client.get_error_log(since=since, limit=500)
    return {"success": True, "data": {"errors": errors, "hours": hours}, "meta": _admin_meta(t0)}


@app.post("/admin/refresh-all")
async def admin_refresh_all(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    if _refresh_running:
        raise HTTPException(status_code=409, detail="A refresh is already running")
    asyncio.create_task(_refresh_all())
    return {"success": True, "data": {"message": "Refresh started"}, "meta": _admin_meta(t0)}


@app.get("/admin/refresh-status")
def admin_refresh_status(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    return {"success": True, "data": {"running": _refresh_running}, "meta": _admin_meta(t0)}


@app.post("/admin/purge")
async def admin_purge(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    if _refresh_running:
        raise HTTPException(status_code=409, detail="Cannot purge while a refresh is running")
    counts = cache_client.purge_all_cache()
    log.info("[PURGE] Deleted %d articles, %d summaries, %d news lists",
             counts["articles"], counts["summaries"], counts["news"])
    asyncio.create_task(_refresh_all())
    return {
        "success": True,
        "data": {"purged": counts, "message": "Cache purged, rescrape started"},
        "meta": _admin_meta(t0),
    }


# ---------------------------------------------------------------------------
# Settings endpoints (auth required)
# ---------------------------------------------------------------------------

@app.get("/admin/settings")
def admin_get_settings(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    return {
        "success": True,
        "data": settings_mod.get_all_settings(),
        "meta": _admin_meta(t0),
    }


@app.put("/admin/settings")
def admin_update_settings(body: dict, _user: str = Depends(require_admin)):
    t0 = time.monotonic()
    errors = []
    for name, value in body.items():
        try:
            settings_mod.set_setting(name, value)
        except (ValueError, TypeError) as e:
            errors.append(f"{name}: {e}")
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return {
        "success": True,
        "data": settings_mod.get_all_settings(),
        "meta": _admin_meta(t0),
    }


@app.post("/admin/settings/reset")
def admin_reset_settings(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    settings_mod.reset_all()
    return {
        "success": True,
        "data": settings_mod.get_all_settings(),
        "meta": _admin_meta(t0),
    }


# ---------------------------------------------------------------------------
# Model management endpoints (auth required)
# ---------------------------------------------------------------------------

class ModelCreate(BaseModel):
    name: str
    base_url: str
    api_key: str
    model_name: str


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None


@app.get("/admin/models")
def admin_list_models(_user: str = Depends(require_admin)):
    t0 = time.monotonic()
    models = cache_client.list_models()
    active_id = cache_client.get_active_model_id()
    _enrich_models(models, active_id)
    return {"success": True, "data": {"models": models, "active_model_id": active_id}, "meta": _admin_meta(t0)}


@app.post("/admin/models")
def admin_add_model(body: ModelCreate, _user: str = Depends(require_admin)):
    t0 = time.monotonic()
    model_id = cache_client.add_model({
        "name": body.name,
        "base_url": body.base_url,
        "api_key": body.api_key,
        "model_name": body.model_name,
    })
    if not model_id:
        raise HTTPException(status_code=500, detail="Failed to add model")
    # Auto-activate if first model
    existing = cache_client.list_models()
    if len(existing) == 1:
        cache_client.set_active_model(model_id)
        llm_client.invalidate_active_client()
    return {"success": True, "data": {"id": model_id}, "meta": _admin_meta(t0)}


@app.put("/admin/models/{model_id}")
def admin_update_model(model_id: str, body: ModelUpdate, _user: str = Depends(require_admin)):
    t0 = time.monotonic()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = cache_client.update_model(model_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    llm_client.invalidate_active_client()
    config = cache_client.get_model_config(model_id)
    if config and "api_key" in config:
        config["api_key"] = _mask_api_key(config["api_key"])
    return {"success": True, "data": config, "meta": _admin_meta(t0)}


@app.delete("/admin/models/{model_id}")
def admin_delete_model(model_id: str, _user: str = Depends(require_admin)):
    t0 = time.monotonic()
    ok = cache_client.delete_model(model_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    llm_client.invalidate_active_client()
    return {"success": True, "meta": _admin_meta(t0)}


@app.post("/admin/models/{model_id}/activate")
def admin_activate_model(model_id: str, _user: str = Depends(require_admin)):
    t0 = time.monotonic()
    config = cache_client.get_model_config(model_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    cache_client.set_active_model(model_id)
    llm_client.invalidate_active_client()
    return {"success": True, "data": {"active_model_id": model_id}, "meta": _admin_meta(t0)}


@app.post("/admin/models/{model_id}/test")
async def admin_test_model(model_id: str, _user: str = Depends(require_admin)):
    t0 = time.monotonic()
    config = cache_client.get_model_config(model_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    result = await asyncio.to_thread(llm_client.test_model, config)
    return {"success": True, "data": result, "meta": _admin_meta(t0)}


# ---------------------------------------------------------------------------
# Preview / manual refresh endpoints (auth required)
# ---------------------------------------------------------------------------

@app.post("/admin/preview/{source_name}")
async def admin_preview_source(
    source_name: str,
    limit: int = Query(default=5, ge=1, le=10),
    _user: str = Depends(require_admin),
):
    if source_name not in SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source_name}'")
    articles = await asyncio.wait_for(
        asyncio.to_thread(scrape_source, source_name, limit, True),
        timeout=300,
    )
    payload = [asdict(a) for a in articles]
    for item in payload:
        item["id"] = _make_id(item["url"])
    return {"success": True, "data": payload, "meta": _admin_meta(time.monotonic())}


@app.post("/admin/refresh/{source_name}")
async def admin_refresh_source(
    source_name: str,
    _user: str = Depends(require_admin),
):
    if source_name not in SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source_name}'")
    articles_per = settings_mod.get_setting("articles_per_source")
    articles = await asyncio.wait_for(
        asyncio.to_thread(scrape_source, source_name, articles_per),
        timeout=600,
    )
    return {"success": True, "data": {"count": len(articles), "source": source_name}, "meta": _admin_meta(time.monotonic())}


# ---------------------------------------------------------------------------
# SPA static files (must be LAST — catch-all for /portal/*)
# ---------------------------------------------------------------------------

PORTAL_DIR = Path(__file__).resolve().parent / "portal_dist"


class SPAStaticFiles(StaticFiles):
    """Falls back to index.html for client-side routing."""
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except (StarletteHTTPException, HTTPException) as ex:
            if ex.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


if PORTAL_DIR.is_dir():
    app.mount("/portal", SPAStaticFiles(directory=str(PORTAL_DIR), html=True), name="portal")
    log.info("Portal mounted from %s", PORTAL_DIR)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=46401, reload=True)
