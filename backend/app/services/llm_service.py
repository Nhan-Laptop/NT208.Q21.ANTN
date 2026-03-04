"""
Gemini LLM Service — with **Function Calling** for academic tool
integration.

Uses the ``google.genai`` SDK exclusively.  The deprecated
``google.generativeai`` package has been removed.

Function Calling Architecture
-----------------------------
User Prompt → Gemini → [Function Call] → Python Tool Execution
→ [Function Response] → Gemini → Final Answer (grounded in real data)
"""

from __future__ import annotations

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

# ---------- google-genai import ------------------------------------------
try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_errors = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

# ---------- tool singletons (lazy — already init'd at module level) ------
from app.services.tools.retraction_scan import retraction_scanner
from app.services.tools.citation_checker import citation_checker
from app.services.tools.journal_finder import journal_finder
from app.services.tools.ai_writing_detector import ai_writing_detector

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
        result = ai_writing_detector.analyze(text)
        return _make_serializable(asdict(result))
    except Exception as exc:
        logger.error("detect_ai_writing failed: %s", exc, exc_info=True)
        return {"error": str(exc), "score": 0.5, "verdict": "ERROR"}


# ---- registries ---------------------------------------------------------

_TOOL_FUNCTIONS: dict[str, Any] = {
    "scan_retraction_and_pubpeer": scan_retraction_and_pubpeer,
    "verify_citation": verify_citation,
    "match_journal": match_journal,
    "detect_ai_writing": detect_ai_writing,
}

_TOOL_CALLABLES: list = [
    scan_retraction_and_pubpeer,
    verify_citation,
    match_journal,
    detect_ai_writing,
]

_TOOL_MESSAGE_TYPE: dict[str, MessageType] = {
    "scan_retraction_and_pubpeer": MessageType.RETRACTION_REPORT,
    "verify_citation": MessageType.CITATION_REPORT,
    "match_journal": MessageType.JOURNAL_LIST,
    "detect_ai_writing": MessageType.AI_WRITING_DETECTION,
}

# Map tool name → key used inside tool_results["data"]
_TOOL_DATA_KEY: dict[str, str] = {
    "scan_retraction_and_pubpeer": "results",
    "verify_citation": "results",
    "match_journal": "journals",
    "detect_ai_writing": "",  # entire dict *is* the data
}

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
# GeminiService
# =========================================================================

