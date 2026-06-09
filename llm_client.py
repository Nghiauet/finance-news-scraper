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
# Core LLM function
# ---------------------------------------------------------------------------

def extract_and_summarize(text: str) -> Optional[dict]:
    """Extract title, published_at, and summary from article text via LLM.
    Uses Redis cache. Returns dict or None on failure."""
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
                    max_tokens=max_output,
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
