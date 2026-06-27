from __future__ import annotations

from datetime import datetime
from typing import Any, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.ai_detection_rule import RuleScope, RuleSeverity, RuleType


ConditionScope = Literal["sentence", "paragraph", "document"]
RuleOperator = Literal["AND", "OR"]
SemanticThreshold = Literal["low", "medium", "high"]
AnalyzeMode = Literal["fast", "deep", "rule_only"]
RiskLevel = Literal["low", "medium", "high"]


class RuleAction(BaseModel):
    flag: bool = True
    message: str | None = None


class PhraseCondition(BaseModel):
    kind: Literal["phrase", "phrase_group"]
    phrase: str | None = None
    phrases: list[str] = Field(default_factory=list)
    threshold: int = Field(default=1, ge=1, le=20)
    scope: ConditionScope = "paragraph"

    @model_validator(mode="after")
    def _validate_phrase_payload(self) -> "PhraseCondition":
        if self.kind == "phrase":
            value = (self.phrase or "").strip()
            if not value:
                raise ValueError("phrase condition requires a non-empty phrase")
            self.phrase = value
            self.phrases = [value]
        else:
            normalized = [phrase.strip() for phrase in self.phrases if phrase.strip()]
            if not normalized:
                raise ValueError("phrase_group requires at least one phrase")
            self.phrases = normalized
            if self.phrase and self.phrase.strip():
                self.phrases.insert(0, self.phrase.strip())
                deduped: list[str] = []
                seen: set[str] = set()
                for phrase in self.phrases:
                    key = phrase.casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(phrase)
                self.phrases = deduped
        return self


class RegexCondition(BaseModel):
    kind: Literal["regex"]
    pattern: str = Field(min_length=1)
    threshold: int = Field(default=1, ge=1, le=20)
    scope: ConditionScope = "paragraph"
    flags: list[Literal["IGNORECASE", "MULTILINE", "DOTALL"]] = Field(default_factory=lambda: ["IGNORECASE"])


class SemanticCondition(BaseModel):
    kind: Literal["semantic"]
    instruction: str = Field(min_length=1)
    threshold: SemanticThreshold = "medium"
    scope: ConditionScope = "paragraph"


class MetricCondition(BaseModel):
    kind: Literal["metric"]
    metric: Literal[
        "sentence_uniformity_above",
        "type_token_ratio_below",
        "transition_density_above",
        "repetition_score_above",
    ]
    value: float = Field(ge=0.0, le=1.0)
    scope: ConditionScope = "paragraph"


class MissingCitationCondition(BaseModel):
    kind: Literal["missing_citation"]
    scope: ConditionScope = "paragraph"
    min_words: int = Field(default=50, ge=20, le=400)
    threshold: int = Field(default=1, ge=1, le=10)


class RepeatedStructureCondition(BaseModel):
    kind: Literal["repeated_structure"]
    scope: ConditionScope = "paragraph"
    threshold: float = Field(default=0.3, ge=0.1, le=1.0)


RuleCondition = Annotated[
    PhraseCondition
    | RegexCondition
    | SemanticCondition
    | MetricCondition
    | MissingCitationCondition
    | RepeatedStructureCondition,
    Field(discriminator="kind"),
]


class CompiledAIDetectionRule(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    rule_type: RuleType
    severity: RuleSeverity = RuleSeverity.MEDIUM
    weight: float = Field(default=0.2, ge=0.0, le=1.0)
    conditions: list[RuleCondition] = Field(default_factory=list)
    operator: RuleOperator = "OR"
    action: RuleAction = Field(default_factory=RuleAction)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None


class AIDetectionRuleCompileRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=4000)


class AIDetectionRuleCompileResponse(BaseModel):
    compiled_rule: CompiledAIDetectionRule
    warnings: list[str] = Field(default_factory=list)


class AIDetectionRuleCreateRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=4000)
    compiled_rule: CompiledAIDetectionRule | None = None
    scope: RuleScope = RuleScope.USER
    enabled: bool = True


class AIDetectionRuleUpdateRequest(BaseModel):
    source_text: str | None = Field(default=None, min_length=1, max_length=4000)
    compiled_rule: CompiledAIDetectionRule | None = None
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    severity: RuleSeverity | None = None
    weight: float | None = Field(default=None, ge=0.0, le=1.0)
    enabled: bool | None = None
    scope: RuleScope | None = None


class AIDetectionRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str | None
    name: str
    description: str | None
    source_text: str
    rule_type: RuleType
    severity: RuleSeverity
    weight: float
    enabled: bool
    scope: RuleScope
    rule_json: dict[str, Any]
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class AIDetectionRuleListResponse(BaseModel):
    rules: list[AIDetectionRuleOut]


class AIDetectionAnalyzeRequest(BaseModel):
    text: str = Field(min_length=20, max_length=20000)
    mode: AnalyzeMode = "deep"
    use_custom_rules: bool = True
    rule_ids: list[str] | None = None
    include_explanation: bool = True


class AIDetectionMatchLocation(BaseModel):
    scope: ConditionScope = "paragraph"
    paragraph_index: int | None = None
    sentence_index: int | None = None
    start: int | None = None
    end: int | None = None


class AIDetectionMatchedRule(BaseModel):
    rule_id: str
    rule_name: str
    rule_type: str
    severity: RuleSeverity
    weight: float
    matched_text: str | None = None
    reason: str
    confidence: float | None = None
    location: AIDetectionMatchLocation | None = None


class AIDetectionEvidence(BaseModel):
    text: str
    reason: str
    rule_id: str
    severity: RuleSeverity
    paragraph_index: int | None = None


class AIDetectionAnalyzeResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    type: Literal["ai_detection"] = "ai_detection"
    mode: AnalyzeMode
    score: float
    model_score: float | None = None
    roberta_score: float | None = None
    custom_rule_score: float = 0.0
    final_score: float
    rule_score: float = 0.0
    risk_level: RiskLevel
    confidence: str
    verdict: str
    method: str = "rule_based_heuristics"
    flags: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    detectors_used: list[str] = Field(default_factory=list)
    skipped_detectors: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
    rule_source: Literal["default_app_rules", "user_custom_rules"] = "default_app_rules"
    matched_rules: list[AIDetectionMatchedRule | str] = Field(default_factory=list)
    evidence: list[AIDetectionEvidence] = Field(default_factory=list)
    explanation: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    disclaimer: str
    warnings: list[str] = Field(default_factory=list)


class AIDetectionWrappedAnalyzeResponse(BaseModel):
    type: Literal["ai_detection"] = "ai_detection"
    data: AIDetectionAnalyzeResponse
    text: str
