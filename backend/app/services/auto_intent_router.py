from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from app.services.heuristic_router import _semantic_router
from app.services.tools.citation_checker import citation_checker


AUTO_MODE = "auto"

FEATURE_GENERAL_QA = "general_qa"
FEATURE_VERIFICATION = "verification"
FEATURE_JOURNAL_MATCH = "journal_match"
FEATURE_RETRACTION = "retraction"
FEATURE_AI_DETECTION = "ai_detection"
FEATURE_GRAMMAR = "grammar"
FEATURE_DOI_METADATA = "doi_metadata"

FEATURE_LABELS: dict[str, str] = {
    FEATURE_GENERAL_QA: "Hỏi đáp học thuật",
    FEATURE_VERIFICATION: "Xác minh trích dẫn",
    FEATURE_JOURNAL_MATCH: "Gợi ý tạp chí",
    FEATURE_RETRACTION: "Rà soát rút bài",
    FEATURE_AI_DETECTION: "Nhận diện văn bản AI",
    FEATURE_GRAMMAR: "Rà soát ngữ pháp",
    FEATURE_DOI_METADATA: "Phân tích DOI",
}

_CITATION_EXPLICIT_RE = re.compile(
    r"\b(citation|verify\s+citation|verify\s+doi|reference\s+check|bibliography"
    r"|trích\s*dẫn|xác\s*minh\s*trích\s*dẫn|kiểm\s*tra\s*tài\s*liệu\s*tham\s*khảo"
    r"|kiểm\s*tra\s*doi)\b",
    re.IGNORECASE,
)
_STRICT_CITATION_RE = re.compile(
    r"\b(citation|reference|bibliography|trích\s*dẫn|tài\s*liệu\s*tham\s*khảo)\b",
    re.IGNORECASE,
)
_JOURNAL_EXPLICIT_RE = re.compile(
    r"\b("
    r"gợi\s*ý\s*tạp\s*chí|đề\s*xuất\s*tạp\s*chí|tạp\s*chí\s+phù\s*hợp|"
    r"tìm\s*tạp\s*chí|nên\s+gửi\s+bài\s+ở\s+đâu|nên\s+nộp\s+tạp\s+chí\s+nào|"
    r"journal\s+suggestion|journals?\s+suggestion|"
    r"journal\s+recommendation|journals?\s+recommendation|"
    r"journal\s+matching|journals?\s+matching|"
    r"recommend\s+journal|suggest\s+journal|"
    r"where\s+should\s+i\s+submit|"
    r"nơi\s*nộp\s*bài|journal\s+match|journals?\s+match"
    r")\b",
    re.IGNORECASE,
)
_RETRACTION_EXPLICIT_RE = re.compile(
    r"\b(retract(?:ion|ed)?|pubpeer|withdrawn|expression\s+of\s+concern"
    r"|rút\s*bài|thu\s*hồi|bị\s*rút|quét\s*retraction)\b",
    re.IGNORECASE,
)
_AI_HINT_RE = re.compile(
    r"\b(ai writing|detect ai|ai detection|chatgpt|gpt viết|ai viết|máy viết"
    r"|phát hiện ai|kiểm tra ai)\b",
    re.IGNORECASE,
)
_GRAMMAR_HINT_RE = re.compile(
    r"\b(grammar|proofread|spelling|typo|spell check|ngữ pháp|chính tả"
    r"|sửa lỗi|chỉnh sửa văn bản|kiểm tra lỗi)\b",
    re.IGNORECASE,
)
_DOI_METADATA_REQUEST_RE = re.compile(
    r"\b("
    r"analyze|phân\s*tích|provide|show|extract|list|"
    r"authors?|tác\s*giả|tac\s*gia|"
    r"thông\s*tin\s+về|thong\s*tin\s+ve|information\s+about|"
    r"doi\s+info|doi\s+metadata|metadata\s+doi|metadata|paper\s+info|"
    r"abstract|summary|title|journal|publisher|publication\s*year|"
    r"research\s*field|lĩnh\s*vực|main\s*topic|chủ\s*đề"
    r")\b",
    re.IGNORECASE,
)
_DOI_AUTHOR_PUBLICATION_RE = re.compile(
    r"(?:\b(?:authors?|tác\s*giả|tac\s*gia)\b(?:[^\n]{0,80}?)"
    r"\b(?:publication(?:s)?|paper(?:s)?|works?|bài\s*báo|bai\s*bao|công\s*trình|cong\s*trinh)\b)|"
    r"(?:\b(?:publication(?:s)?|paper(?:s)?|works?|bài\s*báo|bai\s*bao|công\s*trình|cong\s*trinh)\b"
    r"(?:[^\n]{0,80}?)\b(?:authors?|tác\s*giả|tac\s*gia)\b)",
    re.IGNORECASE,
)
_AUTHOR_PUBLICATION_QUERY_RE = re.compile(
    r"(?:\b(?:publication(?:s)?|paper(?:s)?|works?|bài\s*báo|bai\s*bao|công\s*trình|cong\s*trinh)\b"
    r"(?:[^\n]{0,40}?)\b(?:của|cua|by)\s+[A-Za-zÀ-ỹ])|"
    r"(?:^[A-ZÀ-Ỹ][^\n]{2,120}\s+(?:có|co|has|have)\s+"
    r"(?:những|nhung|các|cac|all|bao\s+nhieu|bao\s+nhiêu|what|which)?\s*"
    r"(?:publication(?:s)?|paper(?:s)?|works?|bài\s*báo|bai\s*bao|công\s*trình|cong\s*trinh)\b)|"
    r"(?:\b(?:tất\s*cả|tat\s*ca|all)\b(?:[^\n]{0,30}?)"
    r"\b(?:publication(?:s)?|paper(?:s)?|works?|bài\s*báo|bai\s*bao|công\s*trình|cong\s*trinh)\b"
    r"(?:[^\n]{0,30}?)\b(?:mà|ma|by)\s+[A-Za-zÀ-ỹ])",
    re.IGNORECASE,
)
_ACADEMIC_QA_IDENTIFIER_RE = re.compile(
    r"\b("
    r"tác\s*giả|tac\s*gia|authors?|"
    r"publication(?:s)?|paper(?:s)?|works?|"
    r"bài\s*báo\s+khác|bai\s*bao\s*khac|paper\s+khác|paper\s+khac|"
    r"công\s*trình\s+khác|cong\s*trinh\s*khac|"
    r"other\s+papers?|related\s+works?|"
    r"venue|journal|nội\s*dung|noi\s*dung|"
    r"phương\s*pháp|phuong\s*phap|kết\s*quả|ket\s*qua"
    r")\b",
    re.IGNORECASE,
)
_GENERAL_DISCUSSION_RE = re.compile(
    r"\b("
    r"hướng\s*nghiên\s*cứu|huong\s*nghien\s*cuu|"
    r"tiềm\s*năng|tiem\s*nang|potential|"
    r"research\s+direction|research\s+trend|"
    r"nghiên\s*cứu\s+về|nghien\s*cuu\s*ve|"
    r"nên\s+nghiên\s*cứu|nen\s+nghien\s*cuu|"
    r"lĩnh\s*vực|linh\s*vuc|field\s+of\s+research|"
    r"phương\s*pháp|phuong\s*phap|methodology|"
    r"brainstorm|ý\s*tưởng|y\s+tuong|idea|"
    r"chủ\s*đề|chu\s*de|topic|"
    r"tư\s*vấn|tu\s+van|advise|"
    r"nhận\s*định|nhan\s*dinh|assessment\s+of|"
    r"\btrend\b|\btopic\b"
    r")\b",
    re.IGNORECASE,
)

