"""
AI Writing Detector — rule-based + optional RoBERTa ML ensemble.

Detection pipeline:
1. RoBERTa GPT-2 detector  (when ``transformers`` + ``torch`` installed)
2. Rule-based heuristics    (always available as fallback / standalone)
3. Ensemble of both         (when ML is available)
"""

import re
import math
import logging
import os
import shutil
import signal
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from enum import Enum

from app.core.config import settings

logger = logging.getLogger(__name__)
_backend_root = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Optional heavy deps – guard every import
# ---------------------------------------------------------------------------
_TRANSFORMERS_AVAILABLE = False
_detector_model = None
_detector_tokenizer = None

try:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore[import-untyped]
    import torch
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    AutoModelForSequenceClassification = None  # type: ignore[assignment,misc]
    AutoTokenizer = None                       # type: ignore[assignment,misc]
    torch = None                               # type: ignore[assignment]

_NP_AVAILABLE = False
try:
    import numpy as np
    _NP_AVAILABLE = True
except ImportError:
    np = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DetectionMethod(str, Enum):
    ROBERTA = "roberta_gpt2_detector"
    RULE_BASED = "rule_based_heuristics"
    ENSEMBLE = "ensemble"
    ACADEMIC_SPECTER2 = "academic_specter2_detector"


class Verdict(str, Enum):
    LIKELY_HUMAN = "LIKELY_HUMAN"
    POSSIBLY_HUMAN = "POSSIBLY_HUMAN"
    UNCERTAIN = "UNCERTAIN"
    POSSIBLY_AI = "POSSIBLY_AI"
    LIKELY_AI = "LIKELY_AI"


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

AI_PATTERNS = [
    r"(?:as|in)\s+(?:an|the)\s+AI\s+(?:language\s+)?model",
    r"(?:I\s+)?(?:cannot|can't)\s+(?:provide|give|offer|generate)",
    r"(?:it'?s?\s+)?(?:important|worth)\s+(?:to\s+)?(?:note|mention|consider|emphasize)",
    r"(?:in\s+)?(?:conclusion|summary),?\s+(?:it\s+)?(?:can\s+be\s+)?(?:said|concluded|observed)",
    r"(?:this|the)\s+(?:study|research|paper|article)\s+(?:aims|seeks|attempts|endeavors)",
    r"(?:moreover|furthermore|additionally|consequently),?\s+(?:it\s+)?(?:is|can|may|should)",
    r"delve(?:s)?\s+(?:into|deeper)",
    r"(?:a\s+)?plethora\s+of",
    r"(?:a\s+)?myriad\s+of",
    r"multifaceted",
    r"(?:plays?\s+)?(?:a\s+)?(?:crucial|pivotal|vital|paramount)\s+role",
    r"(?:in\s+)?(?:today['']?s|the\s+modern|contemporary)\s+(?:world|society|era|landscape)",
    r"(?:it\s+is\s+)?(?:essential|imperative|crucial)\s+(?:to|that)",
    r"(?:this\s+)?(?:phenomenon|concept|notion|paradigm)\s+(?:has|is)",
    r"(?:as\s+)?(?:such|mentioned|stated|noted)\s+(?:above|earlier|previously|before)",
    r"(?:the\s+)?(?:landscape|realm|domain|sphere)\s+of",
    r"(?:shed(?:s)?\s+)?light\s+on",
    r"(?:to\s+)?navigate\s+(?:the\s+)?(?:complex(?:ities)?|challenges?|intricacies)",
    r"(?:the\s+)?(?:ever-(?:changing|evolving)|rapidly\s+(?:changing|evolving))",
    r"embark(?:s|ed|ing)?\s+on\s+(?:a\s+)?(?:journey|exploration|quest)",
    r"(?:a\s+)?(?:comprehensive|holistic|nuanced|thorough)\s+(?:understanding|approach|analysis|examination)",
    r"(?:in\s+)?(?:the\s+)?realm\s+of",
    r"(?:serves?\s+as\s+)?(?:a\s+)?testament\s+to",
    r"(?:at\s+)?(?:the\s+)?(?:forefront|cutting\s+edge)\s+of",
    r"paradigm\s+shift",
    r"(?:a\s+)?game[- ]?changer",
    r"unlock(?:s|ing)?\s+(?:the\s+)?(?:potential|possibilities)",
    r"transformative\s+(?:impact|effect|power)",
    r"(?:robust|seamless|streamlined)\s+(?:solution|approach|framework)",
    r"leverage(?:s|d|ing)?\s+(?:the\s+)?(?:power|potential|capabilities)",
]

