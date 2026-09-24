import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from openai import APIStatusError, OpenAI
from pydantic import BaseModel

import cache_client

log = logging.getLogger(__name__)

_call_lock = threading.Lock()

# Bounds for a single request when the caller supplied a deadline. Below the
# minimum there's no point starting a call at all.
_MIN_CALL_TIMEOUT = 15.0
_MAX_CALL_TIMEOUT = 300.0

# Statuses that mean this model is gone for this account rather than briefly
# unwell, so retrying it — this cycle or the next — cannot succeed:
#   410 provider retired the model (NVIDIA EOLs models with no warning)
#   404 model not available for this account
#   401/403 key rejected or not entitled
# Everything else (timeout, 429, 5xx, empty completion, truncation) is transient
# and must NOT trigger a switch: a healthy model briefly overloaded would
# otherwise get demoted mid-cycle.
_DEAD_MODEL_STATUSES = {401, 403, 404, 410}

# How long a model stays skipped after being marked dead. An expired key can be
# fixed without anything in the registry changing, so dead is not forever.
_DEAD_MODEL_COOLDOWN_S = 6 * 3600

# After a sweep finds nothing alive, stop sweeping for a while. Without this,
# every one of ~260 articles in a cycle would re-probe every registered model.
_ALL_DEAD_BACKOFF_S = 900

_HEALTH_PING_TIMEOUT = 30.0
_PROBE_TIMEOUT = 90.0

# A candidate must produce a real bilingual extraction from this before it is
# promoted. Deliberately not a "reply OK" ping: nvidia/nemotron-parse-2.0
# answers that in 0.9s with 3 tokens and is useless here, so a ping-based gate
# would swap a dead pipeline for a silently broken one.
_PROBE_ARTICLE = (
    "Thị trường chứng khoán Việt Nam phiên hôm nay ghi nhận VN-Index tăng 12 điểm lên 1.320 điểm. "
    "Nhóm ngân hàng dẫn dắt đà tăng với VCB tăng 2,1% và CTG tăng 1,8%. "
    "Khối ngoại mua ròng 450 tỷ đồng, thanh khoản toàn sàn đạt 18.500 tỷ đồng."
)

_SYSTEM_PROMPT = """Bạn là nhà phân tích tin tức tài chính Việt Nam. Đọc bài báo và trả về JSON song ngữ Việt-Anh với 9 trường sau.

Hôm nay là {today}. Chỉ trích xuất thông tin có trong bài — KHÔNG bịa đặt, KHÔNG thêm từ kiến thức bên ngoài.

## 1. title (tiếng Việt)
Viết lại tiêu đề rõ ràng, súc tích, dưới 100 ký tự. Nêu bật: ai, cái gì, con số quan trọng nhất. Không sao chép nguyên tiêu đề gốc.

## 2. published_at
Ngày ĐĂNG BÀI (không phải ngày được nhắc trong nội dung). ISO 8601 với múi giờ +07:00. Nếu chỉ có ngày → T00:00:00+07:00. KHÔNG được muộn hơn hôm nay ({today}) — nếu ngày duy nhất tìm được nằm trong tương lai, hoặc không tìm thấy ngày đăng rõ ràng → null.

## 3. summary (tiếng Việt)
Tóm tắt ngắn gọn 1-2 câu, chỉ giữ lại thông tin quan trọng nhất: sự kiện chính, con số nổi bật (giá, %, giá trị giao dịch). Viết dạng văn xuôi, KHÔNG dùng markdown/emojis/bullet points. Người đọc phải hiểu ngay nội dung mà không cần đọc bài.

## 4. content (tiếng Việt)
Tóm tắt nội dung bài báo dạng markdown, tập trung vào thông tin có giá trị cho nhà đầu tư:
- Sự kiện chính và con số cụ thể (giữ nguyên số liệu, không làm tròn)
- Nguyên nhân/bối cảnh (nếu có)
- Nhận định chuyên gia (nếu có, dùng > blockquote)
- Dùng **in đậm** cho con số và mã cổ phiếu quan trọng
- Dùng bảng markdown nếu có nhiều số liệu so sánh
- Bỏ qua thông tin không có giá trị: quảng cáo, lời dẫn dắt rườm rà, nội dung lặp lại
- Viết ngắn gọn, đi thẳng vào trọng tâm. Độ dài tỷ lệ với lượng thông tin có giá trị trong bài.

## 5. title_en (bản dịch tiếng Anh của `title`)
Dịch ý sang tiếng Anh tự nhiên, ngắn gọn, phù hợp độc giả là nhà đầu tư quốc tế. KHÔNG dịch word-by-word. Giữ nguyên tên riêng tiếng Việt (ví dụ: "Vinamilk", "Hòa Phát") và mã cổ phiếu (HPG, VNM). Dưới 100 ký tự.

## 6. summary_en (bản dịch tiếng Anh của `summary`)
Văn xuôi tự nhiên, 1-2 câu, KHÔNG markdown/emoji/bullet. Giữ nguyên số liệu, đơn vị tiền tệ (VND, USD, tỷ đồng → "trillion VND"/"billion VND" hoặc giữ nguyên), tên riêng và mã cổ phiếu. Phong cách phải tự nhiên như một bản tin tài chính tiếng Anh, không phải dịch máy.

## 7. content_en (bản dịch tiếng Anh của `content`)
GIỮ NGUYÊN cấu trúc markdown (**bold**, > blockquote, bảng, danh sách) khớp với trường `content`. Dịch ý, không dịch từng từ. Giữ nguyên số liệu, mã cổ phiếu, tên công ty Việt Nam. Phong cách: bản tin tài chính tiếng Anh chuyên nghiệp dành cho nhà đầu tư.

## 8. tickers
Mã cổ phiếu Việt Nam (2-5 ký tự IN HOA) được nhắc trực tiếp hoặc suy ra rõ ràng (ví dụ: "Vinamilk" → VNM). Trả về [] nếu không có. KHÔNG dịch — luôn dùng mã gốc.

## 9. is_relevant
true nếu liên quan tài chính/đầu tư/chứng khoán/kinh tế. false nếu tin xã hội/giải trí/thể thao/đời sống. Nghi ngờ → true.

LƯU Ý: Trả về MỘT JSON object phẳng (KHÔNG lồng), gồm đủ 9 trường: title, published_at, summary, content, title_en, summary_en, content_en, tickers, is_relevant."""


