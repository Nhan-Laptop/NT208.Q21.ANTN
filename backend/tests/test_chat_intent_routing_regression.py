from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.chat import create_completion
from app.schemas.chat import ChatCompletionRequest
from app.models.chat_session import SessionMode

try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


class ChatIntentRoutingRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user, mode=SessionMode.GENERAL_QA)

    def tearDown(self) -> None:
        self.env.close()

    def test_journal_match_with_doi_routes_to_journal(self) -> None:
        with patch("app.services.chat_service.ChatService._run_journal_match_from_doi") as run_match:
            from app.models.chat_message import MessageType

            run_match.return_value = (
                MessageType.JOURNAL_LIST,
                "Stubbed journal match",
                {"type": "journal_list", "data": [], "status": "insufficient_corpus"},
            )
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Gợi ý tạp chí 10.1111/gcb.17128",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "journal_list")
        self.assertTrue(run_match.called)

    def test_citation_verification_requires_explicit_verification(self) -> None:
        with patch("app.services.chat_service.ChatService._run_mode_tool") as run_tool:
            from app.models.chat_message import MessageType

            run_tool.return_value = (
                MessageType.CITATION_REPORT,
                "Stubbed citation verification",
                {"type": "citation_report", "data": []},
            )
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Xác minh trích dẫn 10.1111/gcb.17128",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "citation_report")
        self.assertTrue(run_tool.called)

    def test_general_qa_verify_doi_with_metadata_request_routes_to_doi_metadata(self) -> None:
        metadata = {
            "doi": "10.1111/gcb.17128",
            "title": "Climate Signals in Ecosystem Records",
            "journal": "Global Change Biology",
            "publisher": "Wiley",
            "publication_year": 2025,
            "research_field": "Environmental Science",
            "main_topic": "Climate impacts on ecosystems",
            "verification_status": "Valid DOI",
            "confidence": 1.0,
            "source": "Crossref",
            "missing_fields": [],
            "notes": [],
        }
        with (
            patch("app.services.chat_service.ChatService._resolve_doi_metadata", return_value=(metadata, "verified")) as resolve,
            patch("app.services.tools.citation_checker.CitationChecker.verify", side_effect=AssertionError("citation verification should not run")),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=(
                            "Verify DOI 10.1111/gcb.17128 and provide title, journal, publisher, "
                            "publication year, research field, and main topic."
                        ),
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertIsInstance(response.assistant_message.tool_results, dict)
        self.assertEqual(response.assistant_message.tool_results["type"], "doi_metadata")
        self.assertEqual(response.assistant_message.tool_results["data"]["publisher"], "Wiley")
        self.assertTrue(resolve.called)

    def test_verification_mode_analyze_doi_routes_to_doi_metadata(self) -> None:
        verification_session = self.env.create_chat_session(user=self.user, mode=SessionMode.VERIFICATION)
        metadata = {
            "doi": "10.1038/s41586-020-2649-2",
            "title": "Array programming with NumPy",
            "journal": "Nature",
            "publisher": "Springer Nature",
            "publication_year": 2020,
            "research_field": None,
            "research_field_note": "Not directly available from Crossref/OpenAlex metadata.",
            "main_topic": "Array programming with NumPy",
            "main_topic_note": "Not directly available from Crossref/OpenAlex metadata. Inferred from the article title.",
            "verification_status": "Valid DOI",
            "confidence": 1.0,
            "source": "Crossref",
            "missing_fields": ["research_field"],
            "notes": [
                "Not directly available from Crossref/OpenAlex metadata.",
                "Not directly available from Crossref/OpenAlex metadata. Inferred from the article title.",
            ],
        }
        with (
            patch("app.services.chat_service.ChatService._resolve_doi_metadata", return_value=(metadata, "verified")) as resolve,
            patch("app.services.tools.citation_checker.CitationChecker.verify", side_effect=AssertionError("citation verification should not run")),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=verification_session.id,
                        user_message=(
                            "Analyze DOI 10.1038/s41586-020-2649-2. Provide title, journal, "
                            "publisher, publication year, research field, and main topic."
                        ),
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertIsInstance(response.assistant_message.tool_results, dict)
        self.assertEqual(response.assistant_message.tool_results["type"], "doi_metadata")
        self.assertEqual(response.assistant_message.tool_results["data"]["title"], "Array programming with NumPy")
        self.assertTrue(resolve.called)

    def test_bare_pmid_routes_to_citation_verification(self) -> None:
        with patch("app.services.chat_service.ChatService._run_mode_tool") as run_tool:
            from app.models.chat_message import MessageType

            run_tool.return_value = (
                MessageType.CITATION_REPORT,
                "Stubbed citation verification",
                {"type": "citation_report", "data": []},
            )
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="PMID: 12345678",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "citation_report")
        self.assertTrue(run_tool.called)


if __name__ == "__main__":
    unittest.main()
