import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel

import cache_client

log = logging.getLogger(__name__)

_call_lock = threading.Lock()

_SYSTEM_PROMPT = """Bạn là nhà phân tích tin tức tài chính Việt Nam. Đọc bài báo và trả về JSON với 6 trường sau.

Hôm nay là {today}. Chỉ trích xuất thông tin có trong bài — KHÔNG bịa đặt, KHÔNG thêm từ kiến thức bên ngoài.

## 1. title
Viết lại tiêu đề rõ ràng, súc tích, dưới 100 ký tự. Nêu bật: ai, cái gì, con số quan trọng nhất. Không sao chép nguyên tiêu đề gốc.

## 2. published_at
ISO 8601 với múi giờ +07:00. Nếu chỉ có ngày → T00:00:00+07:00. Không tìm thấy → null.

## 3. summary
Tóm tắt ngắn gọn 1-2 câu, chỉ giữ lại thông tin quan trọng nhất: sự kiện chính, con số nổi bật (giá, %, giá trị giao dịch). Viết dạng văn xuôi, KHÔNG dùng markdown/emojis/bullet points. Người đọc phải hiểu ngay nội dung mà không cần đọc bài.

## 4. content
Tóm tắt nội dung bài báo dạng markdown, tập trung vào thông tin có giá trị cho nhà đầu tư:
- Sự kiện chính và con số cụ thể (giữ nguyên số liệu, không làm tròn)
- Nguyên nhân/bối cảnh (nếu có)
- Nhận định chuyên gia (nếu có, dùng > blockquote)
- Dùng **in đậm** cho con số và mã cổ phiếu quan trọng
- Dùng bảng markdown nếu có nhiều số liệu so sánh
- Bỏ qua thông tin không có giá trị: quảng cáo, lời dẫn dắt rườm rà, nội dung lặp lại
- Viết ngắn gọn, đi thẳng vào trọng tâm. Độ dài tỷ lệ với lượng thông tin có giá trị trong bài.

## 5. tickers
Mã cổ phiếu Việt Nam (2-5 ký tự IN HOA) được nhắc trực tiếp hoặc suy ra rõ ràng (ví dụ: "Vinamilk" → VNM). Trả về [] nếu không có.

## 6. is_relevant
true nếu liên quan tài chính/đầu tư/chứng khoán/kinh tế. false nếu tin xã hội/giải trí/thể thao/đời sống. Nghi ngờ → true."""


class ArticleExtraction(BaseModel):
    title: str
    published_at: Optional[str]
    summary: str
    content: str
    tickers: list[str]
    is_relevant: bool


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
# Core LLM function
# ---------------------------------------------------------------------------

def extract_and_summarize(text: str) -> Optional[dict]:
    """Extract title, published_at, and summary from article text via LLM.
    Uses Redis cache. Returns dict or None on failure."""
    import settings as settings_mod

    cached = cache_client.get_summary(text)
    if cached:
        log.debug("Summary cache hit")
        try:
            return json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            return {"title": "", "published_at": None, "summary": cached, "content": cached}

    max_input = settings_mod.get_setting("llm_max_input_chars")
    call_delay = settings_mod.get_setting("llm_call_delay")
    truncated = text[:max_input] if len(text) > max_input else text

    client, config = _manager.get_active_client()
    with _call_lock:
        for attempt in range(2):
            try:
                t0 = time.monotonic()
                resp = client.chat.completions.create(
                    model=config.model_name,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT.format(today=date.today().isoformat())},
                        {"role": "user", "content": truncated},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3,
                )
                elapsed = time.monotonic() - t0
                choice = resp.choices[0]
                finish_reason = choice.finish_reason
                if finish_reason == "length":
                    log.warning("LLM output truncated (finish_reason=length)")
                raw = choice.message.content
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
                log.warning("LLM attempt %d failed: %s", attempt + 1, e)
                if attempt == 1:
                    break
        log.error("LLM failed after 2 attempts — skipping article")
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
