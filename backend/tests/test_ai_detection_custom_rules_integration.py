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
from app.schemas.chat import ChatCompletionRequest
from app.schemas.tools import AIWritingDetectRequest
from app.services import heuristic_router, llm_service
from app.services.ai_detection_rules import build_user_ai_detection_rule_prefs
from app.services.document_cache import store_document
from app.services.tools.ai_writing_detector import DetectionResult

try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


class AIDetectionCustomRulesIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = TestEnvironment()
        self.user = self.env.create_user()
        self.user.ai_detection_rule_prefs = build_user_ai_detection_rule_prefs(
            ["as an AI language model", "it is important to note that"]
        )
        self.session = self.env.create_chat_session(user=self.user, mode=SessionMode.AI_DETECTION)

    def tearDown(self) -> None:
        self.env.close()

    def test_tools_endpoint_uses_saved_custom_rules(self) -> None:
        from app.api.v1.endpoints.tools import detect_ai_writing

        fake_result = DetectionResult(
            score=0.81,
            confidence="MEDIUM",
            verdict="LIKELY_AI",
            flags=["as an AI language model"],
            details={"matched_rules": ["as an AI language model"]},
            rule_score=0.81,
            rule_source="user_custom_rules",
            matched_rules=["as an AI language model"],
        )

        with patch("app.api.v1.endpoints.tools.ai_writing_detector.analyze", return_value=fake_result) as analyze:
            with self.env.session() as db:
                response = detect_ai_writing(
                    payload=AIWritingDetectRequest(
                        session_id=self.session.id,
                        text="As an AI language model, it is important to note that this passage is synthetic enough for testing.",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.data.rule_source, "user_custom_rules")
        analyze.assert_called_once()
        args, kwargs = analyze.call_args
        self.assertIn("As an AI language model", args[0])
        self.assertEqual(
            kwargs["custom_rule_phrases"],
            ["as an AI language model", "it is important to note that"],
        )

    def test_chat_ai_detection_mode_passes_custom_rules(self) -> None:
        fake_result = DetectionResult(
            score=0.74,
            confidence="MEDIUM",
            verdict="POSSIBLY_AI",
            flags=["it is important to note that"],
            details={"matched_rules": ["it is important to note that"]},
            rule_score=0.74,
            rule_source="user_custom_rules",
            matched_rules=["it is important to note that"],
        )

        with patch("app.services.chat_service.ai_writing_detector.analyze", return_value=fake_result) as analyze:
            with self.env.session() as db:
                response = create_completion(
                    payload=ChatCompletionRequest(
                        session_id=self.session.id,
                        user_message="It is important to note that this paragraph is used to test the AI detection wiring path.",
                    ),
                    db=db,
                    current_user=self.user,
                )

        self.assertEqual(response.assistant_message.message_type, MessageType.AI_WRITING_DETECTION)
        analyze.assert_called_once()
        _, kwargs = analyze.call_args
        self.assertEqual(
            kwargs["custom_rule_phrases"],
            ["as an AI language model", "it is important to note that"],
        )

    def test_function_call_execution_forwards_custom_rules(self) -> None:
        doc_id = store_document(
            "As an AI language model, this cached document is long enough for tool execution wiring tests."
        )

        with patch.dict(
            llm_service._TOOL_FUNCTIONS,
            {"detect_ai_writing": lambda **kwargs: {"score": 0.9, "kwargs": kwargs}},
        ):
            result = llm_service._execute_tool_call(
                "detect_ai_writing",
                {"document_id": doc_id},
                {doc_id},
                user_ai_rule_phrases=["as an AI language model"],
            )

        self.assertEqual(result["score"], 0.9)
        self.assertEqual(
            result["kwargs"],
            {
                "text": "As an AI language model, this cached document is long enough for tool execution wiring tests.",
                "user_ai_rule_phrases": ["as an AI language model"],
            },
        )

    def test_heuristic_fallback_forwards_custom_rules(self) -> None:
        with patch.object(
            heuristic_router._semantic_router,
            "classify",
            return_value=(heuristic_router._Intent.AI_DETECT, 1.0),
        ), patch(
            "app.services.llm_service.detect_ai_writing",
            return_value={"score": 0.8, "verdict": "LIKELY_AI"},
        ) as detect:
            result = heuristic_router.fallback_process_request(
                "Please detect AI in this paragraph. It is important to note that the wording is repetitive for testing only.",
                None,
                allowed_tool_names={"detect_ai_writing"},
                user_ai_rule_phrases=["it is important to note that"],
            )

        self.assertIsNotNone(result)
        detect.assert_called_once()
        _, kwargs = detect.call_args
        self.assertEqual(
            kwargs["user_ai_rule_phrases"],
            ["it is important to note that"],
        )
