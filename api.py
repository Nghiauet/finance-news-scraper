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


def _resolve_article(raw: dict, language: str) -> Optional[dict]:
    """Pick title/summary/content for the requested language. Returns None if
    the article lacks a translation in the requested language so the caller
    can skip it (e.g. EN requested but only VI extracted so far).

    language="all" returns every available field (both VI and EN) raw — used
    by downstream ingestion services that want to cache both languages in one
    upstream call."""
    url = raw.get("url", "")
    if language == "all":
        return {
            "id": _make_id(url),
            "title": raw.get("title", ""),
            "title_en": raw.get("title_en"),
            "url": url,
            "source": raw.get("source", ""),
            "published_at": raw.get("published_at"),
            "summary": raw.get("summary"),
            "summary_en": raw.get("summary_en"),
            "tickers": raw.get("tickers", []),
            "thumbnail": raw.get("thumbnail"),
            "content": raw.get("content"),
            "content_en": raw.get("content_en"),
            "scraped_at": raw.get("scraped_at"),
            "language": "all",
        }
    if language == "en":
        title = raw.get("title_en")
        if not title:
            return None
        summary = raw.get("summary_en")
        content = raw.get("content_en")
    else:
        title = raw.get("title", "")
        summary = raw.get("summary")
        content = raw.get("content")
    return {
        "id": _make_id(url),
        "title": title,
        "url": url,
        "source": raw.get("source", ""),
        "published_at": raw.get("published_at"),
        "summary": summary,
        "tickers": raw.get("tickers", []),
        "thumbnail": raw.get("thumbnail"),
        "content": content,
        "scraped_at": raw.get("scraped_at"),
        "language": language,
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
    language: str = "vi"
    title_en: Optional[str] = None
    summary_en: Optional[str] = None
    content_en: Optional[str] = None


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

# Floor for a source's time slice, and the slack allowed for an in-flight LLM
# call to unwind after the cooperative deadline passes.
_MIN_SOURCE_BUDGET = 60.0
_SOURCE_GRACE = 30.0

# asyncio holds only a weak reference to a running task, so a bare
# create_task() can be garbage-collected mid-run. Keep a strong reference
# until the task finishes.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    """Fire-and-forget a coroutine while holding a reference to its task."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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


def _finish_cycle(started_at: float, duration: float, total: int, ok: int,
                  articles_total: int, timed_out: bool, note: str = "") -> None:
    """Record the cycle and alert when it produced nothing.

    A cycle can report every source "ok" and still store zero articles: the
    sources answered and extraction failed afterwards. Nothing used to notice
    that combination, which is why a retired LLM model sat unfixed for 18 days
    while the dashboard showed 13/13 green.
    """
    cache_client.record_cron_run(started_at, duration, total, ok, articles_total, timed_out)
    if articles_total > 0:
        cache_client.clear_zero_article_streak()
        return
    streak = cache_client.bump_zero_article_streak()
    detail = f" — {note}" if note else ""
    log.error("[CRON] ALERT: cycle stored 0 articles (%d/%d sources reported ok), "
              "%d cycle(s) in a row%s", ok, total, streak, detail)
    cache_client.record_error(
        "cron",
        f"Refresh stored 0 articles ({ok}/{total} sources reported ok) — "
        f"{streak} consecutive empty cycle(s){detail}. The pipeline is producing "
        f"nothing: check LLM model health at /admin/llm.",
    )


async def _do_refresh():
    sources = list(SOURCES)
    total = len(sources)
    t_all = time.monotonic()
    started_at = time.time()
    refresh_timeout = settings_mod.get_setting("refresh_timeout")
    articles_per = settings_mod.get_setting("articles_per_source")
    log.info("[CRON] refresh started — %d sources, timeout %ds", total, refresh_timeout)
    # One cheap ping before fanning out to 13 sources: a retired model then
    # costs a single request instead of the entire refresh budget, and the
    # failover happens before any article is attempted.
    health = llm_client.ensure_healthy_active_model()
    if health.get("switched"):
        log.warning("[CRON] active model was gone — failed over to %s", health.get("model"))
    if health.get("dead") and not health.get("switched"):
        duration = time.monotonic() - t_all
        log.error("[CRON] no healthy LLM model — skipping cycle: %s", health.get("detail"))
        _finish_cycle(started_at, duration, total, 0, 0, False,
                      note=f"no healthy LLM model ({health.get('detail', '')})")
        return
    if not health.get("ok"):
        # Transient ping failure: proceed, per-article retries will cope.
        log.warning("[CRON] model ping failed but looks transient — continuing: %s",
                    health.get("detail"))

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
            # Split the time that's left evenly across the sources still to come.
            # Handing source #1 the whole remaining budget meant a slow model let
            # cafef spend all 1800s while the other 12 were never attempted, so
            # every cycle reported 0/13. A fair slice makes partial progress on
            # every source instead, and the incremental flush keeps it.
            per_source = max(_MIN_SOURCE_BUDGET, (refresh_timeout - elapsed) / (total - idx + 1))
            deadline = time.monotonic() + per_source
            articles = await asyncio.wait_for(
                asyncio.to_thread(scrape_source, source_name, articles_per, False, deadline),
                # scrape_source stops itself at the deadline; this only catches a
                # thread wedged in a syscall, since wait_for cannot cancel it.
                timeout=per_source + _SOURCE_GRACE,
            )
            # scrape_source owns the news:<source> write (incrementally during
            # the run, then authoritatively at the end). Re-writing it here
            # duplicated that work and, when a run produced nothing, replaced the
            # cached list with an empty one — wiping a whole source on a
            # transient fetch or LLM failure.
            ok += 1
            articles_total += len(articles)
            log.info("[CRON] [%d/%d] %s — stored %d articles in %.1fs",
                     idx, total, source_name, len(articles), time.monotonic() - t_src)
        except asyncio.TimeoutError:
            log.warning("[CRON] [%d/%d] %s — spent its %.0fs slice, moving on",
                        idx, total, source_name, per_source)
            cache_client.record_error(
                "cron", f"{source_name} used its full {per_source:.0f}s slice", source=source_name,
            )
        except Exception as e:
            log.error("[CRON] [%d/%d] %s — failed: %s", idx, total, source_name, e)
            cache_client.record_error("scrape", str(e), source=source_name)
    duration = time.monotonic() - t_all
    _finish_cycle(started_at, duration, total, ok, articles_total, timed_out)
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
    code_map = {
        400: "BAD_REQUEST", 401: "UNAUTHORIZED", 404: "NOT_FOUND",
        409: "CONFLICT", 422: "VALIDATION_ERROR",
    }
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
    language: str = Query(
        default="vi",
        description="Response language: 'vi' (default) or 'en'.",
        pattern="^(vi|en|all)$",
    ),
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

    normalized = [
        art
        for a in raw_articles
        if a.get("is_relevant", True)
        for art in [_resolve_article(a, language)]
        if art is not None
    ]

    seen_titles: set[str] = set()
    deduped = []
    for a in normalized:
        title_key = a["title"].strip().lower()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            deduped.append(a)
    normalized = deduped

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
        cursor_idx = next((i for i, item in enumerate(normalized) if item["id"] == cursor), None)
        if cursor_idx is None:
            # The cursor's article left the list (cron refresh, TTL expiry, or a
            # changed filter). Falling through with start=0 re-served page 1, so a
            # paginating client re-ingested the same articles instead of
            # finishing. End the sequence; the next pass starts from fresh data.
            log.warning("Stale /news cursor %r — ending pagination", cursor)
            return NewsListResponse(
                data=[],
                pagination=Pagination(next_cursor=None, has_more=False, limit=limit, total=total),
                meta=Meta(request_id=request_id, took_ms=int((time.monotonic() - t0) * 1000)),
            )
        start = cursor_idx + 1

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
def get_news_detail(
    article_id: str,
    language: str = Query(
        default="vi",
        description="Response language: 'vi' (default) or 'en'.",
        pattern="^(vi|en|all)$",
    ),
):
    t0 = time.monotonic()
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    for name in SOURCES:
        for raw in cache_client.get_news(name):
            if _make_id(raw.get("url", "")) == article_id and raw.get("is_relevant", True):
                article = _resolve_article(raw, language)
                if article is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Article '{article_id}' not available in language '{language}'.",
                    )
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


