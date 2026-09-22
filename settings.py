"""Runtime settings with Redis persistence and env-var fallback."""

import os

import cache_client

# "min" is the lowest value that still yields a working system. Anything lower
# breaks scraping silently (e.g. articles_per_source=0 scrapes nothing, a
# negative one slices the link list from the end), so writes are rejected.
_DEFAULTS = {
    "articles_per_source": {"env": "ARTICLES_PER_SOURCE", "default": 23, "type": int, "min": 1},
    "max_total_news": {"env": "MAX_TOTAL_NEWS", "default": 300, "type": int, "min": 0},
    "llm_call_delay": {"env": "LLM_CALL_DELAY", "default": 2.0, "type": float, "min": 0.0},
    "llm_max_input_chars": {"env": "LLM_MAX_INPUT_CHARS", "default": 32000, "type": int, "min": 1000},
    "llm_max_output_tokens": {"env": "LLM_MAX_OUTPUT_TOKENS", "default": 8192, "type": int, "min": 256},
    "refresh_timeout": {"env": "REFRESH_TIMEOUT", "default": 1800, "type": int, "min": 60},
    "cache_ttl_hours": {"env": "CACHE_TTL_HOURS", "default": 72, "type": int, "min": 1},
}

_REDIS_KEY = "settings:general"


def _env_default(name: str):
    """Get the env-var value or hardcoded default for a setting."""
    info = _DEFAULTS[name]
    raw = os.environ.get(info["env"])
    if raw is not None:
        return info["type"](raw)
    return info["default"]


def get_setting(name: str):
    """Read a setting: Redis override first, then env var, then hardcoded default."""
    if name not in _DEFAULTS:
        raise ValueError(f"Unknown setting: {name}")
    r = cache_client._get_client()
    if r is not None:
        try:
            val = r.hget(_REDIS_KEY, name)
            if val is not None:
                return _DEFAULTS[name]["type"](val)
        except Exception:
            pass
    return _env_default(name)


def get_all_settings() -> list[dict]:
    """Return all settings with current value, default, and source."""
    results = []
    r = cache_client._get_client()
    redis_overrides = {}
    if r is not None:
        try:
            redis_overrides = r.hgetall(_REDIS_KEY) or {}
        except Exception:
            pass

    for name, info in _DEFAULTS.items():
        default_val = _env_default(name)
        if name in redis_overrides:
            current_val = info["type"](redis_overrides[name])
            source = "redis"
        else:
            current_val = default_val
            source = "env"
        results.append({
            "name": name,
            "value": current_val,
            "default": default_val,
            "source": source,
            "type": info["type"].__name__,
            # Surfaced so the admin UI can show and enforce the same floor
            # instead of hardcoding a second copy of these numbers.
            "min": info["min"],
        })
    return results


def validate_setting(name: str, value):
    """Return the coerced value, or raise ValueError if the name is unknown or
    the value is not a number at or above the setting's minimum.

    Callers validate every field before writing any of them, so a bad value in a
    batch can't leave the rest half-applied."""
    if name not in _DEFAULTS:
        raise ValueError(f"Unknown setting: {name}")
    info = _DEFAULTS[name]
    type_name = info["type"].__name__
    # JSON null arrives as None, and bool would silently coerce to 0/1.
    if value is None or isinstance(value, bool):
        raise ValueError(f"expected {type_name}, got {value!r}")
    try:
        cast_value = info["type"](value)
    except (ValueError, TypeError):
        raise ValueError(f"expected {type_name}, got {value!r}") from None
    if cast_value != cast_value:  # NaN — survives float() but breaks comparisons
        raise ValueError(f"expected {type_name}, got NaN")
    if cast_value < info["min"]:
        raise ValueError(f"must be >= {info['min']}, got {cast_value}")
    return cast_value


def set_setting(name: str, value) -> None:
    """Write a validated setting override to Redis."""
    cast_value = validate_setting(name, value)
    r = cache_client._get_client()
    if r is not None:
        try:
            r.hset(_REDIS_KEY, name, str(cast_value))
        except Exception:
            pass


def reset_all() -> None:
    """Delete all Redis overrides, reverting to env/default values."""
    r = cache_client._get_client()
    if r is not None:
        try:
            r.delete(_REDIS_KEY)
        except Exception:
            pass
