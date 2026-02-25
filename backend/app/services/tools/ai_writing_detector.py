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
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from enum import Enum

logger = logging.getLogger(__name__)

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

    The fields ``score``, ``confidence``, ``flags``, ``details`` are kept
    for backward compatibility with the existing ``AIWritingDetectResult``
    schema & endpoint.  Extra fields are available for richer clients.
    """
    score: float             # 0.0 (human) -> 1.0 (AI)
    confidence: str          # LOW | MEDIUM | HIGH
    flags: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    # new enriched fields
    verdict: str = "UNCERTAIN"
    method: str = "rule_based_heuristics"
    ml_score: float | None = None
    rule_score: float = 0.0


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
        self._use_ml = use_ml and _TRANSFORMERS_AVAILABLE
        self._model = None
        self._tokenizer = None
        self._device = None

        self._ai_patterns = [re.compile(p, re.IGNORECASE) for p in AI_PATTERNS]
        self._filler_patterns = [re.compile(re.escape(p), re.IGNORECASE) for p in FILLER_PHRASES]

        if self._use_ml:
            self._load_model(device)

    def _load_model(self, device: str) -> None:
        global _detector_model, _detector_tokenizer
        if _detector_model is not None:
            self._model = _detector_model
            self._tokenizer = _detector_tokenizer
            return
        try:
            logger.info("Loading RoBERTa GPT-2 detector...")
            if device == "auto":
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self._device = device
            model_name = "roberta-base-openai-detector"
            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self._model.to(self._device)
            self._model.eval()
            _detector_model = self._model
            _detector_tokenizer = self._tokenizer
            logger.info("RoBERTa detector loaded on %s", self._device)
        except Exception as e:
            logger.warning("Failed to load RoBERTa detector: %s. Using rule-based only.", e)
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
        """Analyze text for AI writing indicators."""
        if len(text) < 50:
            return DetectionResult(
                score=0.5, confidence="LOW",
                flags=["Text too short for reliable analysis"],
                details={"reason": "insufficient_text"},
                verdict=Verdict.UNCERTAIN.value,
                method=DetectionMethod.RULE_BASED.value,
            )

        rule_score, flags, details = self._analyze_rules(text)
        ml_score = self._analyze_ml(text)

        if ml_score is not None:
            final = 0.7 * ml_score + 0.3 * rule_score
            method = DetectionMethod.ENSEMBLE.value
            details["ml_raw_score"] = round(ml_score, 4)
            details["rule_raw_score"] = round(rule_score, 4)
        else:
            final = rule_score
            method = DetectionMethod.RULE_BASED.value

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
    def model_info(self) -> str:
        if self.is_ml_enabled:
            return "RoBERTa GPT-2 OpenAI Detector"
        return "Rule-based heuristics only"


# Singleton
ai_writing_detector = AIWritingDetector(use_ml=True)
