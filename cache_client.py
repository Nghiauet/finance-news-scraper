"""
Redis cache client for scrape-news.
Caches: article content (by URL), LLM summaries (by content hash),
        and news lists per source (key: "news:<source>").
"""

import hashlib
import json
import os

import redis

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:12209")
_ARTICLE_TTL = int(os.environ.get("CACHE_ARTICLE_TTL", 18000))   # 5h
_SUMMARY_TTL = int(os.environ.get("CACHE_SUMMARY_TTL", 18000))   # 5h (depends on content)
_NEWS_TTL    = int(os.environ.get("CACHE_NEWS_TTL",    7200))    # 2h (buffer beyond 1h cron)

_client: redis.Redis | None = None


def _get_client() -> redis.Redis | None:
    global _client
    if _client is not None:
        return _client
    try:
        r = redis.from_url(_REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        r.ping()
        _client = r
        print(f"  [CACHE] Connected to Redis at {_REDIS_URL}")
    except Exception as e:
        print(f"  [CACHE] Redis unavailable ({e}) — running without cache")
        _client = None
    return _client


# ---------------------------------------------------------------------------
# Article cache  (key: "article:<url>")
# Stores JSON: {"content": str, "published_at": str|null}
# ---------------------------------------------------------------------------

def get_article(url: str) -> dict | None:
    """Return {"content": ..., "published_at": ...} or None."""
    r = _get_client()
    if r is None:
        return None
    try:
        raw = r.get(f"article:{url}")
        if not raw:
            return None
        # Migration: old entries stored plain content string, not JSON
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "content" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        # Legacy plain-string entry
        return {"content": raw, "published_at": None}
    except Exception:
        return None


def set_article(url: str, content: str, published_at: str | None = None) -> None:
    r = _get_client()
    if r is None:
        return
    try:
        payload = json.dumps({"content": content, "published_at": published_at}, ensure_ascii=False)
        r.setex(f"article:{url}", _ARTICLE_TTL, payload)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LLM summary cache  (key: "summary:<sha256 of content>")
# ---------------------------------------------------------------------------

def _content_key(content: str) -> str:
    digest = hashlib.sha256(content.encode()).hexdigest()
    return f"summary:{digest}"


def get_summary(content: str) -> str | None:
    r = _get_client()
    if r is None:
        return None
    try:
        return r.get(_content_key(content))
    except Exception:
        return None


def set_summary(content: str, summary: str) -> None:
    r = _get_client()
    if r is None:
        return
    try:
        r.setex(_content_key(content), _SUMMARY_TTL, summary)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# News list cache  (key: "news:<source>")
# ---------------------------------------------------------------------------

def get_news(source: str) -> list[dict]:
    r = _get_client()
    if r is None:
        return []
    try:
        raw = r.get(f"news:{source}")
        return json.loads(raw) if raw else []
    except Exception:
        return []


def set_news(source: str, articles: list[dict]) -> None:
    r = _get_client()
    if r is None:
        return
    try:
        r.setex(f"news:{source}", _NEWS_TTL, json.dumps(articles, ensure_ascii=False))
    except Exception:
        pass
