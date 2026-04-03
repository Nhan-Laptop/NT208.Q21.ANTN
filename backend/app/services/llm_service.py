"""
Groq LLM Service — with **Function Calling** (Tool Use) for academic tool
integration.

Uses the ``groq`` SDK with OpenAI-compatible chat-completions.
Implements pass-by-reference document routing, tool result budgeting,
and anti-pseudo-tool hardening.

Function Calling Architecture
-----------------------------
User Prompt → _prepare_user_text_for_router (pass-by-reference)
→ Groq (lightweight router) → [tool_call JSON] → _execute_tool_call
(resolve document_id → full text) → Tool Execution (local Python/ML)
→ compact summary to Groq OR early-exit for terminal tools
→ Final Answer + full rich tool_results persisted for frontend.

Big Update (2026-04-03):
    - Model-facing vs UI-facing tool result separation
    - Terminal tools (grammar, AI detect) break FC loop immediately
    - Deterministic pass-by-reference at 1500 chars
    - Broadened anti-pseudo-tool sanitisation
    - Dynamic system prompt (no hardcoded tool names)
    - Current-turn-only document ID scoping
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Sequence

from tenacity import (
    retry,
    RetryError,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from app.core.config import settings
from app.models.chat_message import ChatMessage, MessageType
from app.services.document_cache import (
    store_document,
    get_document,
    extract_document_id,
    strip_document_metadata,
    build_document_reference_prompt,
    restore_file_context_from_metadata,
    ATTACHED_DOCUMENT_RE,
)

logger = logging.getLogger(__name__)

# =========================================================================
# Constants
# =========================================================================

_MAX_HISTORY_MESSAGES = 4
_MAX_HISTORY_MESSAGE_CHARS = 2000
_MAX_ROUTER_INPUT_CHARS = 10000
_MAX_TITLE_SOURCE_CHARS = 2000
_DOCUMENT_CACHE_TRIGGER_CHARS = 1500       # deterministic pass-by-reference
_DOCUMENT_ANALYSIS_TRIGGER_CHARS = 300     # intent-hint shortcut threshold
_TOOL_CALL_ARG_PREVIEW_CHARS = 160
_TRUNCATED_HISTORY_SUFFIX = " ...[truncated]"
_TRUNCATED_INPUT_SUFFIX = (
    "\n\n...[Nội dung đã được hệ thống cắt ngắn để đảm bảo giới hạn API]..."
)
_DEFAULT_CHAT_TITLE = "Trò chuyện mới"
_TITLE_GENERATOR_SYSTEM_INSTRUCTION = (
    "You are a title generator. Generate a very short, concise title (max 5 words) "
    "for a chat session based on the user's first message. Respond ONLY with the "
    "title itself, no quotes, no explanations. Language: Vietnamese."
)

_TITLE_PREFIX_RE = re.compile(
    r"^(?:title|tiêu\s*đề|tieu\s*de)\s*[:\-–—]\s*",
    re.IGNORECASE,
)
_TITLE_EXPLANATION_RE = re.compile(
    r"^(?:đây\s+là|day\s+la|this\s+is|here\s+is)\s+(?:tiêu\s*đề|title)\s*[:\-–—]?\s*",
    re.IGNORECASE,
)

# ── Pseudo-tool syntax patterns (broadened) ─────────────────────────────
_PSEUDO_TOOL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\(?\s*function=[^>\n]+>.*?</function>\s*\)?", re.I | re.DOTALL),
    re.compile(r"<function=\w+[^>]*>", re.I),
    re.compile(r"</function\s*>", re.I),
    re.compile(
        r"\.\s*(?:scan_retraction_and_pubpeer|verify_citation|match_journal|detect_ai_writing|check_grammar)\s*>\s*\{.*?\}",
        re.I | re.DOTALL,
    ),
    re.compile(
        r"(?:(?:^|\n)\s*)\{[^{}]{0,240}\"document_id\"\s*:\s*\"[^\"]+\"[^{}]{0,240}\}(?=\s*(?:$|\n))",
        re.I | re.DOTALL,
    ),
    re.compile(r"\[(?:Gọi|Call)\s+tool\s*:.*?\]", re.I | re.DOTALL),
    re.compile(r"\[tool_call\s*:.*?\]", re.I | re.DOTALL),
    re.compile(r"\b(?:tool_call|function_call)\s*[:=]\s*\{.*?\}", re.I | re.DOTALL),
    re.compile(
        r"```(?:json|tool|function)?\s*\{[^}]*\"(?:name|function)\".*?```",
        re.I | re.DOTALL,
    ),
]
_LOW_SIGNAL_ASSISTANT_PATTERNS: list[re.Pattern] = [
    re.compile(r"hệ thống không tìm thấy dữ liệu", re.I),
    re.compile(r"thông tin này dựa trên kiến thức chung", re.I),
    re.compile(r"vui lòng thử lại", re.I),
]

# ── Intent-hint regexes ─────────────────────────────────────────────────
_AI_WRITING_HINT_RE = re.compile(
    r"\b(ai writing|detect ai|ai detection|chatgpt|gpt viết|ai viết|máy viết"
    r"|phát hiện ai|kiểm tra ai)\b",
    re.IGNORECASE,
)
_GRAMMAR_HINT_RE = re.compile(
    r"\b(grammar|proofread|spelling|typo|spell check|ngữ pháp|chính tả"
    r"|sửa lỗi|chỉnh sửa văn bản|kiểm tra lỗi)\b",
    re.IGNORECASE,
)
_CITATION_HINT_RE = re.compile(
    r"\b(citation|verify\s+citation|reference\s+check|bibliography|doi\s*check"
    r"|trích\s*dẫn|xác\s*minh\s*trích\s*dẫn|kiểm\s*tra\s*tài\s*liệu\s*tham\s*khảo"
    r"|kiểm\s*tra\s*doi|reference\s+verification)\b",
    re.IGNORECASE,
)
_RETRACTION_HINT_RE = re.compile(
    r"\b(retract(?:ion|ed)?|withdrawn|expression\s+of\s+concern|pubpeer"
    r"|rút\s*bài|thu\s*hồi|bị\s*rút|kiểm\s*tra\s*rút\s*bài|quét\s*retraction)\b",
    re.IGNORECASE,
)
_BOTH_ACTION_HINT_RE = re.compile(
    r"\b(both|cả\s+hai|đồng\s+thời|and\s+also|và\s+cũng|kiểm\s*tra\s*cả)\b",
    re.IGNORECASE,
)

_ROUTER_INSTRUCTION_PREFIX_RE = re.compile(
    r"^(?:please|hãy|vui\s*lòng|giúp|nhờ|xin|check|verify|detect|scan|match|find|recommend)\b",
    re.IGNORECASE,
)
_ROUTER_INSTRUCTION_HINT_RE = re.compile(
    r"\b(check|verify|detect|scan|match|find|recommend|analy[sz]e|review"
    r"|kiểm\s*tra|xác\s*minh|phát\s*hiện|quét|gợi\s*ý|tìm)\b",
    re.IGNORECASE,
)

# ── Tool argument mappings ──────────────────────────────────────────────
# NOTE: This map is execution-layer only.
# Groq-facing schemas for document-only tools remain `document_id`-only.
_TOOL_DOCUMENT_ARGUMENT: dict[str, str] = {
    "scan_retraction_and_pubpeer": "text",
    "verify_citation": "text",
    "match_journal": "abstract",
    "detect_ai_writing": "text",
    "check_grammar": "text",
}

_TOOL_ALLOWED_ROUTER_ARGS: dict[str, set[str]] = {
    "scan_retraction_and_pubpeer": {"document_id", "text"},
    "verify_citation": {"document_id", "text"},
    "match_journal": {"document_id", "abstract", "title"},
    "detect_ai_writing": {"document_id"},
    "check_grammar": {"document_id"},
}

_DOCUMENT_ID_ONLY_TOOLS = frozenset({"detect_ai_writing", "check_grammar"})
_TERMINAL_TOOLS = frozenset({"detect_ai_writing", "check_grammar"})

# ── Groq tool schemas (OpenAI-compatible) ───────────────────────────────
_GROQ_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "scan_retraction_and_pubpeer",
            "description": (
                "Scan DOIs for retraction status, corrections, expressions of "
                "concern, and PubPeer community discussions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Cached document reference ID (preferred).",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text containing DOIs to scan (use only for short inline input).",
                    },
                },
                "anyOf": [
                    {"required": ["document_id"]},
                    {"required": ["text"]},
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_citation",
            "description": (
                "Verify academic citations against OpenAlex and Crossref."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Cached document reference ID (preferred).",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text containing citations to verify.",
                    },
                },
                "anyOf": [
                    {"required": ["document_id"]},
                    {"required": ["text"]},
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_journal",
            "description": (
                "Find suitable academic journals for a manuscript using "
                "SPECTER2 semantic matching."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Cached document reference ID (preferred).",
                    },
                    "abstract": {
                        "type": "string",
                        "description": "Abstract or main text describing the research.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional paper title.",
                    },
                },
                "anyOf": [
                    {"required": ["document_id"]},
                    {"required": ["abstract"]},
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_ai_writing",
            "description": (
                "Analyse text to detect AI-generated content. "
                "REQUIRES document_id — never pass raw text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Cached document reference ID (required).",
                    },
                },
                "required": ["document_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_grammar",
            "description": (
                "Check text for grammar and spelling errors. "
                "REQUIRES document_id — never pass raw text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Cached document reference ID (required).",
                    },
                },
                "required": ["document_id"],
                "additionalProperties": False,
            },
        },
    },
]

# ── Groq SDK import ─────────────────────────────────────────────────────
try:
    from groq import Groq
    import groq as groq_module
except ImportError:
    Groq = None  # type: ignore[assignment,misc]
    groq_module = None  # type: ignore[assignment]

# ── Tool singletons ─────────────────────────────────────────────────────
from app.services.tools.retraction_scan import retraction_scanner
from app.services.tools.citation_checker import citation_checker
from app.services.tools.journal_finder import journal_finder
from app.services.tools.ai_writing_detector import ai_writing_detector
from app.services.tools.grammar_checker import grammar_checker


# =========================================================================
# System Prompt — base (tool-agnostic) + per-request dynamic guidance
# =========================================================================

SYSTEM_PROMPT_BASE = (
    "Bạn là AIRA — Trợ lý Nghiên cứu Học thuật AI chuyên nghiệp. "
    "Mục tiêu của bạn là cung cấp thông tin học thuật an toàn, chính xác, "
    "có kiểm chứng và sử dụng công cụ đúng cách.\n\n"

    "# 1. NGUYÊN TẮC BẮT BUỘC\n"
    "- Không ảo giác: KHÔNG BAO GIỜ bịa DOI, trích dẫn, tác giả, journal, "
    "retraction status, PubPeer comments, hay dữ liệu học thuật.\n"
    "- Chỉ dùng dữ liệu thật từ công cụ khi trả lời các yêu cầu cần kiểm chứng.\n"
    "- Nếu yêu cầu vượt ngoài khả năng tool hiện có, trả lời ngắn gọn và kèm "
    "cảnh báo: «⚠️ Thông tin này dựa trên kiến thức chung, chưa được xác minh "
    "bằng hệ thống.»\n"
    "- Không được tự ý che giấu hoặc làm nhẹ kết quả xấu.\n\n"

    "# 2. QUY TẮC TOOL CALLING\n"
    "- Chỉ được gọi các tool mà hệ thống expose trong request hiện tại.\n"
    "- Dùng native function-calling. KHÔNG in ra pseudo syntax như "
    "`<function=...>`, XML, JSON thủ công, hay `[Gọi tool: ...]`.\n"
    "- Không được tự bịa arguments, đặc biệt là `document_id`.\n"
    "- Không retry bằng input tự chế nếu tool trả lỗi.\n\n"

    "# 3. DOCUMENT WORKFLOW\n"
    "- Backend có thể cung cấp metadata dạng: "
    "`[Attached Document metadata: document_id='...', length=... chars ...]` "
    "thay vì raw text.\n"
    "- Khi chỉ thấy metadata, bạn KHÔNG có quyền truy cập nội dung tài liệu.\n"
    "- Không được sao chép, tái tạo, suy diễn nội dung từ metadata.\n"
    "- Nếu có `document_id`, chỉ dùng đúng giá trị đó. Không sửa, thay thế, "
    "hay tự tạo.\n"
    "- Không truyền raw document text trong tool args khi đã có "
    "`document_id`.\n\n"

    "# 4. KHI KHÔNG THỂ GỌI TOOL\n"
    "- Nếu tool phù hợp không khả dụng, không bịa tool call.\n"
    "- Nếu tool báo không có pattern đầu vào (không DOI/citation), nói rõ "
    "lý do này thay vì trả lời chung chung.\n"
    "- Nếu tool trả lỗi hạ tầng/API, báo trạng thái tạm thời và đề nghị thử lại.\n\n"

    "# 5. PHONG CÁCH TRẢ LỜI\n"
    "- Trực tiếp, ngắn gọn, chuyên nghiệp.\n"
    "- Trả lời bằng tiếng Việt, trừ khi người dùng viết bằng tiếng Anh.\n"
    "- Giữ nguyên thuật ngữ chuyên ngành khi phù hợp."
)

# Backward-compat alias
SYSTEM_PROMPT = SYSTEM_PROMPT_BASE


def _build_tool_guidance(
    tool_names: set[str],
    document_ids: set[str],
) -> str:
    """Build per-request tool guidance appended to SYSTEM_PROMPT_BASE.

    Only lists tools that are actually exposed, eliminating
    prompt-tool-exposure misalignment.
    """
    parts: list[str] = ["\n\n# TOOL CONTEXT CHO REQUEST NÀY"]

    if document_ids:
        ids_str = ", ".join(f"'{d}'" for d in sorted(document_ids))
        parts.append(f"Document reference khả dụng: {ids_str}.")
    else:
        parts.append(
            "Không có document reference trong scope hiện tại."
        )

    if not tool_names:
        parts.append("Không có tool nào khả dụng.")
        return "\n".join(parts)

    parts.append("\nCác tool khả dụng:")

    _guidance: dict[str, str] = {
        "scan_retraction_and_pubpeer": (
            "Quét DOI kiểm tra retraction/PubPeer"
            + (". Ưu tiên document_id." if document_ids else ". Dùng inline text chứa DOI.")
        ),
        "verify_citation": (
            "Xác minh trích dẫn/reference"
            + (". Ưu tiên document_id." if document_ids else ". Dùng inline text chứa citations.")
        ),
        "match_journal": (
            "Gợi ý tạp chí phù hợp"
            + (". Ưu tiên document_id." if document_ids else ". Dùng inline abstract.")
        ),
        "detect_ai_writing": "Phát hiện AI writing. Chỉ gọi với document_id.",
        "check_grammar": "Kiểm tra ngữ pháp/chính tả. Chỉ gọi với document_id.",
    }

    for name in sorted(tool_names):
        desc = _guidance.get(name, "")
        if desc:
            parts.append(f"- `{name}`: {desc}")

    return "\n".join(parts)


def _build_system_prompt(
    tool_names: set[str],
    document_ids: set[str],
) -> str:
    """Compose the full system prompt for a specific request."""
    return SYSTEM_PROMPT_BASE + _build_tool_guidance(tool_names, document_ids)


# =========================================================================
# Serialisation helpers
# =========================================================================

def _make_serializable(obj: Any) -> Any:
    """Recursively convert Enums, dataclasses, etc. to JSON-safe primitives."""
    if isinstance(obj, dict):
        return {str(k): _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "__dataclass_fields__"):
        return _make_serializable(asdict(obj))
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


def _truncate_text(
    text: str,
    max_chars: int,
    suffix: str = "",
    *,
    log_label: str = "",
) -> str:
    """Truncate *text* to *max_chars*, appending *suffix* if truncated."""
    if len(text) <= max_chars:
        return text
    if log_label:
        logger.info(
            "Truncating %s from %d to %d chars.",
            log_label, len(text), max_chars,
        )
    return text[:max_chars] + suffix


def _sanitize_generated_title(raw_title: str) -> str:
    """Normalize generated title output and remove explanation-like wrappers."""
    title = (raw_title or "").strip()
    if not title:
        return ""

    # Keep only first non-empty line.
    for line in title.splitlines():
        if line.strip():
            title = line.strip()
            break

    title = re.sub(r"^[-*\d.)\s]+", "", title).strip()
    title = title.strip("`\"'“”‘’«»[]()")
    title = _TITLE_PREFIX_RE.sub("", title)
    title = _TITLE_EXPLANATION_RE.sub("", title)
    title = title.strip("`\"'“”‘’«»[]()")

    if ":" in title:
        left, right = title.split(":", 1)
        if len(left.split()) <= 4:
            title = right.strip()

    # Re-run wrapper stripping after colon split.
    title = _TITLE_PREFIX_RE.sub("", title)
    title = _TITLE_EXPLANATION_RE.sub("", title)

    title = re.split(r"[.!?]", title, maxsplit=1)[0].strip()
    title = re.sub(r"\s+", " ", title)
    title = title.strip("`\"'“”‘’«»[]() -:;,.\t")

    words = title.split()
    if len(words) > 8:
        title = " ".join(words[:8])

    low = title.lower()
    if low.startswith("đây là tiêu đề") or low.startswith("day la tieu de"):
        title = re.sub(r"^(?:đây\s+là|day\s+la)\s+tiêu\s*đề\s*[:\-–—]?\s*", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^(?:đây\s+là|day\s+la)\s+tieu\s*de\s*[:\-–—]?\s*", "", title, flags=re.IGNORECASE)
        low = title.lower()

    if any(marker in low for marker in ("because", "vì", "giải thích", "explanation")):
        title = " ".join(title.split()[:5]).strip()

    return title


# =========================================================================
# Tool wrapper functions
# =========================================================================

def scan_retraction_and_pubpeer(text: str) -> dict:
    """Scan DOIs for retraction status and PubPeer discussions."""
    try:
        results = retraction_scanner.scan(text)
        data = _make_serializable([asdict(r) for r in results])
        summary = _make_serializable(retraction_scanner.get_summary(results))
        return {
            "results": data,
            "summary": summary,
            "no_doi_found": bool(summary.get("no_doi_found", False)),
        }
    except Exception as exc:
        logger.error("scan_retraction_and_pubpeer failed: %s", exc, exc_info=True)
        return {"error": str(exc), "results": []}


def verify_citation(text: str) -> dict:
    """Verify academic citations against OpenAlex and Crossref."""
    try:
        results = citation_checker.verify(text)
        data = _make_serializable([asdict(r) for r in results])
        stats = _make_serializable(citation_checker.get_statistics(results))
        no_citation_found = bool(stats.get("no_citation_found", False)) or (bool(results) and all(
            getattr(r, "status", "") == "NO_CITATION_FOUND" for r in results
        ))
        return {
            "results": data,
            "statistics": stats,
            "no_citation_found": no_citation_found,
        }
    except Exception as exc:
        logger.error("verify_citation failed: %s", exc, exc_info=True)
        return {"error": str(exc), "results": []}


def match_journal(abstract: str, title: str = "") -> dict:
    """Find suitable academic journals using SPECTER2 semantic matching."""
    try:
        journals = journal_finder.recommend(
            abstract=abstract, title=title or None, top_k=5,
        )
        return {"journals": _make_serializable(journals), "total": len(journals)}
    except Exception as exc:
        logger.error("match_journal failed: %s", exc, exc_info=True)
        return {"error": str(exc), "journals": []}


def detect_ai_writing(text: str) -> dict:
    """Execution-layer AI writing analysis.

    Router contract:
    - Groq should call `detect_ai_writing` with `document_id` only.

    Execution contract:
    - `_execute_tool_call()` resolves `document_id` -> full text locally,
      then calls this wrapper with resolved `text`.
    """
    try:
        result = ai_writing_detector.analyze(text)
        return _make_serializable(asdict(result))
    except Exception as exc:
        logger.error("detect_ai_writing failed: %s", exc, exc_info=True)
        return {"error": str(exc), "score": 0.5, "verdict": "ERROR"}


def check_grammar(text: str) -> dict:
    """Execution-layer grammar checking.

    Router contract:
    - Groq should call `check_grammar` with `document_id` only.

    Execution contract:
    - `_execute_tool_call()` resolves `document_id` -> full text locally,
      then calls this wrapper with resolved `text`.
    """
    try:
        return _make_serializable(grammar_checker.check_grammar(text))
    except Exception as exc:
        logger.error("check_grammar failed: %s", exc, exc_info=True)
        return {"error": str(exc), "total_errors": -1, "issues": [], "corrected_text": text}


# ── Registries ──────────────────────────────────────────────────────────

_TOOL_FUNCTIONS: dict[str, Any] = {
    "scan_retraction_and_pubpeer": scan_retraction_and_pubpeer,
    "verify_citation": verify_citation,
    "match_journal": match_journal,
    "detect_ai_writing": detect_ai_writing,
    "check_grammar": check_grammar,
}

_TOOL_MESSAGE_TYPE: dict[str, MessageType] = {
    "scan_retraction_and_pubpeer": MessageType.RETRACTION_REPORT,
    "verify_citation": MessageType.CITATION_REPORT,
    "match_journal": MessageType.JOURNAL_LIST,
    "detect_ai_writing": MessageType.AI_WRITING_DETECTION,
    "check_grammar": MessageType.GRAMMAR_REPORT,
}

_TOOL_DATA_KEY: dict[str, str] = {
    "scan_retraction_and_pubpeer": "results",
    "verify_citation": "results",
    "match_journal": "journals",
    "detect_ai_writing": "",
    "check_grammar": "",
}

_MAX_FC_ITERATIONS = 5
_MULTI_TOOL_PAYLOAD_TYPE = "multi_tool_report"


# =========================================================================
# Response dataclass
# =========================================================================

@dataclass
class FunctionCallingResponse:
    """Result of a Groq call that may have used function calling."""

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    message_type: str = "text"
    tool_results: dict[str, Any] | None = None


# =========================================================================
# Pass-by-reference helpers
# =========================================================================

def _should_force_document_reference(user_text: str) -> bool:
    """Determine whether *user_text* must be converted to a document_id
    reference before sending to Groq.

    Policy (deterministic):
        >= 1500 chars  -> always cached (closes the old 500-3999 gap)
        >= 300 chars + intent hint -> cached
        < 300 chars -> passed inline
    """
    normalized = user_text.strip()
    if len(normalized) >= _DOCUMENT_CACHE_TRIGGER_CHARS:
        return True
    if len(normalized) >= _DOCUMENT_ANALYSIS_TRIGGER_CHARS:
        return bool(
            _GRAMMAR_HINT_RE.search(normalized)
            or _AI_WRITING_HINT_RE.search(normalized)
            or _CITATION_HINT_RE.search(normalized)
            or _RETRACTION_HINT_RE.search(normalized)
        )
    return False


def _split_long_user_input(text: str) -> tuple[str, str]:
    """Split user input into (query_part, document_part).

    Heuristic:
    - Use a short leading segment as query ONLY if it looks like an explicit
      user instruction separated from the long body.
    - Otherwise, safe-first fallback treats the entire payload as document
      body and lets router query be inferred without copying raw text.
    """
    normalized = text.strip()
    if not normalized:
        return "", ""

    blocks = [b.strip() for b in re.split(r"\n\s*\n+", normalized) if b.strip()]
    if len(blocks) >= 2:
        head = re.sub(r"\s+", " ", blocks[0]).strip()
        tail = "\n\n".join(blocks[1:]).strip()
        if tail and _looks_like_explicit_router_instruction(head):
            return head, tail

    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    if len(sentences) >= 2:
        head = re.sub(r"\s+", " ", sentences[0]).strip()
        tail = " ".join(sentences[1:]).strip()
        if (
            tail
            and len(tail) >= _DOCUMENT_ANALYSIS_TRIGGER_CHARS
            and _looks_like_explicit_router_instruction(head)
        ):
            return head, tail

    # Safe-first fallback: treat entire payload as document body.
    return "", normalized


def _looks_like_explicit_router_instruction(text: str) -> bool:
    """Return True when *text* looks like a short standalone instruction."""
    compact = re.sub(r"\s+", " ", (text or "")).strip()
    if not compact:
        return False

    word_count = len(compact.split())
    if len(compact) > 240 or word_count > 36:
        return False

    if _ROUTER_INSTRUCTION_PREFIX_RE.search(compact):
        return True
    if _GRAMMAR_HINT_RE.search(compact) or _AI_WRITING_HINT_RE.search(compact):
        return True
    if _ROUTER_INSTRUCTION_HINT_RE.search(compact):
        return True
    return False


def _extract_attached_documents_from_turn(user_text: str) -> tuple[str, str | None, int]:
    """Extract all attached-document blocks and return (query, body, count)."""
    docs: list[str] = []
    for match in ATTACHED_DOCUMENT_RE.finditer(user_text):
        doc = (match.group("text") or "").strip()
        if doc:
            docs.append(doc)

    if not docs:
        return user_text.strip(), None, 0

    query_without_docs = ATTACHED_DOCUMENT_RE.sub(" ", user_text)
    query_without_docs = re.sub(r"\s+", " ", query_without_docs).strip()
    merged_doc = "\n\n".join(docs)
    return query_without_docs, merged_doc, len(docs)


def _infer_document_router_query(user_text: str) -> str:
    """Extract or synthesise a short query for document analysis."""
    low = user_text.lower()
    if _CITATION_HINT_RE.search(low):
        return "Xác minh citation và tài liệu tham khảo cho tài liệu đính kèm."
    if _RETRACTION_HINT_RE.search(low):
        return "Quét DOI để kiểm tra retraction và tín hiệu PubPeer cho tài liệu đính kèm."
    if _GRAMMAR_HINT_RE.search(low):
        return "Kiểm tra ngữ pháp và chính tả cho tài liệu đính kèm."
    if _AI_WRITING_HINT_RE.search(low):
        return "Phát hiện AI writing cho tài liệu đính kèm."
    return (
        "Người dùng đã gửi một tài liệu dài. "
        "Hãy chọn tool phù hợp và chỉ truyền document_id."
    )


def _prepare_user_text_for_router(user_text: str) -> str:
    """Convert raw user text into a router-safe form.

    - Attached documents -> always document_id reference
    - Long text -> document_id reference
    - Short text -> pass-through
    """
    normalized = user_text.strip()
    if not normalized:
        return normalized

    # 1. Attached document XML blocks -> aggregate, cache, replace with metadata
    query_parts, merged_doc, doc_count = _extract_attached_documents_from_turn(normalized)
    if merged_doc:
        doc_id = store_document(merged_doc)
        logger.info(
            "Converted %d attached document block(s) to reference %s (%d chars).",
            doc_count, doc_id, len(merged_doc),
        )
        return build_document_reference_prompt(
            doc_id, merged_doc,
            query_parts or _infer_document_router_query(normalized),
        )

    # 2. Force-reference for long or intent-matched text
    if _should_force_document_reference(normalized):
        query, body = _split_long_user_input(normalized)
        doc_text = body or normalized
        doc_id = store_document(doc_text)
        logger.info(
            "Force-cached user text to reference %s (%d chars, query=%d chars).",
            doc_id, len(doc_text), len(query),
        )
        return build_document_reference_prompt(
            doc_id, doc_text,
            query or _infer_document_router_query(normalized),
        )

    return normalized


def _prepare_history_user_text_for_router(user_text: str) -> str:
    """Prepare prior user turns for router safety without new references.

    Important: history must not create new ``document_id`` entries or expose
    stale document references from unrelated turns.
    """
    normalized = _strip_pseudo_tool_syntax((user_text or "").strip())
    if not normalized:
        return normalized

    if ATTACHED_DOCUMENT_RE.search(normalized):
        without_doc = ATTACHED_DOCUMENT_RE.sub("", normalized).strip()
        marker = "[Attached document content omitted from history for router safety.]"
        return f"{without_doc}\n\n{marker}".strip()

    if extract_document_id(normalized):
        query = strip_document_metadata(normalized)
        marker = "[Historical document reference omitted from history scope.]"
        return f"{query}\n\n{marker}".strip() if query else marker

    if len(normalized) >= _DOCUMENT_CACHE_TRIGGER_CHARS:
        return (
            f"{_infer_document_router_query(normalized)}\n\n"
            "[Historical long content omitted for router safety.]"
        )

    return normalized


# =========================================================================
# Sanitisation helpers
# =========================================================================

def _strip_pseudo_tool_syntax(text: str) -> str:
    """Remove all known pseudo-tool patterns from text.

    Used in THREE places:
    1. Mid-loop assistant content before appending
    2. Final assistant response before returning
    3. Pseudo detection fallback
    """
    if not text:
        return text
    cleaned = text
    for pattern in _PSEUDO_TOOL_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


def _has_pseudo_tool_syntax(text: str) -> bool:
    """Check if text contains any pseudo-tool patterns."""
    if not text:
        return False
    return any(p.search(text) for p in _PSEUDO_TOOL_PATTERNS)


def _is_low_signal_assistant_text(text: str) -> bool:
    """Detect low-signal replies that should be replaced by tool-state text."""
    normalized = (text or "").strip()
    if not normalized:
        return True
    if _has_pseudo_tool_syntax(normalized):
        return True
    return any(p.search(normalized) for p in _LOW_SIGNAL_ASSISTANT_PATTERNS)


def _build_tool_state_text(tool_name: str, result: dict[str, Any]) -> str | None:
    """Build deterministic user-facing status text from tool outcomes."""
    error = str(result.get("error") or "").strip()
    if error:
        low_error = error.lower()
        if (
            "document_id" in low_error
            or "unknown function" in low_error
            or "unexpected arguments" in low_error
            or "missing required argument" in low_error
        ):
            return (
                "Không thể thực thi công cụ do tham chiếu tài liệu không hợp lệ "
                "hoặc tool không khả dụng trong ngữ cảnh hiện tại."
            )
        if tool_name in {"scan_retraction_and_pubpeer", "verify_citation"}:
            return (
                "Không thể truy vấn nguồn dữ liệu học thuật ở thời điểm này. "
                "Vui lòng thử lại sau."
            )
        return f"⚠️ Công cụ trả lỗi: {error}"

    if tool_name == "scan_retraction_and_pubpeer":
        summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
        total_checked = int(summary.get("total_checked", summary.get("total", 0)) or 0)
        no_doi = bool(summary.get("no_doi_found", False))
        if no_doi or total_checked == 0:
            return (
                "Không phát hiện DOI hợp lệ trong nội dung đã cung cấp, "
                "nên hệ thống chưa thể quét trạng thái retraction."
            )
        retracted = int(summary.get("retracted", 0) or 0)
        concerns = int(summary.get("concerns", 0) or 0)
        high_risk = int(summary.get("high_risk", 0) or 0)
        critical_risk = int(summary.get("critical_risk", 0) or 0)
        if retracted > 0 or concerns > 0 or high_risk > 0 or critical_risk > 0:
            return (
                f"Đã quét {total_checked} DOI và phát hiện mục có rủi ro "
                "(retracted/concern). Xem bảng kết quả để biết chi tiết từng DOI."
            )
        return (
            f"Đã quét {total_checked} DOI và chưa phát hiện tín hiệu retraction "
            "hoặc concern trong các nguồn đã kiểm tra."
        )

    if tool_name == "verify_citation":
        stats = result.get("statistics", {}) if isinstance(result.get("statistics"), dict) else {}
        no_citation = bool(result.get("no_citation_found", False))
        total = int(stats.get("total", 0) or 0)
        if no_citation or total == 0:
            return (
                "Không phát hiện mẫu citation/DOI hợp lệ trong nội dung đã cung cấp, "
                "nên chưa có mục nào để xác minh."
            )
        hallucinated = int(stats.get("hallucinated", 0) or 0)
        unverified = int(stats.get("unverified", 0) or 0)
        partial = int(stats.get("partial_match", 0) or 0)
        valid = int(stats.get("valid", 0) or 0) + int(stats.get("doi_verified", 0) or 0)
        if hallucinated > 0:
            return (
                f"Đã xác minh {total} citation: {valid} hợp lệ, "
                f"{hallucinated} mục có dấu hiệu sai/hallucinated, "
                f"{partial + unverified} mục còn lại cần kiểm tra thêm."
            )
        if unverified > 0:
            return (
                f"Đã xác minh {total} citation: {valid} hợp lệ, "
                f"{partial} khớp một phần, {unverified} chưa xác minh được "
                "(có thể do nguồn tra cứu tạm thời không phản hồi)."
            )
        if partial > 0:
            return (
                f"Đã xác minh {total} citation: {valid} hợp lệ, "
                f"{partial} mục khớp một phần và cần rà soát thủ công thêm."
            )
        return f"Đã xác minh {total} citation và chưa phát hiện mục bất thường."

    if tool_name == "match_journal":
        journals = result.get("journals", [])
        if isinstance(journals, list) and not journals:
            return (
                "Hệ thống chưa tìm thấy journal phù hợp từ dữ liệu hiện có. "
                "Hãy mở rộng abstract hoặc từ khóa chủ đề để thử lại."
            )

    return None


def _sanitize_tool_call_args(
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Strip unexpected keys and truncate oversized text arguments."""
    allowed = _TOOL_ALLOWED_ROUTER_ARGS.get(tool_name)
    if allowed:
        args = {k: v for k, v in args.items() if k in allowed}

    for key in ("text", "abstract"):
        if key in args and isinstance(args[key], str) and len(args[key]) > _TOOL_CALL_ARG_PREVIEW_CHARS:
            args[key] = args[key][:_TOOL_CALL_ARG_PREVIEW_CHARS] + "..."
            logger.info(
                "Truncated arg '%s' for %s to %d chars.",
                key, tool_name, _TOOL_CALL_ARG_PREVIEW_CHARS,
            )
    return args


