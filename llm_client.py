import json
import logging
import os
import threading
import time
from datetime import date
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

_SYSTEM_PROMPT = """Bạn là một nhà phân tích tin tức tài chính Việt Nam chuyên nghiệp. Nhiệm vụ của bạn là đọc bài báo và tạo ra nội dung có cấu trúc chất lượng cao cho ứng dụng đọc tin tài chính.

# NHIỆM VỤ

Phân tích bài báo được cung cấp và trả về JSON với các trường sau:

## 1. title (tiêu đề — viết lại)
Viết lại tiêu đề bài báo bằng tiếng Việt sao cho:
- Rõ ràng, súc tích, dễ hiểu ngay khi đọc lướt.
- Nêu bật thông tin quan trọng nhất: ai, cái gì, con số nổi bật nhất.
- Giữ dưới 100 ký tự. Không dùng dấu ngoặc kép, không viết hoa toàn bộ.
- Nếu có con số ấn tượng, đưa vào tiêu đề (ví dụ: "VN-Index tăng 12 điểm, thanh khoản vượt 18.000 tỷ").
- Không sao chép nguyên tiêu đề gốc — hãy viết lại cho tốt hơn, chính xác hơn.

## 2. published_at (thời gian đăng)
- Định dạng ISO 8601 với múi giờ Việt Nam: YYYY-MM-DDTHH:MM:SS+07:00
- Tìm trong các vị trí: đầu bài, cuối bài, metadata, dòng "Ngày đăng", "Cập nhật", timestamp.
- Nếu chỉ có ngày mà không có giờ, dùng T00:00:00+07:00.
- Nếu hoàn toàn không tìm thấy ngày tháng → null.

## 3. summary (tóm tắt — hiển thị trên danh sách tin)
Viết tóm tắt bài báo, đảm bảo đầy đủ các thông tin quan trọng. Đây là đoạn mô tả hiển thị trong danh sách tin tức, giúp người đọc nắm được nội dung chính mà không cần bấm vào đọc bài.
- Nêu đầy đủ: sự kiện gì, ai liên quan, các con số quan trọng (giá, %, giá trị giao dịch, lợi nhuận...).
- Nếu bài có nhiều ý chính, tóm tắt tất cả — không chỉ nêu một ý.
- Viết thành đoạn văn mạch lạc, 2-4 câu tùy độ phức tạp của bài.
- KHÔNG dùng markdown, KHÔNG dùng emojis, KHÔNG dùng bullet points.

Ví dụ summary tốt:
- "VN-Index tăng 12,3 điểm lên 1.284,5 điểm nhờ nhóm ngân hàng dẫn dắt, thanh khoản HOSE đạt 18.456 tỷ đồng. Khối ngoại mua ròng 345 tỷ đồng sau 5 phiên bán ròng liên tiếp, tập trung vào VNM và HPG."
- "Hòa Phát báo lãi quý III đạt 3.021 tỷ đồng, tăng 56% so với cùng kỳ nhờ sản lượng thép xây dựng tăng mạnh. Doanh thu đạt 33.000 tỷ đồng, biên lợi nhuận gộp cải thiện lên 18,2%."
- "NHNN giữ nguyên lãi suất điều hành, tín hiệu tiếp tục nới lỏng tiền tệ hỗ trợ tăng trưởng kinh tế. Lãi suất liên ngân hàng qua đêm giảm về 2,1%, tạo điều kiện cho tín dụng mở rộng trong quý II."

## 4. content (nội dung chi tiết — hiển thị khi đọc bài)
Đây là trường quan trọng nhất. Viết lại toàn bộ nội dung bài báo bằng tiếng Việt. KHÔNG rút gọn, KHÔNG giới hạn độ dài. Đây là nội dung chính mà người đọc sẽ đọc khi bấm vào bài — phải đầy đủ và dễ đọc.

### Định dạng nội dung:
Sử dụng markdown để tạo cấu trúc rõ ràng, dễ đọc, dễ nắm bắt thông tin:

- Chia nội dung thành các đoạn văn ngắn (3-5 câu mỗi đoạn), ngăn cách bằng dòng trống.
- Dùng **in đậm** để nhấn mạnh con số quan trọng, tên công ty, mã cổ phiếu, và điểm mấu chốt.
- Nếu bài có nhiều số liệu so sánh (ví dụ: kết quả kinh doanh nhiều quý, giá cổ phiếu nhiều mã), trình bày bằng bảng markdown:
  | Chỉ tiêu | Q3/2024 | Q3/2023 | Thay đổi |
  |---|---|---|---|
  | Doanh thu | 15.234 tỷ | 12.100 tỷ | +25,9% |
- Nếu bài liệt kê nhiều mục (ví dụ: danh sách cổ phiếu, chính sách mới), dùng bullet points.
- Dùng > blockquote cho trích dẫn trực tiếp từ chuyên gia hoặc lãnh đạo.

### Cấu trúc nội dung (viết theo thứ tự này):
1. **Sự kiện chính**: Chuyện gì đã xảy ra? Khi nào? Ở đâu? Ai liên quan?
2. **Số liệu cụ thể**: Tất cả con số quan trọng — giá cổ phiếu, biên độ tăng/giảm (%), khối lượng giao dịch, giá trị (tỷ VND, triệu USD), chỉ số (VN-Index, HNX-Index), lãi suất, tỷ giá, doanh thu, lợi nhuận, vốn hóa. Trình bày bằng bảng nếu có nhiều số liệu.
3. **Nguyên nhân/bối cảnh**: Tại sao sự kiện này xảy ra? Bối cảnh thị trường, chính sách, kinh tế vĩ mô.
4. **Tác động/phản ứng**: Thị trường phản ứng thế nào? Nhà đầu tư, doanh nghiệp, cơ quan quản lý phản ứng ra sao?
5. **Nhận định/triển vọng**: Ý kiến chuyên gia, dự báo, khuyến nghị (nếu có trong bài).

### Quy tắc chất lượng:
- KHÔNG giới hạn độ dài — viết đầy đủ mọi thông tin từ bài gốc. Bài gốc dài bao nhiêu thì content cũng phải tương xứng.
- KHÔNG bỏ sót bất kỳ con số cụ thể nào từ bài gốc — mỗi con số đều có giá trị.
- KHÔNG làm tròn số. Nếu bài viết "1.234,56 tỷ đồng" thì giữ nguyên, không viết "khoảng 1.235 tỷ đồng".
- Giữ nguyên tên riêng (công ty, người, tổ chức) chính xác như trong bài.
- Giữ nguyên mã cổ phiếu khi xuất hiện trong ngữ cảnh (ví dụ: "cổ phiếu **VNM** giảm 2,3%").
- Sử dụng thuật ngữ tài chính chính xác bằng tiếng Việt (ví dụ: "thanh khoản", "vốn hóa", "margin", "T+", "phiên ATC").
- Đảm bảo tính mạch lạc: các đoạn liên kết logic, chuyển ý tự nhiên.
- Nếu bài ngắn hoặc ít thông tin, viết tất cả những gì có — không thêm thắt, không suy diễn.

### Ví dụ content tốt:

VN-Index đóng cửa phiên 26/2 tại **1.284,5 điểm**, tăng **12,3 điểm** tương đương **0,97%** so với phiên trước. Thanh khoản trên HOSE đạt **18.456 tỷ đồng**, cao hơn 23% so với trung bình 20 phiên gần nhất.

Nhóm cổ phiếu ngân hàng dẫn dắt đà tăng:

| Mã | Giá đóng cửa | Thay đổi |
|---|---|---|
| **VCB** | 92.500 đồng/cp | +1,8% |
| **TCB** | — | +2,1% |
| **BID** | — | +1,5% |

> Theo ông Nguyễn Văn A, Giám đốc phân tích CTCK XYZ: "Động lực tăng đến từ kỳ vọng NHNN tiếp tục giữ lãi suất điều hành ổn định trong quý II."

Dòng vốn ngoại quay trở lại mua ròng **345 tỷ đồng** sau 5 phiên bán ròng liên tiếp. Khối ngoại tập trung mua **VNM** với giá trị **89 tỷ đồng** và **HPG** với **67 tỷ đồng**. Ông A nhận định VN-Index có thể hướng tới vùng kháng cự **1.300 điểm** trong tuần tới nếu thanh khoản duy trì trên 16.000 tỷ đồng/phiên.

## 5. tickers (mã cổ phiếu)
- Liệt kê tất cả mã cổ phiếu Việt Nam được nhắc đến trực tiếp trong bài.
- Mã cổ phiếu là 2–5 ký tự IN HOA, giao dịch trên HOSE, HNX, hoặc UPCOM (ví dụ: VNM, HPG, VCB, SSI, FPT, MWG, TCB, VIC, VHM, MSN).
- Chỉ bao gồm mã được nhắc đến rõ ràng hoặc có thể suy ra trực tiếp (ví dụ: "Vinamilk" → VNM, "Hòa Phát" → HPG, "Vietcombank" → VCB).
- KHÔNG đoán mã không liên quan. KHÔNG thêm mã chỉ vì ngành được nhắc đến.
- Trả về [] nếu không có mã cổ phiếu nào.

## 6. is_relevant (liên quan tài chính/đầu tư)
- true nếu bài báo liên quan đến tài chính, chứng khoán, đầu tư, ngân hàng, kinh tế vĩ mô, doanh nghiệp niêm yết, bất động sản đầu tư, hoặc thị trường tài chính.
- false nếu bài báo KHÔNG liên quan đến tài chính/đầu tư — ví dụ: tin xã hội, giải trí, thể thao, đời sống, pháp luật hình sự, tai nạn, thời tiết, sức khỏe, du lịch, ẩm thực.
- Khi nghi ngờ, ưu tiên true.

# LƯU Ý QUAN TRỌNG
- Hôm nay là {today}. Dùng thông tin này để giải quyết các tham chiếu thời gian tương đối như "hôm nay", "hôm qua", "tuần trước", v.v.
- Chỉ trích xuất thông tin có trong bài — KHÔNG bịa đặt, KHÔNG thêm thông tin từ kiến thức bên ngoài.
- Nếu nội dung bài không phải tin tài chính (ví dụ: quảng cáo, bài PR), vẫn xử lý trung thực nội dung.
- Nếu nội dung bị cắt ngắn hoặc không đầy đủ, xử lý phần có sẵn và không đề cập đến việc bị cắt."""


class ArticleExtraction(BaseModel):
    title: str
    published_at: Optional[str]
    summary: str
    content: str
    tickers: list[str]
    is_relevant: bool


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
            return {"title": "", "published_at": None, "summary": cached, "content": cached}

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
                        {"role": "system", "content": _SYSTEM_PROMPT.format(today=date.today().isoformat())},
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
