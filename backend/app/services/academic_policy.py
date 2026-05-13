from __future__ import annotations

from typing import Any, Mapping
import re


USER_SAFE_CORPUS_LABEL = "corpus học thuật đã xác minh"
USER_SAFE_DATA_LABEL = "dữ liệu học thuật hiện có"

BANNED_USER_TERMS = [
    re.compile(r"crawler\.?db", re.IGNORECASE),
    re.compile(r"aira\.?db", re.IGNORECASE),
    re.compile(r"\bsqlite\b", re.IGNORECASE),
    re.compile(r"\bchroma[_-]?db\b", re.IGNORECASE),
    re.compile(r"\bchroma\b", re.IGNORECASE),
    re.compile(r"\bvenue_profiles\b", re.IGNORECASE),
    re.compile(r"\barticle_exemplars\b", re.IGNORECASE),
    re.compile(r"\bcfp_notices\b", re.IGNORECASE),
]


def sanitize_user_text(text: str) -> str:
    if not text:
        return text
    sanitized = text
    for pattern in BANNED_USER_TERMS:
        sanitized = pattern.sub(USER_SAFE_DATA_LABEL, sanitized)
    return sanitized


def sanitize_user_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: sanitize_user_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [sanitize_user_payload(value) for value in payload]
    if isinstance(payload, tuple):
        return tuple(sanitize_user_payload(value) for value in payload)
    if isinstance(payload, str):
        return sanitize_user_text(payload)
    return payload


CRAWLER_DB_NO_DATA_MESSAGE = (
    f"Mình chưa tìm thấy thông tin liên quan trong {USER_SAFE_DATA_LABEL}. "
    "Bạn có thể gửi DOI, tiêu đề, tác giả, hoặc từ khóa cụ thể hơn để mình kiểm tra lại."
)

EXACT_RECORD_NOT_FOUND_MESSAGE = (
    f"Hiện chưa có bản ghi học thuật khớp hoàn toàn với truy vấn này trong {USER_SAFE_DATA_LABEL}."
)

INSUFFICIENT_GROUNDED_DATA_MESSAGE = (
    f"Mình chưa có đủ dữ liệu trong {USER_SAFE_DATA_LABEL} để kết luận chắc chắn."
)


AIRA_CORPUS_GROUNDED_PROMPT = """Bạn là AIRA, Academic Integrity & Research Assistant trong một nền tảng nghiên cứu học thuật.

Bạn không phải chatbot chung chung. Hành vi mặc định là: retrieve first, reason second, answer last. Ưu tiên bằng chứng từ hệ thống theo thứ tự:
1. structured tool results của backend
2. dữ liệu từ corpus học thuật đã xác minh và các index/search derivative
3. nội dung manuscript/file người dùng tải lên
4. API/metadata học thuật đã được xác minh khi tool thật sự cung cấp
5. kiến thức nền ngắn, chỉ khi mode cho phép và phải tách rõ khỏi grounded findings

Quy tắc bắt buộc:
- Không bịa DOI, citation, venue, CFP, ranking, journal policy, retraction status, PubPeer comment, hoặc metadata học thuật.
- Khi trả lời dựa trên corpus học thuật đã xác minh hoặc tool học thuật, chỉ nêu factual claim nếu có dữ liệu hỗ trợ.
- Phân biệt rõ: thông tin xác minh chính xác, khớp một phần, suy luận/recommendation, và dữ liệu thiếu.
- Nếu không có dữ liệu trong corpus học thuật đã xác minh/tool result, nói rõ: "Mình chưa tìm thấy thông tin liên quan trong dữ liệu học thuật hiện có." Không tự lấp khoảng trống bằng kiến thức ngoài.
- Với dữ liệu trong corpus học thuật đã xác minh, ưu tiên title, abstract, keywords, authors, venue, year/date, DOI, URL, rồi mới dùng raw_metadata khi thật sự cần.
- Khi nêu bằng chứng, dùng format gần với: "Nguồn: <title> | <venue> | <year> | DOI: <doi or N/A>".

DOI và citation:
- Nếu input là DOI hoặc DOI URL, normalize trước và xử lý như định danh học thuật exact.
- Luôn thử exact DOI resolution trước fuzzy logic.
- Nếu DOI không resolve được, trả lời rõ chưa tìm thấy/không xác minh được; không trình bày paper gần giống như DOI đã được xác minh.
- Nếu citation không có DOI, fuzzy/partial match được phép nhưng phải gắn nhãn khớp một phần hoặc approximate.

Retraction/concerning signals:
- Chỉ chạy hoặc diễn giải retraction scan trên scholarly record đã resolve, DOI đã verified, hoặc metadata object được hỗ trợ.
- Nếu DOI/citation chưa resolve được, nói scan đã được bỏ qua vì chưa xác minh được tài liệu gốc.
- Không nói "retracted", "safe", "verified", "exact match" nếu dữ liệu không hỗ trợ.
- Không lộ lỗi thô như Invalid_document_id, tool unavailable, stack/backend failure trong câu trả lời người dùng bình thường.

Journal matching:
- Recommendation phải dựa trên retrieved venue/article/CFP evidence, không dựa vào cảm tính.
- Nói rõ đây là best-fit recommendation, không phải đảm bảo được nhận.
- Khi có dữ liệu, nêu fit/constraints: semantic relevance, subject area, indexing/quartile, policy fit, review time, APC, deadline/freshness.
- Nếu không có candidate grounded trong corpus học thuật đã xác minh/index, nói rõ thiếu dữ liệu và gợi ý mở rộng abstract/keywords.
- Khi truy vấn từ DOI: hiển thị metadata DOI (title, authors, journal, year, subjects) trước danh sách gợi ý.
- Dùng score_breakdown, warning_flags, scope_fit trong dữ liệu để giải thích vì sao journal phù hợp.
- Nếu warning_flags chứa "suspected_book_series", cảnh báo đây là book series, không phải journal chính thống.

Phong cách:
- Chuyên nghiệp, rõ ràng, ngắn gọn, thân thiện.
- Nếu người dùng viết tiếng Việt, mặc định trả lời tiếng Việt.
- Tránh wording robot/khô như "0 valid, manual review required"; dùng câu tự nhiên như "Kết quả hiện chỉ khớp một phần...".
- Structured payload phải giữ ổn định; chỉ cải thiện narrative, label, explanation khi cần.
"""

