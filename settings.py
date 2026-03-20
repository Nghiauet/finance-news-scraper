"""Runtime settings with Redis persistence and env-var fallback."""

import os

import cache_client

_DEFAULTS = {
    "articles_per_source": {"env": "ARTICLES_PER_SOURCE", "default": 23, "type": int},
    "max_total_news": {"env": "MAX_TOTAL_NEWS", "default": 300, "type": int},
    "llm_call_delay": {"env": "LLM_CALL_DELAY", "default": 2.0, "type": float},
    "llm_max_input_chars": {"env": "LLM_MAX_INPUT_CHARS", "default": 32000, "type": int},
    "refresh_timeout": {"env": "REFRESH_TIMEOUT", "default": 1800, "type": int},
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
        })
    return results


def set_setting(name: str, value) -> None:
    """Write a setting override to Redis."""
    if name not in _DEFAULTS:
        raise ValueError(f"Unknown setting: {name}")
    info = _DEFAULTS[name]
    cast_value = info["type"](value)
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
