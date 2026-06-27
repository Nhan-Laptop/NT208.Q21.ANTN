from __future__ import annotations

import logging
from typing import Any

import httpx

from ..models import CandidateWork, ReferenceMetadata
from ..normalize import normalize_doi

logger = logging.getLogger(__name__)

try:
    from habanero import Crossref as _HabaneroCrossref

    _HABANERO_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dep
    _HabaneroCrossref = None
    _HABANERO_AVAILABLE = False

CROSSREF_WORKS_URL = "https://api.crossref.org/works"


def normalize_crossref_work(item: dict[str, Any]) -> CandidateWork:
    if not item:
        return CandidateWork(source="crossref")

    title = None
    titles = item.get("title")
    if isinstance(titles, list) and titles:
        title = titles[0]
    elif isinstance(titles, str):
        title = titles

    authors: list[str] = []
    author_list = item.get("author", [])
    if isinstance(author_list, list):
        for author in author_list:
            if not isinstance(author, dict):
                continue
            family = str(author.get("family") or "").strip()
            given = str(author.get("given") or "").strip()
            if family and given:
                authors.append(f"{family} {given}".strip())
            elif family:
                authors.append(family)
            elif given:
                authors.append(given)

    year = None
    for key in ("published-print", "published-online", "published", "issued"):
        published = item.get(key)
        if isinstance(published, dict):
            parts = published.get("date-parts")
            if isinstance(parts, list) and parts and parts[0]:
                try:
                    year = int(parts[0][0])
                    break
                except (TypeError, ValueError):
                    pass

    venue = None
    containers = item.get("container-title")
    if isinstance(containers, list) and containers:
        venue = containers[0]
    elif isinstance(containers, str):
        venue = containers

    doi = None
    if item.get("DOI"):
        doi = normalize_doi(str(item["DOI"]))

    return CandidateWork(
        source="crossref",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        url=item.get("URL") if isinstance(item.get("URL"), str) else None,
        external_id=doi,
        external_id_type="crossref" if doi else None,
        volume=str(item.get("volume")) if item.get("volume") is not None else None,
        issue=str(item.get("issue")) if item.get("issue") is not None else None,
        pages=item.get("page"),
        raw=item,
    )


class CrossrefSource:
    name = "crossref"

    def __init__(self) -> None:
        self._crossref = _HabaneroCrossref() if _HABANERO_AVAILABLE else None

    def lookup_doi(self, doi: str) -> CandidateWork | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None

        if self._crossref is not None:
            try:
                result = self._crossref.works(ids=normalized)
                message = result.get("message") if isinstance(result, dict) else None
                if isinstance(message, dict):
                    candidate = normalize_crossref_work(message)
                    if candidate.doi == normalized:
                        return candidate
            except Exception as exc:  # pragma: no cover - upstream variability
                logger.debug("Crossref exact DOI lookup via Habanero failed for %s: %s", normalized, exc)

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{CROSSREF_WORKS_URL}/{normalized}", headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"})
            if response.status_code != 200:
                return None
            payload = response.json().get("message", {})
            candidate = normalize_crossref_work(payload)
            return candidate if candidate.doi == normalized else None
        except Exception as exc:  # pragma: no cover - upstream variability
            logger.debug("Crossref exact DOI lookup via HTTP failed for %s: %s", normalized, exc)
            return None

    def search(self, ref: ReferenceMetadata, limit: int = 5) -> list[CandidateWork]:
        if not ref:
            return []

        params: dict[str, Any] = {"rows": limit}
        bibliographic_parts = []
        if ref.title:
            bibliographic_parts.append(ref.title)
        if ref.venue:
            bibliographic_parts.append(ref.venue)
        if ref.pages:
            bibliographic_parts.append(ref.pages)
        if ref.volume:
            bibliographic_parts.append(ref.volume)
        if bibliographic_parts:
            params["query.bibliographic"] = " ".join(str(part).strip() for part in bibliographic_parts if part)
        else:
            raw_parts = [ref.raw, *(ref.authors or [])]
            params["query"] = " ".join(str(part).strip() for part in raw_parts if part).strip()

        if ref.authors:
            params["query.author"] = ref.authors[0]
        if ref.year:
            params["filter"] = f"from-pub-date:{ref.year},until-pub-date:{ref.year}"

        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.get(
                    CROSSREF_WORKS_URL,
                    params=params,
                    headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
                )
            if response.status_code != 200:
                logger.warning("Crossref HTTP query returned status code %s", response.status_code)
                return []
            items = response.json().get("message", {}).get("items", [])
            return [normalize_crossref_work(item) for item in items if isinstance(item, dict)]
        except Exception as exc:
            logger.warning("Crossref candidate search via HTTP failed: %s", exc)
            return []
