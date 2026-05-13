from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.chat_message import MessageType
from app.models.chat_session import SessionMode
from app.schemas.chat import ChatCompletionRequest
from app.api.v1.endpoints.chat import create_completion
from app.services.chat_service import ChatService, chat_service
from app.services.academic_policy import (
    AIRA_GENERAL_ACADEMIC_PROMPT,
    AIRA_CORPUS_GROUNDED_PROMPT,
    CRAWLER_DB_NO_DATA_MESSAGE,
)

try:
    from .support import TestEnvironment
except ImportError:
    from support import TestEnvironment


GENERAL_DISCUSSION_QUERIES = [
    "AI có phải là hướng nghiên cứu tiềm năng ko",
    "Nên nghiên cứu AI trong cybersecurity theo hướng nào?",
    "Cho tôi nhận định về tiềm năng của AI trong nghiên cứu",
    "Research direction nào đang hot trong machine learning?",
    "Phương pháp nghiên cứu nào phù hợp cho interdisciplinary topics?",
]

CORPUS_QUERIES = [
    "Xác minh trích dẫn 10.1111/gcb.17128",
    "Hãy cho tôi biết các bài trong cơ sở dữ liệu này về AI",
    "Gợi ý tạp chí cho bài về machine learning",
    "Kiểm tra rút bài 10.1000/xyz123",
    "Verify DOI 10.1111/gcb.17128",
]


class GeneralAcademicDiscussionRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.session = self.env.create_chat_session(user=self.user, mode=SessionMode.GENERAL_QA)

    def tearDown(self) -> None:
        self.env.close()

    # ── Intent classification tests ───────────────────────────────────────

    def test_classify_general_discussion_intent(self) -> None:
        for query in GENERAL_DISCUSSION_QUERIES:
            with self.subTest(query=query):
                intent = chat_service._classify_academic_intent(query)
                self.assertEqual(
                    intent, "general_academic_discussion",
                    f"Query should be classified as general_academic_discussion: {query}",
                )

    def test_classify_corpus_query_intent(self) -> None:
        for query in CORPUS_QUERIES:
            with self.subTest(query=query):
                intent = chat_service._classify_academic_intent(query)
                self.assertEqual(
                    intent, "corpus_query",
                    f"Query should be classified as corpus_query: {query}",
                )

    def test_classify_unknown_intent(self) -> None:
        non_academic_queries = [
            "Thời tiết hôm nay thế nào",
            "Xin chào",
            "Hello",
            "Bạn có khỏe không",
            "1 + 1 bằng mấy",
        ]
        for query in non_academic_queries:
            with self.subTest(query=query):
                intent = chat_service._classify_academic_intent(query)
                self.assertEqual(
                    intent, "unknown",
                    f"Non-academic query should be classified as unknown: {query}",
                )

    # ── Routing behavior tests (with mock) ────────────────────────────────

    def test_general_discussion_does_not_call_corpus_fallback(self) -> None:
        """General discussion questions should NOT return the corpus-not-found fallback."""
        for query in GENERAL_DISCUSSION_QUERIES:
            with self.subTest(query=query):
                with self.env.session() as db:
                    with patch(
                        "app.services.chat_service.gemini_service.generate_response"
                    ) as mock_generate:
                        mock_generate.return_value.text = (
                            "Đây là câu trả lời từ kiến thức nền về AI."
                        )
                        mock_generate.return_value.message_type = "TEXT"
                        mock_generate.return_value.tool_results = None

                        response = create_completion(
                            payload=ChatCompletionRequest(
                                session_id=self.session.id,
                                user_message=query,
                            ),
                            db=db,
                            current_user=self.user,
                        )

                assistant = response.assistant_message
                self.assertNotIn(
                    "chưa tìm thấy thông tin",
                    assistant.content or "",
                    f"General discussion should not return corpus fallback: {query}",
                )

    def test_general_discussion_receives_general_academic_prompt(self) -> None:
        """General discussion should use AIRA_GENERAL_ACADEMIC_PROMPT and expose_tools=False."""
        query = "AI có phải là hướng nghiên cứu tiềm năng ko"
        with self.env.session() as db:
            with patch(
                "app.services.chat_service.gemini_service.generate_response"
            ) as mock_generate:
                mock_generate.return_value.text = "Mocked response"
                mock_generate.return_value.message_type = "TEXT"
                mock_generate.return_value.tool_results = None

                create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=query,
                    ),
                    db=db,
                    current_user=self.user,
                )

                mock_generate.assert_called_once()
                call_kwargs = mock_generate.call_args.kwargs
                self.assertEqual(
                    call_kwargs.get("system_prompt_override"),
                    AIRA_GENERAL_ACADEMIC_PROMPT,
                )
                self.assertFalse(call_kwargs.get("expose_tools", True))

    def test_corpus_query_still_uses_default_prompt_with_tools(self) -> None:
        """Corpus/tool queries should still use the default corpus-grounded prompt with tools."""
        query = "AI có phải là hướng nghiên cứu tiềm năng ko"
        with self.env.session() as db:
            # Force corpus_query classification for a general discussion question
            with patch.object(
                chat_service, "_classify_academic_intent",
                return_value="corpus_query",
            ):
                with patch(
                    "app.services.chat_service.gemini_service.generate_response"
                ) as mock_generate:
                    mock_generate.return_value.text = "Mocked verification"
                    mock_generate.return_value.message_type = "CITATION_REPORT"
                    mock_generate.return_value.tool_results = {"type": "citation_report", "data": []}

                    create_completion(
                        payload=ChatCompletionRequest(
                            session_id=self.session.id,
                            user_message=query,
                        ),
                        db=db,
                        current_user=self.user,
                    )

                    mock_generate.assert_called_once()
                    call_kwargs = mock_generate.call_args.kwargs
                    self.assertIsNone(
                        call_kwargs.get("system_prompt_override"),
                        "Corpus query should not override system prompt",
                    )
                    self.assertTrue(
                        call_kwargs.get("expose_tools", True),
                        "Corpus query should expose tools",
                    )

    def test_corpus_query_not_affected(self) -> None:
        """Existing DOI + citation verification still works."""
        query = "Xác minh trích dẫn 10.1111/gcb.17128"
        with self.env.session() as db:
            with patch(
                "app.services.chat_service.ChatService._run_mode_tool"
            ) as run_tool:
                run_tool.return_value = (
                    MessageType.CITATION_REPORT,
                    "Stubbed citation verification",
                    {"type": "citation_report", "data": []},
                )
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message=query,
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, "citation_report")
        self.assertTrue(run_tool.called)

    def test_journal_followup_unchanged(self) -> None:
        """Journal followup pattern should still reuse cached result."""
        with self.env.session() as db:
            # First create a journal list message
            from app.models.chat_message import ChatMessage, MessageRole

            cached = ChatMessage(
                session_id=self.session.id,
                role=MessageRole.ASSISTANT,
                content="Prior journal list",
                message_type=MessageType.JOURNAL_LIST,
                tool_results={
                    "type": "journal_list",
                    "data": [
                        {"journal": "Test Journal", "reason": "Good fit"},
                    ],
                },
            )
            db.add(cached)
            db.commit()

            response = create_completion(
                payload=ChatCompletionRequest(
                    session_id=self.session.id,
                    user_message="Giới thiệu từng journal",
                ),
                db=db,
                current_user=self.user,
            )

        self.assertEqual(response.assistant_message.message_type, "journal_list")

    def test_academic_db_query_unchanged(self) -> None:
        """'Bài trong cơ sở dữ liệu' queries still go through academic_query_service."""
        query = "Hãy cho tôi biết các bài trong cơ sở dữ liệu này về M-theory holographic duality."
        with self.env.session() as db:
            response = create_completion(
                payload=ChatCompletionRequest(
                    session_id=self.session.id,
                    user_message=query,
                ),
                db=db,
                current_user=self.user,
            )

        assistant = response.assistant_message
        self.assertEqual(assistant.message_type, "text")
        self.assertIn("chưa tìm thấy bài hoặc bản ghi học thuật liên quan", assistant.content or "")


