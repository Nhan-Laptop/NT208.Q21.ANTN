from __future__ import annotations

import logging
from typing import Any

import httpx

from ..models import CandidateWork, ReferenceMetadata
from ..normalize import normalize_doi

logger = logging.getLogger(__name__)

try:
    import pyalex
    from pyalex import Works

    pyalex.config.email = "aira@research.local"
    _PYALEX_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dep
    Works = None
    _PYALEX_AVAILABLE = False

OPENALEX_WORKS_URL = "https://api.openalex.org/works"


def normalize_openalex_work(item: dict[str, Any]) -> CandidateWork:
    if not item:
        return CandidateWork(source="openalex")

    title = item.get("display_name") or item.get("title")
    authors: list[str] = []
    for authorship in item.get("authorships", []) or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        if isinstance(author, dict) and author.get("display_name"):
            authors.append(str(author["display_name"]))

    year = item.get("publication_year")
    if year is not None:
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None

    venue = None
    primary_location = item.get("primary_location") or {}
    if isinstance(primary_location, dict):
        source = primary_location.get("source") or {}
        if isinstance(source, dict):
            venue = source.get("display_name")
    if not venue:
        host_venue = item.get("host_venue") or {}
        if isinstance(host_venue, dict):
            venue = host_venue.get("display_name")

    doi = None
    if item.get("doi"):
        doi = normalize_doi(str(item["doi"]))

    url = None
    if isinstance(primary_location, dict):
        url = primary_location.get("landing_page_url") or primary_location.get("pdf_url")
    if not url and isinstance(item.get("id"), str):
        url = item["id"]

    biblio = item.get("biblio") or {}
    volume = biblio.get("volume") if isinstance(biblio, dict) else None
    issue = biblio.get("issue") if isinstance(biblio, dict) else None
    first_page = biblio.get("first_page") if isinstance(biblio, dict) else None
    last_page = biblio.get("last_page") if isinstance(biblio, dict) else None
    pages = None
    if first_page and last_page:
        pages = f"{first_page}-{last_page}"
    elif first_page:
        pages = str(first_page)

    external_id = item.get("id") if isinstance(item.get("id"), str) else None
    return CandidateWork(
        source="openalex",
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        url=url,
        external_id=external_id,
        external_id_type="openalex" if external_id else None,
        volume=str(volume) if volume is not None else None,
        issue=str(issue) if issue is not None else None,
        pages=pages,
        raw=item,
    )


class OpenAlexSource:
    name = "openalex"

    def lookup_doi(self, doi: str) -> CandidateWork | None:
        normalized = normalize_doi(doi)
        for value in (normalized, f"https://doi.org/{normalized}"):
            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.get(
                        OPENALEX_WORKS_URL,
                        params={"filter": f"doi:{value}", "per-page": 1},
                        headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
                    )
                response.raise_for_status()
                results = response.json().get("results", [])
                if not results:
                    continue
                candidate = normalize_openalex_work(results[0])
                if candidate.doi == normalized:
                    return candidate
            except Exception as exc:  # pragma: no cover - upstream variability
                logger.debug("OpenAlex exact DOI lookup failed for %s: %s", normalized, exc)
        return None

    def search(self, ref: ReferenceMetadata, limit: int = 5) -> list[CandidateWork]:
        if not ref or not ref.title:
            return []
        query = ref.title.strip()
        if not query:
            return []

        if _PYALEX_AVAILABLE and Works is not None:
            try:
                works_iter = Works().search(query).get(per_page=limit)
                candidates = [normalize_openalex_work(item) for item in (works_iter or []) if isinstance(item, dict)]
                if candidates:
                    return candidates
            except Exception as exc:  # pragma: no cover - optional path
                logger.warning("OpenAlex candidate search via pyalex failed: %s. Falling back to HTTP.", exc)

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    OPENALEX_WORKS_URL,
                    params={"search": query, "per-page": limit},
                    headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
                )
            if response.status_code != 200:
                logger.warning("OpenAlex HTTP query returned status code %s", response.status_code)
                return []
            items = response.json().get("results", [])
            return [normalize_openalex_work(item) for item in items if isinstance(item, dict)]
        except Exception as exc:
            logger.warning("OpenAlex candidate search via HTTP fallback failed: %s", exc)
            return []
