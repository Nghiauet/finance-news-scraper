import json
import logging
import os
import threading
import time
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel

import cache_client

log = logging.getLogger(__name__)

_client: Optional[OpenAI] = None
_MODEL: Optional[str] = None
_MAX_INPUT_CHARS: int = int(os.environ.get("LLM_MAX_INPUT_CHARS", 32000))
_CALL_DELAY: float = float(os.environ.get("LLM_CALL_DELAY", 2))
_call_lock = threading.Lock()

_SYSTEM_PROMPT = """You are an expert Vietnamese financial news analyst.

From the article content below, extract:
- title: Article title in Vietnamese
- published_at: ISO 8601 with +07:00 timezone, or null if not found
- summary: Comprehensive summary in Vietnamese covering: the main event and when it occurred; all specific figures (prices, percentages, volumes, VND/USD amounts, stock tickers); causes or background context; market/corporate/investor reactions; expert opinions or outlook if available. Write as much as needed — do not truncate.
- tickers: List of Vietnamese stock ticker codes explicitly mentioned or clearly implied (e.g. VNM, HPG, VCB, VIC, SSI). Tickers are 2–5 uppercase letters traded on HOSE, HNX, or UPCOM. Return [] if none found.
- icb_codes: List of ICB (Industry Classification Benchmark) sector codes relevant to this article. Use 4-digit codes only. Common codes:
  1010=Energy, 1510=Chemicals, 2010=Basic Resources, 2020=Construction & Materials,
  2710=Industrial Goods & Services, 2720=Industrial Transportation,
  3010=Automobiles & Parts, 3020=Food & Beverage, 3030=Personal & Household Goods,
  3310=Health Care, 3350=Retail, 3530=Media, 3570=Travel & Leisure,
  4010=Telecommunications, 4520=Technology,
  5010=Banks, 5020=Insurance, 5510=Real Estate, 5520=Financial Services.
  Return [] if no clear sector applies.

RULES:
- published_at must be ISO 8601 with +07:00 timezone, or null
- summary must be plain continuous text in Vietnamese — no emojis, no markdown, no bullet points, no numbering
- Preserve every specific number from the article (%, billion VND, VND, USD, stock prices, trading volumes, company names, stock codes)
- If the article is short or thin on information, write everything available — do not fabricate
- tickers must only contain real Vietnamese stock codes — do not guess or fabricate
- icb_codes must be strings from the list above — include only codes clearly relevant to the article"""


class ArticleExtraction(BaseModel):
    title: str
    published_at: Optional[str]
    summary: str
    tickers: list[str]
    icb_codes: list[str]


def _get_client() -> tuple[OpenAI, str]:
    global _client, _MODEL
    if _client is None:
        _client = OpenAI(
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.environ["LLM_BASE_URL"],
            timeout=300.0,
        )
        _MODEL = os.environ["LLM_MODEL"]
        log.info("LLM client initialised — model=%s base_url=%s", _MODEL, os.environ["LLM_BASE_URL"])
    return _client, _MODEL


def extract_and_summarize(text: str) -> Optional[dict]:
    """Extract title, published_at, and summary from article text via LLM.
    Uses Redis cache. Returns dict or None on failure."""
    cached = cache_client.get_summary(text)
    if cached:
        log.debug("Summary cache hit")
        try:
            return json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            return {"title": "", "published_at": None, "summary": cached}

    # Truncate to avoid token limits
    truncated = text[:_MAX_INPUT_CHARS] if len(text) > _MAX_INPUT_CHARS else text

    client, model = _get_client()
    with _call_lock:
        for attempt in range(2):
            try:
                t0 = time.monotonic()
                resp = client.beta.chat.completions.parse(
                    model=model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": truncated},
                    ],
                    response_format=ArticleExtraction,
                    temperature=0.7,
                )
                elapsed = time.monotonic() - t0
                choice = resp.choices[0]
                finish_reason = choice.finish_reason
                if finish_reason == "length":
                    log.warning("LLM output truncated (finish_reason=length)")
                extraction = choice.message.parsed
                result = extraction.model_dump()
                cache_client.set_summary(text, json.dumps(result, ensure_ascii=False))
                log.info("LLM OK (%.1fs, finish_reason=%s)", elapsed, finish_reason)
                time.sleep(_CALL_DELAY)
                return result
            except Exception as e:
                log.warning("LLM attempt %d failed: %s", attempt + 1, e)
                if attempt == 1:
                    break
        log.error("LLM failed after 2 attempts — skipping article")
        return None