_SEMANTIC_INTENT_TO_FEATURE: dict[str, str] = {
    "retraction": FEATURE_RETRACTION,
    "citation": FEATURE_VERIFICATION,
    "journal": FEATURE_JOURNAL_MATCH,
    "ai_detect": FEATURE_AI_DETECTION,
    "grammar": FEATURE_GRAMMAR,
}

_TOOLISH_HINT_RE = re.compile(
    r"|".join(
        [
            _CITATION_EXPLICIT_RE.pattern,
            _JOURNAL_EXPLICIT_RE.pattern,
            _RETRACTION_EXPLICIT_RE.pattern,
            _AI_HINT_RE.pattern,
            _GRAMMAR_HINT_RE.pattern,
            r"10\.\d{4,9}/",
            r"\bdoi\b",
            r"\bpmid\b",
            r"\bpmcid\b",
        ]
    ),
    re.IGNORECASE,
)

_SEMANTIC_SELECT_THRESHOLD = 0.55
_SEMANTIC_AMBIGUOUS_THRESHOLD = 0.35
_SEMANTIC_GAP_THRESHOLD = 0.15


@dataclass(frozen=True)
class AutoIntentCandidate:
    feature: str
    label: str
    confidence: float
    source: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AutoIntentResult:
    resolved_feature: str
    resolved_label: str
    confidence: float
    source: str
    candidates: list[AutoIntentCandidate]
    is_ambiguous: bool = False

    def to_routing_dict(self) -> dict[str, object]:
        return {
            "requested_mode": AUTO_MODE,
            "resolved_feature": self.resolved_feature,
            "resolved_label": self.resolved_label,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "is_ambiguous": self.is_ambiguous,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class AutoIntentRouter:
    def resolve(self, user_text: str, *, has_file_context: bool = False) -> AutoIntentResult:
        normalized = (user_text or "").strip()
        if not normalized:
            return self._result(FEATURE_GENERAL_QA, 0.0, "empty_prompt")

        doi_count = len(citation_checker.extract_dois(normalized))
        has_exact_identifier = bool(citation_checker.extract_exact_identifiers(normalized))

        if doi_count and _DOI_AUTHOR_PUBLICATION_RE.search(normalized):
            return self._result(FEATURE_GENERAL_QA, 0.92, "doi_author_publication_regex")

        if doi_count and _DOI_METADATA_REQUEST_RE.search(normalized) and not _AUTHOR_PUBLICATION_QUERY_RE.search(normalized):
            return self._result(FEATURE_DOI_METADATA, 1.0, "doi_metadata_regex")

        explicit_candidates = self._explicit_candidates(normalized)
        if len(explicit_candidates) > 1:
            return self._ambiguous(explicit_candidates, "explicit_multi_signal")
        if explicit_candidates:
            return self._candidate_result(explicit_candidates[0])

        if (doi_count or has_exact_identifier) and _ACADEMIC_QA_IDENTIFIER_RE.search(normalized):
            return self._result(FEATURE_GENERAL_QA, 0.9, "identifier_academic_qa_regex")

        if _AUTHOR_PUBLICATION_QUERY_RE.search(normalized):
            return self._result(FEATURE_GENERAL_QA, 0.9, "author_publication_regex")

        if doi_count or has_exact_identifier:
            return self._result(FEATURE_VERIFICATION, 0.96, "exact_identifier_default")

        if _GENERAL_DISCUSSION_RE.search(normalized):
            return self._result(FEATURE_GENERAL_QA, 0.78, "general_discussion_regex")

        semantic_candidates = self._semantic_candidates(normalized)
        if semantic_candidates:
            top = semantic_candidates[0]
            second = semantic_candidates[1] if len(semantic_candidates) > 1 else None
            toolish = self._looks_toolish(normalized, has_file_context=has_file_context)

            if top.confidence >= _SEMANTIC_SELECT_THRESHOLD and not self._is_close_second(top, second):
                return self._candidate_result(top, source="semantic_router")

            if toolish and (
                top.confidence >= _SEMANTIC_AMBIGUOUS_THRESHOLD
                or (second is not None and second.confidence >= _SEMANTIC_AMBIGUOUS_THRESHOLD)
            ):
                return self._ambiguous(semantic_candidates[:3], "semantic_ambiguous")

        return self._result(FEATURE_GENERAL_QA, 0.62, "general_fallback")

    def _explicit_candidates(self, text: str) -> list[AutoIntentCandidate]:
        candidates: list[AutoIntentCandidate] = []
        citation_match = _CITATION_EXPLICIT_RE.search(text)
        retraction_match = _RETRACTION_EXPLICIT_RE.search(text)
        keep_citation = bool(citation_match)
        if citation_match and retraction_match and not _STRICT_CITATION_RE.search(text):
            keep_citation = False

        if _JOURNAL_EXPLICIT_RE.search(text):
            candidates.append(self._candidate(FEATURE_JOURNAL_MATCH, 1.0, "journal_regex"))
        if keep_citation:
            candidates.append(self._candidate(FEATURE_VERIFICATION, 1.0, "citation_regex"))
        if retraction_match:
            candidates.append(self._candidate(FEATURE_RETRACTION, 1.0, "retraction_regex"))
        if _AI_HINT_RE.search(text):
            candidates.append(self._candidate(FEATURE_AI_DETECTION, 1.0, "ai_regex"))
        if _GRAMMAR_HINT_RE.search(text):
            candidates.append(self._candidate(FEATURE_GRAMMAR, 1.0, "grammar_regex"))
        return self._dedupe_candidates(candidates)

    def _semantic_candidates(self, text: str) -> list[AutoIntentCandidate]:
        ranked = _semantic_router.score_all(text)
        candidates: list[AutoIntentCandidate] = []
        for intent, score in ranked:
            feature = _SEMANTIC_INTENT_TO_FEATURE.get(intent)
            if not feature:
                continue
            candidates.append(self._candidate(feature, score, "semantic_router"))
        return self._dedupe_candidates(candidates)

    @staticmethod
    def _looks_toolish(text: str, *, has_file_context: bool) -> bool:
        if _TOOLISH_HINT_RE.search(text):
            return True
        return has_file_context and len(text.strip()) >= 120

    @staticmethod
    def _is_close_second(
        top: AutoIntentCandidate,
        second: AutoIntentCandidate | None,
    ) -> bool:
        if second is None:
            return False
        return (top.confidence - second.confidence) < _SEMANTIC_GAP_THRESHOLD

    @staticmethod
    def _dedupe_candidates(candidates: list[AutoIntentCandidate]) -> list[AutoIntentCandidate]:
        best: dict[str, AutoIntentCandidate] = {}
        for candidate in candidates:
            existing = best.get(candidate.feature)
            if existing is None or candidate.confidence > existing.confidence:
                best[candidate.feature] = candidate
        return sorted(best.values(), key=lambda item: item.confidence, reverse=True)

    def _candidate_result(
        self,
        candidate: AutoIntentCandidate,
        *,
        source: str | None = None,
    ) -> AutoIntentResult:
        return AutoIntentResult(
            resolved_feature=candidate.feature,
            resolved_label=candidate.label,
            confidence=candidate.confidence,
            source=source or candidate.source,
            candidates=[candidate],
            is_ambiguous=False,
        )

    def _result(self, feature: str, confidence: float, source: str) -> AutoIntentResult:
        candidate = self._candidate(feature, confidence, source)
        return self._candidate_result(candidate)

    def _ambiguous(
        self,
        candidates: list[AutoIntentCandidate],
        source: str,
    ) -> AutoIntentResult:
        ranked = self._dedupe_candidates(candidates)[:3]
        top = ranked[0]
        return AutoIntentResult(
            resolved_feature=top.feature,
            resolved_label=top.label,
            confidence=top.confidence,
            source=source,
            candidates=ranked,
            is_ambiguous=True,
        )

    @staticmethod
    def _candidate(feature: str, confidence: float, source: str) -> AutoIntentCandidate:
        return AutoIntentCandidate(
            feature=feature,
            label=FEATURE_LABELS.get(feature, feature),
            confidence=float(confidence),
            source=source,
        )


auto_intent_router = AutoIntentRouter()
