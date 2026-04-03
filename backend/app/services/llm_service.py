"""
Groq LLM Service — with **Function Calling** (Tool Use) for academic tool
integration.

Uses the ``groq`` SDK with LLaMA 3.1 models that natively support
tool / function-calling via the OpenAI-compatible chat completions API.

Function Calling Architecture
-----------------------------
User Prompt → Groq (LLaMA 3.1) → [tool_calls] → Python Tool Execution
→ [tool message] → Groq → Final Answer (grounded in real data)
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)

_MAX_HISTORY_MESSAGES = 4
_MAX_HISTORY_MESSAGE_CHARS = 2000
_MAX_ROUTER_INPUT_CHARS = 10000
_MAX_TITLE_SOURCE_CHARS = 2000
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

# ---------- groq SDK import ----------------------------------------------
try:
    from groq import Groq
    import groq as groq_module  # for exception classes
except ImportError:
    Groq = None  # type: ignore[assignment,misc]
    groq_module = None  # type: ignore[assignment]

# ---------- tool singletons (lazy — already init'd at module level) ------
from app.services.tools.retraction_scan import retraction_scanner
from app.services.tools.citation_checker import citation_checker
from app.services.tools.journal_finder import journal_finder
from app.services.tools.ai_writing_detector import ai_writing_detector
from app.services.tools.grammar_checker import grammar_checker

# # =========================================================================
# # Vietnamese System Prompt — anti-hallucination + tool-use enforcement
# # =========================================================================
# SYSTEM_PROMPT = (
#     "Bạn là AIRA — trợ lý nghiên cứu học thuật chuyên nghiệp.\n\n"
#     "### QUY TẮC BẮT BUỘC:\n"
#     "1. **KHÔNG BAO GIỜ bịa dữ liệu học thuật** — không tự tạo DOI, trích dẫn, "
#     "tên tạp chí, tình trạng rút bài, hay số liệu PubPeer.\n"
#     "2. **LUÔN gọi công cụ (function call)** khi người dùng hỏi về:\n"
#     "   - Kiểm tra rút bài / retraction / PubPeer → dùng `scan_retraction_and_pubpeer`\n"
#     "   - Xác minh trích dẫn / citation → dùng `verify_citation`\n"
#     "   - Tìm tạp chí phù hợp / journal matching → dùng `match_journal`\n"
#     "   - Phát hiện AI viết / AI writing detection → dùng `detect_ai_writing`\n"
#     "3. Khi không có công cụ phù hợp, trả lời dựa trên kiến thức chung nhưng "
#     "PHẢI ghi rõ: «Thông tin này dựa trên kiến thức chung, chưa được xác minh bằng công cụ.»\n"
#     "4. Kết quả từ công cụ là DỮ LIỆU THỰC — trình bày chính xác, không thêm bớt.\n"
#     "5. Trả lời bằng tiếng Việt trừ khi người dùng viết bằng tiếng Anh. "
#     "Thuật ngữ chuyên ngành giữ nguyên tiếng Anh.\n"
#     "6. Trả lời ngắn gọn, chính xác, mang tính học thuật.\n\n"
#     "### QUY TẮC XỬ LÝ FILE ĐÍNH KÈM (ATTACHED DOCUMENTS):\n"
#     "Nếu trong ngữ cảnh chat có nội dung nằm trong thẻ <Attached_Document>, "
#     "bạn TUYỆT ĐỐI KHÔNG ĐƯỢC yêu cầu người dùng cung cấp mã DOI hay "
#     "copy/paste danh sách tài liệu tham khảo. Thay vào đó, bạn PHẢI TỰ ĐỘNG:\n"
#     "1. Đọc toàn bộ nội dung file đính kèm.\n"
#     "2. Tự tìm mã DOI của bài báo (thường nằm ở trang đầu, header, hoặc "
#     "footer) và truyền thẳng vào công cụ `scan_retraction_and_pubpeer`.\n"
#     "3. Tự tìm phần \"References\" hoặc \"Tài liệu tham khảo\" trong file "
#     "và truyền toàn bộ nội dung đó vào công cụ `verify_citation`.\n"
#     "4. Nếu người dùng yêu cầu kiểm tra tạp chí, dùng phần Abstract trong "
#     "file để gọi `match_journal`.\n"
#     "5. Nếu người dùng yêu cầu kiểm tra AI, truyền nội dung bài báo vào "
#     "`detect_ai_writing`.\n"
#     "6. Chỉ yêu cầu người dùng cung cấp thông tin nếu file thực sự bị hỏng "
#     "hoặc hoàn toàn không chứa DOI/References.\n"
#     "7. Khi gọi công cụ, truyền trực tiếp text trích xuất — KHÔNG tóm tắt "
#     "hay rút gọn nội dung trước khi truyền vào tool.\n"
# )
SYSTEM_PROMPT = (
    "Bạn là AIRA — Trợ lý Nghiên cứu Học thuật AI chuyên nghiệp. Mục tiêu tối thượng của bạn là "
    "cung cấp thông tin học thuật an toàn, tuyệt đối chính xác và sử dụng công cụ hiệu quả.\n\n"

    "# 1. TÔN CHỈ CỐT LÕI (CORE MANDATES)\n"
    "- **Không Ảo Giác (Zero Hallucination):** KHÔNG BAO GIỜ tự bịa đặt dữ liệu học thuật (DOI, trích dẫn, "
    "tên tác giả, chỉ số IF, tình trạng rút bài, bình luận PubPeer). Bắt buộc phải dựa trên dữ liệu thực từ công cụ.\n"
    "- **Bắt buộc dùng Tool:** LUÔN gọi công cụ (function call) khi người dùng hỏi về tình trạng bài báo, "
    "xác minh trích dẫn, gợi ý tạp chí, hoặc phát hiện AI.\n"
    "- **Giới hạn phạm vi:** Nếu yêu cầu vượt quá khả năng của công cụ, hãy trả lời dựa trên kiến thức chung "
    "NHƯNG BẮT BUỘC phải kèm dòng cảnh báo: «⚠️ Thông tin này dựa trên kiến thức chung, chưa được xác minh bằng hệ thống.»\n"
    "- **Không tự ý che giấu:** Kết quả trả về từ công cụ phải được hiển thị chính xác, trung thực, không tự ý lọc bớt dữ liệu xấu (retracted).\n\n"

    "# 2. QUY TRÌNH XỬ LÝ FILE (DOCUMENT WORKFLOW)\n"
    "Khi có file đính kèm (nằm trong thẻ <Attached_Document>), bạn đóng vai trò là một Agent tự động. "
    "TUYỆT ĐỐI KHÔNG hỏi lại người dùng những thông tin đã có sẵn trong file. Tuân thủ luồng sau:\n"
    "  1. **Đọc & Quét:** Tự động đọc nội dung file để tìm mã DOI (thường ở header/footer trang 1) "
    "và phần danh sách 'References' / 'Tài liệu tham khảo'.\n"
    "  2. **Hành động (Action):**\n"
    "     - Rút bài/PubPeer → Truyền trực tiếp DOI tìm được vào `scan_retraction_and_pubpeer`.\n"
    "     - Xác minh trích dẫn → Truyền toàn bộ text phần References vào `verify_citation`.\n"
    "     - Tìm tạp chí → Truyền text phần Abstract vào `match_journal`.\n"
    "     - Kiểm tra AI viết → Truyền text nội dung vào `detect_ai_writing`.\n"
    "     - Kiểm tra ngữ pháp / chính tả / sửa lỗi văn bản → dùng `check_grammar`.\n"
    "  3. **Truyền dữ liệu thô:** Truyền nguyên văn text trích xuất vào tool, KHÔNG tóm tắt trước.\n"
    "  4. **Ngoại lệ:** Chỉ yêu cầu người dùng cung cấp thêm thông tin BẰNG LỜI nếu file hỏng hoặc hoàn toàn không có DOI/References.\n\n"

    "# 3. GIỌNG ĐIỆU VÀ PHONG CÁCH (TONE & STYLE)\n"
    "- **Trực tiếp & Ngắn gọn:** KHÔNG sử dụng các câu rào trước đón sau (Ví dụ: cấm dùng 'Vâng, tôi sẽ giúp bạn...', "
    "'Dưới đây là kết quả...'). Đi thẳng vào kết quả.\n"
    "- **Ngôn ngữ:** Trả lời bằng Tiếng Việt chuẩn mực, chuyên nghiệp (trừ khi user dùng Tiếng Anh). "
    "Giữ nguyên các thuật ngữ chuyên ngành (Abstract, DOI, Retraction, Citation).\n"
    "- **Xử lý lỗi:** Nếu công cụ trả về lỗi hoặc không tìm thấy, trả lời ngắn gọn: «Hệ thống không tìm thấy dữ liệu cho yêu cầu này.»\n\n"

    "# 4. VÍ DỤ MINH HỌA (EXAMPLES)\n"
    "<example>\n"
    "user: Check giúp tôi bài báo có DOI 10.1038/nature12345\n"
    "model: [Gọi tool: scan_retraction_and_pubpeer với args: {'text': '10.1038/nature12345'}]\n"
    "(Sau khi tool trả kết quả)\n"
    "model: ⚠️ Bài báo này đã bị rút bỏ (RETRACTED). Đồng thời phát hiện 3 bình luận cảnh báo trên PubPeer. Bạn không nên sử dụng bài báo này để trích dẫn.\n"
    "</example>\n\n"
    "<example>\n"
    "user: (Đính kèm file PDF) Tóm tắt và xem các trích dẫn ở cuối bài có chuẩn không?\n"
    "model: \n"
    "1. [Gọi tool: sinh ra câu tóm tắt nội dung file]\n"
    "2. [Tự động gọi tool: verify_citation với args: {'text': '<Toàn bộ text phần References từ file PDF>'}]\n"
    "(Sau khi tool trả kết quả)\n"
    "model: Bài báo nghiên cứu về thuật toán X. Về trích dẫn, hệ thống đã quét 25 tài liệu tham khảo: 23 tài liệu hợp lệ, 2 tài liệu không xác minh được nguồn gốc (có khả năng do AI ảo giác tạo ra).\n"
    "</example>\n"
)

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
    return str(obj)  # fallback — force to string


def _truncate_text(
    text: str,
    limit: int,
    suffix: str,
    *,
    log_label: str | None = None,
) -> str:
    """Trim oversized text inputs before they reach the Groq router/tool."""
    if len(text) <= limit:
        return text
    if log_label:
        logger.warning(
            "Truncating %s from %d to %d chars",
            log_label,
            len(text),
            limit,
        )
    return text[:limit] + suffix

# =========================================================================
# Tool wrapper functions (callable by Gemini via Function Calling)
# =========================================================================

def scan_retraction_and_pubpeer(text: str) -> dict:
    """Scan DOIs in the given text for retraction status, corrections,
    expressions of concern, and PubPeer community discussions.

    Use this tool when the user asks about:
    - Whether a paper has been retracted
    - PubPeer comments or discussions about a paper
    - The integrity status of a publication identified by DOI
    - Risk assessment of cited papers

    Args:
        text: Text containing one or more DOIs to scan
              (e.g. '10.1038/nature12373').

    Returns:
        A dict with 'results' (list of scan results per DOI) and 'summary'
        statistics.
    """
    try:
        results = retraction_scanner.scan(text)
        data = _make_serializable([asdict(r) for r in results])
        summary = _make_serializable(retraction_scanner.get_summary(results))
        return {"results": data, "summary": summary}
    except Exception as exc:
        logger.error("scan_retraction_and_pubpeer failed: %s", exc, exc_info=True)
        return {"error": str(exc), "results": []}


def verify_citation(text: str) -> dict:
    """Verify academic citations found in the given text against OpenAlex
    and Crossref databases.

    Use this tool when the user asks about:
    - Whether citations/references in a paper are real or fabricated
    - Verification of specific DOIs, author-year references, or APA citations
    - Citation integrity checking

    Args:
        text: Text containing citations to verify.  Supports DOI format
              (e.g. '10.1038/nature12373'), APA format, and author-year
              format.

    Returns:
        A dict with 'results' (verification per citation) and 'statistics'.
    """
    try:
        results = citation_checker.verify(text)
        data = _make_serializable([asdict(r) for r in results])
        stats = _make_serializable(citation_checker.get_statistics(results))
        return {"results": data, "statistics": stats}
    except Exception as exc:
        logger.error("verify_citation failed: %s", exc, exc_info=True)
        return {"error": str(exc), "results": []}


def match_journal(abstract: str, title: str = "") -> dict:
    """Find suitable academic journals for a manuscript based on its abstract
    and optional title using SPECTER2 semantic matching.

    Use this tool when the user asks about:
    - Which journal to submit their paper to
    - Journal recommendations for a research topic
    - Finding journals that match their abstract/paper

    Args:
        abstract: The abstract or main text describing the research topic.
        title:    Optional paper title for improved matching accuracy.

    Returns:
        A dict with 'journals' (ranked list) and matching details.
    """
    try:
        journals = journal_finder.recommend(
            abstract=abstract,
            title=title or None,
            top_k=5,
        )
        return {"journals": _make_serializable(journals), "total": len(journals)}
    except Exception as exc:
        logger.error("match_journal failed: %s", exc, exc_info=True)
        return {"error": str(exc), "journals": []}


def detect_ai_writing(text: str) -> dict:
    """Analyse text to detect whether it was written by AI or a human,
    using a RoBERTa ensemble model and rule-based heuristics.

    Use this tool when the user asks about:
    - Whether a text/paper was written by AI
    - AI writing detection or analysis
    - Academic integrity checking for AI-generated content

    Args:
        text: The text to analyse for AI writing indicators
              (minimum 50 characters).

    Returns:
        A dict with detection score, verdict, confidence, and analysis
        details.
    """
    try:
        safe_text = _truncate_text(
            text,
            _MAX_ROUTER_INPUT_CHARS,
            _TRUNCATED_INPUT_SUFFIX,
            log_label="detect_ai_writing input",
        )
        result = ai_writing_detector.analyze(safe_text)
        return _make_serializable(asdict(result))
    except Exception as exc:
        logger.error("detect_ai_writing failed: %s", exc, exc_info=True)
        return {"error": str(exc), "score": 0.5, "verdict": "ERROR"}


def check_grammar(text: str) -> dict:
    """Check text for grammar and spelling errors using LanguageTool.

    Use this tool when the user asks about:
    - Grammar checking or proofreading
    - Spelling mistakes or typos
    - Text correction or editing suggestions
    - Improving writing quality

    Args:
        text: The text to check for grammar and spelling errors
              (any length).

    Returns:
        A dict with total_errors count, a list of issues (each with
        rule_id, message, offset, length, replacements), and the
        corrected_text.
    """
    try:
        return _make_serializable(grammar_checker.check_grammar(text))
    except Exception as exc:
        logger.error("check_grammar failed: %s", exc, exc_info=True)
        return {"error": str(exc), "total_errors": -1, "issues": [], "corrected_text": text}


# ---- registries ---------------------------------------------------------

_TOOL_FUNCTIONS: dict[str, Any] = {
    "scan_retraction_and_pubpeer": scan_retraction_and_pubpeer,
    "verify_citation": verify_citation,
    "match_journal": match_journal,
    "detect_ai_writing": detect_ai_writing,
    "check_grammar": check_grammar,
}

_TOOL_CALLABLES: list = [
    scan_retraction_and_pubpeer,
    verify_citation,
    match_journal,
    detect_ai_writing,
    check_grammar,
]

_TOOL_MESSAGE_TYPE: dict[str, MessageType] = {
    "scan_retraction_and_pubpeer": MessageType.RETRACTION_REPORT,
    "verify_citation": MessageType.CITATION_REPORT,
    "match_journal": MessageType.JOURNAL_LIST,
    "detect_ai_writing": MessageType.AI_WRITING_DETECTION,
    "check_grammar": MessageType.GRAMMAR_REPORT,
}

# Map tool name → key used inside tool_results["data"]
_TOOL_DATA_KEY: dict[str, str] = {
    "scan_retraction_and_pubpeer": "results",
    "verify_citation": "results",
    "match_journal": "journals",
    "detect_ai_writing": "",  # entire dict *is* the data
    "check_grammar": "",  # entire dict *is* the data
}

# ---- Groq / OpenAI-compatible tool schemas ------------------------------

_GROQ_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "scan_retraction_and_pubpeer",
            "description": (
                "Scan DOIs in the given text for retraction status, corrections, "
                "expressions of concern, and PubPeer community discussions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text containing one or more DOIs to scan.",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_citation",
            "description": (
                "Verify academic citations found in the given text against "
                "OpenAlex and Crossref databases."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text containing citations to verify (DOI, APA, author-year).",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_journal",
            "description": (
                "Find suitable academic journals for a manuscript based on its "
                "abstract and optional title using SPECTER2 semantic matching."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "abstract": {
                        "type": "string",
                        "description": "The abstract or main text describing the research topic.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional paper title for improved matching accuracy.",
                    },
                },
                "required": ["abstract"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_ai_writing",
            "description": (
                "Analyse text to detect whether it was written by AI or a human, "
                "using a RoBERTa ensemble model and rule-based heuristics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to analyse for AI writing indicators (min 50 chars).",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_grammar",
            "description": (
                "Check text for grammar and spelling errors using LanguageTool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to check for grammar and spelling errors.",
                    },
                },
                "required": ["text"],
            },
        },
    },
]

_MAX_FC_ITERATIONS = 5

# =========================================================================
# Response dataclass
# =========================================================================

@dataclass
class FunctionCallingResponse:
    """Result of a Gemini call that may have used function calling."""

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # If a tool was invoked, these let chat_service store rich data:
    message_type: str = "text"
    tool_results: dict[str, Any] | None = None


# =========================================================================
# GroqLLMService
# =========================================================================

class GroqLLMService:
    """Wrapper around Groq (LLaMA 3.1) with Function Calling (Tool Use)."""

    def __init__(self) -> None:
        self._client = None
        if not settings.groq_api_key:
            logger.warning("GROQ_API_KEY not set — Groq LLM disabled.")
            return
        if Groq is None:
            logger.warning("groq package not installed — Groq LLM disabled.")
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
        """Call ``chat.completions.create`` with tenacity retry on
        transient Groq errors (503, 429 rate-limit, etc.).

        Retries up to 3 times with exponential back-off (4 s → 10 s).
        """
        retry_types: tuple = (Exception,)  # fallback if SDK missing
        if groq_module is not None:
            retry_types = (
                groq_module.APIStatusError,
                groq_module.APIConnectionError,
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
    # Heuristic fallback helper
    # ------------------------------------------------------------------

    @staticmethod
    def _try_heuristic_fallback(messages: list[dict[str, Any]]) -> FunctionCallingResponse | None:
        """Extract user text + file context from the Groq ``messages``
        list and attempt a heuristic tool execution.

        Returns a ``FunctionCallingResponse`` if a tool was successfully
        executed, or ``None`` if no intent was detected.

        This method is wrapped in a top-level ``try/except`` so it can
        **never** propagate an exception — the worst-case return is
        ``None``, which lets the caller show the static error message.
        """
        try:
            # 1. Safely import the router
            try:
                from app.services.heuristic_router import fallback_process_request
            except ModuleNotFoundError:
                from app.services.tools.heuristic_router import fallback_process_request  # type: ignore[no-redef]

            # 2. Extract the last user message and any <Attached_Document>
            user_text = ""
            file_context: str | None = None
            for msg in reversed(messages):
                if msg.get("role") != "user":
                    continue
                content = msg.get("content", "")
                if not content:
                    continue
                if "<Attached_Document>" in content:
                    file_context = content
                elif not user_text:
                    user_text = content
                if user_text or file_context:
                    break

            if not user_text and not file_context:
                logger.warning("Heuristic fallback: no user_text or file_context found in messages.")
                return None

            logger.info(
                "Heuristic fallback triggered. user_text=%d chars, file_context=%s",
                len(user_text),
                f"{len(file_context)} chars" if file_context else "None",
            )

            # 3. Execute the heuristic router
            result = fallback_process_request(user_text, file_context)
            if result is None:
                logger.warning("Heuristic fallback returned None (no intent matched).")
                return None

            logger.info("Heuristic fallback succeeded (type=%s).", result["message_type"])
            return FunctionCallingResponse(
                text=result["text"],
                tool_calls=result.get("tool_calls", []),
                message_type=result["message_type"],
                tool_results=result.get("tool_results"),
            )
        except Exception as exc:
            logger.exception("CRITICAL: _try_heuristic_fallback crashed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Build multi-turn messages
    # ------------------------------------------------------------------

    @staticmethod
    def _build_messages(
        history: Sequence[ChatMessage], user_text: str,
    ) -> list[dict[str, str]]:
        """Convert DB message history + new user text into Groq/OpenAI
        messages array for multi-turn conversation."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

        recent_history = (
            history[-_MAX_HISTORY_MESSAGES:]
            if len(history) > _MAX_HISTORY_MESSAGES
            else history
        )

        for msg in recent_history:
            role = "user" if msg.role.value == "user" else "assistant"
            text = (msg.content or "").strip()
            text = _truncate_text(
                text,
                _MAX_HISTORY_MESSAGE_CHARS,
                _TRUNCATED_HISTORY_SUFFIX,
                log_label="history message",
            )
            if text:
                messages.append({"role": role, "content": text})

        safe_user_text = _truncate_text(
            user_text,
            _MAX_ROUTER_INPUT_CHARS,
            _TRUNCATED_INPUT_SUFFIX,
            log_label="user_text",
        )
        messages.append({"role": "user", "content": safe_user_text})
        return messages

    # ------------------------------------------------------------------
    # Execute a single tool call
    # ------------------------------------------------------------------

    @staticmethod
    def _execute_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a single function call requested by the LLM."""
        fn = _TOOL_FUNCTIONS.get(name)
        if fn is None:
            logger.warning("LLM requested unknown function: %s", name)
            return {"error": f"Unknown function: {name}"}
        logger.info("Executing tool: %s(%s)", name, list(args.keys()))
        try:
            return fn(**args)
        except Exception as exc:
            logger.error("Tool %s execution failed: %s", name, exc, exc_info=True)
            return {"error": f"Tool execution failed: {exc}"}

    # ------------------------------------------------------------------
    # Function Calling loop
    # ------------------------------------------------------------------

    def _generate_with_fc(
        self,
        messages: list[dict[str, Any]],
    ) -> FunctionCallingResponse:
        """Run the function-calling loop until the LLM returns a final
        text response (or the iteration budget is exhausted)."""

        all_tool_calls: list[dict[str, Any]] = []

        # Build the set of SDK exception types for explicit catching
        _sdk_errors: tuple = ()
        if groq_module is not None:
            _sdk_errors = (
                groq_module.APIStatusError,
                groq_module.APIConnectionError,
            )

        for iteration in range(_MAX_FC_ITERATIONS):
            try:
                response = self._call_chat_completions(
                    model=settings.groq_model,
                    messages=messages,
                    tools=_GROQ_TOOLS,
                    tool_choice="auto",
                )
            except (*_sdk_errors, RetryError) as exc:
                logger.error(
                    "Groq API error after retries (iter %d): %s",
                    iteration, exc, exc_info=True,
                )
                # ── Heuristic Fallback ──────────────────────────────
                fallback = self._try_heuristic_fallback(messages)
                if fallback is not None:
                    return fallback
                # ── Static error (no intent detected) ──────────────
                return FunctionCallingResponse(
                    text=(
                        "⚠️ Hệ thống AI hiện đang quá tải. "
                        "Vui lòng đợi vài phút và thử lại."
                    ),
                    message_type="TEXT",
                    tool_results=None,
                )
            except Exception as exc:
                logger.exception(
                    "Unexpected error calling Groq (iter %d): %s",
                    iteration, exc,
                )
                # ── Heuristic Fallback ──────────────────────────────
                fallback = self._try_heuristic_fallback(messages)
                if fallback is not None:
                    return fallback
                # ── Static error ───────────────────────────────────
                return FunctionCallingResponse(
                    text=(
                        "⚠️ Đã xảy ra lỗi không xác định khi kết nối "
                        "với AI. Vui lòng thử lại sau."
                    ),
                    message_type="TEXT",
                    tool_results=None,
                )

            if not response.choices:
                return FunctionCallingResponse(text="LLM không trả về kết quả.")

            choice = response.choices[0]
            assistant_message = choice.message

            # Check if the model wants to call tools
            tool_calls_in_response = assistant_message.tool_calls

            if not tool_calls_in_response:
                # ---- Final text response ----
                final_text = (assistant_message.content or "").strip()

                msg_type = "text"
                tool_results_payload: dict[str, Any] | None = None

                if all_tool_calls:
                    primary = all_tool_calls[0]
                    mt = _TOOL_MESSAGE_TYPE.get(primary["name"])
                    if mt is not None:
                        msg_type = mt.value
                        data_key = _TOOL_DATA_KEY.get(primary["name"], "")
                        raw = primary["result"]
                        tool_results_payload = {
                            "type": msg_type,
                            "data": raw.get(data_key, raw) if data_key else raw,
                        }

                return FunctionCallingResponse(
                    text=final_text or "Không có phản hồi từ LLM.",
                    tool_calls=all_tool_calls,
                    message_type=msg_type,
                    tool_results=tool_results_payload,
                )

            # ---- Execute tool calls ----
            # Append the assistant message (with tool_calls) to conversation
            messages.append({
                "role": "assistant",
                "content": assistant_message.content or "",
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
            })

            for tc in tool_calls_in_response:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    fn_args = {}

                result = self._execute_tool_call(fn_name, fn_args)
                all_tool_calls.append({
                    "name": fn_name,
                    "args": fn_args,
                    "result": result,
                })

                # Send function result back to the model
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

            logger.info(
                "FC iteration %d: executed %d tool(s) [%s]",
                iteration + 1,
                len(tool_calls_in_response),
                ", ".join(tc.function.name for tc in tool_calls_in_response),
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
        """Generate a response with **Function Calling** support.

        Returns a ``FunctionCallingResponse`` which carries:
        - ``text``: the final synthesised answer,
        - ``tool_calls``: list of executed tool invocations,
        - ``message_type`` / ``tool_results``: structured data for the
          frontend to render rich tool-result components.
        """
        if not self.enabled:
            return FunctionCallingResponse(
                text=(
                    "Groq LLM chưa được cấu hình. Hãy đặt GROQ_API_KEY "
                    "để kích hoạt AI. Tin nhắn của bạn đã được lưu."
                ),
            )

        messages = self._build_messages(history, user_text)
        try:
            return self._generate_with_fc(messages)
        except Exception as exc:
            logger.exception("Unhandled error in generate_response: %s", exc)
            return FunctionCallingResponse(
                text=(
                    "⚠️ Đã xảy ra lỗi hệ thống. "
                    "Vui lòng thử lại sau."
                ),
                message_type="TEXT",
                tool_results=None,
            )

    # ------------------------------------------------------------------
    # Simple generation (no tools — for summarization, etc.)
    # ------------------------------------------------------------------

    def generate_simple(
        self, prompt: str, system_instruction: str | None = None,
    ) -> str | None:
        """Plain text generation WITHOUT function calling."""
        if not self.enabled:
            return None
        try:
            messages: list[dict[str, str]] = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": prompt})
            result = self._call_chat_completions(
                model=settings.groq_model,
                messages=messages,
            )
            text = (result.choices[0].message.content or "").strip() if result.choices else ""
            return text or None
        except (RetryError, Exception):
            logger.exception("Groq generate (simple) failed after retries.")
            return None

    def generate_chat_title(self, user_text: str) -> str:
        """Generate a concise session title from the first user prompt."""
        prompt = _truncate_text(
            user_text.strip(),
            _MAX_TITLE_SOURCE_CHARS,
            "",
            log_label="chat title source",
        )
        if not prompt:
            return _DEFAULT_CHAT_TITLE

        result = self.generate_simple(
            prompt,
            _TITLE_GENERATOR_SYSTEM_INSTRUCTION,
        )
        if not result:
            return _DEFAULT_CHAT_TITLE

        cleaned = " ".join(result.replace("\n", " ").split()).strip(" \"'`")
        if not cleaned:
            return _DEFAULT_CHAT_TITLE

        return " ".join(cleaned.split()[:5])[:255] or _DEFAULT_CHAT_TITLE

    def summarize_text(self, text: str, max_words: int = 180) -> str:
        prompt = (
            "Summarize the following academic document in Vietnamese with an "
            "academic style. Limit to around "
            f"{max_words} words and include core contributions, methods, and "
            f"limitations.\n\n{text}"
        )
        if not self.enabled:
            clipped = " ".join(text.split()[:max_words])
            return f"Tóm tắt (fallback khi LLM chưa cấu hình): {clipped}"

        result = self.generate_simple(prompt, SYSTEM_PROMPT)
        if result:
            return result

        clipped = " ".join(text.split()[:max_words])
        return f"Tóm tắt (fallback do LLM lỗi): {clipped}"


# ---- Module-level singleton + backward-compatible aliases ---------------
groq_llm_service = GroqLLMService()

# Backward compatibility — existing code imports these names
GeminiService = GroqLLMService
gemini_service = groq_llm_service
