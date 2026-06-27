from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.v1.endpoints.chat import create_completion
from app.models.ai_detection_rule import AIDetectionRule
from app.models.chat_message import MessageType
from app.models.chat_session import SessionMode
from app.schemas.chat import ChatCompletionRequest, SessionCreate

try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


class ChatAutoModeRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user, mode=SessionMode.AUTO)

    def tearDown(self) -> None:
        self.env.close()

    def _routing(self, response) -> dict:
        tool_results = response.assistant_message.tool_results
        self.assertIsInstance(tool_results, dict)
        meta = tool_results.get("meta")
        self.assertIsInstance(meta, dict)
        routing = meta.get("routing")
        self.assertIsInstance(routing, dict)
        return routing

    def test_session_create_defaults_to_auto(self) -> None:
        self.assertEqual(SessionCreate().mode, SessionMode.AUTO)

    def test_chat_completion_survives_missing_ai_rule_table(self) -> None:
        AIDetectionRule.__table__.drop(self.env.engine)

        with patch(
            "app.services.chat_service.ChatService._run_general_qa_flow",
            return_value=(MessageType.TEXT, "Fallback general answer", None),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Giải thích xu hướng research retrieval hiện nay.",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.content, "Fallback general answer")

    def test_auto_routes_doi_metadata_without_general_flow(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch(
                "app.services.chat_service.ChatService._run_doi_metadata_lookup",
                return_value=(
                    MessageType.TEXT,
                    "Stubbed DOI metadata",
                    {"type": "doi_metadata", "status": "verified", "data": {"doi": "10.1111/gcb.17128"}},
                ),
            ) as run_lookup,
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Analyze DOI 10.1111/gcb.17128 and provide title, journal, publisher.",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_lookup.called)
        self.assertEqual(response.assistant_message.tool_results["type"], "doi_metadata")
        routing = self._routing(response)
        self.assertEqual(routing["requested_mode"], "auto")
        self.assertEqual(routing["resolved_feature"], "doi_metadata")
        self.assertEqual(response.session.mode, "auto")

    def test_auto_routes_citation_verification_without_general_flow(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch(
                "app.services.chat_service.ChatService._run_mode_tool",
                return_value=(
                    MessageType.CITATION_REPORT,
                    "Stubbed citation verification",
                    {"type": "citation_report", "data": []},
                ),
            ) as run_tool,
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Verify citation 10.1111/gcb.17128",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_tool.called)
        self.assertEqual(response.assistant_message.message_type, "citation_report")
        routing = self._routing(response)
        self.assertEqual(routing["resolved_feature"], "verification")

    def test_auto_routes_doi_author_query_to_general_qa(self) -> None:
        with (
            patch(
                "app.services.chat_service.ChatService._run_mode_tool",
                side_effect=AssertionError("citation verification should not run"),
            ),
            patch(
                "app.services.chat_service.ChatService._run_general_qa_flow",
                return_value=(
                    MessageType.TEXT,
                    "Stubbed author publication search",
                    {"type": "author_publication_search", "status": "matched", "authors": []},
                ),
            ) as general_flow,
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="tác giả của DOI 10.1038/s41586-020-2649-2 có thêm bài báo nào nữa không",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(general_flow.called)
        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.tool_results["type"], "author_publication_search")
        routing = self._routing(response)
        self.assertEqual(routing["resolved_feature"], "general_qa")

    def test_auto_routes_multi_citation_verification_through_shared_batch_pipeline(self) -> None:
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
        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch(
                "app.services.chat_service.citation_batch_service.verify_text",
                return_value=report,
            ) as verify_text,
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Xác minh các trích dẫn sau:\n10.1000/verified\nReview citation",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "citation_report")
        self.assertEqual(response.assistant_message.tool_results["type"], "citation_report")
        self.assertEqual(response.assistant_message.tool_results["summary"]["total_count"], 2)
        self.assertEqual(self._routing(response)["resolved_feature"], "verification")
        verify_text.assert_called_once_with("Xác minh các trích dẫn sau:\n10.1000/verified\nReview citation")

    def test_auto_routes_journal_match_from_doi(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch(
                "app.services.chat_service.ChatService._run_journal_match_from_doi",
                return_value=(
                    MessageType.JOURNAL_LIST,
                    "Stubbed journal match",
                    {"type": "journal_list", "data": [], "status": "insufficient_corpus"},
                ),
            ) as run_match,
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Gợi ý tạp chí cho DOI 10.1111/gcb.17128",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_match.called)
        self.assertEqual(response.assistant_message.message_type, "journal_list")
        routing = self._routing(response)
        self.assertEqual(routing["resolved_feature"], "journal_match")

    def test_auto_routes_journal_match_from_lookup_text(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch(
                "app.services.chat_service.ChatService._run_direct_journal_match",
                return_value=(
                    MessageType.TEXT,
                    "Stubbed direct journal match via title fallback",
                    {"type": "journal_match", "matches": [{"journal": "Cog Psychology"}], "status": "matched"},
                ),
            ) as run_direct,
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=(
                            "Gợi ý tạp chí cho bài này:\n"
                            "Is working memory domain-general or domain-specific?\n"
                            "Nazbanou Nozari, Randi C. Martin"
                        ),
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_direct.called)
        self.assertEqual(response.assistant_message.message_type, "text")
        routing = self._routing(response)
        self.assertEqual(routing["resolved_feature"], "journal_match")

    def test_auto_routes_grammar_without_general_flow(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch(
                "app.services.chat_service.ChatService._run_grammar_tool",
                return_value=(
                    MessageType.GRAMMAR_REPORT,
                    "Stubbed grammar report",
                    {"type": "grammar_report", "data": {"total_errors": 1, "issues": [], "corrected_text": "Fixed text"}},
                ),
            ) as run_grammar,
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Proofread this abstract and fix grammar mistakes.",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_grammar.called)
        self.assertEqual(response.assistant_message.message_type, "grammar_report")
        routing = self._routing(response)
        self.assertEqual(routing["resolved_feature"], "grammar")

    def test_auto_asks_for_clarification_when_prompt_maps_to_multiple_features(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch("app.services.chat_service.ChatService._run_mode_tool", side_effect=AssertionError("tool path should not run")),
            patch("app.services.chat_service.ChatService._run_grammar_tool", side_effect=AssertionError("grammar path should not run")),
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Check grammar and detect AI in this paragraph.",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.tool_results["type"], "intent_disambiguation")
        routing = self._routing(response)
        self.assertTrue(routing["is_ambiguous"])

    def test_auto_routes_journal_match_with_content_to_direct_match(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch("app.services.chat_service.ChatService._run_direct_journal_match",
                return_value=(
                    MessageType.TEXT,
                    "Direct journal match completed.",
                    {"type": "journal_match", "matches": [{"journal": "Test Journal", "score": 0.85}], "status": "matched"},
                ),
            ) as run_direct,
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=(
                            "journal suggestion: Abstract: Machine learning for NLP tasks. "
                            "Keywords: transformers, BERT, deep learning"
                        ),
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_direct.called)
        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.tool_results["type"], "journal_match")
        routing = self._routing(response)
        self.assertEqual(routing["resolved_feature"], "journal_match")

    def test_auto_routes_vn_journal_prompt_to_direct_match(self) -> None:
        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch("app.services.chat_service.ChatService._run_direct_journal_match",
                return_value=(
                    MessageType.TEXT,
                    "Direct journal match completed.",
                    {"type": "journal_match", "matches": [{"journal": "Tạp chí Khoa học", "score": 0.75}], "status": "matched"},
                ),
            ) as run_direct,
        ):
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=(
                            "gợi ý tạp chí cho: Abstract: Nghiên cứu về học máy trong xử lý ngôn ngữ tự nhiên. "
                            "Từ khóa: NLP, deep learning"
                        ),
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_direct.called)
        self.assertEqual(response.assistant_message.message_type, "text")
        self.assertEqual(response.assistant_message.tool_results["type"], "journal_match")
        routing = self._routing(response)
        self.assertEqual(routing["resolved_feature"], "journal_match")

    def test_auto_re_evaluates_each_message_while_session_stays_auto(self) -> None:
        with patch(
            "app.services.chat_service.ChatService._run_general_qa_flow",
            return_value=(MessageType.TEXT, "General answer", None),
        ) as general_flow:
            with self.env.session() as db:
                first = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Những hướng nghiên cứu tiềm năng của retrieval-augmented systems là gì?",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(general_flow.called)
        self.assertEqual(first.assistant_message.message_type, "text")
        self.assertEqual(self._routing(first)["resolved_feature"], "general_qa")
        self.assertEqual(first.session.mode, "auto")

        with (
            patch("app.services.chat_service.ChatService._run_general_qa_flow", side_effect=AssertionError("general flow should not run")),
            patch(
                "app.services.chat_service.ChatService._run_mode_tool",
                return_value=(
                    MessageType.RETRACTION_REPORT,
                    "Retraction check",
                    {"type": "retraction_report", "data": []},
                ),
            ) as run_tool,
        ):
            with self.env.session() as db:
                second = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="Kiểm tra DOI 10.1111/gcb.17128 có bị retract không?",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertTrue(run_tool.called)
        self.assertEqual(second.assistant_message.message_type, "retraction_report")
        self.assertEqual(self._routing(second)["resolved_feature"], "retraction")
        self.assertEqual(second.session.mode, "auto")


if __name__ == "__main__":
    unittest.main()
