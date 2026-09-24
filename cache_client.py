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
import uuid
from datetime import datetime, timezone, timedelta

import redis
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:12209")
_DEFAULT_TTL = 259200  # 3 days fallback

VN_TZ = timezone(timedelta(hours=7))


def vn_now_iso() -> str:
    """Current Vietnam time as ISO 8601 with a genuine +07:00 offset.

    These timestamps used to be built with time.strftime("...+07:00"), which
    pasted a fixed offset onto the container's local clock. The container has no
    TZ set and therefore runs UTC, so every value claimed +07:00 while carrying a
    UTC reading and came out 7 hours early.
    """
    return datetime.now(VN_TZ).strftime("%Y-%m-%dT%H:%M:%S+07:00")



def _get_cache_ttl() -> int:
    """Read cache_ttl_hours from Redis settings, convert to seconds.
    Reads directly from Redis to avoid circular import with settings module."""
    r = _get_client()
    if r is not None:
        try:
            val = r.hget("settings:general", "cache_ttl_hours")
            if val is not None:
                return max(1, int(val)) * 3600
        except Exception:
            pass
    env_val = os.environ.get("CACHE_TTL_HOURS")
    if env_val:
        return max(1, int(env_val)) * 3600
    return _DEFAULT_TTL

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
    *,
    title_en: str | None = None,
    summary_en: str | None = None,
    content_en: str | None = None,
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
                "title_en": title_en,
                "summary_en": summary_en,
                "content_en": content_en,
                "scraped_at": vn_now_iso(),
            },
            ensure_ascii=False,
        )
        r.setex(f"article:{url}", _get_cache_ttl(), payload)
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
        r.setex(_content_key(content), _get_cache_ttl(), summary)
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
        r.setex(f"news:{source}", _get_cache_ttl(), json.dumps(articles, ensure_ascii=False))
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
            "model_id": model_id,
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

def _new_model_id() -> str:
    """Opaque unique id for a new model.

    Deliberately NOT derived from the config. The old sha256(base_url +
    model_name) scheme meant editing either field left the id no longer matching
    its own contents, and adding a model with those original values then
    collided with the edited one and silently overwrote its API key.
    """
    return uuid.uuid4().hex[:12]


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
        mid = _new_model_id()
        pipe = r.pipeline()
        pipe.hset(f"model:{mid}", mapping={
            "name": config["name"],
            "base_url": config["base_url"],
            "api_key": config["api_key"],
            "model_name": config["model_name"],
            "created_at": vn_now_iso(),
        })
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


def mark_model_dead(model_id: str, reason: str) -> None:
    """Flag a model as permanently failing so failover stops retrying it.

    Written on a 401/403/404/410 — the statuses that mean the model is gone for
    this account rather than briefly unwell. The timestamp lets the caller
    re-test it after a cooldown, since an expired key can be fixed without
    anything in the registry changing.
    """
    r = _get_client()
    if r is None:
        return
    try:
        r.hset(f"model:{model_id}", mapping={
            "health": "dead",
            "health_reason": (reason or "")[:300],
            "health_checked_at": str(int(time.time())),
        })
    except Exception:
        pass


def clear_model_health(model_id: str) -> None:
    """Drop the dead mark — the model answered, or an operator edited it."""
    r = _get_client()
    if r is None:
        return
    try:
        r.hdel(f"model:{model_id}", "health", "health_reason", "health_checked_at")
    except Exception:
        pass


def model_dead_since(model_id: str) -> int | None:
    """Unix ts the model was marked dead, or None if it is not marked."""
    r = _get_client()
    if r is None:
        return None
    try:
        data = r.hmget(f"model:{model_id}", "health", "health_checked_at")
        if not data or data[0] != "dead":
            return None
        return int(data[1] or 0)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Short-lived locks / flags  (SET NX EX)
# ---------------------------------------------------------------------------

def acquire_lock(name: str, ttl_s: int) -> bool:
    """Take a named lock, or return False if it is already held.

    Used to keep the API and a concurrently running `scrape.py` from probing
    every model at the same moment, and to hold a back-off window after a
    failover sweep finds nothing alive. Redis being unavailable returns True:
    caching degrades gracefully everywhere else, so a missing lock must not be
    the thing that blocks a failover.
    """
    r = _get_client()
    if r is None:
        return True
    try:
        return bool(r.set(f"lock:{name}", "1", nx=True, ex=max(1, ttl_s)))
    except Exception:
        return True


def lock_held(name: str) -> bool:
    """True while a lock/flag window is still active."""
    r = _get_client()
    if r is None:
        return False
    try:
        return bool(r.exists(f"lock:{name}"))
    except Exception:
        return False


