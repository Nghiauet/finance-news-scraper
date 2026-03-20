"""
Redis cache client for scrape-news.
Caches: article data (by URL), LLM results (by content hash),
        and news lists per source (key: "news:<source>").
"""

import hashlib
import json
import logging
import os
import time

import redis
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:12209")
_ARTICLE_TTL = int(os.environ.get("CACHE_ARTICLE_TTL", 259200))   # 3 days
_SUMMARY_TTL = int(os.environ.get("CACHE_SUMMARY_TTL", 259200))   # 3 days
_NEWS_TTL    = int(os.environ.get("CACHE_NEWS_TTL",    259200))    # 3 days

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
    thumbnail: dict | None = None,
    content: str | None = None,
    is_relevant: bool = True,
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
                "thumbnail": thumbnail,
                "content": content,
                "is_relevant": is_relevant,
                "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
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


# ---------------------------------------------------------------------------
# LLM usage tracking  (keys: "llm:totals" hash, "llm:calls" list)
# ---------------------------------------------------------------------------

_LLM_CALLS_MAX = 500  # keep last N call records


def record_llm_call(prompt_tokens: int, completion_tokens: int, latency_ms: int, model_id: str = "") -> None:
    r = _get_client()
    if r is None:
        return
    try:
        total = prompt_tokens + completion_tokens
        record = json.dumps({
            "timestamp": int(time.time()),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total,
            "latency_ms": latency_ms,
        })
        pipe = r.pipeline()
        # Global totals
        pipe.hincrby("llm:totals", "prompt_tokens", prompt_tokens)
        pipe.hincrby("llm:totals", "completion_tokens", completion_tokens)
        pipe.hincrby("llm:totals", "total_tokens", total)
        pipe.hincrby("llm:totals", "call_count", 1)
        pipe.lpush("llm:calls", record)
        pipe.ltrim("llm:calls", 0, _LLM_CALLS_MAX - 1)
        # Per-model totals
        if model_id:
            pipe.hincrby(f"llm:totals:{model_id}", "prompt_tokens", prompt_tokens)
            pipe.hincrby(f"llm:totals:{model_id}", "completion_tokens", completion_tokens)
            pipe.hincrby(f"llm:totals:{model_id}", "total_tokens", total)
            pipe.hincrby(f"llm:totals:{model_id}", "call_count", 1)
            pipe.lpush(f"llm:calls:{model_id}", record)
            pipe.ltrim(f"llm:calls:{model_id}", 0, _LLM_CALLS_MAX - 1)
        pipe.execute()
    except Exception:
        pass


def record_llm_error(model_id: str = "") -> None:
    r = _get_client()
    if r is None:
        return
    try:
        pipe = r.pipeline()
        pipe.hincrby("llm:totals", "error_count", 1)
        if model_id:
            pipe.hincrby(f"llm:totals:{model_id}", "error_count", 1)
        pipe.execute()
    except Exception:
        pass


def get_llm_stats(recent_limit: int = 100, model_id: str | None = None) -> dict:
    r = _get_client()
    if r is None:
        return {"totals": {}, "recent_calls": []}
    try:
        totals_key = f"llm:totals:{model_id}" if model_id else "llm:totals"
        calls_key = f"llm:calls:{model_id}" if model_id else "llm:calls"
        totals = r.hgetall(totals_key)
        totals = {k: int(v) for k, v in totals.items()} if totals else {}
        recent_calls = []
        if recent_limit > 0:
            raw_calls = r.lrange(calls_key, 0, recent_limit - 1)
            recent_calls = [json.loads(c) for c in raw_calls] if raw_calls else []
        return {"totals": totals, "recent_calls": recent_calls}
    except Exception:
        return {"totals": {}, "recent_calls": []}


# ---------------------------------------------------------------------------
# Model management  (keys: "models:list", "model:<id>", "models:active")
# ---------------------------------------------------------------------------

def _model_id(base_url: str, model_name: str) -> str:
    return hashlib.sha256((base_url + model_name).encode()).hexdigest()[:12]


def list_models() -> list[dict]:
    r = _get_client()
    if r is None:
        return []
    try:
        ids = r.lrange("models:list", 0, -1)
        models = []
        for mid in (ids or []):
            data = r.hgetall(f"model:{mid}")
            if data:
                data["id"] = mid
                models.append(data)
        return models
    except Exception:
        return []


def get_model_config(model_id: str) -> dict | None:
    r = _get_client()
    if r is None:
        return None
    try:
        data = r.hgetall(f"model:{model_id}")
        if data:
            data["id"] = model_id
            return data
        return None
    except Exception:
        return None


def add_model(config: dict) -> str | None:
    r = _get_client()
    if r is None:
        return None
    try:
        mid = _model_id(config["base_url"], config["model_name"])
        pipe = r.pipeline()
        pipe.hset(f"model:{mid}", mapping={
            "name": config["name"],
            "base_url": config["base_url"],
            "api_key": config["api_key"],
            "model_name": config["model_name"],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+07:00"),
        })
        pipe.lrem("models:list", 0, mid)
        pipe.rpush("models:list", mid)
        pipe.execute()
        return mid
    except Exception:
        return None


def update_model(model_id: str, config: dict) -> bool:
    r = _get_client()
    if r is None:
        return False
    try:
        if not r.exists(f"model:{model_id}"):
            return False
        r.hset(f"model:{model_id}", mapping=config)
        return True
    except Exception:
        return False


def delete_model(model_id: str) -> bool:
    r = _get_client()
    if r is None:
        return False
    try:
        if not r.exists(f"model:{model_id}"):
            return False
        pipe = r.pipeline()
        pipe.delete(f"model:{model_id}")
        pipe.lrem("models:list", 0, model_id)
        # Clear active if this was the active model
        active = r.get("models:active")
        if active == model_id:
            pipe.delete("models:active")
        pipe.execute()
        return True
    except Exception:
        return False


def get_active_model_id() -> str | None:
    r = _get_client()
    if r is None:
        return None
    try:
        return r.get("models:active")
    except Exception:
        return None


def set_active_model(model_id: str) -> bool:
    r = _get_client()
    if r is None:
        return False
    try:
        if not r.exists(f"model:{model_id}"):
            return False
        r.set("models:active", model_id)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Cache statistics
# ---------------------------------------------------------------------------

def get_cache_stats() -> dict:
    r = _get_client()
    if r is None:
        return {"connected": False}
    try:
        article_count = 0
        for _ in r.scan_iter("article:*", count=500):
            article_count += 1
        summary_count = 0
        for _ in r.scan_iter("summary:*", count=500):
            summary_count += 1

        source_counts = {}
        for key in r.scan_iter("news:*", count=100):
            source_name = key.removeprefix("news:")
            raw = r.get(key)
            if raw:
                articles = json.loads(raw)
                source_counts[source_name] = len(articles)

        info = r.info("memory")
        return {
            "connected": True,
            "article_count": article_count,
            "summary_count": summary_count,
            "news_sources": len(source_counts),
            "source_counts": source_counts,
            "memory_used_mb": round(info.get("used_memory", 0) / (1024 * 1024), 2),
            "ttl_config": {
                "article_seconds": _ARTICLE_TTL,
                "summary_seconds": _SUMMARY_TTL,
                "news_seconds": _NEWS_TTL,
            },
        }
    except Exception:
        return {"connected": False}


# ---------------------------------------------------------------------------
# Rebuild news from cached articles
# ---------------------------------------------------------------------------

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
