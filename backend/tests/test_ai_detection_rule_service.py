from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.services.ai_detection_rule_service as rule_service_module
from app.schemas.ai_detection import CompiledAIDetectionRule
from app.services.ai_detection_rule_service import (
    AIDetectionRuleCompileError,
    AIDetectionRuleError,
    compile_natural_language_rule,
    validate_compiled_rule,
)


class AIDetectionRuleServiceTest(unittest.TestCase):
    def test_compile_rule_success_with_mocked_llm(self) -> None:
        llm_output = """
        {
          "name": "Generic academic phrasing",
          "description": "Flags generic academic transition phrases.",
          "rule_type": "phrase",
          "severity": "medium",
          "weight": 0.3,
          "conditions": [
            {
              "kind": "phrase_group",
              "phrases": ["it is important to note that", "plays a crucial role"],
              "threshold": 1,
              "scope": "paragraph"
            }
          ],
          "operator": "OR",
          "action": {"flag": true, "message": "Generic phrasing detected."}
        }
        """

        with patch.object(type(rule_service_module.gemini_service), "enabled", new_callable=PropertyMock, return_value=True), patch(
            "app.services.ai_detection_rule_service.gemini_service.generate_simple",
            return_value=llm_output,
        ):
            compiled_rule, warnings = compile_natural_language_rule("Flag generic academic phrasing.")

        self.assertEqual(compiled_rule.name, "Generic academic phrasing")
        self.assertEqual(compiled_rule.rule_type.value, "phrase")
        self.assertEqual(warnings, [])

    def test_compile_rule_repairs_invalid_json_once(self) -> None:
        malformed_output = """```json {"name":"Broken" """
        repaired_output = """
        {
          "name": "Semantic genericity",
          "description": "Flags generic paragraphs.",
          "rule_type": "semantic",
          "severity": "medium",
          "weight": 0.25,
          "conditions": [
            {
              "kind": "semantic",
              "instruction": "Flag generic template-like paragraphs.",
              "threshold": "medium",
              "scope": "paragraph"
            }
          ],
          "operator": "OR",
          "action": {"flag": true, "message": "Generic paragraph detected."}
        }
        """

        with patch.object(type(rule_service_module.gemini_service), "enabled", new_callable=PropertyMock, return_value=True), patch(
            "app.services.ai_detection_rule_service.gemini_service.generate_simple",
            side_effect=[malformed_output, repaired_output],
        ):
            compiled_rule, warnings = compile_natural_language_rule("Flag generic template-like paragraphs.")

        self.assertEqual(compiled_rule.rule_type.value, "semantic")
        self.assertTrue(any("repair" in warning.lower() for warning in warnings))

    def test_compile_rule_normalizes_common_llm_alias_fields(self) -> None:
        llm_output = """
        {
          "name": "Repetitive Generic Phrases",
          "description": "Checks for repetitive generic phrases",
          "rule_type": "semantic",
          "severity": "medium",
          "weight": 0.7,
          "conditions": [
            {
              "name": "Generic Phrases Pattern",
              "condition_kind": "phrase_group",
              "pattern": "it is important to note that|plays a crucial role|this highlights the importance of"
            }
          ],
          "operator": "AND",
          "action": {"flag": true, "message": "Manuscript contains repeated generic language."}
        }
        """

        with patch.object(type(rule_service_module.gemini_service), "enabled", new_callable=PropertyMock, return_value=True), patch(
            "app.services.ai_detection_rule_service.gemini_service.generate_simple",
            return_value=llm_output,
        ):
            compiled_rule, warnings = compile_natural_language_rule("Flag generic filler phrases.")

        self.assertEqual(compiled_rule.rule_type.value, "phrase")
        self.assertEqual(compiled_rule.conditions[0].kind, "phrase_group")
        self.assertEqual(compiled_rule.conditions[0].phrases[0], "it is important to note that")
        self.assertTrue(any("normalized" in warning.lower() or "dropped" in warning.lower() for warning in warnings) or warnings == [])

    def test_compile_rule_prefers_later_valid_json_candidate(self) -> None:
        llm_output = """
        Compiled rule in JSON:
        {
          "name": "academic_claims_without_citation",
          "description": "Flag broad academic claims without citation",
          "rule_type": "semantic",
          "severity": "high",
          "weight": 0.8,
          "conditions": [
            {
              "kind": "semantic",
              "instruction": "has_phrase('research has shown that' OR 'studies indicate that') AND not_missing_citation()",
              "threshold": "medium",
              "scope": "paragraph"
            }
          ],
          "operator": "AND",
          "action": {
            "flag": true,
            "message": "Broad academic claim without citation"
          }
        }

        {
          "name": "academic_claims_without_citation",
          "description": "Flag broad academic claims without citation",
          "rule_type": "hybrid",
          "severity": "high",
          "weight": 0.8,
          "conditions": [
            {
              "kind": "phrase_group",
              "phrases": ["research has shown that", "studies indicate that"],
              "threshold": 1,
              "scope": "paragraph"
            },
            {
              "kind": "missing_citation",
              "scope": "paragraph",
              "min_words": 50,
              "threshold": 1
            }
          ],
          "operator": "AND",
          "action": {
            "flag": true,
            "message": "Broad academic claim without citation"
          }
        }
        """

        with patch.object(type(rule_service_module.gemini_service), "enabled", new_callable=PropertyMock, return_value=True), patch(
            "app.services.ai_detection_rule_service.gemini_service.generate_simple",
            return_value=llm_output,
        ):
            compiled_rule, _ = compile_natural_language_rule("Flag broad academic claims without citation.")

        self.assertEqual(compiled_rule.rule_type.value, "hybrid")
        self.assertEqual(compiled_rule.conditions[0].kind, "phrase_group")

    def test_validate_compiled_rule_rejects_invalid_regex(self) -> None:
        compiled_rule = CompiledAIDetectionRule.model_validate(
            {
                "name": "Bad regex",
                "description": "Should fail regex validation.",
                "rule_type": "regex",
                "severity": "low",
                "weight": 0.2,
                "conditions": [
                    {
                        "kind": "regex",
                        "pattern": "(unclosed",
                        "threshold": 1,
                        "scope": "paragraph",
                        "flags": ["IGNORECASE"],
                    }
                ],
                "operator": "OR",
                "action": {"flag": True, "message": "Bad regex."},
            }
        )

        with self.assertRaises(AIDetectionRuleError):
            validate_compiled_rule(compiled_rule)

    def test_compile_rule_raises_when_llm_unavailable(self) -> None:
        with patch.object(type(rule_service_module.gemini_service), "enabled", new_callable=PropertyMock, return_value=False):
            with self.assertRaises(AIDetectionRuleCompileError):
                compile_natural_language_rule("Flag generic academic writing.")


if __name__ == "__main__":
    unittest.main()