class GeminiService:
    """Wrapper around Google Gemini with Function Calling support."""

    def __init__(self) -> None:
        self._client = None
        if not settings.google_api_key:
            logger.warning("GOOGLE_API_KEY not set — Gemini disabled.")
            return
        if genai is None:
            logger.warning("google-genai package not installed — Gemini disabled.")
            return
        try:
            self._client = genai.Client(api_key=settings.google_api_key)
            logger.info(
                "Gemini client initialised (model=%s) with Function Calling.",
                settings.gemini_model,
            )
        except Exception:
            logger.exception("Failed to create Gemini client.")
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------
    # Retryable Gemini API call
    # ------------------------------------------------------------------

    def _call_generate_content(self, **kwargs: Any) -> Any:
        """Call ``generate_content`` with tenacity retry on transient
        Gemini errors (503 UNAVAILABLE, 429 RESOURCE_EXHAUSTED, etc.).

        Retries up to 3 times with exponential back-off (4 s → 10 s).
        """
        # Build the retry-decorated closure at call-time so *self* is
        # captured properly and the decorator's exception filter uses
        # the (possibly-None) genai_errors reference.
        retry_types: tuple = (Exception,)  # fallback if SDK missing
        if genai_errors is not None:
            retry_types = (genai_errors.ServerError, genai_errors.APIError)

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=4, max=10),
            retry=retry_if_exception_type(retry_types),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )
        def _inner():
            return self._client.models.generate_content(**kwargs)  # type: ignore[union-attr]

        return _inner()

    # ------------------------------------------------------------------
    # Heuristic fallback helper
    # ------------------------------------------------------------------

    @staticmethod
    def _try_heuristic_fallback(contents: list) -> FunctionCallingResponse | None:
        """Extract user text + file context from the Gemini ``contents``
        list and attempt a heuristic tool execution.

        Returns a ``FunctionCallingResponse`` if a tool was successfully
        executed, or ``None`` if no intent was detected.

        This method is wrapped in a top-level ``try/except`` so it can
        **never** propagate an exception — the worst-case return is
        ``None``, which lets the caller show the static error message.
        """
        try:
            # 1. Safely import the router (handle both possible locations)
            try:
                from app.services.heuristic_router import fallback_process_request
            except ModuleNotFoundError:
                from app.services.tools.heuristic_router import fallback_process_request  # type: ignore[no-redef]

            # 2. Extract the last user message and any <Attached_Document>
            user_text = ""
            file_context: str | None = None
            for content_obj in reversed(contents):
                role = getattr(content_obj, "role", None)
                if role != "user":
                    continue
                parts = getattr(content_obj, "parts", [])
                for part in parts:
                    text = getattr(part, "text", "") or ""
                    if not text:
                        continue
                    if "<Attached_Document>" in text:
                        file_context = text
                    elif not user_text:
                        user_text = text
                if user_text or file_context:
                    break  # found the latest user turn

            if not user_text and not file_context:
                logger.warning("Heuristic fallback: no user_text or file_context found in contents.")
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
    # Build multi-turn contents
    # ------------------------------------------------------------------

    def _build_contents(
        self, history: Sequence[ChatMessage], user_text: str,
    ) -> list:
        """Convert DB message history + new user text into Gemini Content
        objects for multi-turn conversation."""
        if genai_types is None:
            return []
        contents: list = []
        for msg in history:
            role = "user" if msg.role.value == "user" else "model"
            text = (msg.content or "").strip()
            if text:
                contents.append(
                    genai_types.Content(role=role, parts=[genai_types.Part(text=text)])
                )
        contents.append(
            genai_types.Content(role="user", parts=[genai_types.Part(text=user_text)])
        )
        return contents

    # ------------------------------------------------------------------
    # Function Calling loop
    # ------------------------------------------------------------------

    def _execute_function_call(self, fc: Any) -> dict[str, Any]:
        """Execute a single function call requested by Gemini."""
        name: str = fc.name
        args: dict = dict(fc.args) if fc.args else {}
        fn = _TOOL_FUNCTIONS.get(name)
        if fn is None:
            logger.warning("Gemini requested unknown function: %s", name)
            return {"error": f"Unknown function: {name}"}
        logger.info("Executing tool: %s(%s)", name, list(args.keys()))
        try:
            return fn(**args)
        except Exception as exc:
            logger.error("Tool %s execution failed: %s", name, exc, exc_info=True)
            return {"error": f"Tool execution failed: {exc}"}

    def _generate_with_fc(
        self,
        contents: list,
        system_instruction: str,
    ) -> FunctionCallingResponse:
        """Run the function-calling loop until Gemini returns a final text
        response (or the iteration budget is exhausted)."""

        config = genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=_TOOL_CALLABLES,
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
        )

        all_tool_calls: list[dict[str, Any]] = []

        # Build the set of SDK exception types for explicit catching
        _sdk_errors: tuple = ()
        if genai_errors is not None:
            _sdk_errors = (genai_errors.ServerError, genai_errors.APIError)

        for iteration in range(_MAX_FC_ITERATIONS):
            try:
                response = self._call_generate_content(
                    model=settings.gemini_model,
                    contents=contents,
                    config=config,
                )
            except (*_sdk_errors, RetryError) as exc:
                # Tenacity RetryError (all retries exhausted) or SDK
                # error that bypassed the retry filter.
                logger.error(
                    "Gemini API error after retries (iter %d): %s",
                    iteration, exc, exc_info=True,
                )
                # ── Heuristic Fallback ──────────────────────────────
                fallback = self._try_heuristic_fallback(contents)
                if fallback is not None:
                    return fallback
                # ── Static error (no intent detected) ──────────────
                return FunctionCallingResponse(
                    text=(
                        "⚠️ Hệ thống AI hiện đang quá tải "
                        "(Lỗi 503/429 từ Google). "
                        "Vui lòng đợi vài phút và thử lại."
                    ),
                    message_type="TEXT",
                    tool_results=None,
                )
            except Exception as exc:
                # Any other unexpected error — NEVER propagate.
                logger.exception(
                    "Unexpected error calling Gemini (iter %d): %s",
                    iteration, exc,
                )
                # ── Heuristic Fallback ──────────────────────────────
                fallback = self._try_heuristic_fallback(contents)
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

            if not response.candidates:
                return FunctionCallingResponse(text="Gemini không trả về kết quả.")

            candidate = response.candidates[0]
            parts = candidate.content.parts if candidate.content else []

            # Separate function-call parts from text parts
            fc_parts = [p for p in parts if getattr(p, "function_call", None)]
            text_parts = [p.text for p in parts if getattr(p, "text", None)]

            if not fc_parts:
                # ---- Final text response ----
                final_text = "\n".join(text_parts).strip()

                msg_type = "text"
                tool_results_payload: dict[str, Any] | None = None

                if all_tool_calls:
                    # Use the first tool call to determine MessageType
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
                    text=final_text or "Không có phản hồi từ Gemini.",
                    tool_calls=all_tool_calls,
                    message_type=msg_type,
                    tool_results=tool_results_payload,
                )

            # ---- Execute function calls ----
            # Append model's response (containing function_call parts)
            contents.append(candidate.content)

            fn_response_parts: list = []
            for fc_part in fc_parts:
                fc = fc_part.function_call
                result = self._execute_function_call(fc)
                all_tool_calls.append({
                    "name": fc.name,
                    "args": dict(fc.args) if fc.args else {},
                    "result": result,
                })
                fn_response_parts.append(
                    genai_types.Part.from_function_response(
                        name=fc.name,
                        response=result,
                    )
                )

            # Send function responses back to Gemini
            contents.append(genai_types.Content(parts=fn_response_parts))

            logger.info(
                "FC iteration %d: executed %d tool(s) [%s]",
                iteration + 1,
                len(fc_parts),
                ", ".join(p.function_call.name for p in fc_parts),
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
                    "Gemini chưa được cấu hình. Hãy đặt GOOGLE_API_KEY "
                    "để kích hoạt AI. Tin nhắn của bạn đã được lưu."
                ),
            )

        contents = self._build_contents(history, user_text)
        try:
            return self._generate_with_fc(contents, SYSTEM_PROMPT)
        except Exception as exc:
            # Ultimate safety net — should never be reached, but
            # guarantees the backend NEVER crashes on a Gemini failure.
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
            config: dict = {}
            if system_instruction:
                config["system_instruction"] = system_instruction
            result = self._call_generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=config,
            )
            text = getattr(result, "text", "") or ""
            return text.strip() or None
        except (RetryError, Exception):
            logger.exception("Gemini generate_content (simple) failed after retries.")
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
            return f"Tóm tắt (fallback khi Gemini chưa cấu hình): {clipped}"

        result = self.generate_simple(prompt, SYSTEM_PROMPT)
        if result:
            return result

        clipped = " ".join(text.split()[:max_words])
        return f"Tóm tắt (fallback do Gemini lỗi): {clipped}"


gemini_service = GeminiService()
