from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.services.ai_detection_service as ai_detection_service_module
from app.services.ai_detection_service import ai_detection_service


class AIDetectionServiceTest(unittest.TestCase):
    def test_phrase_and_regex_rules_match(self) -> None:
        text = (
            "It is important to note that this paragraph plays a crucial role in the discussion.\n\n"
            "The section concludes with repeated wording and examples like AI-AI-AI."
        )
        runtime_rules = [
            {
                "id": "rule-phrase",
                "name": "Generic phrase",
                "rule_type": "phrase",
                "severity": "medium",
                "weight": 0.4,
                "scope": "user",
                "source": "table",
                "compiled_rule": {
                    "name": "Generic phrase",
                    "description": "Generic academic phrase rule",
                    "rule_type": "phrase",
                    "severity": "medium",
                    "weight": 0.4,
                    "conditions": [
                        {
                            "kind": "phrase_group",
                            "phrases": ["it is important to note that", "plays a crucial role"],
                            "threshold": 1,
                            "scope": "paragraph",
                        }
                    ],
                    "operator": "OR",
                    "action": {"flag": True, "message": "Generic phrasing."},
                },
            },
            {
                "id": "rule-regex",
                "name": "Repeated AI token",
                "rule_type": "regex",
                "severity": "low",
                "weight": 0.2,
                "scope": "user",
                "source": "table",
                "compiled_rule": {
                    "name": "Repeated AI token",
                    "description": "Regex rule",
                    "rule_type": "regex",
                    "severity": "low",
                    "weight": 0.2,
                    "conditions": [
                        {
                            "kind": "regex",
                            "pattern": r"AI-AI-AI",
                            "threshold": 1,
                            "scope": "paragraph",
                            "flags": ["IGNORECASE"],
                        }
                    ],
                    "operator": "OR",
                    "action": {"flag": True, "message": "Repeated AI token."},
                },
            },
        ]

        result = ai_detection_service.analyze_text(
            text,
            mode="rule_only",
            runtime_rule_payloads=runtime_rules,
            include_explanation=False,
        )

        self.assertEqual(result.type, "ai_detection")
        self.assertGreater(result.custom_rule_score, 0)
        self.assertGreaterEqual(len(result.matched_rules), 2)
        self.assertEqual(result.rule_source, "user_custom_rules")

    def test_semantic_rule_uses_mocked_llm(self) -> None:
        runtime_rules = [
            {
                "id": "rule-semantic",
                "name": "Generic semantic rule",
                "rule_type": "semantic",
                "severity": "medium",
                "weight": 0.3,
                "scope": "user",
                "source": "table",
                "compiled_rule": {
                    "name": "Generic semantic rule",
                    "description": "Flags generic paragraphs.",
                    "rule_type": "semantic",
                    "severity": "medium",
                    "weight": 0.3,
                    "conditions": [
                        {
                            "kind": "semantic",
                            "instruction": "Flag generic template-like paragraphs.",
                            "threshold": "medium",
                            "scope": "paragraph",
                        }
                    ],
                    "operator": "OR",
                    "action": {"flag": True, "message": "Generic paragraph."},
                },
            }
        ]
        semantic_output = """
        {
          "matched": true,
          "confidence": 0.84,
          "reason": "The paragraph is generic and template-like.",
          "evidence_span": "It is important to note that this section is highly generic.",
          "suggestions": ["Add concrete examples."]
        }
        """

        with patch.object(type(ai_detection_service_module.gemini_service), "enabled", new_callable=PropertyMock, return_value=True), patch(
            "app.services.ai_detection_service.gemini_service.generate_simple",
            side_effect=[semantic_output, "Short deterministic explanation."],
        ):
            result = ai_detection_service.analyze_text(
                "It is important to note that this section is highly generic and lacks concrete examples.",
                mode="deep",
                runtime_rule_payloads=runtime_rules,
                include_explanation=True,
            )

        self.assertGreater(result.custom_rule_score, 0)
        self.assertTrue(any("generic" in match.reason.lower() for match in result.matched_rules if not isinstance(match, str)))
        self.assertIn("Add concrete examples.", result.suggestions)

    def test_score_aggregation_uses_weighted_combination(self) -> None:
        runtime_rules = [
            {
                "id": "rule-aggregation",
                "name": "Generic phrase",
                "rule_type": "phrase",
                "severity": "medium",
                "weight": 0.5,
                "scope": "user",
                "source": "table",
                "compiled_rule": {
                    "name": "Generic phrase",
                    "description": "Generic phrase rule",
                    "rule_type": "phrase",
                    "severity": "medium",
                    "weight": 0.5,
                    "conditions": [
                        {
                            "kind": "phrase",
                            "phrase": "it is important to note that",
                            "phrases": ["it is important to note that"],
                            "threshold": 1,
                            "scope": "paragraph",
                        }
                    ],
                    "operator": "OR",
                    "action": {"flag": True, "message": "Generic phrase."},
                },
            }
        ]
        baseline = SimpleNamespace(
            score=0.8,
            confidence="MEDIUM",
            method="ensemble",
            flags=["baseline flag"],
            detectors_used=["rule_based", "roberta_gpt2_detector"],
            skipped_detectors=[],
            fallback_reason=None,
            details={"baseline": True},
            ml_score=0.82,
        )

        with patch("app.services.ai_detection_service.ai_writing_detector.analyze", return_value=baseline):
            result = ai_detection_service.analyze_text(
                "It is important to note that this paragraph is generic enough for aggregation testing.",
                mode="fast",
                runtime_rule_payloads=runtime_rules,
                include_explanation=False,
            )

        self.assertAlmostEqual(result.custom_rule_score, 0.35, places=2)
        self.assertAlmostEqual(result.final_score, 0.6875, places=3)


if __name__ == "__main__":
    unittest.main()