AIRA_GENERAL_ACADEMIC_PROMPT = """Bạn là AIRA, Academic Integrity & Research Assistant.

Chế độ hiện tại: Hỗ trợ học thuật tổng quát (General Academic Discussion).
Bạn được phép trả lời dựa trên kiến thức học thuật nền của mình cho các câu hỏi thảo luận,
định hướng nghiên cứu, brainstorming ý tưởng, và tư vấn phương pháp luận.

QUY TẮC BẮT BUỘC:
- KHÔNG bịa DOI, citation, paper, journal, journal metric, ranking, hoặc bất kỳ metadata học thuật nào.
- KHÔNG dùng cụm từ "dữ liệu học thuật hiện có", "corpus học thuật đã xác minh", hoặc "crawler db" —
  đây là câu trả lời từ kiến thức nền, không phải từ corpus đã xác minh.
- KHÔNG gọi tool verify_citation, scan_retraction, match_journal, detect_ai_writing, check_grammar.
- Nếu câu hỏi yêu cầu kiểm tra cụ thể (DOI, citation, retraction, journal match), hãy nói rõ
  người dùng cần chuyển sang chế độ tra cứu chuyên dụng.
- Phân biệt rõ ràng: kiến thức nền mang tính tham khảo, không thay thế dữ liệu đã xác minh.
- Trả lời bằng tiếng Việt nếu người dùng hỏi tiếng Việt.
- Phong cách chuyên nghiệp, rõ ràng, ngắn gọn, thân thiện.
"""

# Backward-compat alias
AIRA_SYSTEM_PROMPT = AIRA_CORPUS_GROUNDED_PROMPT


def format_grounded_evidence(record: Mapping[str, Any]) -> str:
    """Return a compact evidence line for scholarly records."""
    title = (
        record.get("title")
        or record.get("display_name")
        or record.get("name")
        or "N/A"
    )
    venue = (
        record.get("venue")
        or record.get("journal")
        or record.get("conference")
        or record.get("source_title")
        or record.get("publisher")
        or "N/A"
    )
    year = (
        record.get("year")
        or record.get("publication_year")
        or record.get("metric_year")
        or record.get("publication_date")
        or "N/A"
    )
    doi = record.get("doi") or record.get("DOI") or "N/A"
    return f"Nguồn: {title} | {venue} | {year} | DOI: {doi}"


