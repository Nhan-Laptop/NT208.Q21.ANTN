from __future__ import annotations

import logging
from typing import Any

import httpx

from ..models import CandidateWork, ReferenceMetadata
from ..normalize import normalize_doi

logger = logging.getLogger(__name__)

DATACITE_DOIS_URL = "https://api.datacite.org/dois"


def _creator_name(creator: dict[str, Any]) -> str | None:
    if not isinstance(creator, dict):
        return None
    for key in ("name", "familyName", "givenName"):
        value = creator.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_datacite_work(item: dict[str, Any]) -> CandidateWork:
    if not isinstance(item, dict):
        return CandidateWork(source="datacite")

    attributes = item.get("attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {}
    titles = attributes.get("titles") or []
    title = None
    if isinstance(titles, list) and titles:
        first_title = titles[0]
        if isinstance(first_title, dict):
            title = first_title.get("title")
        elif isinstance(first_title, str):
            title = first_title

    authors = []
    creators = attributes.get("creators") or []
    if isinstance(creators, list):
        for creator in creators:
            name = _creator_name(creator)
            if name:
                authors.append(name)

    year = attributes.get("publicationYear")
    if year is not None:
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None

    container = attributes.get("container") or {}
    venue = None
    if isinstance(container, dict):
        for key in ("title", "container-title"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                venue = value.strip()
                break
    if not venue:
        publisher = attributes.get("publisher")
        if isinstance(publisher, str) and publisher.strip():
            venue = publisher.strip()

    doi = None
    if isinstance(attributes.get("doi"), str) and attributes["doi"].strip():
        doi = normalize_doi(attributes["doi"])
    elif isinstance(item.get("id"), str) and item["id"].strip():
        doi = normalize_doi(item["id"])

    types = attributes.get("types") or {}
    volume = None
    issue = None
    if isinstance(container, dict):
        vol_value = container.get("volume")
        issue_value = container.get("issue")
        volume = str(vol_value) if vol_value is not None else None
        issue = str(issue_value) if issue_value is not None else None

    url = None
    for key in ("url", "contentUrl"):
        value = attributes.get(key)
        if isinstance(value, str) and value.strip():
            url = value.strip()
            break

    return CandidateWork(
        source="datacite",
        title=title.strip() if isinstance(title, str) else None,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        url=url,
        external_id=item.get("id") if isinstance(item.get("id"), str) else doi,
        external_id_type="datacite" if item.get("id") or doi else None,
        volume=volume,
        issue=issue,
        raw={"type": (types.get("schemaOrg") if isinstance(types, dict) else None), **item},
    )


class DataCiteSource:
    name = "datacite"

    def lookup_doi(self, doi: str) -> CandidateWork | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{DATACITE_DOIS_URL}/{normalized}", headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"})
            if response.status_code != 200:
                return None
            payload = response.json().get("data")
            candidate = normalize_datacite_work(payload)
            return candidate if candidate.doi == normalized else None
        except Exception as exc:
            logger.debug("DataCite exact DOI lookup failed for %s: %s", normalized, exc)
            return None

    def search(self, ref: ReferenceMetadata, limit: int = 5) -> list[CandidateWork]:
        query_parts = []
        if ref.title:
            query_parts.append(ref.title)
        if ref.authors:
            query_parts.append(ref.authors[0])
        if ref.year:
            query_parts.append(str(ref.year))
        if ref.venue:
            query_parts.append(ref.venue)
        query = " ".join(part.strip() for part in query_parts if part and str(part).strip())
        if not query:
            return []

        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.get(
                    DATACITE_DOIS_URL,
                    params={"query": query, "page[size]": limit},
                    headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
                )
            if response.status_code != 200:
                logger.warning("DataCite HTTP query returned status code %s", response.status_code)
                return []
            items = response.json().get("data", [])
            return [normalize_datacite_work(item) for item in items if isinstance(item, dict)]
        except Exception as exc:
            logger.warning("DataCite candidate search via HTTP failed: %s", exc)
            return []