# =========================================================================
# Tool result budgeting — model-facing vs UI-facing separation
# =========================================================================

def _compact_tool_result_for_model(tool_name: str, full_result: dict) -> dict:
    """Create a compact summary of tool results for Groq model feedback.

    The model only needs enough context to synthesise a natural-language
    response.  Full results are kept for UI/persistence via all_tool_calls.
    """
    if tool_name == "check_grammar":
        total = full_result.get("total_errors", 0)
        issues = full_result.get("issues", [])
        # Aggregate top categories
        categories = Counter(
            i.get("category", "OTHER") for i in issues if isinstance(i, dict)
        )
        top_cats = [cat for cat, _ in categories.most_common(5)]
        corrected = full_result.get("corrected_text", "")
        preview = corrected[:200] + "..." if len(corrected) > 200 else corrected
        return {
            "status": "error" if full_result.get("error") else "ok",
            "total_errors": total,
            "top_categories": top_cats,
            "corrected_preview": preview,
        }

    if tool_name == "detect_ai_writing":
        return {
            "score": full_result.get("score", 0.5),
            "verdict": full_result.get("verdict", "UNCERTAIN"),
            "confidence": full_result.get("confidence", "LOW"),
            "method": full_result.get("method", "unknown"),
        }

    if tool_name == "scan_retraction_and_pubpeer":
        summary = full_result.get("summary", {})
        total_checked = summary.get("total_checked", summary.get("total", 0))
        return {
            "status": "error" if full_result.get("error") else "ok",
            "total": total_checked,
            "total_checked": total_checked,
            "no_doi_found": bool(summary.get("no_doi_found", False)),
            "retracted": summary.get("retracted", 0),
            "concerns": summary.get("concerns", 0),
            "critical_risk": summary.get("critical_risk", 0),
            "high_risk": summary.get("high_risk", 0),
        }

    if tool_name == "verify_citation":
        stats = full_result.get("statistics", {})
        return {
            "status": "error" if full_result.get("error") else "ok",
            "total": stats.get("total", 0),
            "no_citation_found": bool(full_result.get("no_citation_found", False)),
            "valid": stats.get("valid", 0),
            "doi_verified": stats.get("doi_verified", 0),
            "partial_match": stats.get("partial_match", 0),
            "hallucinated": stats.get("hallucinated", 0),
            "unverified": stats.get("unverified", 0),
        }

    if tool_name == "match_journal":
        journals = full_result.get("journals", [])
        top_name = journals[0].get("journal", "N/A") if journals else "none"
        return {
            "status": "error" if full_result.get("error") else "ok",
            "found": len(journals),
            "top": top_name,
        }

    # Fallback: truncate JSON to 1000 chars
    serialized = json.dumps(full_result, ensure_ascii=False, default=str)
    if len(serialized) > 1000:
        return {"summary": serialized[:1000] + "...[truncated]"}
    return full_result


