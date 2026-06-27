from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.chat import create_completion
from app.models.chat_message import MessageType
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

    def test_general_qa_doi_author_query_uses_author_publication_lookup(self) -> None:
        with (
            patch(
                "app.services.chat_service.ChatService._run_author_publication_search",
                return_value=(
                    MessageType.TEXT,
                    "Stubbed author publication lookup",
                    {"type": "author_publication_search", "status": "matched", "authors": []},
                ),
            ) as run_author_lookup,
            patch(
                "app.services.chat_service.ChatService._run_mode_tool",
                side_effect=AssertionError("citation verification should not run"),
            ),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="tác giả của DOI 10.1038/s41586-020-2649-2 còn công bố bài nào khác không",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_author_lookup.called)
        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.tool_results["type"], "author_publication_search")

    def test_general_qa_named_author_query_uses_named_author_lookup(self) -> None:
        with (
            patch(
                "app.services.chat_service.ChatService._run_named_author_publication_search",
                return_value=(
                    MessageType.TEXT,
                    "Stubbed named author publication lookup",
                    {
                        "type": "author_publication_search",
                        "status": "matched",
                        "query": "publication khác của Stéfan J. van der Walt",
                        "author": {"name": "Stéfan J. van der Walt", "matched_from_context": False},
                        "authors": [],
                    },
                ),
            ) as run_author_lookup,
            patch(
                "app.services.chat_service.ChatService._run_mode_tool",
                side_effect=AssertionError("citation verification should not run"),
            ),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="publication khác của Stéfan J. van der Walt",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_author_lookup.called)
        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.tool_results["type"], "author_publication_search")
        self.assertEqual(response.assistant_message.tool_results["author"]["name"], "Stéfan J. van der Walt")

    def test_general_qa_doi_author_list_query_routes_to_doi_metadata(self) -> None:
        metadata = {
            "doi": "10.1038/s41586-020-2649-2",
            "title": "Array programming with NumPy",
            "authors": ["Stéfan J. van der Walt", "K. Jarrod Millman"],
            "journal": "Nature",
            "publisher": "Springer Nature",
            "publication_year": 2020,
            "research_field": "Computer Science",
            "main_topic": "Array programming with NumPy",
            "verification_status": "Valid DOI",
            "confidence": 1.0,
            "source": "Crossref",
            "missing_fields": [],
            "notes": [],
        }
        with (
            patch("app.services.chat_service.ChatService._resolve_doi_metadata", return_value=(metadata, "verified")) as resolve,
            patch(
                "app.services.chat_service.ChatService._run_mode_tool",
                side_effect=AssertionError("citation verification should not run"),
            ),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="các tác giả của DOI 10.1038/s41586-020-2649-2",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(resolve.called)
        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.tool_results["type"], "doi_metadata")
        self.assertEqual(response.assistant_message.tool_results["requested_field"], "authors")
        self.assertIn("Stéfan J. van der Walt", response.assistant_message.tool_results["data"]["authors"])
        self.assertIn("1. Stéfan J. van der Walt", response.assistant_message.content or "")

    def test_general_qa_compact_doi_prefix_author_query_routes_to_doi_metadata(self) -> None:
        metadata = {
            "doi": "10.1038/s41586-020-2649-2",
            "title": "Array programming with NumPy",
            "authors": ["Charles R. Harris", "K. Jarrod Millman"],
            "journal": "Nature",
            "publisher": "Springer Nature",
            "publication_year": 2020,
            "verification_status": "Valid DOI",
            "confidence": 1.0,
            "source": "Crossref",
            "missing_fields": [],
            "notes": [],
        }
        with (
            patch("app.services.chat_service.ChatService._resolve_doi_metadata", return_value=(metadata, "verified")) as resolve,
            patch(
                "app.services.chat_service.ChatService._run_mode_tool",
                side_effect=AssertionError("citation verification should not run"),
            ),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="các tác giả của DOI10.1038/s41586-020-2649-2",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(resolve.called)
        self.assertEqual(response.assistant_message.tool_results["type"], "doi_metadata")
        self.assertEqual(response.assistant_message.tool_results["requested_field"], "authors")
        self.assertIn("1. Charles R. Harris", response.assistant_message.content or "")

    def test_general_qa_single_journal_field_query_routes_to_doi_metadata(self) -> None:
        metadata = {
            "doi": "10.1038/s41586-020-2649-2",
            "title": "Array programming with NumPy",
            "authors": ["Charles R. Harris"],
            "journal": "Nature",
            "publisher": "Springer Nature",
            "publication_year": 2020,
            "verification_status": "Valid DOI",
            "confidence": 1.0,
            "source": "Crossref",
            "missing_fields": [],
            "notes": [],
        }
        with (
            patch("app.services.chat_service.ChatService._resolve_doi_metadata", return_value=(metadata, "verified")) as resolve,
            patch(
                "app.services.chat_service.ChatService._run_mode_tool",
                side_effect=AssertionError("citation verification should not run"),
            ),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="journal của 10.1038/s41586-020-2649-2 là gì?",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(resolve.called)
        self.assertEqual(response.assistant_message.tool_results["type"], "doi_metadata")
        self.assertEqual(response.assistant_message.tool_results["requested_field"], "journal")
        self.assertIn("Nature", response.assistant_message.content or "")

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

    def test_verification_mode_multi_citation_input_uses_shared_batch_pipeline(self) -> None:
        verification_session = self.env.create_chat_session(user=self.user, mode=SessionMode.VERIFICATION)
        report = {
            "type": "citation_report",
            "text": "1 verified, 1 review.",
            "summary": {
                "total_count": 2,
                "verified_count": 1,
                "review_count": 1,
                "problem_count": 0,
                "temporary_issue_count": 0,
                "status_counts": {"DOI_VERIFIED": 1, "LIKELY_MATCH": 1},
            },
            "results": [
                {"index": 1, "raw_citation": "10.1000/verified", "status": "DOI_VERIFIED"},
                {"index": 2, "raw_citation": "Review citation", "status": "LIKELY_MATCH"},
            ],
        }
        with patch(
            "app.services.chat_service.citation_batch_service.verify_text",
            return_value=report,
        ) as verify_text:
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=verification_session.id,
                        user_message="10.1000/verified\nReview citation",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "citation_report")
        self.assertIsInstance(response.assistant_message.tool_results, dict)
        self.assertEqual(response.assistant_message.tool_results["type"], "citation_report")
        self.assertEqual(response.assistant_message.tool_results["summary"]["total_count"], 2)
        verify_text.assert_called_once_with("10.1000/verified\nReview citation")


    def test_journal_match_vn_prompt_returns_text_with_journal_match_type(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_direct_journal_match") as run_direct,
            patch("app.services.chat_service.ChatService._run_journal_match_from_doi", side_effect=AssertionError("DOI path should not run")),
            patch("app.services.chat_service.ChatService._run_mode_tool", side_effect=AssertionError("tool path should not run")),
            patch("app.services.chat_service.citation_batch_service.verify_text", side_effect=AssertionError("citation verification should not run")),
        ):
            run_direct.return_value = (
                MessageType.TEXT,
                "Đã hoàn tất gợi ý tạp chí.",
                {"type": "journal_match", "matches": [{"journal": "Test Journal", "score": 0.85}], "status": "matched"},
            )
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=(
                            "gợi ý tạp chí cho: Abstract: This is a study about machine learning "
                            "for natural language processing. Keywords: NLP, deep learning"
                        ),
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertIsInstance(response.assistant_message.tool_results, dict)
        self.assertEqual(response.assistant_message.tool_results["type"], "journal_match")
        self.assertIn("matches", response.assistant_message.tool_results)
        self.assertTrue(run_direct.called)

    def test_journal_match_en_prompt_returns_text_with_journal_match_type(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_direct_journal_match") as run_direct,
            patch("app.services.chat_service.ChatService._run_journal_match_from_doi", side_effect=AssertionError("DOI path should not run")),
            patch("app.services.chat_service.ChatService._run_mode_tool", side_effect=AssertionError("tool path should not run")),
            patch("app.services.chat_service.citation_batch_service.verify_text", side_effect=AssertionError("citation verification should not run")),
        ):
            run_direct.return_value = (
                MessageType.TEXT,
                "Journal match completed.",
                {"type": "journal_match", "matches": [{"journal": "Test Journal", "score": 0.85}], "status": "matched"},
            )
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=(
                            "journal recommendation for: Abstract: This study explores "
                            "climate change impacts on coastal ecosystems. Keywords: climate, ecology"
                        ),
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertIsInstance(response.assistant_message.tool_results, dict)
        self.assertEqual(response.assistant_message.tool_results["type"], "journal_match")
        self.assertIn("matches", response.assistant_message.tool_results)
        self.assertTrue(run_direct.called)

    def test_journal_match_text_does_not_call_citation_verification(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_direct_journal_match") as run_direct,
            patch("app.services.chat_service.ChatService._run_journal_match_from_doi", side_effect=AssertionError("DOI path should not run")),
            patch("app.services.chat_service.citation_batch_service.verify_text", side_effect=AssertionError("citation verification should not run")),
            patch("app.services.chat_service.external_academic_search_service.lookup", side_effect=AssertionError("external lookup should not run")),
        ):
            run_direct.return_value = (
                MessageType.TEXT,
                "Journal match completed.",
                {"type": "journal_match", "matches": [], "status": "insufficient_manuscript_content"},
            )
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=(
                            "journal matching for: Abstract: A study about quantum computing. "
                            "Keywords: quantum, computing, algorithm"
                        ),
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.tool_results["type"], "journal_match")
        self.assertTrue(run_direct.called)

    def test_journal_match_degraded_external_falls_back_to_direct_match(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_direct_journal_match") as run_direct,
            patch("app.services.chat_service.ChatService._run_journal_match_from_lookup_text", return_value=(
                MessageType.JOURNAL_LIST,
                "Degraded lookup",
                {"type": "journal_list", "data": [], "status": "source_degraded"},
            )),
            patch("app.services.chat_service.external_academic_search_service.should_handle", return_value=True),
        ):
            run_direct.return_value = (
                MessageType.TEXT,
                "Direct journal match fallback.",
                {"type": "journal_match", "matches": [{"journal": "Fallback Journal"}], "status": "matched"},
            )
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=(
                            "journal suggestion for: Title: Quantum Networks. "
                            "Abstract: A study on quantum communication protocols and network security."
                        ),
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.tool_results["type"], "journal_match")
        self.assertTrue(run_direct.called)


if __name__ == "__main__":
    unittest.main()
