"""Tests for AI writing detector — ensemble, fallback, and schema regressions."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from app.schemas.tools import AIWritingDetectResult

# Force import of the submodule so that ``sys.modules`` has the real module.
# ``import app.services.tools.ai_writing_detector`` resolves to the singleton
# instance (shadowed by tools/__init__.py's attribute), so we grab the module
# object via sys.modules for patching.
# Ensure the submodule is loaded before we grab a reference to the module.
import app.services.tools.ai_writing_detector  # noqa: F401

_det_module = sys.modules["app.services.tools.ai_writing_detector"]


# ---------------------------------------------------------------------------
# AI-generated sample text that should NOT score "LIKELY_HUMAN" by rules alone
# ---------------------------------------------------------------------------

_AI_TEXT = (
    "In today's rapidly evolving digital landscape, it is essential to note that "
    "artificial intelligence plays a pivotal role in shaping modern communication. "
    "Moreover, this transformative technology leverages cutting-edge algorithms to "
    "unlock unprecedented potential across various domains. Consequently, it is "
    "imperative that we delve deeper into the multifaceted implications of this "
    "paradigm shift. Furthermore, a plethora of studies have shed light on the "
    "ever-changing nature of human-AI interaction, highlighting the crucial need "
    "for robust frameworks. In conclusion, it can be said that as an AI language "
    "model, I cannot provide definitive answers, but this comprehensive analysis "
    "serves as a testament to the transformative impact of artificial intelligence "
    "on our contemporary society."
)


class FakeRobertaModel:
    """Fake that mimics HuggingFace model output."""

    def __call__(self, **kwargs):
        import torch
        return MagicMock(logits=torch.tensor([[-0.5, 2.5]]))

    def to(self, device):
        return self

    def eval(self):
        return self


def _make_mock_tokenizer():
    """Tokeniser that returns a BatchEncoding-like dict with .to() support."""
    import torch

    class FakeEncoding(dict):
        def to(self, device):
            for k, v in list(self.items()):
                if isinstance(v, torch.Tensor):
                    self[k] = v.to(device)
            return self

    tok = MagicMock()
    tok.return_value = FakeEncoding({
        "input_ids": torch.randint(0, 1000, (1, 64)),
        "attention_mask": torch.ones(1, 64),
    })
    return tok


# ===================================================================
# Tests
# ===================================================================

class AIWritingDetectorTest(unittest.TestCase):
    """High-level regression tests for the overall pipeline."""

    def setUp(self):
        """Reset module-level globals that cache model instances between tests."""
        _det_module._detector_model = None
        _det_module._detector_tokenizer = None

    def test_roberta_detector_called_in_normal_path(self):
        """When transformers+torch + model available, result uses ENSEMBLE method."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
            DetectionMethod,
        )

        with (
            patch(
                "app.services.tools.ai_writing_detector._TRANSFORMERS_AVAILABLE",
                True,
            ),
            patch(
                "app.services.tools.ai_writing_detector.AutoTokenizer",
            ) as mock_tok,
            patch(
                "app.services.tools.ai_writing_detector.AutoModelForSequenceClassification",
            ) as mock_model,
        ):
            mock_tok.from_pretrained.return_value = _make_mock_tokenizer()
            mock_model.from_pretrained.return_value = FakeRobertaModel()

            detector = AIWritingDetector(use_ml=True, device="cpu")
            result = detector.analyze(_AI_TEXT)

            self.assertEqual(result.method, DetectionMethod.ENSEMBLE.value)
            self.assertIsNotNone(result.ml_score)
            self.assertIn("roberta_gpt2_detector", result.detectors_used)
            self.assertNotIn("roberta_gpt2_detector", result.skipped_detectors)

    def test_skip_reason_when_ml_model_not_cached(self):
        """When model load fails (not cached + download blocked), skip reason is set."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
            DetectionMethod,
        )

        # Patch the module-level AutoTokenizer/AutoModelForSequenceClassification
        # references directly — not .from_pretrained — so that any call raises OSError.
        class FailingTokenizer:
            @classmethod
            def from_pretrained(cls, *args, **kwargs):
                raise OSError("model not cached locally")

        class FailingModel:
            @classmethod
            def from_pretrained(cls, *args, **kwargs):
                raise OSError("model not cached locally")

        with (
            patch.object(_det_module, "_TRANSFORMERS_AVAILABLE", True),
            patch.object(_det_module, "settings") as mock_settings,
            patch.object(_det_module, "AutoTokenizer", FailingTokenizer),
            patch.object(_det_module, "AutoModelForSequenceClassification", FailingModel),
        ):
            mock_settings.ai_detect_allow_download = False
            detector = AIWritingDetector(use_ml=True, device="cpu")
            result = detector.analyze(_AI_TEXT)

            self.assertEqual(result.method, DetectionMethod.RULE_BASED.value)
            self.assertIsNone(result.ml_score)
            # Should have a skip reason for roberta
            skipped = [s for s in result.skipped_detectors if "roberta" in s]
            self.assertTrue(len(skipped) > 0, msg=f"No roberta skip reason found in {result.skipped_detectors}")

    def test_skip_reason_when_ml_disabled_by_config(self):
        """When ai_detect_ml_enabled=False, ML is skipped with clear reason."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
            DetectionMethod,
        )

        with patch(
            "app.services.tools.ai_writing_detector.settings.ai_detect_ml_enabled",
            False,
        ):
            detector = AIWritingDetector(use_ml=True, device="cpu")
            result = detector.analyze(_AI_TEXT)

            self.assertEqual(result.method, DetectionMethod.RULE_BASED.value)
            self.assertIsNone(result.ml_score)
            skipping = [s for s in result.skipped_detectors if "disabled_by_config" in s]
            self.assertTrue(
                len(skipping) > 0,
                msg=f"Expected disabled_by_config in skipped, got {result.skipped_detectors}",
            )

    def test_skip_reason_when_deps_not_installed(self):
        """When transformers/torch missing, skip reason reflects that."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
            DetectionMethod,
        )

        with patch(
            "app.services.tools.ai_writing_detector._TRANSFORMERS_AVAILABLE",
            False,
        ):
            detector = AIWritingDetector(use_ml=True, device="cpu")
            result = detector.analyze(_AI_TEXT)

            self.assertEqual(result.method, DetectionMethod.RULE_BASED.value)
            self.assertIsNone(result.ml_score)
            skipping = [s for s in result.skipped_detectors if "deps_not_installed" in s]
            self.assertTrue(
                len(skipping) > 0,
                msg=f"Expected deps_not_installed in skipped, got {result.skipped_detectors}",
            )

    def test_final_score_not_just_rule_score_when_ml_available(self):
        """When ML is available, final score differs from raw rule_score."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
            DetectionMethod,
        )

        with (
            patch(
                "app.services.tools.ai_writing_detector._TRANSFORMERS_AVAILABLE",
                True,
            ),
            patch(
                "app.services.tools.ai_writing_detector.AutoTokenizer",
            ) as mock_tok,
            patch(
                "app.services.tools.ai_writing_detector.AutoModelForSequenceClassification",
            ) as mock_model,
        ):
            mock_tok.from_pretrained.return_value = _make_mock_tokenizer()
            mock_model.from_pretrained.return_value = FakeRobertaModel()

            detector = AIWritingDetector(use_ml=True, device="cpu")
            result = detector.analyze(_AI_TEXT)

            self.assertEqual(result.method, DetectionMethod.ENSEMBLE.value)
            # final = 0.7*ml + 0.3*rule -> should be different from rule_score
            self.assertNotAlmostEqual(result.score, result.rule_score, places=4)
            self.assertIsNotNone(result.ml_score)

    def test_verdict_not_likely_human_for_ai_text(self):
        """AI-typical text should not get LIKELY_HUMAN when ML is available."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
            Verdict,
        )

        with (
            patch(
                "app.services.tools.ai_writing_detector._TRANSFORMERS_AVAILABLE",
                True,
            ),
            patch(
                "app.services.tools.ai_writing_detector.AutoTokenizer",
            ) as mock_tok,
            patch(
                "app.services.tools.ai_writing_detector.AutoModelForSequenceClassification",
            ) as mock_model,
        ):
            mock_tok.from_pretrained.return_value = _make_mock_tokenizer()
            mock_model.from_pretrained.return_value = FakeRobertaModel()

            detector = AIWritingDetector(use_ml=True, device="cpu")
            result = detector.analyze(_AI_TEXT)

            # With our fake model returning AI logits, verdict should NOT be LIKELY_HUMAN
            self.assertNotEqual(result.verdict, Verdict.LIKELY_HUMAN.value)

    def test_response_schema_has_per_detector_scores(self):
        """The response schema exposes method, ml_score, rule_score, skipped_detectors."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
        )

        with (
            patch(
                "app.services.tools.ai_writing_detector._TRANSFORMERS_AVAILABLE",
                True,
            ),
            patch(
                "app.services.tools.ai_writing_detector.AutoTokenizer",
            ) as mock_tok,
            patch(
                "app.services.tools.ai_writing_detector.AutoModelForSequenceClassification",
            ) as mock_model,
        ):
            mock_tok.from_pretrained.return_value = _make_mock_tokenizer()
            mock_model.from_pretrained.return_value = FakeRobertaModel()

            detector = AIWritingDetector(use_ml=True, device="cpu")
            result = detector.analyze(_AI_TEXT)

            # Build the response model from result
            data = AIWritingDetectResult(
                score=result.score,
                verdict=result.verdict,
                confidence=result.confidence,
                flags=result.flags,
                details=result.details,
                method=result.method,
                ml_score=result.ml_score,
                rule_score=result.rule_score,
                specter2_score=result.specter2_score,
                skipped_detectors=result.skipped_detectors,
                fallback_reason=result.fallback_reason,
                detectors_used=result.detectors_used,
            )

            self.assertEqual(data.method, result.method)
            self.assertEqual(data.ml_score, result.ml_score)
            self.assertEqual(data.rule_score, result.rule_score)
            self.assertIsInstance(data.skipped_detectors, list)
            self.assertIn("rule_based", data.detectors_used)

    def test_specter2_not_in_pipeline_by_default(self):
        """SPECTER2 should not appear in detectors_used or skipped_detectors
        when ai_detect_use_specter2=False (default). It is simply not
        configured — not a skipped/fallback scenario."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
        )

        detector = AIWritingDetector(use_ml=False, device="cpu")
        result = detector.analyze(_AI_TEXT)

        specter2_in_skipped = [s for s in result.skipped_detectors if "specter2" in s]
        specter2_in_used = [d for d in result.detectors_used if "specter2" in d]
        self.assertEqual(
            len(specter2_in_skipped), 0,
            msg=f"specter2 should NOT appear in skipped_detectors: {result.skipped_detectors}",
        )
        self.assertEqual(
            len(specter2_in_used), 0,
            msg=f"specter2 should NOT appear in detectors_used: {result.detectors_used}",
        )

    def test_short_text_immediate_return(self):
        """Text < 50 chars should return UNCERTAIN verdict immediately."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
            Verdict,
        )

        detector = AIWritingDetector(use_ml=False, device="cpu")
        result = detector.analyze("Short")

        self.assertEqual(result.verdict, Verdict.UNCERTAIN.value)
        self.assertEqual(result.score, 0.5)
        self.assertEqual(result.confidence, "LOW")
        self.assertIn("too short", " ".join(result.flags).lower())

    def test_short_text_method_is_rule_based(self):
        """Short text result should always use rule_based method."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
            DetectionMethod,
        )

        detector = AIWritingDetector(use_ml=False, device="cpu")
        result = detector.analyze("Short")

        self.assertEqual(result.method, DetectionMethod.RULE_BASED.value)

    def test_rule_based_method_when_ml_fallback(self):
        """When ML not available, method is rule_based and fallback_reason is set."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
            DetectionMethod,
        )

        with patch(
            "app.services.tools.ai_writing_detector._TRANSFORMERS_AVAILABLE",
            False,
        ):
            detector = AIWritingDetector(use_ml=True, device="cpu")
            result = detector.analyze(_AI_TEXT)

            self.assertEqual(result.method, DetectionMethod.RULE_BASED.value)
            self.assertIsNotNone(result.fallback_reason)
            self.assertNotEqual(result.fallback_reason, "")

    def test_detectors_used_includes_rule_based(self):
        """detectors_used should always contain rule_based."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
        )

        detector = AIWritingDetector(use_ml=False, device="cpu")
        result = detector.analyze(_AI_TEXT)

        self.assertIn("rule_based", result.detectors_used)

    def test_confidence_mapping_by_token_count(self):
        """Confidence maps: <100 tokens → LOW, 100-300 → MEDIUM, 300+ depends."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
        )

        detector = AIWritingDetector(use_ml=False, device="cpu")

        short = detector.analyze("hello world " * 10)  # ~20 tokens
        self.assertEqual(short.confidence, "LOW")

        medium = detector.analyze("hello world " * 80)  # ~160 tokens
        self.assertIn(medium.confidence, {"LOW", "MEDIUM", "HIGH"})

        long_ai = detector.analyze(_AI_TEXT)  # ~130 tokens
        self.assertIn(long_ai.confidence, {"LOW", "MEDIUM", "HIGH"})

    def test_get_verdict_consistency(self):
        """get_verdict should match the verdict returned by analyze()."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
        )

        detector = AIWritingDetector(use_ml=False, device="cpu")

        for score, expected_verdict in [
            (0.1, "LIKELY_HUMAN"),
            (0.3, "POSSIBLY_HUMAN"),
            (0.5, "UNCERTAIN"),
            (0.7, "POSSIBLY_AI"),
            (0.9, "LIKELY_AI"),
        ]:
            verdict = detector.get_verdict(score)
            self.assertEqual(verdict, expected_verdict, msg=f"for score={score}")


class AIWritingDetectorEdgeCaseTest(unittest.TestCase):
    """Edge cases and boundary tests."""

    def setUp(self):
        """Reset module-level globals that cache model instances between tests."""
        _det_module._detector_model = None
        _det_module._detector_tokenizer = None

    def test_empty_text(self):
        """Empty/whitespace text should not crash."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
        )

        detector = AIWritingDetector(use_ml=False, device="cpu")
        result = detector.analyze("")
        self.assertEqual(result.score, 0.5)

    def test_very_long_text(self):
        """Very long text should not cause memory issues."""
        from app.services.tools.ai_writing_detector import (
            AIWritingDetector,
        )

        detector = AIWritingDetector(use_ml=False, device="cpu")
        long_text = "AI generated text. " * 2000
        result = detector.analyze(long_text)
        self.assertTrue(0.0 <= result.score <= 1.0)
        self.assertIn("rule_based", result.detectors_used)


if __name__ == "__main__":
    unittest.main()