class ArticleExtraction(BaseModel):
    title: str
    published_at: Optional[str] = None
    summary: str
    content: str
    tickers: list[str]
    is_relevant: bool
    title_en: Optional[str] = None
    summary_en: Optional[str] = None
    content_en: Optional[str] = None


@dataclass
class ModelConfig:
    id: str
    name: str
    base_url: str
    api_key: str
    model_name: str


def _sanitize_and_parse_json(raw: str) -> ArticleExtraction:
    """Strip markdown code fences, control characters, and parse JSON from LLM output."""
    raw = re.sub(r'^```(?:json)?\s*\n?', '', raw.strip())
    raw = re.sub(r'\n?```\s*$', '', raw.strip())
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
    data = json.loads(raw)
    return ArticleExtraction.model_validate(data)


# ---------------------------------------------------------------------------
# Multi-model client manager
# ---------------------------------------------------------------------------

class _ClientManager:
    """Manages multiple OpenAI-compatible LLM clients with an active model concept."""

    def __init__(self):
        self._clients: dict[str, OpenAI] = {}
        self._lock = threading.Lock()

    def get_active_client(self) -> tuple[OpenAI, ModelConfig]:
        """Return the active model's client and config.
        Falls back to env vars if no model is configured in Redis."""
        active_id = cache_client.get_active_model_id()
        if active_id:
            config_data = cache_client.get_model_config(active_id)
            if config_data:
                config = ModelConfig(
                    id=active_id,
                    name=config_data.get("name", ""),
                    base_url=config_data["base_url"],
                    api_key=config_data["api_key"],
                    model_name=config_data["model_name"],
                )
                with self._lock:
                    if active_id not in self._clients:
                        self._clients[active_id] = OpenAI(
                            api_key=config.api_key,
                            base_url=config.base_url,
                            timeout=300.0,
                        )
                        log.info("LLM client created for model %s (%s)", config.name, config.model_name)
                return self._clients[active_id], config

        # Fallback to env vars
        env_key = os.environ.get("LLM_API_KEY", "")
        env_url = os.environ.get("LLM_BASE_URL", "")
        env_model = os.environ.get("LLM_MODEL", "")
        if not env_key or not env_url or not env_model:
            raise RuntimeError("No active model configured and LLM_API_KEY/LLM_BASE_URL/LLM_MODEL env vars are missing")
        config = ModelConfig(id="_env", name="Default (env)", base_url=env_url, api_key=env_key, model_name=env_model)
        with self._lock:
            if "_env" not in self._clients:
                self._clients["_env"] = OpenAI(api_key=env_key, base_url=env_url, timeout=300.0)
                log.info("LLM client initialised from env — model=%s base_url=%s", env_model, env_url)
        return self._clients["_env"], config

    def invalidate(self):
        """Drop all cached clients so they get recreated with fresh config."""
        with self._lock:
            self._clients.clear()
            log.info("All LLM clients invalidated")