def release_lock(name: str) -> None:
    r = _get_client()
    if r is None:
        return
    try:
        r.delete(f"lock:{name}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Cron run tracking  (key: "cron:runs" list, bounded to 100)
# ---------------------------------------------------------------------------

_CRON_RUNS_MAX = 100


def record_cron_run(
    started_at: float,
    duration_s: float,
    sources_total: int,
    sources_ok: int,
    articles_total: int,
    timed_out: bool = False,
) -> None:
    r = _get_client()
    if r is None:
        return
    try:
        record = json.dumps({
            "started_at": int(started_at),
            "duration_s": round(duration_s, 1),
            "sources_total": sources_total,
            "sources_ok": sources_ok,
            "sources_failed": sources_total - sources_ok,
            "articles_total": articles_total,
            "timed_out": timed_out,
        })
        pipe = r.pipeline()
        pipe.lpush("cron:runs", record)
        pipe.ltrim("cron:runs", 0, _CRON_RUNS_MAX - 1)
        pipe.execute()
    except Exception:
        pass


def bump_zero_article_streak() -> int:
    """Count consecutive refresh cycles that stored nothing; returns the streak.

    A cycle can report every source "ok" and still store zero articles — the
    sources answered and extraction failed afterwards. That combination hid a
    retired LLM model for 18 days, so the streak is tracked explicitly instead
    of being inferred from the run history.
    """
    r = _get_client()
    if r is None:
        return 0
    try:
        return int(r.incr("cron:zero_streak"))
    except Exception:
        return 0


def clear_zero_article_streak() -> None:
    r = _get_client()
    if r is None:
        return
    try:
        r.delete("cron:zero_streak")
    except Exception:
        pass


def get_zero_article_streak() -> int:
    r = _get_client()
    if r is None:
        return 0
    try:
        return int(r.get("cron:zero_streak") or 0)
    except Exception:
        return 0


def get_cron_runs(limit: int = 50) -> list[dict]:
    r = _get_client()
    if r is None:
        return []
    try:
        raw = r.lrange("cron:runs", 0, limit - 1)
        return [json.loads(rec) for rec in (raw or [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Error event log  (key: "errors:log" sorted set, score = timestamp)
# ---------------------------------------------------------------------------

_ERRORS_MAX = 1000
_ERRORS_TTL_S = 7 * 86400  # 7 days


def record_error(
    category: str,
    message: str,
    source: str = "",
    model_id: str = "",
) -> None:
    r = _get_client()
    if r is None:
        return
    try:
        now = time.time()
        record = json.dumps({
            "ts": int(now),
            "category": category,
            "message": message[:500],
            "source": source,
            "model_id": model_id,
        })
        # Append a nonce to handle duplicate messages at the same second
        member = f"{record}|{now:.6f}"
        pipe = r.pipeline()
        pipe.zadd("errors:log", {member: now})
        pipe.zremrangebyscore("errors:log", "-inf", now - _ERRORS_TTL_S)
        pipe.zremrangebyrank("errors:log", 0, -(_ERRORS_MAX + 1))
        pipe.execute()
    except Exception:
        pass


def get_error_log(since: int = 0, limit: int = 200) -> list[dict]:
    r = _get_client()
    if r is None:
        return []
    try:
        raw = r.zrangebyscore("errors:log", since or "-inf", "+inf", withscores=False)
        results = []
        for member in (raw or []):
            # Strip the nonce suffix we appended
            json_part = member.rsplit("|", 1)[0]
            try:
                results.append(json.loads(json_part))
            except (json.JSONDecodeError, TypeError):
                continue
        # Return newest first, capped at limit
        results.reverse()
        return results[:limit]
    except Exception:
        return []


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
                "cache_ttl_seconds": _get_cache_ttl(),
            },
        }
    except Exception:
        return {"connected": False}


# ---------------------------------------------------------------------------
# Purge cache data
# ---------------------------------------------------------------------------

def purge_all_cache() -> dict:
    """Delete all article:*, summary:*, and news:* keys. Returns counts."""
    r = _get_client()
    if r is None:
        return {"articles": 0, "summaries": 0, "news": 0}
    counts = {"articles": 0, "summaries": 0, "news": 0}
    try:
        for key in r.scan_iter("article:*", count=500):
            r.delete(key)
            counts["articles"] += 1
        for key in r.scan_iter("summary:*", count=500):
            r.delete(key)
            counts["summaries"] += 1
        for key in r.scan_iter("news:*", count=500):
            r.delete(key)
            counts["news"] += 1
    except Exception:
        pass
    return counts


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
                    _get_cache_ttl(),
                    json.dumps(articles, ensure_ascii=False),
                )
                rebuilt += 1
                log.info("Rebuilt news:%s from %d cached articles", source_name, len(articles))
        except Exception:
            continue

    return rebuilt
