"""
Heuristic Fallback Router — processes tool requests WITHOUT Gemini.

When Gemini is unavailable (503 / 429 / quota exhausted) the LLM service
delegates to ``fallback_process_request()`` which:

1. Extracts DOIs from user text and/or attached-document text via regex.
2. Extracts the References section from PDF text via keyword splitting.
3. Determines the user's intent via keyword matching.
4. Directly executes the appropriate tool and returns a
   ``FunctionCallingResponse`` with template text + rich ``tool_results``
   so the frontend cards render identically to a Gemini-assisted call.

If no intent can be determined, returns ``None`` so the caller can fall
back to the static "AI quá tải" message.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── DOI regex (case-insensitive, handles most real-world DOI formats) ────
# Allow parentheses inside DOIs (e.g. Lancet DOIs like S0140-6736(97)11096-0)
_DOI_RE = re.compile(
    r"10\.\d{4,9}/[^\s,;\"'<>\]}>]+",
    re.IGNORECASE,
)

# ── References section splitters (order matters — first match wins) ──────
_REF_SPLIT_PATTERNS: list[re.Pattern] = [
    re.compile(r"\n\s*references?\s*\n", re.IGNORECASE),
    re.compile(r"\n\s*tài\s+liệu\s+tham\s+khảo\s*\n", re.IGNORECASE),
    re.compile(r"\n\s*bibliography\s*\n", re.IGNORECASE),
]

# ── Abstract section extractor ───────────────────────────────────────────
_ABSTRACT_RE = re.compile(
    r"(?:abstract|tóm\s+tắt)\s*[:\-—]?\s*\n?(.*?)(?:\n\s*(?:keywords?|introduction|1[\.\s])|$)",
    re.IGNORECASE | re.DOTALL,
)


# =========================================================================
# Extraction helpers
# =========================================================================

def _extract_dois(text: str) -> list[str]:
    """Return de-duplicated DOIs found in *text*."""
    if not text:
        return []
    # Strip trailing punctuation that regex may over-capture
    raw = _DOI_RE.findall(text)
    cleaned: list[str] = []
    seen: set[str] = set()
    for doi in raw:
        doi = doi.rstrip(".,;:)")
        low = doi.lower()
        if low not in seen:
            seen.add(low)
            cleaned.append(doi)
    return cleaned


def _extract_references_section(text: str) -> str | None:
    """Try to extract the References section from document text."""
    if not text:
        return None
    for pat in _REF_SPLIT_PATTERNS:
        parts = pat.split(text, maxsplit=1)
        if len(parts) >= 2:
            refs = parts[-1].strip()
            if len(refs) > 30:
                return refs
    return None


def _extract_abstract(text: str) -> str | None:
    """Try to extract the Abstract section from document text."""
    if not text:
        return None
    m = _ABSTRACT_RE.search(text)
    if m:
        abstract = m.group(1).strip()
        if len(abstract) > 40:
            return abstract
    # Fallback: first 1500 chars (title + abstract region of most papers)
    if len(text) > 200:
        return text[:1500]
    return None


# =========================================================================
# Intent detection (keyword-based)
# =========================================================================

class _Intent:
    RETRACTION = "retraction"
    CITATION = "citation"
    JOURNAL = "journal"
    AI_DETECT = "ai_detect"
    GRAMMAR = "grammar"


_INTENT_KEYWORDS: dict[str, list[str]] = {
    _Intent.RETRACTION: [
        "rút", "retract", "pubpeer", "phốt", "thu hồi",
        "rút bài", "retraction", "bị rút",
    ],
    _Intent.CITATION: [
        "trích dẫn", "citation", "reference", "tham khảo",
        "xác minh", "verify", "kiểm tra trích",
    ],
    _Intent.JOURNAL: [
        "tạp chí", "journal", "nộp bài", "submit", "gợi ý tạp chí",
        "recommend journal",
    ],
    _Intent.AI_DETECT: [
        "ai viết", "ai writing", "phát hiện ai", "detect ai",
        "ai detection", "chatgpt", "gpt viết", "máy viết",
    ],
    _Intent.GRAMMAR: [
        "ngữ pháp", "chính tả", "grammar", "spelling", "typo",
        "sửa lỗi", "lỗi chữ", "spell check", "proofread",
        "kiểm tra lỗi", "chỉnh sửa văn bản",
    ],
}


def _detect_intent(user_text: str, has_doi: bool) -> str | None:
    """Return the best-matching intent string, or None."""
    low = user_text.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in low:
                return intent
    # If a DOI was found but no other keywords → default to retraction scan
    if has_doi:
        return _Intent.RETRACTION
    return None


# =========================================================================
# Template response generators
# =========================================================================

def _template_retraction(results: dict) -> str:
    """Generate fallback text for retraction scan results."""
    items = results.get("results", [])
    summary = results.get("summary", {})
    count = len(items)
    retracted = summary.get("retracted", 0)
    concerns = summary.get("has_concern", 0)
    pubpeer = sum(1 for r in items if r.get("pubpeer_comments", 0) > 0)

    lines = [
        "🔍 **(Chế độ dự phòng — Gemini offline)**",
        f"Đã quét **{count}** DOI.",
    ]
    if retracted:
        lines.append(f"⚠️ Phát hiện **{retracted}** bài bị rút bỏ (RETRACTED).")
    if concerns:
        lines.append(f"⚠️ **{concerns}** bài có biểu thức quan ngại (Expression of Concern).")
    if pubpeer:
        lines.append(f"💬 **{pubpeer}** bài có bình luận trên PubPeer.")
    if not retracted and not concerns and not pubpeer:
        lines.append("✅ Không phát hiện vấn đề nghiêm trọng.")
    lines.append("\nXem chi tiết ở bảng kết quả bên dưới.")
    return "\n".join(lines)


def _template_citation(results: dict) -> str:
    """Generate fallback text for citation verification results."""
    items = results.get("results", [])
    stats = results.get("statistics", {})
    total = len(items)
    verified = stats.get("verified", 0)
    not_found = stats.get("not_found", 0)

    lines = [
        "📚 **(Chế độ dự phòng — Gemini offline)**",
        f"Đã kiểm tra **{total}** trích dẫn.",
        f"✅ Xác minh thành công: **{verified}**",
    ]
    if not_found:
        lines.append(f"❌ Không xác minh được: **{not_found}** (có thể do AI ảo giác tạo ra)")
    lines.append("\nXem chi tiết ở bảng kết quả bên dưới.")
    return "\n".join(lines)


def _template_journal(results: dict) -> str:
    """Generate fallback text for journal matching results."""
    journals = results.get("journals", [])
    count = len(journals)
    lines = [
        "📖 **(Chế độ dự phòng — Gemini offline)**",
        f"Tìm thấy **{count}** tạp chí phù hợp.",
    ]
    for i, j in enumerate(journals[:3], 1):
        name = j.get("name", j.get("journal_name", "N/A"))
        score = j.get("similarity_score", j.get("score", j.get("match_score", 0)))
        try:
            score_str = f"{float(score):.1%}"
        except (TypeError, ValueError):
            score_str = str(score)
        lines.append(f"  {i}. {name} (score: {score_str})")
    if count > 3:
        lines.append(f"  … và {count - 3} tạp chí khác.")
    lines.append("\nXem chi tiết ở bảng kết quả bên dưới.")
    return "\n".join(lines)


def _template_ai_detect(results: dict) -> str:
    """Generate fallback text for AI writing detection results."""
    # The AI detector may return the score under different keys
    score = results.get("final_score", results.get("ml_score", results.get("score", 0)))
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    verdict = results.get("verdict", "UNKNOWN")
    lines = [
        "🤖 **(Chế độ dự phòng — Gemini offline)**",
        f"Điểm phát hiện AI: **{score:.1%}**",
        f"Kết luận: **{verdict}**",
    ]
    if score > 0.7:
        lines.append("⚠️ Văn bản có khả năng cao được viết bởi AI.")
    elif score > 0.4:
        lines.append("⚡ Văn bản có dấu hiệu hỗn hợp — cần kiểm tra thêm.")
    else:
        lines.append("✅ Văn bản có vẻ được viết bởi con người.")
    return "\n".join(lines)


def _template_grammar(results: dict) -> str:
    """Generate fallback text for grammar checking results."""
    total = results.get("total_errors", 0)
    error_msg = results.get("error")
    if error_msg:
        return (
            "✍️ **(Chế độ dự phòng — Gemini offline)**\n"
            f"⚠️ Không thể khởi động LanguageTool: {error_msg}"
        )
    lines = [
        "✍️ **(Chế độ dự phòng — Gemini offline)**",
        f"Đã kiểm tra đoạn văn. Phát hiện **{total}** lỗi.",
    ]
    if total == 0:
        lines.append("✅ Không phát hiện lỗi ngữ pháp hay chính tả.")
    else:
        # Show first 5 issues inline
        for i, issue in enumerate(results.get("issues", [])[:5], 1):
            msg = issue.get("message", "")
            replacements = issue.get("replacements", [])
            fix = f" → {replacements[0]}" if replacements else ""
            lines.append(f"  {i}. {msg}{fix}")
        remaining = total - 5
        if remaining > 0:
            lines.append(f"  … và {remaining} lỗi khác.")
        lines.append("\nVui lòng xem văn bản đã sửa bên dưới.")
    return "\n".join(lines)


# =========================================================================
# Public API
# =========================================================================

def fallback_process_request(
    user_text: str,
    file_context: str | None,
) -> dict[str, Any] | None:
    """Attempt to process the user's request using heuristics + direct
    tool execution, bypassing Gemini entirely.

    Returns a dict with keys ``text``, ``message_type``, ``tool_results``,
    ``tool_calls`` — matching the ``FunctionCallingResponse`` fields.
    Returns ``None`` if no intent could be determined.
    """
    combined_text = (user_text or "") + "\n" + (file_context or "")
    dois = _extract_dois(combined_text)
    intent = _detect_intent(user_text or "", has_doi=bool(dois))

    if intent is None:
        logger.info("Heuristic fallback: no intent detected — giving up.")
        return None

    logger.info(
        "Heuristic fallback: intent=%s, dois=%d, has_file=%s",
        intent, len(dois), bool(file_context),
    )

    # ── lazy imports to avoid circular deps at module level ──────────
    from app.services.llm_service import (
        _TOOL_MESSAGE_TYPE,
        _TOOL_DATA_KEY,
        scan_retraction_and_pubpeer,
        verify_citation,
        match_journal,
        detect_ai_writing,
        check_grammar,
        _make_serializable,
    )

    try:
        if intent == _Intent.RETRACTION:
            # Feed DOIs (or full text if no DOIs extracted cleanly)
            input_text = " ".join(dois) if dois else combined_text[:3000]
            tool_name = "scan_retraction_and_pubpeer"
            raw = scan_retraction_and_pubpeer(text=input_text)
            text = _template_retraction(raw)

        elif intent == _Intent.CITATION:
            # Prefer References section; fall back to full text
            refs = _extract_references_section(file_context or "")
            input_text = refs or combined_text[:5000]
            tool_name = "verify_citation"
            raw = verify_citation(text=input_text)
            text = _template_citation(raw)

        elif intent == _Intent.JOURNAL:
            abstract = _extract_abstract(file_context or "")
            input_text = abstract or user_text[:2000]
            tool_name = "match_journal"
            raw = match_journal(abstract=input_text)
            text = _template_journal(raw)

        elif intent == _Intent.AI_DETECT:
            # Use file content if available, otherwise user text
            input_text = (file_context or user_text or "")[:5000]
            if len(input_text.strip()) < 50:
                logger.warning("Fallback AI Detect: text too short (%d chars < 50).", len(input_text.strip()))
                return None
            logger.info("Fallback executing AI Writing Detector (%d chars)...", len(input_text))
            tool_name = "detect_ai_writing"
            raw = detect_ai_writing(text=input_text)
            text = _template_ai_detect(raw)

        elif intent == _Intent.GRAMMAR:
            input_text = (file_context or user_text or "")[:10000]
            if len(input_text.strip()) < 10:
                logger.warning("Fallback Grammar: text too short (%d chars).", len(input_text.strip()))
                return None
            logger.info("Fallback executing Grammar Checker (%d chars)...", len(input_text))
            tool_name = "check_grammar"
            raw = check_grammar(text=input_text)
            raw = _make_serializable(raw)
            text = _template_grammar(raw)

        else:
            return None

    except Exception as exc:
        logger.error("Heuristic fallback tool execution failed: %s", exc, exc_info=True)
        return None

    # Build response matching FunctionCallingResponse structure
    mt = _TOOL_MESSAGE_TYPE.get(tool_name)
    msg_type = mt.value if mt else "text"
    data_key = _TOOL_DATA_KEY.get(tool_name, "")
    tool_results = {
        "type": msg_type,
        "data": raw.get(data_key, raw) if data_key else raw,
    }

    return {
        "text": text,
        "message_type": msg_type,
        "tool_results": tool_results,
        "tool_calls": [{
            "name": tool_name,
            "args": {"text": input_text[:200] + "..." if len(input_text) > 200 else input_text},
            "result": raw,
        }],
    }