TRANSITION_PHRASES = [
    "however", "moreover", "furthermore", "additionally", "consequently",
    "nevertheless", "nonetheless", "therefore", "thus", "hence",
    "in contrast", "on the other hand", "conversely", "similarly",
    "in addition", "as a result", "for instance", "in particular",
    "specifically", "notably", "importantly", "significantly",
    "interestingly", "surprisingly", "remarkably", "ultimately",
]

FILLER_PHRASES = [
    "it is important to note that",
    "it should be noted that",
    "it is worth mentioning that",
    "it is essential to understand that",
    "it goes without saying that",
    "needless to say",
    "as we can see",
    "as mentioned earlier",
    "as previously stated",
    "in other words",
    "to put it simply",
    "in essence",
    "at the end of the day",
    "all things considered",
    "taking everything into account",
    "with this in mind",
    "having said that",
    "that being said",
    "it is no secret that",
    "one cannot deny that",
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DetectionResult:
    """Result of AI writing detection analysis.

    ``score``, ``confidence``, ``flags``, ``details`` are kept for
    backward compatibility with ``AIWritingDetectResult`` schema.
    Additional fields expose per-detector scores and pipeline info.
    """
    score: float             # 0.0 (human) -> 1.0 (AI)
    confidence: str          # LOW | MEDIUM | HIGH
    flags: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    verdict: str = "UNCERTAIN"
    method: str = "rule_based_heuristics"
    ml_score: float | None = None
    rule_score: float = 0.0
    specter2_score: float | None = None
    skipped_detectors: list[str] = field(default_factory=list)
    fallback_reason: str | None = None
    detectors_used: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class AIWritingDetector:
    """
    AI writing detector with optional ML ensemble.

    * When ``transformers`` + ``torch`` are installed, uses RoBERTa GPT-2
      detector in ensemble with rule-based heuristics (70/30 weight).
    * Otherwise, uses rule-based heuristics only.
    """

    def __init__(self, use_ml: bool = True, device: str = "auto") -> None:
        self._use_ml = use_ml and settings.ai_detect_ml_enabled and _TRANSFORMERS_AVAILABLE
        self._use_specter2 = settings.ai_detect_use_specter2
        self._model = None
        self._tokenizer = None
        self._device = None
        self._model_load_attempted = False
        self._requested_device = device

        self._ai_patterns = [re.compile(p, re.IGNORECASE) for p in AI_PATTERNS]
        self._filler_patterns = [re.compile(re.escape(p), re.IGNORECASE) for p in FILLER_PHRASES]

    def _ensure_cache_dir(self) -> None:
        cache_root = (_backend_root / settings.hf_cache_dir).resolve()
        cache_root.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(cache_root))
        # TRANSFORMERS_CACHE is deprecated in favour of HF_HOME/hub.
        # We intentionally do NOT set it so that huggingface_hub places
        # downloaded files under HF_HOME/hub/ where local_files_only=True
        # will find them.

    def _ensure_model(self) -> None:
        if not self._use_ml or self._model is not None or self._model_load_attempted:
            return
        self._model_load_attempted = True
        self._load_model(self._requested_device)

    @staticmethod
    def _clean_partial_cache(model_name: str) -> None:
        """Remove partial / corrupted cache entries for *model_name*.

        Without this, a partially-downloaded model can leave config files
        but missing weights, causing ``local_files_only=True`` to crash
        on ``AttributeError`` instead of raising a clean ``OSError``.
        """
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            slug = f"models--{model_name.replace('/', '--')}"
            # Check HF_HOME/hub/ (the huggingface_hub cache)
            for path in Path(hf_home, "hub").glob(f"{slug}*"):
                if path.exists():
                    logger.warning("Removing partial cache: %s", path)
                    shutil.rmtree(path)
            # Also check HF_HOME/ directly for legacy layouts
            for path in Path(hf_home).glob(f"{slug}*"):
                if path.exists():
                    logger.warning("Removing partial cache: %s", path)
                    shutil.rmtree(path)
        # Also check legacy TRANSFORMERS_CACHE
        legacy = os.environ.get("TRANSFORMERS_CACHE")
        if legacy:
            slug = f"models--{model_name.replace('/', '--')}"
            for path in Path(legacy).glob(f"{slug}*"):
                if path.exists():
                    logger.warning("Removing partial cache: %s", path)
                    shutil.rmtree(path)

    def _load_model(self, device: str) -> None:
        global _detector_model, _detector_tokenizer
        if _detector_model is not None:
            self._model = _detector_model
            self._tokenizer = _detector_tokenizer
            return
        try:
            logger.info("Loading RoBERTa GPT-2 detector...")
            self._ensure_cache_dir()
            if device == "auto":
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self._device = device
            model_name = settings.ai_detect_model_name
            try:
                self._tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    model_name, local_files_only=True
                )
            except OSError:
                if settings.ai_detect_allow_download:
                    logger.info(
                        "Model %s not cached, downloading (this may take a while)...",
                        model_name,
                    )
                    # Clean any partial artifacts before starting fresh
                    self._clean_partial_cache(model_name)
                    self._tokenizer = AutoTokenizer.from_pretrained(
                        model_name, local_files_only=False
                    )
                    self._model = AutoModelForSequenceClassification.from_pretrained(
                        model_name, local_files_only=False
                    )
                else:
                    raise
            except (AttributeError, RuntimeError) as cache_err:
                # Partial / corrupted cache: config files exist but weights missing
                logger.warning("Corrupted cache for %s: %s. Cleaning and retrying...", model_name, cache_err)
                self._clean_partial_cache(model_name)
                if settings.ai_detect_allow_download:
                    logger.info("Re-downloading %s ...", model_name)
                    self._tokenizer = AutoTokenizer.from_pretrained(
                        model_name, local_files_only=False
                    )
                    self._model = AutoModelForSequenceClassification.from_pretrained(
                        model_name, local_files_only=False
                    )
                else:
                    raise
            self._model.to(self._device)
            self._model.eval()
            _detector_model = self._model
            _detector_tokenizer = self._tokenizer
            logger.info("RoBERTa detector loaded on %s", self._device)
        except Exception as e:
            logger.warning("Failed to load RoBERTa detector: %s. Using rule-based only.", e)
            # Clean any partial artifacts so the next attempt starts fresh
            self._clean_partial_cache(settings.ai_detect_model_name)
            self._use_ml = False

    # -- text helpers ------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z]+", text.lower())

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        return [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]

    @staticmethod
    def _calculate_ttr(tokens: list[str]) -> float:
        if not tokens:
            return 0.0
        return len(set(tokens)) / len(tokens)

    @staticmethod
    def _calculate_hapax_ratio(tokens: list[str]) -> float:
        if not tokens:
            return 0.0
        freq = Counter(tokens)
        return sum(1 for c in freq.values() if c == 1) / len(freq) if freq else 0.0

    @staticmethod
    def _sentence_length_uniformity(sentences: list[str]) -> float:
        if len(sentences) < 2:
            return 0.0
        lengths = [len(s.split()) for s in sentences]
        mean_len = sum(lengths) / len(lengths)
        if mean_len == 0:
            return 0.0
        variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
        cv = math.sqrt(variance) / mean_len
        if cv < 0.25:
            return 0.9
        if cv < 0.35:
            return 0.7
        if cv < 0.45:
            return 0.5
        if cv < 0.55:
            return 0.3
        return 0.1

    def _count_ai_patterns(self, text: str) -> tuple[int, list[str]]:
        count, found = 0, []
        for p in self._ai_patterns:
            ms = p.findall(text)
            if ms:
                count += len(ms)
                found.extend(ms[:2])
        return count, found[:10]

    def _count_filler_phrases(self, text: str) -> int:
        return sum(len(p.findall(text)) for p in self._filler_patterns)

    @staticmethod
    def _count_transitions(text: str) -> int:
        low = text.lower()
        return sum(low.count(p) for p in TRANSITION_PHRASES)

    @staticmethod
    def _detect_repetition(sentences: list[str]) -> float:
        if len(sentences) < 3:
            return 0.0
        starters = []
        for s in sentences:
            words = s.lower().split()[:3]
            if len(words) >= 2:
                starters.append(" ".join(words[:2]))
        if not starters:
            return 0.0
        freq = Counter(starters)
        repeated = sum(c - 1 for c in freq.values() if c > 1)
        return min(repeated / len(starters), 1.0)

    # -- ML analysis -------------------------------------------------------

    def _analyze_ml(self, text: str) -> float | None:
        self._ensure_model()
        if not self._use_ml or self._model is None:
            return None
        try:
            inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512, padding=True).to(self._device)
            with torch.no_grad():
                logits = self._model(**inputs).logits
                probs = torch.softmax(logits, dim=1)
                return probs[0][1].item()
        except Exception as e:
            logger.warning("ML analysis failed: %s", e)
            return None

    # -- academic (SPECTER2) analysis --------------------------------------

    def _analyze_academic(self, text: str) -> tuple[float | None, str | None]:
        """Use SPECTER2 embeddings to detect AI academic writing patterns.

        Returns (score, skip_reason).  When SPECTER2 is disabled or not
        ready, returns (None, reason_string).
        """
        if not self._use_specter2:
            return None, None  # not skipped, simply not configured
        try:
            from app.services.embeddings.specter2_service import specter2_service

            if not specter2_service.is_ready:
                return None, "specter2_service_not_ready"

            embedding = specter2_service.embed_text(text)
            if embedding is None:
                return None, "specter2_embedding_failed"

            # Lightweight heuristic on embedding norm / length as a proxy
            # for typical AI academic text patterns.
            import numpy as np  # already guarded at module level

            vec = np.array(embedding, dtype=np.float64)
            norm = float(np.linalg.norm(vec))
            entropy_estimate = (
                -np.sum((vec / (norm + 1e-12)) ** 2) / max(len(vec), 1)
            )
            score = max(0.0, min(1.0, 0.5 + (entropy_estimate + 0.02) * 2.0))
            return score, None
        except Exception as exc:
            logger.warning("SPECTER2 academic analysis failed: %s", exc)
            return None, f"specter2_error: {exc}"

    # -- rule-based analysis -----------------------------------------------

    def _analyze_rules(self, text: str) -> tuple[float, list[str], dict[str, Any]]:
        tokens = self._tokenize(text)
        sentences = self._split_sentences(text)

        if len(tokens) < 20:
            return 0.5, ["Text too short for reliable analysis"], {"word_count": len(tokens)}

        ttr = self._calculate_ttr(tokens)
        hapax = self._calculate_hapax_ratio(tokens)
        uniformity = self._sentence_length_uniformity(sentences)
        ai_cnt, ai_ex = self._count_ai_patterns(text)
        filler_cnt = self._count_filler_phrases(text)
        trans_cnt = self._count_transitions(text)
        rep_score = self._detect_repetition(sentences)

        wf = max(len(tokens) / 100, 1)
        n_ai = ai_cnt / wf
        n_fill = filler_cnt / wf
        n_trans = trans_cnt / wf

        flags: list[str] = []
        if n_ai >= 2:
            flags.append(f"Detected {ai_cnt} AI-typical phrases")
        if n_fill >= 1.5:
            flags.append(f"High filler phrase density ({filler_cnt} found)")
        if n_trans >= 4:
            flags.append(f"Excessive transition words ({trans_cnt} found)")
        if uniformity > 0.6:
            flags.append("Unusually uniform sentence lengths")
        if ttr < 0.35:
            flags.append("Low vocabulary diversity")
        if rep_score > 0.3:
            flags.append("Repetitive sentence structures detected")
        if hapax < 0.3:
            flags.append("Low unique word usage ratio")

        components = [
            (n_ai * 0.15, 0.25),
            (n_fill * 0.1, 0.15),
            (min(n_trans * 0.05, 0.3), 0.10),
            (uniformity, 0.20),
            (1.0 - min(ttr * 2, 1.0), 0.15),
            (rep_score, 0.10),
            (1.0 - min(hapax * 1.5, 1.0), 0.05),
        ]
        final = max(0.0, min(1.0, sum(min(v, 1.0) * w for v, w in components)))

        details = {
            "word_count": len(tokens),
            "sentence_count": len(sentences),
            "type_token_ratio": round(ttr, 3),
            "hapax_ratio": round(hapax, 3),
            "sentence_uniformity": round(uniformity, 3),
            "ai_patterns_found": ai_cnt,
            "ai_pattern_examples": ai_ex,
            "filler_count": filler_cnt,
            "transition_count": trans_cnt,
            "repetition_score": round(rep_score, 3),
        }
        return final, flags, details

    # -- public API --------------------------------------------------------

    def analyze(self, text: str) -> DetectionResult:
        """Analyze text for AI writing indicators using ensemble detection."""
        if len(text) < 50:
            return DetectionResult(
                score=0.5, confidence="LOW",
                flags=["Text too short for reliable analysis"],
                details={"reason": "insufficient_text"},
                verdict=Verdict.UNCERTAIN.value,
                method=DetectionMethod.RULE_BASED.value,
            )

        # Run all available detectors
        rule_score, flags, details = self._analyze_rules(text)
        ml_score = self._analyze_ml(text)
        specter2_score, specter2_skip_reason = self._analyze_academic(text)

        detectors_used = ["rule_based"]
        skipped_detectors: list[str] = []
        fallback_reason: str | None = None

        if ml_score is not None:
            detectors_used.append("roberta_gpt2_detector")
        else:
            if not settings.ai_detect_ml_enabled:
                skipped_detectors.append("roberta_gpt2_detector(disabled_by_config)")
            elif not _TRANSFORMERS_AVAILABLE:
                skipped_detectors.append("roberta_gpt2_detector(deps_not_installed)")
            else:
                skipped_detectors.append("roberta_gpt2_detector(model_not_available)")

        if specter2_score is not None:
            detectors_used.append("academic_specter2_detector")
        elif specter2_skip_reason:
            skipped_detectors.append(f"academic_specter2_detector({specter2_skip_reason})")

        # Ensemble scoring
        details["rule_raw_score"] = round(rule_score, 4)
        if ml_score is not None:
            details["ml_raw_score"] = round(ml_score, 4)

        w_ml = settings.ai_detect_ensemble_weight_ml
        w_rule = settings.ai_detect_ensemble_weight_rules

        if ml_score is not None and specter2_score is not None:
            w_specter2 = 0.2
            w_ml_adj = w_ml * (1.0 - w_specter2)
            w_rule_adj = w_rule * (1.0 - w_specter2)
            final = w_ml_adj * ml_score + w_rule_adj * rule_score + w_specter2 * specter2_score
            method = DetectionMethod.ENSEMBLE.value
        elif ml_score is not None:
            total_w = w_ml + w_rule
            final = (w_ml / total_w) * ml_score + (w_rule / total_w) * rule_score
            method = DetectionMethod.ENSEMBLE.value
        else:
            final = rule_score
            method = DetectionMethod.RULE_BASED.value
            if not _TRANSFORMERS_AVAILABLE:
                fallback_reason = "roberta_deps_not_installed"
            elif not settings.ai_detect_ml_enabled:
                fallback_reason = "roberta_disabled_by_config"
            elif self._model_load_attempted:
                fallback_reason = "roberta_model_load_failed"
            else:
                fallback_reason = "roberta_disabled_by_request"

        # verdict
        if final < 0.25:
            verdict = Verdict.LIKELY_HUMAN
        elif final < 0.40:
            verdict = Verdict.POSSIBLY_HUMAN
        elif final < 0.60:
            verdict = Verdict.UNCERTAIN
        elif final < 0.75:
            verdict = Verdict.POSSIBLY_AI
        else:
            verdict = Verdict.LIKELY_AI

        tokens = self._tokenize(text)
        if len(tokens) < 100:
            confidence = "LOW"
        elif len(tokens) < 300:
            confidence = "MEDIUM"
        else:
            confidence = "HIGH" if len(flags) >= 3 or final > 0.7 else "MEDIUM"

        return DetectionResult(
            score=round(final, 4),
            confidence=confidence,
            flags=flags,
            details=details,
            verdict=verdict.value,
            method=method,
            ml_score=round(ml_score, 4) if ml_score is not None else None,
            rule_score=round(rule_score, 4),
            specter2_score=round(specter2_score, 4) if specter2_score is not None else None,
            skipped_detectors=skipped_detectors,
            fallback_reason=fallback_reason,
            detectors_used=detectors_used,
        )

    def get_verdict(self, score: float) -> str:
        """Convert score to human-readable verdict string."""
        if score < 0.25:
            return Verdict.LIKELY_HUMAN.value
        if score < 0.40:
            return Verdict.POSSIBLY_HUMAN.value
        if score < 0.60:
            return Verdict.UNCERTAIN.value
        if score < 0.75:
            return Verdict.POSSIBLY_AI.value
        return Verdict.LIKELY_AI.value

    def analyze_chunks(self, text: str, chunk_size: int = 500) -> list[DetectionResult]:
        """Analyze text in chunks for longer documents."""
        words = text.split()
        chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size) if len(words[i:i + chunk_size]) >= 50]
        if not chunks:
            return [self.analyze(text)]
        return [self.analyze(c) for c in chunks]

    @property
    def is_ml_enabled(self) -> bool:
        return self._use_ml and self._model is not None

    @property
    def is_specter2_enabled(self) -> bool:
        return self._use_specter2

    @property
    def model_info(self) -> str:
        parts = []
        if self.is_ml_enabled:
            parts.append("RoBERTa GPT-2 OpenAI Detector")
        if self._use_specter2:
            parts.append("SPECTER2 Academic Detector")
        parts.append("Rule-based heuristics")
        return " + ".join(parts) if parts else "Rule-based heuristics only"


# Singleton
ai_writing_detector = AIWritingDetector(use_ml=True)
