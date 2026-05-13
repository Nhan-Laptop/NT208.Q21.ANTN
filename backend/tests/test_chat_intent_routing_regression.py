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


if __name__ == "__main__":
    unittest.main()
