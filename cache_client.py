"""
Redis cache client for scrape-news.
Caches: article data (by URL), LLM results (by content hash),
        and news lists per source (key: "news:<source>").
"""

import hashlib
import json
import logging
import os

import redis
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:12209")
_ARTICLE_TTL = int(os.environ.get("CACHE_ARTICLE_TTL", 18000))   # 5h
_SUMMARY_TTL = int(os.environ.get("CACHE_SUMMARY_TTL", 18000))   # 5h
_NEWS_TTL    = int(os.environ.get("CACHE_NEWS_TTL",    7200))    # 2h

_client: redis.Redis | None = None


def _get_client() -> redis.Redis | None:
    global _client
    if _client is not None:
        return _client
    try:
        r = redis.from_url(_REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        r.ping()
        _client = r
        log.info("Connected to Redis at %s", _REDIS_URL)
    except Exception as e:
        log.warning("Redis unavailable (%s) — running without cache", e)
        _client = None
    return _client


# ---------------------------------------------------------------------------
# Article cache  (key: "article:<url>")
# Stores JSON: {"title": str, "published_at": str|null, "summary": str|null}
# ---------------------------------------------------------------------------

def get_article(url: str) -> dict | None:
    r = _get_client()
    if r is None:
        return None
    try:
        raw = r.get(f"article:{url}")
        if not raw:
            return None
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def set_article(
    url: str,
    title: str,
    published_at: str | None = None,
    summary: str | None = None,
    tickers: list | None = None,
    icb_codes: list | None = None,
    thumbnail: dict | None = None,
) -> None:
    r = _get_client()
    if r is None:
        return
    try:
        payload = json.dumps(
            {
                "title": title,
                "published_at": published_at,
                "summary": summary,
                "tickers": tickers or [],
                "icb_codes": icb_codes or [],
                "thumbnail": thumbnail,
            },
            ensure_ascii=False,
        )
        r.setex(f"article:{url}", _ARTICLE_TTL, payload)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LLM result cache  (key: "summary:<sha256 of content>")
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


def rebuild_news_from_articles(sources: dict) -> int:
    """Scan article:<url> keys and rebuild news:<source> lists.

    Called at API startup so cached articles are immediately servable
    even before the background cron finishes a full refresh.
    Returns the number of sources rebuilt.
    """
    r = _get_client()
    if r is None:
        return 0

    # Collect all cached articles
    try:
        article_keys = list(r.scan_iter("article:*", count=500))
    except Exception:
        return 0

    if not article_keys:
        return 0

    # Group articles by source domain
    by_source: dict[str, list[dict]] = {}
    # Invert sources dict: domain -> source_name
    domain_to_name = {cfg["domain"]: name for name, cfg in sources.items()}

    for key in article_keys:
        try:
            raw = r.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            url = key.removeprefix("article:")
            # Determine source from URL domain
            source_name = None
            for domain, name in domain_to_name.items():
                if domain in url:
                    source_name = name
                    break
            if not source_name:
                continue
            data["url"] = url
            data["source"] = next(
                (d for d in domain_to_name if d in url), ""
            )
            by_source.setdefault(source_name, []).append(data)
        except Exception:
            continue

    rebuilt = 0
    for source_name, articles in by_source.items():
        # Only rebuild if news:<source> doesn't already exist
        try:
            if not r.exists(f"news:{source_name}"):
                r.setex(
                    f"news:{source_name}",
                    _NEWS_TTL,
                    json.dumps(articles, ensure_ascii=False),
                )
                rebuilt += 1
                log.info("Rebuilt news:%s from %d cached articles", source_name, len(articles))
        except Exception:
            continue

    return rebuilt