# =========================================================================
# Terminal tool text generation
# =========================================================================

def _generate_terminal_tool_text(tool_name: str, result: dict) -> str:
    """Generate assistant text for terminal tools that exit the FC loop."""
    if tool_name == "check_grammar":
        total = result.get("total_errors", 0)
        error = result.get("error")
        if error:
            low_error = str(error).lower()
            if "document_id" in low_error:
                return (
                    "⚠️ Không thể kiểm tra ngữ pháp vì tham chiếu tài liệu "
                    "không hợp lệ hoặc đã hết hiệu lực."
                )
            return f"⚠️ Không thể kiểm tra ngữ pháp: {error}"
        if total == 0:
            return "✅ Không phát hiện lỗi ngữ pháp hay chính tả."
        return (
            f"Đã kiểm tra ngữ pháp và chính tả. Phát hiện **{total}** lỗi.\n"
            "Xem chi tiết trong bảng kết quả bên dưới."
        )

    if tool_name == "detect_ai_writing":
        score = result.get("score", 0.5)
        verdict = result.get("verdict", "UNCERTAIN")
        error = result.get("error")
        if error:
            low_error = str(error).lower()
            if "document_id" in low_error:
                return (
                    "⚠️ Không thể phân tích AI writing vì tham chiếu tài liệu "
                    "không hợp lệ hoặc đã hết hiệu lực."
                )
            return f"⚠️ Không thể phân tích AI writing: {error}"
        try:
            score_pct = f"{float(score):.1%}"
        except (TypeError, ValueError):
            score_pct = str(score)
        return (
            f"Phân tích AI writing (mang tính ước lượng): điểm = **{score_pct}**, "
            f"phân loại: **{verdict}**.\n"
            "Kết quả này không phải bằng chứng kết luận tuyệt đối; "
            "xem chi tiết bên dưới để đánh giá thêm."
        )

    return "Tool đã thực thi thành công. Xem kết quả bên dưới."


