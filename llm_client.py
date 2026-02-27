import json
import os
from typing import Optional

from openai import OpenAI

import cache_client

_client: Optional[OpenAI] = None
_MODEL: Optional[str] = None

_SYSTEM_PROMPT = """You are an expert Vietnamese financial news analyst.

From the article content below, extract and return a JSON object with exactly 3 fields:

{
  "title": "Article title in Vietnamese",
  "published_at": "YYYY-MM-DDTHH:MM:SS+07:00 or null if not found",
  "summary": "Comprehensive summary written in Vietnamese covering: the main event and when it occurred; all specific figures (prices, percentages, volumes, VND/USD amounts, stock tickers); causes or background context; market/corporate/investor reactions; expert opinions or outlook if available. Write as much as needed to cover all key information — do not truncate."
}

RULES:
- Return only the JSON object, nothing else
- published_at must be ISO 8601 with +07:00 timezone, or null
- summary must be plain continuous text in Vietnamese — no emojis, no markdown, no bullet points, no numbering
- Preserve every specific number from the article (%, billion VND, VND, USD, stock prices, trading volumes, company names, stock codes)
- If the article is short or thin on information, write everything available — do not fabricate"""


def _get_client() -> tuple[OpenAI, str]:
    global _client, _MODEL
    if _client is None:
        _client = OpenAI(
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.environ["LLM_BASE_URL"],
        )
        _MODEL = os.environ["LLM_MODEL"]
    return _client, _MODEL


def extract_and_summarize(text: str) -> Optional[dict]:
    """Extract title, published_at, and summary from article text via LLM.
    Uses Redis cache. Returns dict or None on failure."""
    cached = cache_client.get_summary(text)
    if cached:
        print("     [CACHE] Summary hit")
        try:
            return json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            return {"title": "", "published_at": None, "summary": cached}

    # Truncate to avoid token limits
    truncated = text[:6000] if len(text) > 6000 else text

    client, model = _get_client()
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": truncated},
                ],
                temperature=0.3,
            )
            raw = resp.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
            result = json.loads(raw)
            cache_client.set_summary(text, json.dumps(result, ensure_ascii=False))
            return result
        except Exception as e:
            if attempt == 0:
                print(f"     [LLM] Retry after error: {e}")
    print("     [LLM] Failed after retry — skipping")
    return None