_manager = _ClientManager()


def invalidate_active_client():
    """Called by API when model config changes."""
    _manager.invalidate()


# ---------------------------------------------------------------------------
# Automatic failover when a model is retired
# ---------------------------------------------------------------------------

def _is_model_dead(e: Exception) -> bool:
    """True when the error means this model will never answer again."""
    return isinstance(e, APIStatusError) and e.status_code in _DEAD_MODEL_STATUSES


def _system_prompt() -> str:
    """The extraction prompt with today's Vietnam date filled in.

    Derived from the epoch rather than `datetime`/`date` so the probe path does
    not depend on which of the two this module happens to import.
    """
    return _SYSTEM_PROMPT.format(today=time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 3600)))


def _probe_extraction(config_data: dict) -> tuple[bool, str, bool]:
    """Run one real extraction against a candidate model.

    Returns (ok, detail, dead). `ok` means the endpoint answered AND the answer
    validated as a bilingual ArticleExtraction — the same bar the pipeline
    applies, so a model that cannot do the job is never promoted. `dead` marks a
    permanent rejection (401/403/404/410), which is the only kind worth
    remembering: a candidate that merely timed out may be fine in ten minutes.
    """
    base_url = (config_data.get("base_url") or "").strip()
    api_key = (config_data.get("api_key") or "").strip()
    model_name = (config_data.get("model_name") or "").strip()
    if not base_url or not api_key or not model_name:
        return False, "incomplete model config (base_url/api_key/model_name)", False
    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=_PROBE_TIMEOUT)
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _PROBE_ARTICLE},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=min(2048, _probe_max_tokens()),
        )
        choice = resp.choices[0]
        raw = choice.message.content
        if not raw or not raw.strip():
            return False, "empty response", False
        if choice.finish_reason == "length":
            return False, "output truncated at max_tokens", False
        extraction = _sanitize_and_parse_json(raw)
        if not (extraction.title or "").strip():
            return False, "extraction returned an empty title", False
        if not (extraction.title_en or "").strip():
            return False, "no English translation (title_en missing)", False
        return True, f"extracted {len(extraction.content or '')} chars, tickers={extraction.tickers}", False
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", _is_model_dead(e)


def _probe_max_tokens() -> int:
    """Output cap for a probe — the configured one, bounded to keep probes cheap."""
    import settings as settings_mod
    try:
        return int(settings_mod.get_setting("llm_max_output_tokens"))
    except Exception:
        return 2048