# =========================================================================
# Tool exposure & scoping
# =========================================================================

def _extract_current_turn_document_ids(current_user_text: str) -> set[str]:
    """Extract document IDs from ONLY the current user message.

    Current-turn-only scoping is the safe-first behaviour.
    Conversational document carry-forward is deferred to future work.
    """
    doc_id = extract_document_id(current_user_text)
    if doc_id:
        return {doc_id}
    return set()


def _select_groq_tools(allowed_document_ids: set[str]) -> list[dict[str, Any]]:
    """Return the subset of tools to expose for this request.

    Document-only tools are hidden when no valid document_id is in scope.
    """
    if allowed_document_ids:
        return _GROQ_TOOLS  # all tools

    return [
        t for t in _GROQ_TOOLS
        if t["function"]["name"] not in _DOCUMENT_ID_ONLY_TOOLS
    ]


def _extract_router_query_signal(text: str) -> str:
    """Extract user query signal from router-prepared content."""
    normalized = (text or "").strip()
    if not normalized:
        return ""
    if extract_document_id(normalized):
        normalized = strip_document_metadata(normalized)
    normalized = ATTACHED_DOCUMENT_RE.sub(" ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _tool_label(tool_name: str) -> str:
    labels = {
        "verify_citation": "Citation Verification",
        "scan_retraction_and_pubpeer": "Retraction & PubPeer Scan",
        "match_journal": "Journal Matching",
        "detect_ai_writing": "AI Writing Detection",
        "check_grammar": "Grammar Check",
    }
    return labels.get(tool_name, tool_name)


def _to_tool_result_block(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    msg_type_enum = _TOOL_MESSAGE_TYPE.get(tool_name)
    msg_type = msg_type_enum.value if msg_type_enum else "text"
    data_key = _TOOL_DATA_KEY.get(tool_name, "")
    block: dict[str, Any] = {
        "tool_name": tool_name,
        "label": _tool_label(tool_name),
        "type": msg_type,
        "data": result.get(data_key, result) if data_key else result,
    }
    summary = _build_tool_state_text(tool_name, result)
    if summary:
        block["summary"] = summary
    return block


def _build_tool_results_payload(
    tool_calls: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    if not tool_calls:
        return "text", None

    if len(tool_calls) == 1:
        only = tool_calls[0]
        block = _to_tool_result_block(only["name"], only["result"])
        return block["type"], {
            "type": block["type"],
            "data": block["data"],
            "tool_name": block["tool_name"],
            "label": block["label"],
        }

    groups = [_to_tool_result_block(tc["name"], tc["result"]) for tc in tool_calls]
    return "text", {
        "type": _MULTI_TOOL_PAYLOAD_TYPE,
        "groups": groups,
    }


def _build_tool_state_text_from_calls(tool_calls: list[dict[str, Any]]) -> str | None:
    if not tool_calls:
        return None

    chunks: list[str] = []
    for call in tool_calls:
        tool_name = call.get("name", "")
        result = call.get("result", {})
        if not isinstance(result, dict):
            continue
        state_text = _build_tool_state_text(tool_name, result)
        if not state_text:
            continue
        chunks.append(f"{_tool_label(tool_name)}: {state_text}")

    if not chunks:
        return None
    if len(chunks) == 1:
        return chunks[0].split(": ", 1)[1]
    return "\n\n".join(chunks)


def _detect_explicit_tool_requests(prepared_user_text: str) -> list[str]:
    """Detect deterministic explicit tool request(s) from user phrasing."""
    signal = _extract_router_query_signal(prepared_user_text)
    if not signal:
        return []

    low = signal.lower()
    citation_match = _CITATION_HINT_RE.search(low)
    retraction_match = _RETRACTION_HINT_RE.search(low)

    has_citation = bool(citation_match)
    has_retraction = bool(retraction_match)

    if has_citation and has_retraction:
        if not _BOTH_ACTION_HINT_RE.search(low):
            if retraction_match and citation_match:
                if retraction_match.start() <= citation_match.start():
                    return ["scan_retraction_and_pubpeer"]
                return ["verify_citation"]
        ordered = [
            ("verify_citation", citation_match.start() if citation_match else 10**9),
            ("scan_retraction_and_pubpeer", retraction_match.start() if retraction_match else 10**9),
        ]
        return [name for name, _ in sorted(ordered, key=lambda x: x[1])]
    if has_citation:
        return ["verify_citation"]
    if has_retraction:
        return ["scan_retraction_and_pubpeer"]
    return []


def _execute_explicit_tool_requests(
    tool_names: list[str],
    prepared_user_text: str,
    allowed_document_ids: set[str],
) -> FunctionCallingResponse | None:
    """Execute deterministic explicit tool request(s) without Groq routing."""
    ordered_tools = [
        name for name in tool_names
        if name in {"verify_citation", "scan_retraction_and_pubpeer"}
    ]
    if not ordered_tools:
        return None

    if allowed_document_ids:
        doc_id = next(iter(allowed_document_ids))
        shared_args: dict[str, Any] = {"document_id": doc_id}
    else:
        query_text = _extract_router_query_signal(prepared_user_text)
        if not query_text:
            return None
        shared_args = {"text": query_text}

    tool_calls: list[dict[str, Any]] = []
    for tool_name in ordered_tools:
        raw_args = dict(shared_args)
        result = _execute_tool_call(tool_name, raw_args, allowed_document_ids)
        safe_args = _sanitize_tool_call_args(tool_name, raw_args)
        tool_calls.append({
            "name": tool_name,
            "args": safe_args,
            "result": result,
        })

    msg_type, tool_results_payload = _build_tool_results_payload(tool_calls)
    text = _build_tool_state_text_from_calls(tool_calls) or (
        "Yêu cầu đã được xử lý bằng đường dẫn công cụ xác định."
    )

    return FunctionCallingResponse(
        text=text,
        tool_calls=tool_calls,
        message_type=msg_type,
        tool_results=tool_results_payload,
    )


# =========================================================================
# FC loop — tool call execution
# =========================================================================

def _execute_tool_call(
    fn_name: str,
    fn_args: dict[str, Any],
    allowed_document_ids: set[str],
) -> dict[str, Any]:
    """Execute a single tool call, resolving document_id if needed."""
    fn = _TOOL_FUNCTIONS.get(fn_name)
    if fn is None:
        logger.warning("Groq requested unknown function: %s", fn_name)
        return {"error": f"Unknown function: {fn_name}"}

    allowed_keys = _TOOL_ALLOWED_ROUTER_ARGS.get(fn_name, set())
    unexpected = sorted(set(fn_args) - allowed_keys)
    if unexpected:
        logger.warning(
            "Rejecting tool %s due to unexpected args: %s",
            fn_name,
            unexpected,
        )
        return {"error": f"Unexpected arguments for {fn_name}: {', '.join(unexpected)}"}

    target_arg = _TOOL_DOCUMENT_ARGUMENT.get(fn_name)

    # Resolve document_id -> full cached text
    doc_id = fn_args.get("document_id")
    if fn_name in _DOCUMENT_ID_ONLY_TOOLS and not doc_id:
        logger.warning("Tool %s requires pass-by-reference document_id.", fn_name)
        return {"error": f"{fn_name} requires a valid document_id"}

    if doc_id:
        if not isinstance(doc_id, str) or not doc_id.strip():
            return {"error": "document_id must be a non-empty string"}
        doc_id = doc_id.strip()

        if doc_id not in allowed_document_ids:
            logger.warning(
                "Tool %s got out-of-scope document_id '%s'. Allowed: %s",
                fn_name, doc_id, allowed_document_ids,
            )
            return {"error": f"Invalid document_id: {doc_id}"}

        full_text = get_document(doc_id)
        if not full_text:
            logger.error("Document %s not found in cache.", doc_id)
            return {"error": f"Document {doc_id} not found in cache."}

        # Replace document_id with resolved text in tool arguments
        if target_arg and fn_args.get(target_arg):
            logger.warning(
                "Rejecting tool %s because both document_id and %s were provided.",
                fn_name,
                target_arg,
            )
            return {"error": f"{fn_name} cannot receive both document_id and {target_arg}"}

        exec_args = {target_arg: full_text} if target_arg else {}
        # Carry other args (e.g. title for match_journal)
        for k, v in fn_args.items():
            if k != "document_id" and k != target_arg:
                exec_args[k] = v
    else:
        exec_args = {k: v for k, v in fn_args.items() if k != "document_id"}

    if target_arg and not exec_args.get(target_arg):
        return {"error": f"Missing required argument: {target_arg} or document_id"}

    logger.info(
        "Executing tool: %s (doc_id=%s, text_len=%d)",
        fn_name, doc_id or "none",
        len(exec_args.get(target_arg or "text", "")),
    )

    try:
        return fn(**exec_args)
    except Exception as exc:
        logger.error("Tool %s execution failed: %s", fn_name, exc, exc_info=True)
        return {"error": f"Tool execution failed: {exc}"}


# =========================================================================
# GroqLLMService
# =========================================================================

class GroqLLMService:
    """Wrapper around Groq with Function Calling support."""

    def __init__(self) -> None:
        self._client = None
        if not settings.groq_api_key:
            logger.warning("GROQ_API_KEY not set — Groq disabled.")
            return
        if Groq is None:
            logger.warning("groq package not installed — Groq disabled.")
            return
        try:
            self._client = Groq(api_key=settings.groq_api_key)
            logger.info(
                "Groq client initialised (model=%s) with Function Calling.",
                settings.groq_model,
            )
        except Exception:
            logger.exception("Failed to create Groq client.")
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------
    # Retryable Groq API call
    # ------------------------------------------------------------------

    def _call_chat_completions(self, **kwargs: Any) -> Any:
        """Call Groq chat.completions.create with tenacity retry."""
        retry_types: tuple = (Exception,)
        if groq_module is not None:
            retry_types = (
                getattr(groq_module, "InternalServerError", Exception),
                getattr(groq_module, "RateLimitError", Exception),
                getattr(groq_module, "APIStatusError", Exception),
            )

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=4, max=10),
            retry=retry_if_exception_type(retry_types),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )
        def _inner():
            return self._client.chat.completions.create(**kwargs)  # type: ignore[union-attr]

        return _inner()

    # ------------------------------------------------------------------
    # Heuristic fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _try_heuristic_fallback(
        messages: list[dict[str, Any]],
        *,
        allowed_tool_names: set[str] | None = None,
    ) -> FunctionCallingResponse | None:
        """Attempt heuristic tool execution when Groq is unavailable.

        The fallback path still honors the current request's exposed-tool
        contract via ``allowed_tool_names``.
        """
        try:
            try:
                from app.services.heuristic_router import fallback_process_request
            except ModuleNotFoundError:
                from app.services.tools.heuristic_router import fallback_process_request  # type: ignore[no-redef]

            user_text = ""
            file_context: str | None = None

            for msg in reversed(messages):
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", "")
                if not content:
                    continue

                # Check for attached document
                if "<Attached_Document" in content:
                    file_context = content
                elif not user_text:
                    # Check for document metadata -> resolve from cache
                    resolved = restore_file_context_from_metadata(content)
                    if resolved:
                        file_context = resolved
                        clean_query = strip_document_metadata(content)
                        user_text = clean_query or content
                    else:
                        user_text = content

                if user_text or file_context:
                    break

            if not user_text and not file_context:
                return None

            result = fallback_process_request(
                user_text,
                file_context,
                allowed_tool_names=allowed_tool_names,
            )
            if result is None:
                return None

            safe_text = _strip_pseudo_tool_syntax(result["text"])
            return FunctionCallingResponse(
                text=safe_text or "Hệ thống đã xử lý yêu cầu bằng fallback an toàn.",
                tool_calls=result.get("tool_calls", []),
                message_type=result["message_type"],
                tool_results=result.get("tool_results"),
            )
        except Exception as exc:
            logger.exception("CRITICAL: _try_heuristic_fallback crashed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Build messages
    # ------------------------------------------------------------------

    @staticmethod
    def _build_messages(
        history: Sequence[ChatMessage],
        prepared_user_text: str,
        system_prompt: str,
    ) -> list[dict[str, str]]:
        """Convert DB history + prepared user text into Groq messages."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Sliding window over history (current user msg NOT in history)
        recent = history[-_MAX_HISTORY_MESSAGES:] if len(history) > _MAX_HISTORY_MESSAGES else list(history)
        for msg in recent:
            role = "user" if msg.role.value == "user" else "assistant"
            text = (msg.content or "").strip()
            if role == "user":
                text = _prepare_history_user_text_for_router(text)
            else:
                text = _strip_pseudo_tool_syntax(text)
            text = _truncate_text(
                text, _MAX_HISTORY_MESSAGE_CHARS,
                _TRUNCATED_HISTORY_SUFFIX, log_label="history",
            )
            if text:
                messages.append({"role": role, "content": text})

        # Current user message (already prepared by caller)
        safe_user = _truncate_text(
            prepared_user_text, _MAX_ROUTER_INPUT_CHARS,
            _TRUNCATED_INPUT_SUFFIX, log_label="user_text",
        )
        messages.append({"role": "user", "content": safe_user})
        return messages

    # ------------------------------------------------------------------
    # FC loop
    # ------------------------------------------------------------------

    def _generate_with_fc(
        self,
        messages: list[dict[str, str]],
        available_tools: list[dict[str, Any]],
        allowed_document_ids: set[str],
    ) -> FunctionCallingResponse:
        """Run the function-calling loop."""
        all_tool_calls: list[dict[str, Any]] = []
        available_tool_names = {
            tool.get("function", {}).get("name", "")
            for tool in available_tools
            if tool.get("function", {}).get("name")
        }

        _sdk_errors: tuple = ()
        if groq_module is not None:
            _sdk_errors = (
                getattr(groq_module, "InternalServerError", Exception),
                getattr(groq_module, "RateLimitError", Exception),
                getattr(groq_module, "APIStatusError", Exception),
            )

        for iteration in range(_MAX_FC_ITERATIONS):
            try:
                call_kwargs: dict[str, Any] = {
                    "model": settings.groq_model,
                    "messages": messages,
                }
                if available_tools:
                    call_kwargs["tools"] = available_tools
                    call_kwargs["tool_choice"] = "auto"

                response = self._call_chat_completions(**call_kwargs)

            except (*_sdk_errors, RetryError) as exc:
                logger.error(
                    "Groq API error after retries (iter %d): %s",
                    iteration, exc, exc_info=True,
                )
                fallback = self._try_heuristic_fallback(
                    messages,
                    allowed_tool_names=available_tool_names,
                )
                if fallback is not None:
                    return fallback
                return FunctionCallingResponse(
                    text=(
                        "⚠️ Hệ thống AI hiện đang quá tải "
                        "(Lỗi 503/429 từ Groq). "
                        "Vui lòng đợi vài phút và thử lại."
                    ),
                    message_type="TEXT",
                )
            except Exception as exc:
                logger.exception(
                    "Unexpected error calling Groq (iter %d): %s",
                    iteration, exc,
                )
                fallback = self._try_heuristic_fallback(
                    messages,
                    allowed_tool_names=available_tool_names,
                )
                if fallback is not None:
                    return fallback
                return FunctionCallingResponse(
                    text="⚠️ Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.",
                    message_type="TEXT",
                )

            if not response.choices:
                return FunctionCallingResponse(text="Groq không trả về kết quả.")

            choice = response.choices[0]
            assistant_message = choice.message
            tool_calls_in_response = assistant_message.tool_calls or []

            if not tool_calls_in_response:
                # ── Final text response ──────────────────────────────
                raw_final_text = (assistant_message.content or "").strip()

                # Pseudo tool content without native tool_calls is invalid.
                if _has_pseudo_tool_syntax(raw_final_text):
                    logger.warning(
                        "Groq returned pseudo tool syntax without native tool_calls; treating as invalid action path."
                    )
                    fallback = self._try_heuristic_fallback(
                        messages,
                        allowed_tool_names=available_tool_names,
                    )
                    if fallback is not None:
                        return fallback
                    return FunctionCallingResponse(
                        text=(
                            "⚠️ Hệ thống nhận phản hồi công cụ không hợp lệ từ mô hình. "
                            "Vui lòng thử lại."
                        ),
                        message_type="text",
                    )

                final_text = _strip_pseudo_tool_syntax(raw_final_text)

                msg_type = "text"
                tool_results_payload: dict[str, Any] | None = None
                state_text: str | None = None

                if all_tool_calls:
                    msg_type, tool_results_payload = _build_tool_results_payload(all_tool_calls)
                    state_text = _build_tool_state_text_from_calls(all_tool_calls)

                if state_text and len(all_tool_calls) > 1:
                    final_text = state_text
                elif state_text and _is_low_signal_assistant_text(final_text):
                    final_text = state_text

                return FunctionCallingResponse(
                    text=final_text or "Không có phản hồi từ Groq.",
                    tool_calls=all_tool_calls,
                    message_type=msg_type,
                    tool_results=tool_results_payload,
                )

            # ── Execute tool calls ───────────────────────────────────
            # Sanitize assistant content before appending to messages
            assistant_content = _strip_pseudo_tool_syntax(
                assistant_message.content or ""
            )
            # Build assistant message with tool_calls for Groq protocol
            assistant_msg_dict: dict[str, Any] = {
                "role": "assistant",
                "content": assistant_content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls_in_response
                ],
            }
            messages.append(assistant_msg_dict)

            has_terminal = False
            terminal_data: tuple[str, dict] | None = None
            pending_tool_feedback: list[tuple[str, dict[str, Any]]] = []

            for tc in tool_calls_in_response:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    fn_args = {}
                if not isinstance(fn_args, dict):
                    logger.warning(
                        "Tool %s returned non-object arguments; coercing to empty object.",
                        fn_name,
                    )
                    fn_args = {}

                # Sanitize args
                safe_args = _sanitize_tool_call_args(fn_name, dict(fn_args))

                # Execute
                result = _execute_tool_call(
                    fn_name, fn_args, allowed_document_ids,
                )

                # Store FULL result for UI/persistence
                all_tool_calls.append({
                    "name": fn_name,
                    "args": safe_args,
                    "result": result,
                })

                if fn_name in _TERMINAL_TOOLS:
                    has_terminal = True
                    if terminal_data is None:
                        terminal_data = (fn_name, result)
                    continue

                # Keep compact feedback only for non-terminal tools that
                # require another model synthesis round.
                compact = _compact_tool_result_for_model(fn_name, result)
                pending_tool_feedback.append((tc.id, compact))

            for tool_call_id, compact in pending_tool_feedback:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(compact, ensure_ascii=False, default=str),
                })

            logger.info(
                "FC iteration %d: executed %d tool(s) [%s]",
                iteration + 1,
                len(tool_calls_in_response),
                ", ".join(tc.function.name for tc in tool_calls_in_response),
            )

            # ── Terminal tool early exit ──────────────────────────────
            if has_terminal and terminal_data is not None:
                fn_name, result = terminal_data
                msg_type, tool_results_payload = _build_tool_results_payload(all_tool_calls)
                template_text = _generate_terminal_tool_text(fn_name, result)
                if len(all_tool_calls) > 1:
                    non_terminal_state = _build_tool_state_text_from_calls([
                        tc for tc in all_tool_calls if tc.get("name") != fn_name
                    ])
                    if non_terminal_state:
                        template_text = f"{template_text}\n\n{non_terminal_state}"
                return FunctionCallingResponse(
                    text=template_text,
                    tool_calls=all_tool_calls,
                    message_type=msg_type,
                    tool_results=tool_results_payload,
                )

        # Budget exhausted
        logger.warning("FC loop exceeded %d iterations.", _MAX_FC_ITERATIONS)
        return FunctionCallingResponse(
            text="Đã vượt quá số lần gọi công cụ tối đa. Vui lòng thử lại.",
            tool_calls=all_tool_calls,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_response(
        self,
        history: Sequence[ChatMessage],
        user_text: str,
    ) -> FunctionCallingResponse:
        """Generate a response with Function Calling support."""
        if not self.enabled:
            return FunctionCallingResponse(
                text=(
                    "Groq chưa được cấu hình. Hãy đặt GROQ_API_KEY "
                    "để kích hoạt AI. Tin nhắn của bạn đã được lưu."
                ),
            )

        # 1. Prepare user text (may create document references)
        prepared_user_text = _prepare_user_text_for_router(user_text)

        # 2. Extract document IDs (current turn only — safe-first)
        current_doc_ids = _extract_current_turn_document_ids(prepared_user_text)

        # 3. Select available tools
        available_tools = _select_groq_tools(current_doc_ids)
        available_tool_names = {
            t["function"]["name"] for t in available_tools
        }

        # 3.5 Deterministic explicit action path (citation/retraction)
        explicit_tools = [
            name for name in _detect_explicit_tool_requests(prepared_user_text)
            if name in available_tool_names
        ]
        if explicit_tools:
            direct = _execute_explicit_tool_requests(
                explicit_tools,
                prepared_user_text,
                current_doc_ids,
            )
            if direct is not None:
                direct.text = _strip_pseudo_tool_syntax(direct.text)
                if not direct.text.strip():
                    direct.text = "⚠️ Hệ thống nhận phản hồi không hợp lệ. Vui lòng thử lại."
                return direct

        # 4. Build system prompt with dynamic tool guidance
        system_prompt = _build_system_prompt(available_tool_names, current_doc_ids)

        # 5. Build messages (history does NOT include current user msg)
        messages = self._build_messages(history, prepared_user_text, system_prompt)

        logger.info(
            "generate_response: doc_ids=%s, tools=%s, msg_count=%d",
            current_doc_ids, available_tool_names, len(messages),
        )

        # 6. Run FC loop
        try:
            response = self._generate_with_fc(
                messages, available_tools, current_doc_ids,
            )
            response.text = _strip_pseudo_tool_syntax(response.text)
            if not response.text.strip():
                response.text = "⚠️ Hệ thống nhận phản hồi không hợp lệ. Vui lòng thử lại."
            return response
        except Exception as exc:
            logger.exception("Unhandled error in generate_response: %s", exc)
            return FunctionCallingResponse(
                text="⚠️ Đã xảy ra lỗi hệ thống. Vui lòng thử lại sau.",
                message_type="TEXT",
            )

    # ------------------------------------------------------------------
    # Title generation
    # ------------------------------------------------------------------

    def generate_chat_title(self, user_message: str) -> str:
        """Generate a concise chat title from the user's first message."""
        if not self.enabled:
            return _DEFAULT_CHAT_TITLE
        try:
            source = user_message[:_MAX_TITLE_SOURCE_CHARS]
            response = self._call_chat_completions(
                model=settings.groq_model,
                messages=[
                    {"role": "system", "content": _TITLE_GENERATOR_SYSTEM_INSTRUCTION},
                    {"role": "user", "content": f"Generate a title for: {source}"},
                ],
            )
            raw_title = (response.choices[0].message.content or "").strip()
            cleaned = _sanitize_generated_title(raw_title)
            return cleaned[:80] if cleaned else _DEFAULT_CHAT_TITLE
        except Exception:
            logger.exception("generate_chat_title failed.")
            return _DEFAULT_CHAT_TITLE

    # ------------------------------------------------------------------
    # Simple generation (no tools)
    # ------------------------------------------------------------------

    def generate_simple(
        self, prompt: str, system_instruction: str | None = None,
    ) -> str | None:
        """Plain text generation WITHOUT function calling."""
        if not self.enabled:
            return None
        try:
            msgs: list[dict[str, str]] = []
            if system_instruction:
                msgs.append({"role": "system", "content": system_instruction})
            msgs.append({"role": "user", "content": prompt})
            response = self._call_chat_completions(
                model=settings.groq_model,
                messages=msgs,
            )
            text = (response.choices[0].message.content or "").strip()
            return text or None
        except Exception:
            logger.exception("Groq generate (simple) failed.")
            return None

    def summarize_text(self, text: str, max_words: int = 180) -> str:
        prompt = (
            "Summarize the following academic document in Vietnamese with an "
            "academic style. Limit to around "
            f"{max_words} words and include core contributions, methods, and "
            f"limitations.\n\n{text}"
        )
        if not self.enabled:
            clipped = " ".join(text.split()[:max_words])
            return f"Tóm tắt (fallback khi Groq chưa cấu hình): {clipped}"

        result = self.generate_simple(prompt, SYSTEM_PROMPT_BASE)
        if result:
            return result

        clipped = " ".join(text.split()[:max_words])
        return f"Tóm tắt (fallback do Groq lỗi): {clipped}"


# Module-level singleton
gemini_service = GroqLLMService()
