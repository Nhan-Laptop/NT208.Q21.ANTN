from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from html.parser import HTMLParser
from typing import Any

import httpx

from ..models import CandidateWork
from ..normalize import normalize_doi

logger = logging.getLogger(__name__)


class _HeadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, list[str]] = {}
        self.scripts: list[str] = []
        self._capture_ld_json = False
        self._script_chunks: list[str] = []
        self.title_text: list[str] = []
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "meta":
            key = (attrs_map.get("name") or attrs_map.get("property") or attrs_map.get("http-equiv") or "").strip().lower()
            content = attrs_map.get("content", "").strip()
            if key and content:
                self.meta.setdefault(key, []).append(content)
        elif tag.lower() == "script" and attrs_map.get("type", "").lower() == "application/ld+json":
            self._capture_ld_json = True
            self._script_chunks = []
        elif tag.lower() == "title":
            self._capture_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capture_ld_json:
            payload = "".join(self._script_chunks).strip()
            if payload:
                self.scripts.append(payload)
            self._capture_ld_json = False
            self._script_chunks = []
        elif tag.lower() == "title":
            self._capture_title = False

    def handle_data(self, data: str) -> None:
        if self._capture_ld_json:
            self._script_chunks.append(data)
        if self._capture_title:
            self.title_text.append(data)


def _first_meta(meta: dict[str, list[str]], *names: str) -> str | None:
    for name in names:
        values = meta.get(name.lower()) or []
        for value in values:
            if value and value.strip():
                return value.strip()
    return None


def _extract_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2})\b", value)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_doi_text(value: str | None) -> str | None:
    if not value:
        return None
    doi_match = re.search(r"(10\.\d{4,9}/[^\s\"'<>]+)", value, re.IGNORECASE)
    if not doi_match:
        return None
    return normalize_doi(doi_match.group(1))


def _collect_json_ld_value(payload: Any, path: str) -> list[Any]:
    parts = path.split(".")
    values = [payload]
    for part in parts:
        next_values: list[Any] = []
        for value in values:
            if isinstance(value, dict) and part in value:
                next_values.append(value[part])
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and part in item:
                        next_values.append(item[part])
        values = next_values
    return values


def _flatten_strings(values: list[Any]) -> list[str]:
    flattened: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            flattened.append(value.strip())
        elif isinstance(value, list):
            flattened.extend(_flatten_strings(value))
        elif isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str) and name.strip():
                flattened.append(name.strip())
    return flattened


def _extract_json_ld_metadata(scripts: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for script in scripts:
        try:
            payload = json.loads(script)
        except json.JSONDecodeError:
            continue
        title_values = _flatten_strings(_collect_json_ld_value(payload, "headline")) or _flatten_strings(_collect_json_ld_value(payload, "name")) or _flatten_strings(_collect_json_ld_value(payload, "title"))
        author_values = _flatten_strings(_collect_json_ld_value(payload, "author"))
        venue_values = _flatten_strings(_collect_json_ld_value(payload, "isPartOf.name")) or _flatten_strings(_collect_json_ld_value(payload, "periodical.name"))
        doi_values = _flatten_strings(_collect_json_ld_value(payload, "identifier")) + _flatten_strings(_collect_json_ld_value(payload, "doi"))
        url_values = _flatten_strings(_collect_json_ld_value(payload, "url"))
        date_values = _flatten_strings(_collect_json_ld_value(payload, "datePublished"))

        if title_values and "title" not in metadata:
            metadata["title"] = title_values[0]
        if author_values and "authors" not in metadata:
            metadata["authors"] = author_values
        if venue_values and "venue" not in metadata:
            metadata["venue"] = venue_values[0]
        if doi_values and "doi" not in metadata:
            doi = next((value for value in ( _extract_doi_text(item) for item in doi_values ) if value), None)
            if doi:
                metadata["doi"] = doi
        if url_values and "resolved_url" not in metadata:
            metadata["resolved_url"] = url_values[0]
        if date_values and "year" not in metadata:
            metadata["year"] = _extract_year(date_values[0])
    return metadata


class PublisherMetaSource:
    name = "publisher_meta"

    def lookup_doi(self, doi: str) -> CandidateWork | None:  # pragma: no cover - not used directly
        return None

    def search(self, ref, limit: int = 5) -> list[CandidateWork]:  # pragma: no cover - not used
        return []

    def enrich_candidate(self, candidate: CandidateWork) -> CandidateWork:
        target_url = candidate.resolved_url or candidate.url
        if not target_url:
            return candidate

        with httpx.Client(timeout=8.0, follow_redirects=True, headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"}) as client:
            response = client.get(target_url)
        response.raise_for_status()
        parser = _HeadParser()
        parser.feed(response.text)

        meta = parser.meta
        structured = _extract_json_ld_metadata(parser.scripts)
        resolved_url = str(response.url)
        title = _first_meta(meta, "citation_title", "dc.title", "og:title") or structured.get("title") or " ".join(parser.title_text).strip() or candidate.title
        venue = _first_meta(meta, "citation_journal_title", "citation_conference_title", "dc.source", "prism.publicationname") or structured.get("venue") or candidate.venue
        doi = (
            _extract_doi_text(_first_meta(meta, "citation_doi", "dc.identifier", "prism.doi", "dc.identifier.doi"))
            or structured.get("doi")
            or candidate.doi
        )
        authors = []
        for key in ("citation_author", "dc.creator", "author"):
            authors.extend(meta.get(key, []))
        if not authors:
            authors = structured.get("authors") or list(candidate.authors or [])
        year = _extract_year(_first_meta(meta, "citation_publication_date", "citation_date", "dc.date", "prism.publicationdate")) or structured.get("year") or candidate.year

        evidence_urls = [resolved_url]
        if candidate.url and candidate.url != resolved_url:
            evidence_urls.append(candidate.url)
        if candidate.doi:
            doi_url = f"https://doi.org/{candidate.doi}"
            if doi_url not in evidence_urls:
                evidence_urls.append(doi_url)

        publisher_meta = {
            "title": title,
            "authors": authors,
            "venue": venue,
            "doi": doi,
            "year": year,
            "resolved_url": resolved_url,
            "meta_names": sorted(meta.keys()),
        }

        enriched = replace(candidate)
        enriched.title = candidate.title or title
        enriched.authors = list(candidate.authors or authors)
        enriched.venue = candidate.venue or venue
        enriched.doi = candidate.doi or doi
        enriched.year = candidate.year or year
        enriched.resolved_url = resolved_url
        merged_urls = list(dict.fromkeys([*(candidate.evidence_urls or []), *evidence_urls]))
        enriched.evidence_urls = merged_urls
        enriched.raw = dict(candidate.raw or {})
        enriched.raw["publisher_meta"] = publisher_meta
        if doi and candidate.doi and normalize_doi(doi) == normalize_doi(candidate.doi):
            enriched.raw["publisher_meta_confirmed"] = True
        elif title and candidate.title and title.strip().lower() == candidate.title.strip().lower():
            enriched.raw["publisher_meta_confirmed"] = True
        return enriched
