from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ManuscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    session_id: str | None
    file_attachment_id: str | None
    title: str | None
    abstract: str | None
    body_text: str
    keywords_json: list[str] | None
    references_json: list[dict[str, Any]] | None
    parsed_structure: dict[str, Any] | None
    source_type: str | None
    created_at: datetime
    updated_at: datetime


class ManuscriptAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    manuscript_id: str
    readiness_score: float
    title_present: bool
    abstract_present: bool
    keyword_count: int
    reference_count: int
    estimated_word_count: int
    warnings: list[str] | None
    created_at: datetime
    updated_at: datetime


class ManuscriptParseRequest(BaseModel):
    session_id: str | None = None
    file_id: str | None = None
    text: str | None = Field(default=None, min_length=20)
    title: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_text_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("text"):
            return data
        for key in ("abstract", "body_text", "manuscript_text"):
            if data.get(key):
                payload = dict(data)
                payload["text"] = data[key]
                return payload
        return data


class ManuscriptParseResponse(BaseModel):
    manuscript: ManuscriptOut
    assessment: ManuscriptAssessmentOut


class MatchRequestCreate(BaseModel):
    manuscript_id: str | None = None
    session_id: str | None = None
    file_id: str | None = None
    text: str | None = Field(default=None, min_length=20)
    title: str | None = None
    desired_venue_type: str | None = None
    min_quartile: str | None = None
    require_scopus: bool = False
    require_wos: bool = False
    apc_budget_usd: float | None = None
    max_review_weeks: float | None = None
    include_cfps: bool = True
    top_k: int = Field(default=10, ge=1, le=30)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_text_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("text"):
            return data
        for key in ("abstract", "body_text", "manuscript_text"):
            if data.get(key):
                payload = dict(data)
                payload["text"] = data[key]
                return payload
        return data


class MatchRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    manuscript_id: str
    user_id: str
    desired_venue_type: str | None
    min_quartile: str | None
    require_scopus: bool
    require_wos: bool
    apc_budget_usd: float | None
    max_review_weeks: float | None
    include_cfps: bool
    status: str
    request_payload: dict[str, Any] | None
    retrieval_diagnostics: dict[str, Any] | None
    executed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MatchCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    match_request_id: str
    entity_type: str
    venue_id: str | None
    cfp_event_id: str | None
    article_id: str | None
    rank: int
    retrieval_score: float
    scope_overlap_score: float
    quality_fit_score: float
    policy_fit_score: float
    freshness_score: float
    manuscript_readiness_score: float
    penalty_score: float
    final_score: float
    explanation_payload: dict[str, Any] | None
    evidence_payload: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class MatchResultResponse(BaseModel):
    request: MatchRequestOut
    manuscript: ManuscriptOut
    assessment: ManuscriptAssessmentOut | None
    candidates: list[MatchCandidateOut]


class VenueSearchItem(BaseModel):
    id: str
    title: str
    canonical_title: str
    venue_type: str
    publisher: str | None
    subjects: list[str]
    metrics: dict[str, Any]
    policy: dict[str, Any]
    indexed_scopus: bool
    indexed_wos: bool
    is_open_access: bool
    is_hybrid: bool


class VenueSearchResponse(BaseModel):
    items: list[VenueSearchItem]
    total: int


class CrawlRunRequest(BaseModel):
    source_slugs: list[str] | None = None
    include_bootstrap: bool = False
    include_live_sources: bool = True
    limit: int | None = Field(default=None, ge=1, le=10000)
    download_only: bool = False


class CrawlReindexRequest(BaseModel):
    source_slugs: list[str] | None = None


class CrawlJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str | None
    requested_by_user_id: str | None
    job_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    records_seen: int
    records_created: int
    records_updated: int
    records_deduped: int
    records_indexed: int
    error_message: str | None
    job_metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class CrawlSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    source_type: str
    base_url: str | None
    active: bool
    config_json: dict[str, Any] | None
    notes: str | None
    last_crawled_at: datetime | None


class ManuscriptUploadResponse(BaseModel):
    file_id: str
    manuscript: ManuscriptOut
    assessment: ManuscriptAssessmentOut