def failover_active_model(exclude_id: str, reason: str) -> Optional[tuple[OpenAI, ModelConfig]]:
    """Promote the next registered model that can actually do an extraction.

    Candidates are tried in `models:list` order, skipping the model that just
    died and any marked dead inside the cooldown window. Callers must already
    hold `_call_lock` — this does network I/O but never takes the lock itself,
    because its only callers run inside it.
    """
    if cache_client.lock_held("failover:all_dead"):
        log.debug("failover suppressed — no healthy model as of %ds ago", _ALL_DEAD_BACKOFF_S)
        return None

    # Keep a concurrently running scrape.py from probing the same models.
    if not cache_client.acquire_lock("failover:sweep", 300):
        current = cache_client.get_active_model_id()
        if current and current != exclude_id:
            log.info("another process already failed over to %s", current)
            _manager.invalidate()
            try:
                return _manager.get_active_client()
            except Exception:
                return None
        return None

    try:
        candidates = cache_client.list_models()
        log.warning("model %s is gone (%s) — trying %d alternative(s)",
                    exclude_id, reason, max(0, len(candidates) - 1))
        now = time.time()
        for cand in candidates:
            mid = cand.get("id")
            if not mid or mid == exclude_id:
                continue
            dead_since = cache_client.model_dead_since(mid)
            if dead_since and (now - dead_since) < _DEAD_MODEL_COOLDOWN_S:
                log.info("skipping %s (%s) — marked dead %.0f min ago",
                         cand.get("name"), mid, (now - dead_since) / 60)
                continue
            ok, detail, cand_dead = _probe_extraction(cand)
            if ok:
                cache_client.clear_model_health(mid)
                if not cache_client.set_active_model(mid):
                    log.error("could not activate %s — registry write failed", mid)
                    continue
                cache_client.release_lock("failover:all_dead")
                cache_client.record_error(
                    "failover",
                    f"Switched active model to '{cand.get('name')}' ({cand.get('model_name')}) "
                    f"after '{exclude_id}' failed: {reason}",
                    model_id=mid,
                )
                log.warning("FAILOVER → %s (%s): %s", cand.get("name"), cand.get("model_name"), detail)
                _manager.invalidate()
                return _manager.get_active_client()
            log.warning("candidate %s (%s) rejected: %s", cand.get("name"), mid, detail)
            # Only a permanent failure earns a dead mark. A candidate that timed
            # out may well be fine later, and marking it would hide it for 6h.
            if cand_dead:
                cache_client.mark_model_dead(mid, detail)

        cache_client.acquire_lock("failover:all_dead", _ALL_DEAD_BACKOFF_S)
        cache_client.record_error(
            "failover",
            f"No healthy LLM model available — '{exclude_id}' is gone ({reason}) and no "
            f"registered alternative passed an extraction probe",
        )
        log.error("FAILOVER FAILED — no registered model passed the probe")
        return None
    finally:
        cache_client.release_lock("failover:sweep")


def ensure_healthy_active_model() -> dict:
    """Check the active model with one cheap ping, failing over if it is gone.

    Called before a refresh cycle so a retired model costs one request instead
    of an entire refresh budget. Detection is cheap (a dead model returns
    401/403/404/410 whatever the prompt is); promotion is strict and lives in
    `failover_active_model`.
    """
    with _call_lock:
        try:
            client, config = _manager.get_active_client()
        except Exception as e:
            return {"ok": False, "dead": True, "switched": False, "model": None, "detail": str(e)}

        try:
            client.chat.completions.create(
                model=config.model_name,
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                max_tokens=8,
                timeout=_HEALTH_PING_TIMEOUT,
            )
            return {"ok": True, "dead": False, "switched": False,
                    "model": config.model_name, "detail": "ping ok"}
        except Exception as e:
            if not _is_model_dead(e):
                # One bad ping is not grounds for a switch — the per-article
                # retries handle a wobbly endpoint.
                log.warning("active model ping failed (transient): %s", e)
                return {"ok": False, "dead": False, "switched": False,
                        "model": config.model_name, "detail": str(e)}
            reason = str(e)
            if config.id != "_env":
                cache_client.mark_model_dead(config.id, reason)
            promoted = failover_active_model(config.id, reason)
            if promoted:
                _client, new_config = promoted
                return {"ok": True, "dead": True, "switched": True,
                        "model": new_config.model_name,
                        "detail": f"failed over from {config.model_name}: {reason}"}
            return {"ok": False, "dead": True, "switched": False,
                    "model": config.model_name, "detail": reason}


# ---------------------------------------------------------------------------
# Core LLM function
# ---------------------------------------------------------------------------

