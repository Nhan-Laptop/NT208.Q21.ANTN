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