def _find_model_by_target(base_url: str, model_name: str, exclude_id: str | None = None) -> Optional[dict]:
    """Return an existing model aimed at the same base_url + model_name, if any.

    Model ids used to be a hash of exactly these two fields, so adding a
    duplicate silently overwrote the original (including its API key). Ids are
    opaque now, so the collision is reported instead of applied.
    """
    for m in cache_client.list_models():
        if m["id"] == exclude_id:
            continue
        if m.get("base_url") == base_url and m.get("model_name") == model_name:
            return m
    return None


def _enrich_models(models: list[dict], active_id: str | None) -> list[dict]:
    """Annotate models with is_active flag, per-model stats, and masked API keys."""
    for m in models:
        m["is_active"] = m["id"] == active_id
        # "ok" unless failover marked it dead, so the portal can show at a glance
        # which models are retired rather than only which one is active.
        m["health"] = m.get("health") or "ok"
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
    return {
        "success": True,
        "data": {"runs": runs, "zero_article_streak": cache_client.get_zero_article_streak()},
        "meta": _admin_meta(t0),
    }


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
    _spawn(_refresh_all())
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
    _spawn(_refresh_all())
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
    # Validate the whole batch before writing any of it — applying settings one
    # by one and then raising left the caller with a 400 and no way to tell which
    # values had already taken effect.
    errors = []
    for name, value in body.items():
        try:
            settings_mod.validate_setting(name, value)
        except (ValueError, TypeError) as e:
            errors.append(f"{name}: {e}")
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    for name, value in body.items():
        settings_mod.set_setting(name, value)
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
    dup = _find_model_by_target(body.base_url, body.model_name)
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"Model '{dup.get('name')}' already targets '{body.model_name}' "
                   f"at {body.base_url} — edit that one instead",
        )
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
    # Omitted or blank fields mean "leave unchanged" — never overwrite a stored
    # value with an empty one.
    updates = {
        k: v.strip() for k, v in body.model_dump().items()
        if isinstance(v, str) and v.strip()
    }
    # Read endpoints return the key masked; ignore a mask echoed back so editing
    # another field cannot replace the real key with asterisks.
    if updates.get("api_key", "").startswith("*"):
        del updates["api_key"]
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    current = cache_client.get_model_config(model_id)
    if not current:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    # Editing base_url/model_name must not land on another model's target either.
    dup = _find_model_by_target(
        updates.get("base_url", current.get("base_url", "")),
        updates.get("model_name", current.get("model_name", "")),
        exclude_id=model_id,
    )
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"Model '{dup.get('name')}' already targets that base_url + model_name",
        )
    ok = cache_client.update_model(model_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    # An edit is how a dead model gets fixed (rotated key, renamed model), so the
    # dead mark must not outlive the fix and keep failover skipping it.
    cache_client.clear_model_health(model_id)
    cache_client.release_lock("failover:all_dead")
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
    # Activating by hand is an operator saying "use this one" — drop any dead
    # mark and the all-dead back-off so the choice takes effect immediately
    # instead of being skipped by failover's cooldown.
    cache_client.clear_model_health(model_id)
    cache_client.release_lock("failover:all_dead")
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
    t0 = time.monotonic()
    if source_name not in SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source_name}'")
    articles = await asyncio.wait_for(
        asyncio.to_thread(scrape_source, source_name, limit, True),
        timeout=300,
    )
    payload = [asdict(a) for a in articles]
    for item in payload:
        item["id"] = _make_id(item["url"])
    return {"success": True, "data": payload, "meta": _admin_meta(t0)}


@app.post("/admin/refresh/{source_name}")
async def admin_refresh_source(
    source_name: str,
    _user: str = Depends(require_admin),
):
    t0 = time.monotonic()
    if source_name not in SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source_name}'")
    articles_per = settings_mod.get_setting("articles_per_source")
    articles = await asyncio.wait_for(
        asyncio.to_thread(scrape_source, source_name, articles_per),
        timeout=600,
    )
    return {"success": True, "data": {"count": len(articles), "source": source_name}, "meta": _admin_meta(t0)}


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