def extract_and_summarize(text: str, deadline: Optional[float] = None) -> Optional[dict]:
    """Extract title, published_at, and summary from article text via LLM.
    Uses Redis cache. Returns dict or None on failure.

    `deadline` is a time.monotonic() value. Attempts stop once it passes and each
    request is capped at the time left, so a hung endpoint can't overrun the
    caller's budget: a 300s client timeout retried 3x is 15 minutes per article,
    which was enough for one source to consume an entire refresh cycle.
    """
    import settings as settings_mod

    cached = cache_client.get_summary(text)
    if cached:
        try:
            cached_obj = json.loads(cached)
            if isinstance(cached_obj, dict) and cached_obj.get("title_en"):
                log.debug("Summary cache hit")
                return cached_obj
            log.info("Summary cache hit (legacy, missing EN) — calling LLM to upgrade")
        except (json.JSONDecodeError, TypeError):
            log.info("Summary cache hit (unparseable) — calling LLM to upgrade")

    max_input = settings_mod.get_setting("llm_max_input_chars")
    call_delay = settings_mod.get_setting("llm_call_delay")
    max_output = settings_mod.get_setting("llm_max_output_tokens")
    truncated = text[:max_input] if len(text) > max_input else text

    client, config = _manager.get_active_client()
    attempts = 3
    with _call_lock:
        for attempt in range(attempts):
            # Don't start another attempt we have no time for. Checked inside the
            # lock, since waiting for the lock itself can consume the budget.
            if deadline is not None:
                left = deadline - time.monotonic()
                if left <= _MIN_CALL_TIMEOUT:
                    log.warning("LLM deadline reached before attempt %d/%d — skipping article",
                                attempt + 1, attempts)
                    return None
                call_timeout: Optional[float] = min(_MAX_CALL_TIMEOUT, left)
            else:
                call_timeout = None
            try:
                t0 = time.monotonic()
                resp = client.chat.completions.create(
                    model=config.model_name,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT.format(today=datetime.now(cache_client.VN_TZ).date().isoformat())},
                        {"role": "user", "content": truncated},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3,
                    max_tokens=max_output,
                    **({"timeout": call_timeout} if call_timeout is not None else {}),
                )
                elapsed = time.monotonic() - t0
                choice = resp.choices[0]
                finish_reason = choice.finish_reason
                raw = choice.message.content
                # The endpoint occasionally returns an empty completion or cuts
                # the JSON off mid-string (finish_reason=length). Both yield
                # invalid JSON — treat as a retryable failure with a clear message
                # instead of letting json.loads/strip raise a cryptic error.
                if not raw or not raw.strip():
                    raise ValueError("empty LLM response (no content returned)")
                if finish_reason == "length":
                    raise ValueError(
                        f"LLM output truncated at max_tokens={max_output} "
                        "(finish_reason=length) — raise llm_max_output_tokens"
                    )
                extraction = _sanitize_and_parse_json(raw)
                result = extraction.model_dump()
                cache_client.set_summary(text, json.dumps(result, ensure_ascii=False))
                usage = resp.usage
                if usage:
                    cache_client.record_llm_call(
                        usage.prompt_tokens or 0,
                        usage.completion_tokens or 0,
                        int(elapsed * 1000),
                        model_id=config.id,
                    )
                log.info("LLM OK (%.1fs, model=%s, finish_reason=%s)", elapsed, config.model_name, finish_reason)
                time.sleep(call_delay)
                return result
            except Exception as e:
                cache_client.record_llm_error(model_id=config.id)
                cache_client.record_error("llm", str(e), model_id=config.id)
                log.warning("LLM attempt %d/%d failed: %s", attempt + 1, attempts, e)
                # A retired model returns the same error however many times it
                # is asked, so retrying it burns the whole refresh budget (this
                # is how a 410 went unnoticed for 18 days). Switch models and
                # retry the article on the replacement instead of counting the
                # attempt against it.
                if _is_model_dead(e):
                    if config.id != "_env":
                        cache_client.mark_model_dead(config.id, str(e))
                    promoted = failover_active_model(config.id, str(e))
                    if promoted is None:
                        log.error("no healthy LLM model available — skipping article")
                        return None
                    client, config = promoted
                    continue
                if attempt == attempts - 1:
                    break
        log.error("LLM failed after %d attempts — skipping article", attempts)
        return None


def get_model_info() -> dict:
    """Return current LLM configuration."""
    import settings as settings_mod
    max_input = settings_mod.get_setting("llm_max_input_chars")
    try:
        _client, config = _manager.get_active_client()
        return {
            "model": config.model_name,
            "base_url": config.base_url,
            "name": config.name,
            "id": config.id,
            "max_input_chars": max_input,
        }
    except Exception:
        return {
            "model": os.environ.get("LLM_MODEL", ""),
            "base_url": os.environ.get("LLM_BASE_URL", ""),
            "name": "Default (env)",
            "id": "_env",
            "max_input_chars": max_input,
        }


def test_model(config_data: dict) -> dict:
    """Send a simple test prompt to verify a model works. Returns result dict."""
    try:
        client = OpenAI(
            api_key=config_data["api_key"],
            base_url=config_data["base_url"],
            timeout=30.0,
        )
        t0 = time.monotonic()
        resp = client.chat.completions.create(
            model=config_data["model_name"],
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=10,
        )
        elapsed = time.monotonic() - t0
        content = resp.choices[0].message.content or ""
        return {"ok": True, "response": content.strip(), "latency_ms": int(elapsed * 1000)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
