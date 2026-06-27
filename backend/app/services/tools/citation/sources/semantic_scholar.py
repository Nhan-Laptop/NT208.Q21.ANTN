from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

from ..models import CandidateWork, ReferenceMetadata
from ..normalize import normalize_doi

logger = logging.getLogger(__name__)

SEMANTIC_SCHOLAR_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_FIELDS = (
    "paperId,url,title,authors,year,venue,externalIds,publicationTypes,publicationDate"
)


def normalize_semantic_scholar_paper(paper: dict[str, Any]) -> CandidateWork | None:
    if not isinstance(paper, dict):
        return None

    title = paper.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    authors: list[str] = []
    for author in paper.get("authors", []) or []:
        if isinstance(author, dict) and isinstance(author.get("name"), str) and author["name"].strip():
            authors.append(author["name"].strip())

    year = paper.get("year")
    if year is not None:
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None

    venue = paper.get("venue")
    if not isinstance(venue, str) or not venue.strip():
        venue = None

    external_ids = paper.get("externalIds") or {}
    doi = None
    if isinstance(external_ids, dict) and isinstance(external_ids.get("DOI"), str) and external_ids["DOI"].strip():
        doi = normalize_doi(external_ids["DOI"])

    paper_id = str(paper.get("paperId")) if paper.get("paperId") is not None else None
    url = paper.get("url") if isinstance(paper.get("url"), str) and paper.get("url").strip() else None
    return CandidateWork(
        source="semantic_scholar",
        title=title.strip(),
        authors=authors,
        year=year,
        venue=venue.strip() if isinstance(venue, str) else None,
        doi=doi,
        url=url,
        external_id=paper_id,
        external_id_type="semantic_scholar" if paper_id else None,
        raw=paper,
    )


class SemanticScholarSource:
    name = "semantic_scholar"

    def lookup_doi(self, doi: str) -> CandidateWork | None:
        normalized = normalize_doi(doi)
        candidates = self.search(ReferenceMetadata(raw=normalized, title=normalized), limit=1)
        for candidate in candidates:
            if candidate.doi == normalized:
                return candidate
        return None

    def search(self, ref: ReferenceMetadata, limit: int = 5) -> list[CandidateWork]:
        settings = get_settings()
        if not settings.semantic_scholar_enabled or not ref or not ref.title:
            return []

        headers = {"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"}
        if settings.semantic_scholar_api_key:
            headers["x-api-key"] = settings.semantic_scholar_api_key
        params = {"query": ref.title.strip(), "limit": max(1, min(limit, 10)), "fields": SEMANTIC_SCHOLAR_FIELDS}

        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.get(SEMANTIC_SCHOLAR_SEARCH_URL, params=params, headers=headers)
            if response.status_code == 429 or response.status_code >= 500:
                logger.warning("Semantic Scholar query returned retryable status code %s", response.status_code)
                return []
            if response.status_code != 200:
                logger.warning("Semantic Scholar query returned status code %s", response.status_code)
                return []
            payload = response.json()
            papers = payload.get("data", []) if isinstance(payload, dict) else []
            return [normalize_semantic_scholar_paper(paper) for paper in papers if normalize_semantic_scholar_paper(paper)]
        except (httpx.TimeoutException, httpx.RequestError, ValueError, TypeError) as exc:
            logger.warning("Semantic Scholar candidate search failed: %s", exc)
            return []
        except Exception as exc:  # pragma: no cover - upstream variability
            logger.warning("Semantic Scholar candidate search failed unexpectedly: %s", exc)
            return []
