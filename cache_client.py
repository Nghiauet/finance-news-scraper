"""
Redis cache client for scrape-news.
Caches: article content (by URL) and LLM summaries (by content hash).
"""

import hashlib
import os

import redis

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:12209")
_ARTICLE_TTL = int(os.environ.get("CACHE_ARTICLE_TTL", 18000))   # 5h
_SUMMARY_TTL = int(os.environ.get("CACHE_SUMMARY_TTL", 18000))   # 5h (depends on content)

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
# Article content cache  (key: "article:<url>")
# ---------------------------------------------------------------------------

def get_article(url: str) -> str | None:
    r = _get_client()
    if r is None:
        return None
    try:
        return r.get(f"article:{url}")
    except Exception:
        return None


def set_article(url: str, content: str) -> None:
    r = _get_client()
    if r is None:
        return
    try:
        r.setex(f"article:{url}", _ARTICLE_TTL, content)
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