def format_crawler_record_summary(record: Mapping[str, Any]) -> str:
    """Summarize an academic corpus record without inventing claims."""
    if not record:
        return CRAWLER_DB_NO_DATA_MESSAGE

    title = str(record.get("title") or record.get("display_name") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    keywords_raw = record.get("keywords") or record.get("topic_tags") or record.get("subject_labels") or []
    if isinstance(keywords_raw, str):
        keywords = [item.strip() for item in keywords_raw.split(",") if item.strip()]
    elif isinstance(keywords_raw, (list, tuple)):
        keywords = [str(item).strip() for item in keywords_raw if str(item).strip()]
    else:
        keywords = []

    lines: list[str] = []
    if title:
        lines.append(f"**Bản ghi:** {title}")
    if abstract:
        lines.append(f"**Tóm tắt từ abstract:** {abstract}")
    else:
        lines.append("Bản ghi này chưa có abstract trong dữ liệu hiện tại, nên mình không suy đoán thêm về phương pháp hoặc kết quả.")
    if keywords:
        lines.append(f"**Từ khóa/chủ đề có sẵn:** {', '.join(keywords[:8])}")
    lines.append(format_grounded_evidence(record))
    return "\n".join(lines)


def format_journal_match_summary(
    *,
    status: Any,
    candidate_count: int,
    diagnostics: Mapping[str, Any] | None = None,
) -> str:
    """User-safe journal matching summary aligned with grounded policy."""
    diagnostics = diagnostics or {}
    status_value = getattr(status, "value", str(status or "")).lower()

    if status_value == "failed":
        return (
            "Mình chưa thể hoàn tất journal matching ở thời điểm này vì bước truy xuất dữ liệu học thuật gặp sự cố. "
            "Dữ liệu lỗi kỹ thuật đã được lưu trong diagnostics để kiểm tra nội bộ; bạn có thể thử lại sau."
        )

    if candidate_count <= 0:
        insufficient_corpus = diagnostics.get("insufficient_corpus", False)
        missing_info = diagnostics.get("missing_manuscript_info", False)

        if insufficient_corpus or not missing_info:
            # User provided manuscript info but corpus has no suitable venues
            domain_text = ""
            detected_domain = diagnostics.get("detected_domain", [])
            if detected_domain and isinstance(detected_domain, list) and len(detected_domain) > 0:
                domain_text = f" Chủ đề phát hiện: {', '.join(str(d) for d in detected_domain[:5])}."
            return (
                f"Mình không tìm thấy journal phù hợp trong corpus học thuật đã xác minh "
                f"sau khi đọc abstract/keywords của bạn.{domain_text} "
                "Để tránh gợi ý sai lĩnh vực hoặc thiếu căn cứ khoa học, mình sẽ không tự tạo "
                "danh sách từ thông tin chưa kiểm chứng. "
                "Bạn có thể mở rộng nguồn dữ liệu nghiên cứu theo các hướng sau: "
                "Scopus (đã đồng bộ), SCImago Journal Rank (SJR), CORE Conference Ranks, "
                "IEEE Publication Recommender, ACM Computing Classification System, Springer Link Journals."
            )

        # User hasn't provided enough manuscript info
        return (
            "Mình chưa có đủ thông tin manuscript (title, abstract, keywords, hoặc lĩnh vực "
            "nghiên cứu) để chạy journal matching. "
            "Hãy bổ sung thêm abstract, keywords, hoặc lĩnh vực nghiên cứu để mình thử lại."
        )

    if diagnostics.get("embedding_model") == "hash-fallback":
        return (
            "Mình đã tạo một danh sách gợi ý journal từ dữ liệu học thuật hiện có, có dùng bài báo liên quan làm evidence phụ. "
            "CẢNH BÁO: Embedding đang chạy ở chế độ fallback (hash-based) vì mô hình SPECTER2 chưa khả dụng. "
            "Kết quả gợi ý CÓ THỂ KHÔNG CHÍNH XÁC về mặt ngữ nghĩa. "
            "Vui lòng cài đặt mô hình SPECTER2 hoặc cấu hình HF_TOKEN để có chất lượng matching tốt nhất."
        )

    return (
        "Mình đã tạo một danh sách gợi ý journal duy nhất dựa trên dữ liệu học thuật hiện có, có dùng bài báo liên quan làm evidence phụ khi phù hợp. "
        "Đây là best-fit recommendation có căn cứ từ corpus học thuật đã xác minh, không phải đảm bảo chấp nhận đăng bài."
    )
