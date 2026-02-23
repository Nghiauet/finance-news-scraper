import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

import cache_client

load_dotenv()

_client = OpenAI(
    api_key=os.environ["LLM_API_KEY"],
    base_url=os.environ["LLM_BASE_URL"],
)
_MODEL = os.environ["LLM_MODEL"]

_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích tin tức tài chính. Nhiệm vụ của bạn là tóm tắt bài báo theo định dạng chuẩn bên dưới bằng tiếng Việt, giúp người đọc nắm bắt thông tin và ra quyết định nhanh chóng.

**ĐỊNH DẠNG BẮT BUỘC:**

📌 **TÓM TẮT:** [1 câu ngắn gọn nêu rõ sự kiện chính]

🔑 **ĐIỂM CHÍNH:**
- [Số liệu / sự kiện cụ thể 1]
- [Số liệu / sự kiện cụ thể 2]
- [Số liệu / sự kiện cụ thể 3 — nếu có]

📊 **TÁC ĐỘNG THỊ TRƯỜNG:** [Ảnh hưởng đến thị trường, ngành, hoặc tài sản liên quan]

✅ **GỢI Ý HÀNH ĐỘNG:** [Khuyến nghị ngắn gọn dành cho nhà đầu tư: theo dõi, mua/bán/giữ, thận trọng...]

**QUY TẮC:**
- Ưu tiên số liệu cụ thể (%, giá trị, thời gian) hơn mô tả chung chung
- Ngôn ngữ súc tích, rõ ràng — không viết dài dòng
- Nếu bài báo không liên quan tài chính, chỉ điền mục TÓM TẮT và bỏ qua các mục còn lại
"""


def summarize(text: str) -> Optional[str]:
    """Summarize article text via LLM. Uses Redis cache when available.
    Retries once on LLM failure; returns None if both fail."""
    cached = cache_client.get_summary(text)
    if cached:
        print("  [CACHE] Summary hit")
        return cached

    for attempt in range(2):
        try:
            resp = _client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.3,
            )
            result = resp.choices[0].message.content.strip()
            cache_client.set_summary(text, result)
            return result
        except Exception as e:
            if attempt == 0:
                print(f"  [LLM] Retry after error: {e}")
    print("  [LLM] Failed after retry — skipping summary")
    return None

