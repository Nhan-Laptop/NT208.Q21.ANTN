from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.chat import create_completion
from app.models.chat_session import SessionMode
from app.schemas.chat import ChatCompletionRequest
from app.services import llm_service
from app.services import heuristic_router
from app.services.academic_query_service import academic_query_service
from app.services.academic_verification_formatter import format_citation_summary
from app.services.tools.citation_checker import CitationChecker, CitationCheckResult

try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


ACADEMIC_DB_QUERY = "Hãy cho tôi biết các bài trong cơ sở dữ liệu này về M-theory holographic duality."


class ChatAcademicDatabaseRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user, mode=SessionMode.GENERAL_QA)

    def tearDown(self) -> None:
        self.env.close()

    def test_general_academic_database_query_returns_grounded_no_data_without_llm(self) -> None:
        with self.env.session() as db:
            with patch.object(llm_service.gemini_service, "generate_response", side_effect=AssertionError("LLM should not route no-data academic query")):
                response = create_completion(
                    payload=ChatCompletionRequest(session_id=self.session.id, user_message=ACADEMIC_DB_QUERY),
                    db=db,
                    current_user=self.user,
                )

        assistant = response.assistant_message
        self.assertEqual(assistant.message_type, "text")
        self.assertIsNotNone(assistant.tool_results)
        self.assertEqual(assistant.tool_results.get("type"), "academic_lookup")
        self.assertEqual(assistant.tool_results.get("status"), "no_data")
        self.assertIn("chưa tìm thấy bài hoặc bản ghi học thuật liên quan", assistant.content or "")
        self.assertNotIn("crawler.db", assistant.content or "")
        self.assertNotIn("citation_report", str(assistant.tool_results))
        self.assertNotIn("Kết quả tìm kiếm", assistant.content or "")
        self.assertNotIn("Maldacena", assistant.content or "")

    def test_academic_database_query_does_not_route_to_citation_verification(self) -> None:
        self.assertTrue(academic_query_service.should_handle(ACADEMIC_DB_QUERY))
        self.assertEqual(llm_service._detect_explicit_tool_requests(ACADEMIC_DB_QUERY), [])

    def test_citation_like_input_still_routes_to_citation_verification(self) -> None:
        citation_query = "Hãy xác minh trích dẫn Smith, J. A. (2023). Retrieval augmented search."

        self.assertFalse(academic_query_service.should_handle(citation_query))
        self.assertEqual(llm_service._detect_explicit_tool_requests(citation_query), ["verify_citation"])

        doi_query = "Please verify DOI 10.1111/gcb.17128"
        self.assertFalse(academic_query_service.should_handle(doi_query))
        self.assertEqual(llm_service._detect_explicit_tool_requests(doi_query), ["verify_citation"])

        doi_only = "https://doi.org/10.1111/GCB.17128"
        self.assertEqual(llm_service._detect_explicit_tool_requests(doi_only), ["verify_citation"])

    def test_heuristic_router_treats_doi_only_as_exact_verification_not_retraction(self) -> None:
        with patch.object(heuristic_router._semantic_router, "classify", return_value=(None, 0.0)):
            intent = heuristic_router._detect_intent("https://doi.org/10.1111/GCB.17128", has_doi=True)

        self.assertEqual(intent, heuristic_router._Intent.CITATION)

    def test_partial_citation_summary_is_not_database_finding_wording(self) -> None:
        checker = CitationChecker()
        partial = [
            CitationCheckResult(
                citation="Smith (2023)",
                status="PARTIAL_MATCH",
                evidence="Possible match: nearby record",
                doi="10.5555/nearby",
                title="Nearby Record",
                confidence=0.5,
            )
        ]
        text = format_citation_summary(checker.get_statistics(partial))

        self.assertIn("chỉ khớp một phần", text)
        self.assertNotIn("cơ sở dữ liệu", text.lower())
        self.assertNotIn("crawler.db", text.lower())
        self.assertNotIn("tìm thấy bài", text.lower())

    # ── DOI detection tests ───────────────────────────────────────────

    def test_bare_doi_routes_to_citation_verification(self) -> None:
        """Bare DOI without keywords routes to verify_citation."""
        result = llm_service._detect_explicit_tool_requests("10.1111/gcb.17128")
        self.assertEqual(result, ["verify_citation"])

    def test_doi_url_routes_to_citation_verification(self) -> None:
        """DOI URL without keywords routes to verify_citation."""
        result = llm_service._detect_explicit_tool_requests("https://doi.org/10.1111/gcb.17128")
        self.assertEqual(result, ["verify_citation"])

    def test_doi_prefix_routes_to_citation_verification(self) -> None:
        """doi: prefix routes to verify_citation."""
        result = llm_service._detect_explicit_tool_requests("doi:10.1111/gcb.17128")
        self.assertEqual(result, ["verify_citation"])

    def test_doi_with_retraction_keyword_routes_to_retraction(self) -> None:
        """DOI + 'retracted' keyword routes to scan_retraction_and_pubpeer."""
        result = llm_service._detect_explicit_tool_requests("DOI 10.1111/gcb.17128 bị rút bài")
        self.assertEqual(result, ["scan_retraction_and_pubpeer"])

    def test_general_discussion_without_doi_not_routed_to_tools(self) -> None:
        """General discussion questions without DOI are NOT routed to tools."""
        result = llm_service._detect_explicit_tool_requests("AI có phải là hướng nghiên cứu tiềm năng ko")
        self.assertEqual(result, [])

    def test_heuristic_router_bare_doi_returns_citation(self) -> None:
        with patch.object(heuristic_router._semantic_router, "classify", return_value=(None, 0.0)):
            intent = heuristic_router._detect_intent("10.1111/gcb.17128", has_doi=True)
        self.assertEqual(intent, heuristic_router._Intent.CITATION)

    def test_heuristic_router_doi_with_retraction_returns_retraction(self) -> None:
        with patch.object(heuristic_router._semantic_router, "classify", return_value=(None, 0.0)):
            intent = heuristic_router._detect_intent("DOI 10.1111/gcb.17128 có bị retract không?", has_doi=True)
        self.assertEqual(intent, heuristic_router._Intent.RETRACTION)

    def test_no_data_vietnamese_wording_is_user_safe_and_grounded(self) -> None:
        with self.env.session() as db:
            result = academic_query_service.answer(db, ACADEMIC_DB_QUERY)

        self.assertEqual(result.records, [])
        self.assertIn("Mình chưa tìm thấy bài hoặc bản ghi học thuật liên quan", result.text)
        self.assertNotIn("crawler.db", result.text)
        self.assertIn("Từ khóa đã kiểm tra", result.text)
        self.assertNotIn("Invalid_document_id", result.text)
        self.assertNotIn("tool unavailable", result.text.lower())


if __name__ == "__main__":
    unittest.main()