class GeneralAcademicPromptTest(unittest.TestCase):
    def test_general_academic_prompt_is_distinct_from_corpus_grounded(self) -> None:
        self.assertNotEqual(AIRA_GENERAL_ACADEMIC_PROMPT, AIRA_CORPUS_GROUNDED_PROMPT)

    def test_general_academic_prompt_allows_background_knowledge(self) -> None:
        """The general prompt should NOT contain the 'không tự lấp khoảng trống' rule."""
        self.assertNotIn("không tự lấp khoảng trống", AIRA_GENERAL_ACADEMIC_PROMPT)
        self.assertNotIn("chưa tìm thấy thông tin", AIRA_GENERAL_ACADEMIC_PROMPT)
        self.assertNotIn("CRAWLER_DB_NO_DATA", AIRA_GENERAL_ACADEMIC_PROMPT)

    def test_general_academic_prompt_forbids_fabrication(self) -> None:
        self.assertIn("KHÔNG bịa DOI", AIRA_GENERAL_ACADEMIC_PROMPT)

    def test_corpus_grounded_prompt_contains_fallback_rule(self) -> None:
        self.assertIn("chưa tìm thấy thông tin", AIRA_CORPUS_GROUNDED_PROMPT)
        self.assertIn("Không tự lấp khoảng trống", AIRA_CORPUS_GROUNDED_PROMPT)

    def test_corpus_grounded_prompt_contains_retrieval_priority(self) -> None:
        self.assertIn("retrieve first, reason second", AIRA_CORPUS_GROUNDED_PROMPT)

    def test_backward_compat_alias(self) -> None:
        from app.services.academic_policy import AIRA_SYSTEM_PROMPT
        self.assertEqual(AIRA_SYSTEM_PROMPT, AIRA_CORPUS_GROUNDED_PROMPT)


class ChatServiceIntentClassificationTest(unittest.TestCase):
    def test_empty_text_returns_unknown(self) -> None:
        self.assertEqual(chat_service._classify_academic_intent(""), "unknown")
        self.assertEqual(chat_service._classify_academic_intent(None), "unknown")
        self.assertEqual(chat_service._classify_academic_intent("   "), "unknown")

    def test_corpus_intent_takes_priority_over_general_discussion(self) -> None:
        """A query with both DOI and academic discussion keywords should be corpus_query."""
        query = "Xác minh DOI 10.1111/gcb.17128 về AI potential"
        intent = chat_service._classify_academic_intent(query)
        self.assertEqual(intent, "corpus_query")

    def test_retraction_keyword_classifies_as_corpus(self) -> None:
        queries = [
            "Kiểm tra rút bài 10.1000/xyz123",
            "Retraction status của paper này?",
            "PubPeer có gì về DOI này không?",
        ]
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(chat_service._classify_academic_intent(query), "corpus_query")

    def test_bare_doi_classified_as_corpus_query(self) -> None:
        """Bare DOI is classified as corpus_query."""
        intent = chat_service._classify_academic_intent("10.1111/gcb.17128")
        self.assertEqual(intent, "corpus_query")

    def test_doi_url_classified_as_corpus_query(self) -> None:
        """DOI URL is classified as corpus_query."""
        intent = chat_service._classify_academic_intent("https://doi.org/10.1111/gcb.17128")
        self.assertEqual(intent, "corpus_query")

    def test_doi_with_retraction_classified_as_corpus_query(self) -> None:
        """DOI + retraction keyword is classified as corpus_query."""
        intent = chat_service._classify_academic_intent("DOI 10.1111/gcb.17128 đã bị retract")
        self.assertEqual(intent, "corpus_query")


if __name__ == "__main__":
    unittest.main()
