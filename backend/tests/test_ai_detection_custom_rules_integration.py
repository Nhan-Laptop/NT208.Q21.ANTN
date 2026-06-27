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
from app.schemas.ai_detection import AIDetectionAnalyzeResponse
from app.schemas.chat import ChatCompletionRequest
from app.schemas.tools import AIWritingDetectRequest
from app.services import heuristic_router, llm_service
from app.services.ai_detection_rules import build_user_ai_detection_rule_prefs
from app.services.document_cache import store_document

try:
    from .support import TestEnvironment
except ImportError:  # pragma: no cover - unittest discover fallback
    from support import TestEnvironment


class AIDetectionCustomRulesIntegrationTest(unittest.TestCase):
    @staticmethod
    def _fake_result(score: float = 0.81, matched_rule_name: str = "Legacy phrase rule") -> AIDetectionAnalyzeResponse:
        return AIDetectionAnalyzeResponse(
            mode="deep",
            score=score,
            model_score=score,
            roberta_score=0.71,
            custom_rule_score=0.44,
            final_score=score,
            rule_score=0.44,
            risk_level="high" if score >= 0.67 else "medium",
            confidence="MEDIUM",
            verdict="LIKELY_AI" if score >= 0.75 else "POSSIBLY_AI",
            method="ensemble",
            flags=["Matched custom rule signals"],
            details={"matched_rule_count": 1},
            detectors_used=["rule_based", "roberta_gpt2_detector"],
            skipped_detectors=[],
            rule_source="user_custom_rules",
            matched_rules=[
                {
                    "rule_id": "legacy-phrase-1",
                    "rule_name": matched_rule_name,
                    "rule_type": "phrase",
                    "severity": "low",
                    "weight": 0.15,
                    "matched_text": "it is important to note that",
                    "reason": "Matched custom phrase rule.",
                    "confidence": 0.8,
                    "location": {"scope": "paragraph", "paragraph_index": 0},
                }
            ],
            evidence=[
                {
                    "text": "it is important to note that",
                    "reason": "Matched custom phrase rule.",
                    "rule_id": "legacy-phrase-1",
                    "severity": "low",
                    "paragraph_index": 0,
                }
            ],
            explanation="Moderate AI-like signals from generic phrasing.",
            suggestions=["Add more specific evidence."],
            disclaimer="AI-writing detection is probabilistic and should not be treated as definitive proof.",
            warnings=[],
        )

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

        fake_result = self._fake_result()

        with patch(
            "app.api.v1.endpoints.tools.get_runtime_rule_payloads",
            return_value=[{"id": "legacy-phrase-1"}],
        ), patch(
            "app.api.v1.endpoints.tools.ai_detection_service.analyze_text",
            return_value=fake_result,
        ) as analyze:
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
        _, kwargs = analyze.call_args
        self.assertEqual(kwargs["mode"], "deep")
        self.assertEqual(kwargs["runtime_rule_payloads"], [{"id": "legacy-phrase-1"}])

    def test_chat_ai_detection_mode_passes_custom_rules(self) -> None:
        fake_result = self._fake_result(score=0.74)

        with patch(
            "app.services.chat_service.get_runtime_rule_payloads",
            return_value=[{"id": "legacy-phrase-1"}],
        ), patch(
            "app.services.chat_service.ai_detection_service.analyze_text",
            return_value=fake_result,
        ) as analyze:
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
        self.assertEqual(response.assistant_message.tool_results["type"], "ai_detection")
        analyze.assert_called_once()
        _, kwargs = analyze.call_args
        self.assertEqual(kwargs["runtime_rule_payloads"], [{"id": "legacy-phrase-1"}])

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
                user_ai_runtime_rules=[{"id": "structured-rule-1"}],
            )

        self.assertEqual(result["score"], 0.9)
        self.assertEqual(
            result["kwargs"],
            {
                "text": "As an AI language model, this cached document is long enough for tool execution wiring tests.",
                "user_ai_rule_phrases": ["as an AI language model"],
                "user_ai_runtime_rules": [{"id": "structured-rule-1"}],
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
                user_ai_runtime_rules=[{"id": "structured-rule-1"}],
            )

        self.assertIsNotNone(result)
        detect.assert_called_once()
        _, kwargs = detect.call_args
        self.assertEqual(
            kwargs["user_ai_rule_phrases"],
            ["it is important to note that"],
        )
        self.assertEqual(kwargs["user_ai_runtime_rules"], [{"id": "structured-rule-1"}])
